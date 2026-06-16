from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

from .commodity_service import load_config, resolve_sqlite_path, user_agent

MACRO_CACHE_LOCK = asyncio.Lock()
DB_LOCK = asyncio.Lock()
MACRO_CACHE: dict[str, Any] = {"expires_at": datetime.min.replace(tzinfo=UTC), "data": None}
MACRO_SCHEMA_VERSION = 6

COUNTRY_ORDER = ["china", "us", "japan", "europe"]
NBS_RELEASE_LIST_URL = "https://www.stats.gov.cn/sj/zxfb/"
NBS_PRODUCTION_MATERIAL_TITLE = "流通领域重要生产资料市场价格变动情况"
NBS_PRODUCTION_MATERIAL_FALLBACK_URL = "https://www.stats.gov.cn/sj/zxfb/202606/t20260612_1963938.html"
NBS_PRODUCTION_MATERIAL_FALLBACK_PERIOD = "2026-06上旬"
NBS_PRODUCTION_MATERIAL_FALLBACK_PREVIOUS = "2026-05下旬"
NBS_PRODUCTION_MATERIAL_FALLBACK_SUMMARY = {"up": 14, "down": 33, "flat": 3}
NBS_PRODUCTION_MATERIAL_FALLBACK_ROWS: list[tuple[str, str, str, float, float, float]] = [
    ("黑色金属", "螺纹钢（Φ20mm，HRB400E）", "吨", 3243.9, -21.8, -0.7),
    ("黑色金属", "线材（Φ8—10mm，HPB300）", "吨", 3404.5, -23.2, -0.7),
    ("黑色金属", "普通中板（20mm，Q235）", "吨", 3547.3, -12.5, -0.4),
    ("黑色金属", "热轧普通板卷（4.75—11.5mm，Q235）", "吨", 3384.1, -16.0, -0.5),
    ("黑色金属", "无缝钢管（219*6，20#）", "吨", 4055.0, 6.2, 0.2),
    ("黑色金属", "角钢（5#）", "吨", 3523.1, -25.5, -0.7),
    ("有色金属", "电解铜（1#）", "吨", 105083.8, 288.1, 0.3),
    ("有色金属", "铝锭（A00）", "吨", 24132.5, -131.8, -0.5),
    ("有色金属", "铅锭（1#）", "吨", 16262.5, -223.2, -1.4),
    ("有色金属", "锌锭（0#）", "吨", 24756.3, -18.0, -0.1),
    ("化工产品", "硫酸（98%）", "吨", 1899.8, 27.0, 1.4),
    ("化工产品", "烧碱（液碱，32%）", "吨", 673.7, -6.4, -0.9),
    ("化工产品", "甲醇（优等品）", "吨", 2996.1, 55.2, 1.9),
    ("化工产品", "纯苯（石油苯，工业级）", "吨", 7662.7, -261.9, -3.3),
    ("化工产品", "乙醇（95.0%）", "吨", 5492.1, -88.1, -1.6),
    ("化工产品", "聚乙烯（LLDPE，熔融指数2薄膜料）", "吨", 8556.7, -82.3, -1.0),
    ("化工产品", "聚丙烯（拉丝料）", "吨", 9752.5, 3.2, 0.0),
    ("化工产品", "冰醋酸（99.5%及以上）", "吨", 2793.1, -112.1, -3.9),
    ("化工产品", "顺丁胶（BR9000）", "吨", 14029.2, -516.0, -3.5),
    ("化工产品", "涤纶长丝（POY150D/48F）", "吨", 8459.4, -40.6, -0.5),
    ("化工产品", "磷酸铁锂（普通动力型）", "吨", 57634.3, -1776.8, -3.0),
    ("石油天然气", "液化天然气（LNG）", "吨", 6202.6, 84.1, 1.4),
    ("石油天然气", "液化石油气（LPG）", "吨", 6114.2, -106.1, -1.7),
    ("石油天然气", "汽油（95#国VI）", "吨", 8980.0, -89.6, -1.0),
    ("石油天然气", "柴油（0#国VI）", "吨", 7688.0, -119.8, -1.5),
    ("石油天然气", "石蜡（58#半）", "吨", 7385.0, -400.0, -5.1),
    ("煤炭", "无烟煤（洗中块）", "吨", 1079.7, 78.3, 7.8),
    ("煤炭", "山西优混（5500大卡）", "吨", 861.0, 17.4, 2.1),
    ("煤炭", "焦煤（主焦煤）", "吨", 1770.6, 189.2, 12.0),
    ("煤炭", "焦炭（准一级冶金焦）", "吨", 1590.2, 65.2, 4.3),
    ("非金属矿物制品", "普通硅酸盐水泥（P.O 42.5散装）", "吨", 260.5, 3.0, 1.2),
    ("非金属矿物制品", "浮法平板玻璃（5/6mm）", "吨", 1125.3, -14.8, -1.3),
    ("非金属矿物制品", "多晶硅（致密料）", "千克", 34.5, -0.1, -0.3),
    ("农产品（主要用于加工）", "稻米（粳稻米）", "吨", 4006.1, -3.0, -0.1),
    ("农产品（主要用于加工）", "小麦（国标三等）", "吨", 2476.8, -55.5, -2.2),
    ("农产品（主要用于加工）", "玉米（黄玉米二等）", "吨", 2294.8, -10.4, -0.5),
    ("农产品（主要用于加工）", "棉花（皮棉，白棉三级）", "吨", 17060.0, -4.6, 0.0),
    ("农产品（主要用于加工）", "生猪（外三元）", "千克", 9.5, -0.1, -1.0),
    ("农产品（主要用于加工）", "大豆（黄豆）", "吨", 4411.5, -58.1, -1.3),
    ("农产品（主要用于加工）", "豆粕（粗蛋白含量≥43%）", "吨", 2827.8, -60.3, -2.1),
    ("农产品（主要用于加工）", "花生（油料花生米）", "吨", 7385.4, -42.0, -0.6),
    ("农产品（主要用于加工）", "白糖（国标一级白砂糖）", "吨", 5364.4, -5.6, -0.1),
    ("农业生产资料", "尿素（中小颗粒）", "吨", 1860.2, 12.0, 0.6),
    ("农业生产资料", "磷肥（55%磷酸一铵）", "吨", 4279.7, 96.7, 2.3),
    ("农业生产资料", "钾肥（港口62%白色氯化钾）", "吨", 3243.8, -8.3, -0.3),
    ("农业生产资料", "复合肥（硫酸钾复合肥，氮磷钾含量45%）", "吨", 3596.7, -1.6, 0.0),
    ("农业生产资料", "农药（草甘膦，95%原药）", "吨", 29375.0, -1053.6, -3.5),
    ("林产品", "天然橡胶（标准胶SCRWF）", "吨", 17734.4, 309.4, 1.8),
    ("林产品", "纸浆（进口针叶浆）", "吨", 4885.5, -78.3, -1.6),
    ("林产品", "瓦楞纸（AA级120g）", "吨", 2979.7, 57.1, 2.0),
]


def item(
    id: str,
    name: str,
    value: str | None,
    unit: str,
    period: str,
    previous: str | None,
    category: str,
    source: str,
    note: str,
    polarity: str | None = None,
    forecast: str | None = None,
    forecast_probability: str | None = None,
    forecast_period: str | None = None,
    forecast_source: str | None = None,
) -> dict[str, Any]:
    row = {
        "id": id,
        "name": name,
        "value": value,
        "unit": unit,
        "period": period,
        "previous": previous,
        "category": category,
        "source": source,
        "note": note,
    }
    if polarity:
        row["polarity"] = polarity
    if forecast is not None:
        row["forecast"] = forecast
    if forecast_probability is not None:
        row["forecastProbability"] = forecast_probability
    if forecast_period is not None:
        row["forecastPeriod"] = forecast_period
    if forecast_source is not None:
        row["forecastSource"] = forecast_source
    return row


MACRO_COUNTRIES: list[dict[str, Any]] = [
    {
        "id": "china",
        "name": "中国",
        "focus": True,
        "source": "国家统计局 / 中国人民银行 / 财新 / 中指研究院",
        "groups": [
            {
                "name": "利率与货币",
                "items": [
                    item("policy_rate", "7天逆回购利率", "1.40", "%", "2025-10", "1.50", "政策利率", "PBOC", "短端政策利率锚"),
                    item("lpr_1y", "1年期 LPR", "3.00", "%", "2025-10", "3.10", "贷款市场报价利率", "全国银行间同业拆借中心", "企业贷款定价基准"),
                    item("lpr_5y", "5年期以上 LPR", "3.50", "%", "2025-10", "3.60", "贷款市场报价利率", "全国银行间同业拆借中心", "房贷和中长期贷款定价基准"),
                    item("m2", "M2 同比", "8.4", "%", "2026-05", "8.1", "货币供应", "PBOC", "宽信用强弱观察"),
                    item("shibor_3m", "3M Shibor", None, "%", "实时", None, "市场利率", "SHIBOR", "待接实时行情"),
                ],
            },
            {
                "name": "通胀与景气",
                "items": [
                    item("cpi", "CPI 同比", "-0.1", "%", "2026-05", "0.1", "通胀", "NBS", "居民消费价格"),
                    item("ppi", "PPI 同比", "-3.3", "%", "2026-05", "-2.7", "工业价格", "NBS", "工业品出厂价格"),
                    item("official_pmi", "官方制造业 PMI", "49.5", "", "2026-05", "49.0", "景气调查", "NBS", "50 为荣枯线"),
                    item("caixin_pmi", "财新制造业 PMI", "50.7", "", "2026-05", "50.4", "景气调查", "财新 / S&P Global", "更偏中小和出口企业"),
                    item("services_pmi", "官方非制造业 PMI", "50.3", "", "2026-05", "50.4", "景气调查", "NBS", "服务业和建筑业景气"),
                ],
            },
            {
                "name": "信用与财政",
                "items": [
                    item("tsf_flow", "社融当月新增", "2.29", "万亿元", "2026-05", "1.16", "社会融资", "PBOC", "实体融资总量"),
                    item("tsf_stock_yoy", "社融存量同比", "8.7", "%", "2026-05", "8.5", "社会融资", "PBOC", "广义信用周期"),
                    item("new_loans", "人民币贷款新增", "0.62", "万亿元", "2026-05", "0.28", "信贷", "PBOC", "银行体系信用投放"),
                    item("fiscal_revenue", "一般公共预算收入累计同比", None, "%", "月度", None, "财政", "财政部", "待接财政部月度数据"),
                ],
            },
            {
                "name": "地产与内需",
                "items": [
                    item("new_home_price", "70城新房价格环比", "-0.3", "%", "2026-05", "-0.4", "房地产价格", "NBS", "新建商品住宅"),
                    item("used_home_price", "70城二手房价格环比", "-0.5", "%", "2026-05", "-0.6", "房地产价格", "NBS", "二手住宅"),
                    item("property_investment", "房地产开发投资累计同比", "-10.7", "%", "2026-05", "-10.3", "房地产投资", "NBS", "地产链需求"),
                    item("retail_sales", "社零当月同比", "-0.6", "%", "2026-05", "0.2", "消费", "NBS", "5月社会消费品零售总额41090亿元"),
                    item("retail_sales_ytd", "社零累计同比", "1.4", "%", "2026-01~05", "1.9", "消费", "NBS", "1-5月社会消费品零售总额206031亿元，累计口径"),
                    item("retail_ex_auto", "除汽车外消费品零售同比", "1.1", "%", "2026-05", "1.8", "消费", "NBS", "5月除汽车外消费品零售额37781亿元"),
                    item("online_retail_ytd", "网上零售累计同比", "5.9", "%", "2026-01~05", "6.6", "电商消费", "NBS", "网上商品和服务零售额83177亿元，累计口径"),
                    item("online_goods_ytd", "网上商品零售累计同比", "5.0", "%", "2026-01~05", "5.7", "电商消费", "NBS", "网上商品零售额52718亿元，累计口径"),
                    item("online_services_ytd", "网上服务零售累计同比", "7.6", "%", "2026-01~05", "8.3", "电商消费", "NBS", "网上服务零售额30459亿元，累计口径"),
                    item("industrial_output", "规模以上工业增加值同比", "5.6", "%", "2026-05", "6.1", "生产", "NBS", "工业生产动能"),
                ],
            },
        ],
    },
    {
        "id": "us",
        "name": "美国",
        "source": "Federal Reserve / BLS / ISM / S&P Global",
        "groups": [
            {
                "name": "核心指标",
                "items": [
                    item("fed_funds", "联邦基金目标区间", "4.25-4.50", "%", "2026-05", "4.25-4.50", "政策利率", "Fed", "FOMC 政策区间"),
                    item("cpi", "CPI 同比", "2.4", "%", "2026-05", "2.3", "通胀", "BLS", "居民通胀"),
                    item("ppi", "PPI 同比", "2.6", "%", "2026-05", "2.5", "工业价格", "BLS", "最终需求 PPI"),
                    item("ism_pmi", "ISM 制造业 PMI", "48.5", "", "2026-05", "48.7", "景气调查", "ISM", "50 为荣枯线"),
                    item("home_price", "Case-Shiller 房价同比", None, "%", "月度", None, "房地产价格", "S&P Dow Jones", "待接房价指数"),
                ],
            }
        ],
    },
    {
        "id": "japan",
        "name": "日本",
        "source": "Bank of Japan / Statistics Bureau / Jibun Bank",
        "groups": [
            {
                "name": "核心指标",
                "items": [
                    item("policy_rate", "政策利率", "0.50", "%", "2026-05", "0.50", "政策利率", "BOJ", "无担保隔夜拆借目标"),
                    item("cpi", "核心 CPI 同比", "3.2", "%", "2026-04", "3.2", "通胀", "Statistics Bureau", "剔除生鲜食品"),
                    item("ppi", "企业物价指数同比", "4.0", "%", "2026-05", "4.0", "工业价格", "BOJ", "CGPI"),
                    item("pmi", "Jibun 制造业 PMI", "50.4", "", "2026-05", "48.7", "景气调查", "Jibun Bank", "50 为荣枯线"),
                    item("home_price", "住宅价格指数同比", None, "%", "月度", None, "房地产价格", "MLIT", "待接国交省数据"),
                ],
            }
        ],
    },
    {
        "id": "europe",
        "name": "欧洲",
        "source": "ECB / Eurostat / HCOB",
        "groups": [
            {
                "name": "核心指标",
                "items": [
                    item("deposit_rate", "ECB 存款便利利率", "2.25", "%", "2026-05", "2.50", "政策利率", "ECB", "欧元区政策利率"),
                    item("hicp", "HICP 同比", "1.9", "%", "2026-05", "2.2", "通胀", "Eurostat", "欧元区调和 CPI"),
                    item("ppi", "PPI 同比", "0.7", "%", "2026-04", "1.9", "工业价格", "Eurostat", "工业生产者价格"),
                    item("pmi", "HCOB 制造业 PMI", "49.4", "", "2026-05", "49.0", "景气调查", "HCOB / S&P Global", "50 为荣枯线"),
                    item("house_price", "住宅价格指数同比", None, "%", "季度", None, "房地产价格", "Eurostat", "待接季度房价数据"),
                ],
            }
        ],
    },
]


ADDITIONAL_MACRO_GROUPS: dict[str, list[dict[str, Any]]] = {
    "china": [
        {
            "name": "就业与经济增长",
            "items": [
                item("gdp_yoy", "实际GDP同比", "5.0", "%", "2026-Q1", "4.5", "经济增长", "NBS", "季度实际GDP同比，初步核算"),
                item("fai_ytd_yoy", "固定资产投资累计同比", "-4.1", "%", "2026-01~05", "-1.6", "投资", "NBS", "不含农户，累计口径"),
                item("urban_unemployment", "城镇调查失业率", "5.1", "%", "2026-05", "5.2", "就业", "NBS", "全国城镇调查失业率，月度", polarity="lower_good"),
                item("major_city_unemployment", "31城调查失业率", "5.1", "%", "2026-05", "5.2", "就业", "NBS", "31个大城市城镇调查失业率", polarity="lower_good"),
                item("weekly_hours", "企业人员周平均工作时间", "48.2", "小时/周", "2026-05", "48.0", "就业", "NBS", "企业就业人员周平均工作时间"),
            ],
        }
    ],
    "us": [
        {
            "name": "就业与经济增长",
            "items": [
                item("real_gdp_saar", "实际GDP环比折年率", "1.6", "%", "2026-Q1", "0.5", "经济增长", "BEA", "季度实际GDP，二次估计"),
                item("private_final_sales", "私人国内最终销售", "2.4", "%", "2026-Q1", "2.5", "内生需求", "BEA", "Real final sales to private domestic purchasers"),
                item("unemployment_rate", "失业率", "4.3", "%", "2026-05", "4.3", "就业", "BLS", "家庭调查，季调", polarity="lower_good"),
                item("nonfarm_payrolls", "非农就业新增", "172", "千人", "2026-05", "179", "就业", "BLS", "机构调查，当月新增"),
                item("labor_force_participation", "劳动参与率", "61.8", "%", "2026-05", "61.8", "就业", "BLS", "Labor force participation rate"),
            ],
        }
    ],
    "japan": [
        {
            "name": "就业与经济增长",
            "items": [
                item("real_gdp_saar", "实际GDP环比折年率", "1.8", "%", "2026-Q1", "0.7", "经济增长", "Cabinet Office / ESRI", "季度GDP二次速報，年率换算"),
                item("real_gdp_qoq", "实际GDP环比", "0.5", "%", "2026-Q1", "0.2", "经济增长", "Cabinet Office / ESRI", "季度实际GDP，季调环比"),
                item("unemployment_rate", "完全失业率", "2.5", "%", "2026-04", "2.7", "就业", "Statistics Bureau", "劳动力调查，季调", polarity="lower_good"),
            ],
        }
    ],
    "europe": [
        {
            "name": "就业与经济增长",
            "items": [
                item("real_gdp_qoq", "欧元区实际GDP环比", "-0.2", "%", "2026-Q1", "0.2", "经济增长", "Eurostat", "季调环比，最终估计"),
                item("real_gdp_yoy", "欧元区实际GDP同比", "0.3", "%", "2026-Q1", "1.2", "经济增长", "Eurostat", "季调同比，最终估计"),
                item("employment_qoq", "欧元区就业人数环比", "0.1", "%", "2026-Q1", "0.2", "就业", "Eurostat", "就业人数，季调环比"),
                item("unemployment_rate", "欧元区失业率", "6.3", "%", "2026-04", "6.3", "就业", "Eurostat", "月度失业率，季调", polarity="lower_good"),
            ],
        }
    ],
}


MACRO_FORECASTS: dict[str, dict[str, str]] = {
    "china:policy_rate": {"forecast": "1.40", "forecastProbability": "78%", "forecastPeriod": "下次操作", "forecastSource": "观察池共识"},
    "china:lpr_1y": {"forecast": "3.00", "forecastProbability": "74%", "forecastPeriod": "下次报价", "forecastSource": "观察池共识"},
    "china:lpr_5y": {"forecast": "3.50", "forecastProbability": "72%", "forecastPeriod": "下次报价", "forecastSource": "观察池共识"},
    "china:m2": {"forecast": "8.2", "forecastProbability": "56%", "forecastPeriod": "2026-06", "forecastSource": "观察池共识"},
    "china:cpi": {"forecast": "0.0", "forecastProbability": "58%", "forecastPeriod": "2026-06", "forecastSource": "观察池共识"},
    "china:ppi": {"forecast": "-3.2", "forecastProbability": "55%", "forecastPeriod": "2026-06", "forecastSource": "观察池共识"},
    "china:official_pmi": {"forecast": "49.6", "forecastProbability": "54%", "forecastPeriod": "2026-06", "forecastSource": "观察池共识"},
    "china:caixin_pmi": {"forecast": "50.5", "forecastProbability": "52%", "forecastPeriod": "2026-06", "forecastSource": "观察池共识"},
    "china:services_pmi": {"forecast": "50.4", "forecastProbability": "51%", "forecastPeriod": "2026-06", "forecastSource": "观察池共识"},
    "china:tsf_flow": {"forecast": "3.20", "forecastProbability": "53%", "forecastPeriod": "2026-06", "forecastSource": "观察池共识"},
    "china:tsf_stock_yoy": {"forecast": "8.8", "forecastProbability": "55%", "forecastPeriod": "2026-06", "forecastSource": "观察池共识"},
    "china:new_loans": {"forecast": "1.05", "forecastProbability": "52%", "forecastPeriod": "2026-06", "forecastSource": "观察池共识"},
    "china:gdp_yoy": {"forecast": "4.8", "forecastProbability": "54%", "forecastPeriod": "2026-Q2", "forecastSource": "观察池共识"},
    "china:fai_ytd_yoy": {"forecast": "-3.5", "forecastProbability": "52%", "forecastPeriod": "2026-01~06", "forecastSource": "观察池共识"},
    "china:urban_unemployment": {"forecast": "5.1", "forecastProbability": "61%", "forecastPeriod": "2026-06", "forecastSource": "观察池共识"},
    "china:major_city_unemployment": {"forecast": "5.1", "forecastProbability": "58%", "forecastPeriod": "2026-06", "forecastSource": "观察池共识"},
    "china:weekly_hours": {"forecast": "48.1", "forecastProbability": "53%", "forecastPeriod": "2026-06", "forecastSource": "观察池共识"},
    "us:fed_funds": {"forecast": "4.25-4.50", "forecastProbability": "84%", "forecastPeriod": "下次FOMC", "forecastSource": "市场隐含/观察池"},
    "us:cpi": {"forecast": "2.5", "forecastProbability": "57%", "forecastPeriod": "2026-06", "forecastSource": "观察池共识"},
    "us:ppi": {"forecast": "2.6", "forecastProbability": "52%", "forecastPeriod": "2026-06", "forecastSource": "观察池共识"},
    "us:ism_pmi": {"forecast": "48.7", "forecastProbability": "50%", "forecastPeriod": "2026-06", "forecastSource": "观察池共识"},
    "us:real_gdp_saar": {"forecast": "1.7", "forecastProbability": "55%", "forecastPeriod": "2026-Q2", "forecastSource": "观察池共识"},
    "us:private_final_sales": {"forecast": "2.3", "forecastProbability": "54%", "forecastPeriod": "2026-Q2", "forecastSource": "观察池共识"},
    "us:unemployment_rate": {"forecast": "4.3", "forecastProbability": "64%", "forecastPeriod": "2026-06", "forecastSource": "观察池共识"},
    "us:nonfarm_payrolls": {"forecast": "165", "forecastProbability": "43%", "forecastPeriod": "2026-06", "forecastSource": "观察池共识"},
    "us:labor_force_participation": {"forecast": "61.8", "forecastProbability": "60%", "forecastPeriod": "2026-06", "forecastSource": "观察池共识"},
    "japan:policy_rate": {"forecast": "0.50", "forecastProbability": "76%", "forecastPeriod": "下次BOJ", "forecastSource": "市场隐含/观察池"},
    "japan:cpi": {"forecast": "3.3", "forecastProbability": "56%", "forecastPeriod": "2026-05", "forecastSource": "观察池共识"},
    "japan:ppi": {"forecast": "3.8", "forecastProbability": "53%", "forecastPeriod": "2026-06", "forecastSource": "观察池共识"},
    "japan:pmi": {"forecast": "50.6", "forecastProbability": "52%", "forecastPeriod": "2026-06", "forecastSource": "观察池共识"},
    "japan:real_gdp_saar": {"forecast": "0.9", "forecastProbability": "52%", "forecastPeriod": "2026-Q2", "forecastSource": "观察池共识"},
    "japan:real_gdp_qoq": {"forecast": "0.2", "forecastProbability": "52%", "forecastPeriod": "2026-Q2", "forecastSource": "观察池共识"},
    "japan:unemployment_rate": {"forecast": "2.6", "forecastProbability": "58%", "forecastPeriod": "2026-05", "forecastSource": "观察池共识"},
    "europe:deposit_rate": {"forecast": "2.25", "forecastProbability": "72%", "forecastPeriod": "下次ECB", "forecastSource": "市场隐含/观察池"},
    "europe:hicp": {"forecast": "2.0", "forecastProbability": "55%", "forecastPeriod": "2026-06", "forecastSource": "观察池共识"},
    "europe:ppi": {"forecast": "0.5", "forecastProbability": "52%", "forecastPeriod": "2026-05", "forecastSource": "观察池共识"},
    "europe:pmi": {"forecast": "49.7", "forecastProbability": "54%", "forecastPeriod": "2026-06", "forecastSource": "观察池共识"},
    "europe:real_gdp_qoq": {"forecast": "0.1", "forecastProbability": "53%", "forecastPeriod": "2026-Q2", "forecastSource": "观察池共识"},
    "europe:real_gdp_yoy": {"forecast": "0.6", "forecastProbability": "52%", "forecastPeriod": "2026-Q2", "forecastSource": "观察池共识"},
    "europe:employment_qoq": {"forecast": "0.1", "forecastProbability": "60%", "forecastPeriod": "2026-Q2", "forecastSource": "观察池共识"},
    "europe:unemployment_rate": {"forecast": "6.3", "forecastProbability": "66%", "forecastPeriod": "2026-05", "forecastSource": "观察池共识"},
}


MACRO_HISTORY: dict[str, list[tuple[str, float]]] = {
    "china:policy_rate": [("2025-06", 1.50), ("2025-07", 1.50), ("2025-08", 1.50), ("2025-09", 1.50), ("2025-10", 1.40)],
    "china:lpr_1y": [("2025-06", 3.10), ("2025-07", 3.10), ("2025-08", 3.10), ("2025-09", 3.10), ("2025-10", 3.00)],
    "china:lpr_5y": [("2025-06", 3.60), ("2025-07", 3.60), ("2025-08", 3.60), ("2025-09", 3.60), ("2025-10", 3.50)],
    "china:m2": [("2026-01", 7.0), ("2026-02", 7.1), ("2026-03", 7.4), ("2026-04", 8.1), ("2026-05", 8.4)],
    "china:cpi": [("2026-01", 0.5), ("2026-02", -0.7), ("2026-03", -0.1), ("2026-04", 0.1), ("2026-05", -0.1)],
    "china:ppi": [("2026-01", -2.3), ("2026-02", -2.2), ("2026-03", -2.5), ("2026-04", -2.7), ("2026-05", -3.3)],
    "china:official_pmi": [("2026-01", 49.1), ("2026-02", 50.2), ("2026-03", 50.5), ("2026-04", 49.0), ("2026-05", 49.5)],
    "china:caixin_pmi": [("2026-01", 50.1), ("2026-02", 50.8), ("2026-03", 51.2), ("2026-04", 50.4), ("2026-05", 50.7)],
    "china:services_pmi": [("2026-01", 50.2), ("2026-02", 50.4), ("2026-03", 50.8), ("2026-04", 50.4), ("2026-05", 50.3)],
    "china:tsf_flow": [("2026-01", 7.06), ("2026-02", 2.23), ("2026-03", 5.89), ("2026-04", 1.16), ("2026-05", 2.29)],
    "china:tsf_stock_yoy": [("2026-01", 8.0), ("2026-02", 8.2), ("2026-03", 8.4), ("2026-04", 8.5), ("2026-05", 8.7)],
    "china:new_loans": [("2026-01", 5.13), ("2026-02", 1.01), ("2026-03", 3.64), ("2026-04", 0.28), ("2026-05", 0.62)],
    "china:new_home_price": [("2026-01", -0.3), ("2026-02", -0.1), ("2026-03", -0.2), ("2026-04", -0.4), ("2026-05", -0.3)],
    "china:used_home_price": [("2026-01", -0.5), ("2026-02", -0.4), ("2026-03", -0.5), ("2026-04", -0.6), ("2026-05", -0.5)],
    "china:property_investment": [("2026-01", -9.8), ("2026-02", -9.8), ("2026-03", -9.9), ("2026-04", -10.3), ("2026-05", -10.7)],
    "china:retail_sales": [("2026-01~02", 2.8), ("2026-03", 1.7), ("2026-04", 0.2), ("2026-05", -0.6)],
    "china:retail_sales_ytd": [("2026-01~02", 2.8), ("2026-01~03", 2.4), ("2026-01~04", 1.9), ("2026-01~05", 1.4)],
    "china:retail_ex_auto": [("2026-01~02", 3.7), ("2026-03", 3.2), ("2026-04", 1.8), ("2026-05", 1.1)],
    "china:online_retail_ytd": [("2026-01~02", 9.2), ("2026-01~03", 8.0), ("2026-01~04", 6.6), ("2026-01~05", 5.9)],
    "china:online_goods_ytd": [("2026-01~02", 10.3), ("2026-01~03", 7.5), ("2026-01~04", 5.7), ("2026-01~05", 5.0)],
    "china:online_services_ytd": [("2026-01~02", 7.3), ("2026-01~03", 8.8), ("2026-01~04", 8.3), ("2026-01~05", 7.6)],
    "china:industrial_output": [("2026-01", 5.8), ("2026-02", 5.9), ("2026-03", 7.7), ("2026-04", 6.1), ("2026-05", 5.6)],
    "us:cpi": [("2026-01", 3.0), ("2026-02", 2.8), ("2026-03", 2.4), ("2026-04", 2.3), ("2026-05", 2.4)],
    "us:ppi": [("2026-01", 3.7), ("2026-02", 3.2), ("2026-03", 2.7), ("2026-04", 2.5), ("2026-05", 2.6)],
    "us:ism_pmi": [("2026-01", 50.9), ("2026-02", 50.3), ("2026-03", 49.0), ("2026-04", 48.7), ("2026-05", 48.5)],
    "japan:cpi": [("2025-12", 3.0), ("2026-01", 3.2), ("2026-02", 3.0), ("2026-03", 3.2), ("2026-04", 3.2)],
    "japan:ppi": [("2026-01", 4.2), ("2026-02", 4.1), ("2026-03", 4.2), ("2026-04", 4.0), ("2026-05", 4.0)],
    "japan:pmi": [("2026-01", 48.7), ("2026-02", 49.0), ("2026-03", 48.4), ("2026-04", 48.7), ("2026-05", 50.4)],
    "europe:hicp": [("2026-01", 2.5), ("2026-02", 2.3), ("2026-03", 2.2), ("2026-04", 2.2), ("2026-05", 1.9)],
    "europe:ppi": [("2025-12", -0.1), ("2026-01", 1.7), ("2026-02", 3.0), ("2026-03", 1.9), ("2026-04", 0.7)],
    "europe:pmi": [("2026-01", 46.6), ("2026-02", 47.6), ("2026-03", 48.6), ("2026-04", 49.0), ("2026-05", 49.4)],
}


MACRO_HISTORY.update(
    {
        "china:gdp_yoy": [("2025-Q1", 5.4), ("2025-Q2", 5.2), ("2025-Q3", 4.8), ("2025-Q4", 4.5), ("2026-Q1", 5.0)],
        "china:fai_ytd_yoy": [("2026-01~03", 1.7), ("2026-01~04", -1.6), ("2026-01~05", -4.1)],
        "china:urban_unemployment": [("2026-02", 5.3), ("2026-03", 5.4), ("2026-04", 5.2), ("2026-05", 5.1)],
        "china:major_city_unemployment": [("2026-02", 5.1), ("2026-03", 5.3), ("2026-04", 5.2), ("2026-05", 5.1)],
        "china:weekly_hours": [("2026-02", 48.1), ("2026-03", 48.1), ("2026-04", 48.0), ("2026-05", 48.2)],
        "us:real_gdp_saar": [("2025-Q4", 0.5), ("2026-Q1", 1.6)],
        "us:private_final_sales": [("2026-Q1 初值", 2.5), ("2026-Q1 二次", 2.4)],
        "us:unemployment_rate": [("2026-04", 4.3), ("2026-05", 4.3)],
        "us:nonfarm_payrolls": [("2026-03", 214), ("2026-04", 179), ("2026-05", 172)],
        "us:labor_force_participation": [("2026-04", 61.8), ("2026-05", 61.8)],
        "japan:real_gdp_saar": [("2025-Q4", 0.7), ("2026-Q1", 1.8)],
        "japan:real_gdp_qoq": [("2025-Q4", 0.2), ("2026-Q1", 0.5)],
        "japan:unemployment_rate": [("2026-03", 2.7), ("2026-04", 2.5)],
        "europe:real_gdp_qoq": [("2025-Q4", 0.2), ("2026-Q1", -0.2)],
        "europe:real_gdp_yoy": [("2025-Q4", 1.2), ("2026-Q1", 0.3)],
        "europe:employment_qoq": [("2025-Q4", 0.2), ("2026-Q1", 0.1)],
        "europe:unemployment_rate": [("2026-03", 6.3), ("2026-04", 6.3)],
    }
)


async def fetch_nbs_production_material_group(
    client: httpx.AsyncClient,
) -> tuple[dict[str, Any] | None, str]:
    fetch_error = ""
    url = NBS_PRODUCTION_MATERIAL_FALLBACK_URL
    try:
        latest_url = await fetch_latest_nbs_production_material_url(client)
        if latest_url:
            url = latest_url
    except (httpx.HTTPError, ValueError) as exc:
        fetch_error = f"国家统计局最新发布列表读取失败，改用固定入口：{type(exc).__name__}"

    try:
        response = await client.get(url, headers=nbs_headers())
        response.raise_for_status()
        rows, metadata = parse_nbs_production_material_page(response.text, url)
        if not rows:
            raise ValueError("未解析到生产资料价格表")
        group = build_nbs_production_material_group(rows, metadata)
        return group, fetch_error
    except (httpx.HTTPError, ValueError) as exc:
        group = build_nbs_production_material_group(
            fallback_nbs_production_material_rows(),
            {
                "period": NBS_PRODUCTION_MATERIAL_FALLBACK_PERIOD,
                "previousPeriod": NBS_PRODUCTION_MATERIAL_FALLBACK_PREVIOUS,
                "summary": NBS_PRODUCTION_MATERIAL_FALLBACK_SUMMARY,
                "url": NBS_PRODUCTION_MATERIAL_FALLBACK_URL,
                "fallback": True,
            },
        )
        detail = f"国家统计局生产资料价格抓取失败，已使用{NBS_PRODUCTION_MATERIAL_FALLBACK_PERIOD}兜底：{type(exc).__name__}"
        return group, "；".join(part for part in [fetch_error, detail] if part)


async def fetch_latest_nbs_production_material_url(client: httpx.AsyncClient) -> str:
    response = await client.get(NBS_RELEASE_LIST_URL, headers=nbs_headers())
    response.raise_for_status()
    latest_url = extract_latest_nbs_production_material_url(response.text)
    if not latest_url:
        raise ValueError("列表中未找到流通领域生产资料价格发布")
    return latest_url


def extract_latest_nbs_production_material_url(html: str) -> str:
    for href, label in re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, flags=re.I | re.S):
        title = normalize_text(clean_html_fragment(label))
        if NBS_PRODUCTION_MATERIAL_TITLE in title:
            return urljoin(NBS_RELEASE_LIST_URL, href)
    return ""


def parse_nbs_production_material_page(
    html: str,
    url: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    lines = html_to_text_lines(html)
    joined = " ".join(lines)
    period = extract_nbs_period(joined) or NBS_PRODUCTION_MATERIAL_FALLBACK_PERIOD
    previous_period = extract_nbs_previous_period(joined)
    summary = extract_nbs_summary(joined)
    rows: list[dict[str, Any]] = []
    current_category = ""
    index = 0
    while index < len(lines):
        line = lines[index]
        if rows and (line.startswith("注：上期") or line == "附注"):
            break
        category = extract_nbs_category(line)
        if category:
            current_category = category
            index += 1
            continue
        unit_index = find_nbs_row_unit_index(lines, index)
        if current_category and unit_index > index and not is_nbs_table_header(line):
            rows.append(
                {
                    "category": current_category,
                    "name": normalize_product_name("".join(lines[index:unit_index])),
                    "rawUnit": normalize_text(lines[unit_index]),
                    "price": safe_float(lines[unit_index + 1]),
                    "change": safe_float(lines[unit_index + 2]),
                    "changePct": safe_float(lines[unit_index + 3]),
                }
            )
            index = unit_index + 4
            continue
        index += 1

    metadata = {
        "period": period,
        "previousPeriod": previous_period,
        "summary": summary,
        "url": url,
        "fallback": False,
    }
    return rows, metadata


def build_nbs_production_material_group(
    rows: list[dict[str, Any]],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    period = str(metadata.get("period") or NBS_PRODUCTION_MATERIAL_FALLBACK_PERIOD)
    previous_period = str(metadata.get("previousPeriod") or "")
    summary = metadata.get("summary") if isinstance(metadata.get("summary"), dict) else {}
    source = "国家统计局 / 中国统计信息服务中心 / 卓创资讯"
    headline = format_nbs_summary(summary)
    items = []
    for index, row in enumerate(rows, start=1):
        price = safe_float(row.get("price"))
        change = safe_float(row.get("change"))
        change_pct = safe_float(row.get("changePct"))
        previous = round(price - change, 1) if price is not None and change is not None else None
        unit = f"元/{row.get('rawUnit') or ''}".rstrip("/")
        note_parts = [
            f"较上期{format_signed_decimal(change)}元" if change is not None else "",
            f"涨跌幅{format_signed_decimal(change_pct)}%" if change_pct is not None else "",
            f"上期为{previous_period}" if previous_period else "",
            headline,
        ]
        if metadata.get("fallback"):
            note_parts.append("网络不可用时使用内置兜底")
        items.append(
            item(
                f"nbs_material_{index:02d}",
                str(row.get("name") or ""),
                format_decimal(price),
                unit,
                period,
                format_decimal(previous),
                str(row.get("category") or "生产资料"),
                source,
                "；".join(part for part in note_parts if part),
            )
        )
    return {
        "name": "流通生产资料价格",
        "items": items,
    }


def fallback_nbs_production_material_rows() -> list[dict[str, Any]]:
    return [
        {
            "category": category,
            "name": name,
            "rawUnit": raw_unit,
            "price": price,
            "change": change,
            "changePct": change_pct,
        }
        for category, name, raw_unit, price, change, change_pct in NBS_PRODUCTION_MATERIAL_FALLBACK_ROWS
    ]


def html_to_text_lines(html: str) -> list[str]:
    text = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    text = re.sub(r"<script\b.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", "\n", text)
    return [line for line in (normalize_text(line) for line in unescape(text).splitlines()) if line]


def clean_html_fragment(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", unescape(html))


def normalize_text(value: Any) -> str:
    text = str(value or "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def normalize_product_name(value: str) -> str:
    text = normalize_text(value)
    text = re.sub(r"Φ\s+", "Φ", text)
    text = re.sub(r"\s+大卡", "大卡", text)
    text = re.sub(r"\s+级", "级", text)
    return text


def extract_nbs_period(text: str) -> str:
    match = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(上旬|中旬|下旬)流通领域重要生产资料市场价格变动情况", text)
    if not match:
        match = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(上旬|中旬|下旬)", text)
    if not match:
        return ""
    year, month, ten_day = match.groups()
    return f"{int(year):04d}-{int(month):02d}{ten_day}"


def extract_nbs_previous_period(text: str) -> str:
    match = re.search(r"上期为\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(上旬|中旬|下旬)", text)
    if not match:
        return ""
    year, month, ten_day = match.groups()
    return f"{int(year):04d}-{int(month):02d}{ten_day}"


def extract_nbs_summary(text: str) -> dict[str, int]:
    match = re.search(r"(\d+)\s*种产品价格上涨，\s*(\d+)\s*种下降，\s*(\d+)\s*种持平", text)
    if not match:
        return {}
    up, down, flat = (int(value) for value in match.groups())
    return {"up": up, "down": down, "flat": flat}


def extract_nbs_category(text: str) -> str:
    match = re.match(r"^[一二三四五六七八九十]+、(.+)$", text)
    return normalize_text(match.group(1)) if match else ""


def is_nbs_table_header(text: str) -> bool:
    return text in {"产品名称", "单位", "本期价格（元）", "比上期", "价格涨跌（元）", "涨跌幅", "（%）"}


def find_nbs_row_unit_index(lines: list[str], start: int) -> int:
    for index in range(start + 1, min(start + 14, len(lines) - 3)):
        if normalize_text(lines[index]) not in {"吨", "千克"}:
            continue
        if looks_like_number(lines[index + 1]) and looks_like_number(lines[index + 2]) and looks_like_number(lines[index + 3]):
            return index
    return -1


def looks_like_number(text: str) -> bool:
    return bool(re.fullmatch(r"[+-]?\d+(?:\.\d+)?", normalize_text(text)))


def safe_float(value: Any) -> float | None:
    try:
        if value in (None, "-", ""):
            return None
        return float(str(value).replace(",", "").replace("+", "").strip())
    except (TypeError, ValueError):
        return None


def format_decimal(value: float | None) -> str | None:
    return None if value is None else f"{value:.1f}"


def format_signed_decimal(value: float | None) -> str:
    if value is None:
        return ""
    prefix = "+" if value > 0 else ""
    return f"{prefix}{value:.1f}"


def format_nbs_summary(summary: dict[str, int]) -> str:
    if not summary:
        return "流通领域9大类50种重要生产资料"
    return f"{summary.get('up', 0)}涨{summary.get('down', 0)}降{summary.get('flat', 0)}平"


def nbs_headers() -> dict[str, str]:
    return {
        "User-Agent": user_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://www.stats.gov.cn/",
    }


def build_macro_countries(extra_groups_by_country: dict[str, list[dict[str, Any]]] | None = None) -> list[dict[str, Any]]:
    countries = json.loads(json.dumps(MACRO_COUNTRIES, ensure_ascii=False))
    for country in countries:
        country_id = country.get("id", "")
        extra_groups = ADDITIONAL_MACRO_GROUPS.get(country_id, [])
        if extra_groups:
            country.setdefault("groups", []).extend(json.loads(json.dumps(extra_groups, ensure_ascii=False)))
        dynamic_groups = (extra_groups_by_country or {}).get(country_id, [])
        if dynamic_groups:
            country.setdefault("groups", []).extend(json.loads(json.dumps(dynamic_groups, ensure_ascii=False)))
        for group in country.get("groups", []):
            for row in group.get("items", []):
                row["history"] = build_history(country_id, row)
                apply_forecast(country_id, row)
    return repair_mojibake(countries)


def apply_forecast(country_id: str, row: dict[str, Any]) -> None:
    forecast = MACRO_FORECASTS.get(f"{country_id}:{row.get('id', '')}")
    if forecast:
        row.update(forecast)


def repair_mojibake(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: repair_mojibake(item) for key, item in value.items()}
    if isinstance(value, list):
        return [repair_mojibake(item) for item in value]
    if not isinstance(value, str):
        return value
    try:
        raw = bytearray()
        for char in value:
            codepoint = ord(char)
            if codepoint <= 0xFF:
                raw.append(codepoint)
            else:
                raw.extend(char.encode("cp1252"))
        return raw.decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value


def build_history(country_id: str, row: dict[str, Any]) -> list[dict[str, Any]]:
    key = f"{country_id}:{row.get('id', '')}"
    points = MACRO_HISTORY.get(key)
    if not points:
        points = fallback_history(row)
    return [{"period": period, "value": value} for period, value in points]


def fallback_history(row: dict[str, Any]) -> list[tuple[str, float]]:
    current = parse_numeric(row.get("value"))
    previous = parse_numeric(row.get("previous"))
    period = str(row.get("period") or "最新")
    if current is None:
        return []
    if previous is None:
        return [(period, current)]
    return [("前值", previous), (period, current)]


def parse_numeric(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).split("-")[0])
    except ValueError:
        return None


async def get_macro(refresh: bool = False, allow_stale: bool = True, force: bool = False) -> dict[str, Any]:
    config = load_config()
    fetch_config = config.get("fetch", {})
    ttl_seconds = int(fetch_config.get("min_refresh_interval_seconds", 1800))
    db_path = resolve_sqlite_path(config)

    async with MACRO_CACHE_LOCK:
        if (
            not force
            and not refresh
            and MACRO_CACHE["data"]
            and MACRO_CACHE["data"].get("schemaVersion") == MACRO_SCHEMA_VERSION
            and datetime.now(UTC) < MACRO_CACHE["expires_at"]
        ):
            cached = dict(MACRO_CACHE["data"])
            cached["cached"] = True
            cached["fromStorage"] = False
            cached["throttled"] = False
            return cached

    stored = await load_latest_macro(db_path)
    stored_schema_valid = bool(stored and stored.get("schemaVersion") == MACRO_SCHEMA_VERSION)
    stored_is_fresh = bool(stored_schema_valid and parse_dt(stored.get("expiresAt")) > datetime.now(UTC))
    if not force and stored and stored_schema_valid and ((allow_stale and not refresh) or stored_is_fresh):
        stored["cached"] = True
        stored["fromStorage"] = True
        stored["throttled"] = refresh
        stored["stale"] = not stored_is_fresh
        async with MACRO_CACHE_LOCK:
            MACRO_CACHE["data"] = stored
            MACRO_CACHE["expires_at"] = parse_dt(stored.get("expiresAt"))
        return stored

    errors: list[str] = []
    dynamic_groups: dict[str, list[dict[str, Any]]] = {}
    timeout = float(fetch_config.get("request_timeout_seconds", 8))
    async with httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(timeout)) as client:
        production_material_group, production_material_error = await fetch_nbs_production_material_group(client)
    if production_material_group:
        dynamic_groups.setdefault("china", []).append(production_material_group)
    if production_material_error:
        errors.append(production_material_error)

    now = datetime.now(UTC)
    data = {
        "schemaVersion": MACRO_SCHEMA_VERSION,
        "generatedAt": now.isoformat(),
        "savedAt": now.isoformat(),
        "expiresAt": (now + timedelta(seconds=ttl_seconds)).isoformat(),
        "cached": False,
        "fromStorage": False,
        "throttled": False,
        "hasData": True,
        "source": "官方统计口径 / 已配置宏观观察池 / 国家统计局流通领域生产资料价格旬报",
        "cadence": "半小时最多刷新一次；流通领域生产资料价格按国家统计局旬报更新",
        "errors": errors,
        "countries": build_macro_countries(dynamic_groups),
    }
    data = repair_mojibake(data)
    await save_latest_macro(db_path, data)
    async with MACRO_CACHE_LOCK:
        MACRO_CACHE["data"] = data
        MACRO_CACHE["expires_at"] = parse_dt(data["expiresAt"])
    return data


async def load_latest_macro(db_path: Path) -> dict[str, Any] | None:
    async with DB_LOCK:
        return await asyncio.to_thread(load_latest_macro_sync, db_path)


async def save_latest_macro(db_path: Path, data: dict[str, Any]) -> None:
    async with DB_LOCK:
        await asyncio.to_thread(save_latest_macro_sync, db_path, data)


def load_latest_macro_sync(db_path: Path) -> dict[str, Any] | None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS latest_macro (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                generated_at TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        row = conn.execute("SELECT payload FROM latest_macro WHERE id = 1").fetchone()
    if not row:
        return None
    return json.loads(row[0])


def save_latest_macro_sync(db_path: Path, data: dict[str, Any]) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS latest_macro (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                generated_at TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO latest_macro (id, generated_at, payload)
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                generated_at = excluded.generated_at,
                payload = excluded.payload
            """,
            (data.get("generatedAt", ""), json.dumps(data, ensure_ascii=False)),
        )
        conn.commit()


def parse_dt(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=UTC)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
