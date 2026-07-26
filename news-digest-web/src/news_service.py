from __future__ import annotations

import asyncio
import html
import json
import random
import re
import sqlite3
from collections import defaultdict
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from xml.etree import ElementTree

import httpx

from .request_coordinator import coordinate_httpx_client

ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT_DIR / "config" / "sources.json"
CACHE_LOCK = asyncio.Lock()
DB_LOCK = asyncio.Lock()
CACHE: dict[str, Any] = {"expires_at": datetime.min.replace(tzinfo=UTC), "data": None}
BEIJING_TZ = timezone(timedelta(hours=8))
NEWS_SCHEMA_VERSION = 21
NEWS_RETENTION_DAYS = 7
TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"
TRANSLATE_DOMAIN = "translate.googleapis.com"
TRANSLATE_BATCH_SIZE = 12
STRICT_TRANSLATE_PER_SECTION = 12
TRANSLATE_RETRIES = 3
ALLOWED_TITLE_ENGLISH = {
    "AI",
    "OPENAI",
    "BYD",
    "CVC",
    "DDN",
    "ETF",
    "GDP",
    "OPEC",
    "NATO",
    "JD",
    "UNITREE",
    "SPACEX",
    "FTSE",
    "HSBC",
    "SK",
    "CRUSOE",
    "MUJIN",
    "IPO",
    "CEO",
    "GCC",
    "EV",
    "PBOC",
    "HKEX",
    "HKMA",
    "HKSAR",
    "HANG",
    "SENG",
    "METAX",
    "JPMORGAN",
    "JPM",
    "SPACEXIPO",
    "WOODSIDE",
    "PETROCHINA",
    "BROWSE",
    "ELEVENLABS",
}
ENGLISH_RESIDUE_RE = re.compile(r"[A-Za-z]{3,}")
COMMON_ENGLISH_TITLE_WORDS = {
    "about",
    "after",
    "again",
    "against",
    "ahead",
    "alleged",
    "amid",
    "among",
    "around",
    "asks",
    "based",
    "before",
    "behind",
    "between",
    "billion",
    "buys",
    "chair",
    "could",
    "cuts",
    "developing",
    "finally",
    "from",
    "grand",
    "help",
    "indicts",
    "into",
    "joins",
    "jury",
    "limited",
    "long",
    "loom",
    "management",
    "markets",
    "million",
    "minutes",
    "morning",
    "over",
    "path",
    "plans",
    "plot",
    "public",
    "raise",
    "raises",
    "remain",
    "reports",
    "reserve",
    "says",
    "sale",
    "share",
    "shares",
    "sources",
    "trust",
    "under",
    "with",
    "warns",
    "would",
}
LOW_VALUE_TITLE_RE = re.compile(
    r"^(stocks|commodities|sector & industry performance|joe weisenthal|tracy alloway)$",
    re.I,
)
SPORTS_NOISE_RE = re.compile(
    r"\b(set-piece|fighting spirit|triumphs over|defeat by|coach .* better team won)\b",
    re.I,
)
GENERIC_TITLES = {
    "中国相关事件出现新进展",
    "香港市场与政策消息出现变化",
    "国际要闻出现新变化",
    "全球市场走势出现变化",
    "大宗能源出现新变化",
    "中东局势继续影响市场",
    "俄乌局势出现新进展",
    "AI与芯片产业消息影响市场",
    "AI芯片与科技股受关注",
    "贸易政策变化牵动市场",
    "制裁与限制措施出现新变化",
}

HONG_KONG_TERMS = [
    "hong kong",
    "hongkong",
    "hksar",
    "hkex",
    "hkma",
    "hang seng",
    "h shares",
    "h-shares",
    "h share",
    "h-share",
    "hong kong dollar",
    "hkd",
    "cathay pacific",
    "港股",
    "香港",
    "恒生",
    "港交所",
    "香港金管局",
    "港元",
    "国泰航空",
]

MACAU_TERMS = [
    "macau",
    "macao",
    "macanese",
    "macau sar",
    "macao sar",
    "澳門",
    "澳门",
]

CHINA_TERMS = [
    "china",
    "chinese",
    "beijing",
    "shanghai",
    *HONG_KONG_TERMS,
    *MACAU_TERMS,
    "taiwan",
    "xi jinping",
    "yuan",
    "renminbi",
    "pboc",
    "byd",
    "huawei",
    "tencent",
    "alibaba",
    "property",
    "中国",
    "北京",
    "上海",
    "香港",
    "台湾",
    "人民币",
    "央行",
    "华为",
    "腾讯",
    "阿里",
]

WORLD_TERMS = [
    "fed",
    "trump",
    "white house",
    "ukraine",
    "russia",
    "israel",
    "iran",
    "oil",
    "opec",
    "nato",
    "tariff",
    "inflation",
    "rates",
    "ai",
    "nvidia",
    "election",
    "central bank",
    "stocks",
    "markets",
    "economy",
    "treasury",
    "dollar",
    "earnings",
    "europe",
    "japan",
    "india",
    "middle east",
    "gaza",
    "全球",
    "战争",
    "通胀",
    "能源",
]

IMPORTANT_TERMS = [
    *CHINA_TERMS,
    *WORLD_TERMS,
    "breaking",
    "exclusive",
    "deal",
    "merger",
    "sanctions",
    "court",
    "crisis",
    "economy",
    "growth",
    "bank",
    "shares",
    "科技",
    "金融",
    "贸易",
    "制裁",
    "危机",
]

SECTION_QUERY_PROFILES = [
    {
        "section": "china",
        "query": (
            "China OR Chinese OR Beijing OR Shanghai OR Shenzhen OR \"Hong Kong\" OR Hongkong OR "
            "HKSAR OR Macau OR Macao OR Taiwan OR PBOC OR yuan OR renminbi OR BYD OR "
            "Huawei OR Tencent OR Alibaba OR JD OR property"
        ),
        "hl": "en-US",
        "gl": "US",
        "ceid": "US:en",
    },
    {
        "section": "china",
        "query": "中国 OR 香港 OR 澳门 OR 澳門 OR 台湾 OR 北京 OR 上海 OR 深圳 OR 人民币 OR 央行 OR 港股 OR 房地产 OR 科技",
        "hl": "zh-CN",
        "gl": "CN",
        "ceid": "CN:zh-Hans",
    },
    {
        "section": "world",
        "query": (
            "Fed OR Federal Reserve OR Trump OR White House OR Ukraine OR Russia OR Israel OR "
            "Iran OR Gaza OR oil OR OPEC OR NATO OR tariff OR inflation OR rates OR election OR "
            "AI OR Nvidia OR markets OR economy OR central bank OR Europe OR Japan OR India"
        ),
        "hl": "en-US",
        "gl": "US",
        "ceid": "US:en",
    },
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]

TITLE_PATTERNS = [
    (re.compile(r"chinese chipmaker metax.*hong kong listing|metax.*hong kong listing", re.I), "中国芯片制造商沐曦计划赴港上市，借IPO热潮"),
    (re.compile(r"hedge funds sold broader tech.*spacex ipo|spacex ipo.*jpmorgan data", re.I), "摩根大通数据：对冲基金在SpaceX IPO前减持科技股"),
    (re.compile(r"asia gold.*india gold demand.*china premiums", re.I), "亚洲黄金：价格回落提振印度需求，中国黄金升水收窄"),
    (re.compile(r"pilot union.*european regulators.*labor loophole", re.I), "飞行员工会拟敦促欧洲监管机构堵住劳工漏洞"),
    (re.compile(r"chinese robot appliance maker dreame tech.*hong kong", re.I), "追觅科技据悉考虑赴港IPO"),
    (re.compile(r"humanoid robot manufacturer engineai.*hong kong ipo", re.I), "众擎机器人据悉已提交香港IPO申请"),
    (re.compile(r"woodside.*pre-emptive right.*petrochina.*browse", re.I), "伍德赛德行使优先购买权，拟买下中石油Browse项目权益"),
    (re.compile(r"london.*ai ecosystem.*elevenlabs", re.I), "ElevenLabs CEO称伦敦AI生态从未如此强劲"),
    (re.compile(r"elliott mulls.*takeover.*very group", re.I), "Elliott据悉考虑以26.7亿美元收购英国The Very Group"),
    (re.compile(r"anthropic.*data center leases.*google", re.I), "Anthropic寻求数据中心租约，并向Google寻求资金支持"),
    (re.compile(r"dazn.*directv latin america.*world cup", re.I), "DAZN与DirecTV拉美在世界杯前达成体育频道协议"),
    (re.compile(r"^commodities$", re.I), "大宗商品"),
    (re.compile(r"^stocks$", re.I), "股市"),
    (re.compile(r"china credit growth.*tops forecasts|rebound from lending slump", re.I), "中国信贷增长超预期，贷款低迷后回升"),
    (re.compile(r"alibaba bids.*china grocer|fight with meituan", re.I), "阿里巴巴出价15亿美元收购中国杂货商，对抗美团"),
    (re.compile(r"china asks big banks.*interbank lending|ease cash glut", re.I), "中国要求大型银行限制同业拆借以缓解资金过剩"),
    (re.compile(r"china confirms arrest.*american citizen.*spying", re.I), "中国证实以间谍罪逮捕一名美国公民"),
    (re.compile(r"china arrests us scholar.*myanmar.*spying", re.I), "中国以涉嫌间谍罪逮捕美国缅甸问题学者"),
    (re.compile(r"china.*coal.*coal-to-oil.*energy security", re.I), "中国主要产煤地区将扩大煤制油以保障能源安全"),
    (re.compile(r"spacex playbook.*china.*ipo", re.I), "SpaceX模式助推中国IPO雄心，但技术差距仍在"),
    (re.compile(r"spacex.*order book.*chinese ipos", re.I), "SpaceX千亿美元订单仍小于中国热门IPO规模"),
    (re.compile(r"red-hot spacex ipo.*retail buyers", re.I), "火热的SpaceX IPO可能让散户投资者受伤"),
    (re.compile(r"nvidia hires.*bruce andrews.*government affairs", re.I), "英伟达聘请资深游说人士负责政府事务"),
    (re.compile(r"world chess body suspends russia|chess body.*russia", re.I), "国际棋联暂停俄罗斯会员资格"),
    (re.compile(r"taiwan.*china coast guard.*harassed|coast guard.*commercial shipping", re.I), "台湾称中国海警骚扰商船"),
    (re.compile(r"philippine defence chief|philippine defense chief", re.I), "中国制裁菲律宾防长"),
    (re.compile(r"taiwan simulates destroying.*chinese force|coastal drill", re.I), "台湾演练摧毁登陆部队"),
    (re.compile(r"merz.*eu.*china stand|eu.*tough china stand", re.I), "默茨摇摆削弱欧盟对华强硬立场"),
    (re.compile(r"unitree.*robot reality|china.*robot reality", re.I), "宇树科技折射中国机器人产业压力"),
    (re.compile(r"energy official.*saudi aramco|saudi aramco.*beijing", re.I), "中国能源官员会见沙特阿美高管"),
    (re.compile(r"alibaba.*jd.*price-cut|jd\.com.*price-cut|beijing slams price-cut", re.I), "阿里京东因价格促销监管下跌"),
    (re.compile(r"dingtalk chief.*ai focus|alibaba.*dingtalk", re.I), "阿里钉钉负责人在AI争议后离职"),
    (re.compile(r"changchun.*auto revamp|byd and xiaomi.*ev", re.I), "长春发布汽车改造计划并寻求比亚迪小米助力"),
    (re.compile(r"austin.*china.*taiwan.*force|china will take taiwan by force", re.I), "美国前防长称中国未必会武力攻台"),
    (re.compile(r"mainland chinese savers.*hong kong|capital controls.*hong kong", re.I), "内地储户因资本管制趋严涌向香港"),
    (re.compile(r"pboc adds gold|bullion remains under pressure", re.I), "中国央行再次增持黄金"),
    (re.compile(r"china escalates patrols near taiwan|japan-philippines talks", re.I), "日菲会谈后中国加强台湾附近巡逻"),
    (re.compile(r"indium phosphide exports|ai data centre rollout", re.I), "中国磷化铟出口管制影响AI数据中心"),
    (re.compile(r"iran and ukraine.*g7|g7.*france.*trump", re.I), "伊朗和乌克兰议题笼罩G7峰会"),
    (re.compile(r"gulf markets rebound.*iran.*israel|iran and israel halt attacks", re.I), "伊以停止袭击后海湾市场反弹"),
    (re.compile(r"ai.*mega stock deals|mega stock deals.*shares", re.I), "AI巨额股票交易引发供需担忧"),
    (re.compile(r"brazil senate.*central bank autonomy|central bank autonomy.*lula", re.I), "巴西参院委员会支持央行独立"),
    (re.compile(r"physical oil markets.*floundering|100 days of war", re.I), "百日战事后现货油市仍显低迷"),
    (re.compile(r"japan wholesale inflation|energy costs spike", re.I), "日本批发通胀创三年最快"),
    (re.compile(r"strait of hormuz|gulf will.*continue to rise", re.I), "美国能源部长称霍尔木兹油运出口将增加"),
    (re.compile(r"us trade gap narrows|oil exports offset.*imports", re.I), "美国贸易逆差因石油出口收窄"),
    (re.compile(r"russian urals oil.*discount|asian demand ebbs", re.I), "俄罗斯乌拉尔原油因亚洲需求走弱转为折价"),
    (re.compile(r"crusoe.*wyoming ai|google concerns", re.I), "谷歌担忧后Crusoe被AI项目边缘化"),
    (re.compile(r"thailand.*uyghurs.*death|deadly 2015 blast", re.I), "泰国判处两名维吾尔人死刑"),
    (re.compile(r"ten reasons oil.*below.*100", re.I), "油价仍低于100美元的十个原因"),
    (re.compile(r"nvidia.*sk hynix|multi-year pact.*ai chips", re.I), "英伟达与SK海力士签署AI芯片多年协议"),
    (re.compile(r"hsbc ceo.*gcc|banking amid ai", re.I), "汇丰CEO谈海湾就业和AI下的银行业"),
    (re.compile(r"banks.*workforce cuts.*ai|mass workforce cuts", re.I), "银行为AI推动的大规模裁员做准备"),
    (re.compile(r"trading day.*ai.*fizzling|sizzling ai.*fizzling", re.I), "AI交易热度开始降温"),
    (re.compile(r"factory robot startup mujin|mujin.*ipo", re.I), "机器人初创Mujin为IPO前融资"),
    (re.compile(r"spacex.*ipo market|launch may set.*ipo", re.I), "SpaceX上市预期或抬升IPO市场"),
    (re.compile(r"ftse 100 rises|energy and consumer staples gain", re.I), "英国富时100因能源和消费股上涨"),
    (re.compile(r"openai.*chinese propaganda|propaganda.*tariffs.*data centers", re.I), "OpenAI称中国宣传影响关税和数据中心舆论"),
    (re.compile(r"china inc.*quiet.*layoffs|quiet layoffs.*ai adoption", re.I), "中国企业在AI转型中低调裁员"),
    (re.compile(r"taiwan.*curbs.*ai chip.*exports.*china|ai chip exports.*china.*align", re.I), "台湾考虑限制对华AI芯片出口"),
    (re.compile(r"chinese consumer inflation.*stalls|consumer inflation.*oil shock", re.I), "中国消费通胀意外停滞"),
    (re.compile(r"byd chairman.*biggest automaker|world.?s biggest automaker.*shares slide", re.I), "比亚迪称五年内将成全球最大车企"),
    (re.compile(r"china.*taiwan.*spar.*coast guard|coast guard patrols east", re.I), "中台围绕海警巡逻合法性争执"),
    (re.compile(r"alibaba.*baidu.*pentagon|baidu.*alibaba.*pentagon|accused by pentagon.*chinese military", re.I), "五角大楼指阿里百度协助中国军方"),
    (re.compile(r"copper holds gain.*iran tensions.*china data|copper.*china data", re.I), "铜价受伊朗局势和中国数据影响"),
    (re.compile(r"ai sparks alarm.*protect|protect workers.*ai", re.I), "人工智能风险引发监管讨论"),
    (re.compile(r"ai ambitions.*power.?grid|massive power.?grid", re.I), "中国AI发展依赖电网扩张"),
    (re.compile(r"mega stock trades.*specter|stock trades.*froth", re.I), "AI巨额交易引发股市过热担忧"),
    (re.compile(r"anthropic.*openai|openai.*anthropic", re.I), "人工智能公司法律纠纷升级"),
    (re.compile(r"apollo.*software.*ai|software investments.*ai", re.I), "阿波罗审查软件投资中的AI风险"),
    (re.compile(r"americans wary.*data center|data center boom", re.I), "美国民众担忧AI数据中心扩张"),
    (re.compile(r"cvc.*ai impact.*pe|ai impact.*private equity", re.I), "AI影响私募股权投资判断"),
    (re.compile(r"ai fears.*private equity|private equity tech", re.I), "AI担忧冲击私募科技估值"),
    (re.compile(r"ai data firm.*ddn|ddn.*fresh funding", re.I), "AI数据公司寻求新融资"),
    (re.compile(r"china healthcare.*record low|healthcare.*record low", re.I), "中国医疗股估值跌至低位"),
    (re.compile(r"hengli.*west african|hengli.*middle eastern", re.I), "恒力寻求西非和中东原油供应"),
    (re.compile(r"us hits.*china.*hong kong|china.*hong kong.*sanction", re.I), "美国制裁中国及香港相关实体"),
    (re.compile(r"tencent.*raises.*dual", re.I), "腾讯发行双币债筹资"),
    (re.compile(r"byd.*baidu.*alibaba|baidu.*alibaba", re.I), "美国点名中国科技巨头"),
    (re.compile(r"iron ore.*iran.*china", re.I), "铁矿石暂未受伊朗战事影响"),
    (re.compile(r"emerging-market stocks.*chinese e-commerce", re.I), "中国电商拖累新兴市场股票"),
    (re.compile(r"china learns to live on less fuel|less fuel", re.I), "中国燃油需求下降成新常态"),
    (re.compile(r"beijing.*investment clampdown|investment clampdown", re.I), "北京收紧投资监管"),
    (re.compile(r"kenya airport", re.I), "中国企业获肯尼亚机场改造项目"),
    (re.compile(r"taiwan.*foreign ships|foreign ships.*taiwan", re.I), "中国加大对台湾周边船舶查问"),
    (re.compile(r"taiwan.*won.?t tolerate.*chinese patrols", re.I), "台湾称不会容忍中国巡逻并将驱离"),
    (re.compile(r"china taps commercial oil stocks|commercial oil stocks.*gulf", re.I), "中国动用商业油库存应对海湾风险"),
    (re.compile(r"us seizes.*website domains|website domains.*alleged", re.I), "美国查扣涉嫌违法的网站域名"),
    (re.compile(r"fed.*rate|federal reserve.*rate", re.I), "美联储利率路径受关注"),
    (re.compile(r"oil.*iran|iran.*oil", re.I), "伊朗局势牵动国际油价"),
    (re.compile(r"world markets.*tightrope|tightrope between ai.*oil", re.I), "全球市场在AI股票和油价冲击间摇摆"),
    (re.compile(r"world bank.*global growth|global growth outlook", re.I), "世界银行下调全球经济增长预期"),
    (re.compile(r"breakingviews.*ukraine.*rearm", re.I), "乌克兰可帮助欧洲重整军备"),
    (re.compile(r"ukraine strikes.*logistics", re.I), "乌克兰打击俄占区关键后勤设施"),
    (re.compile(r"equities drop.*oil rallies|oil rallies.*tensions", re.I), "股市下跌、油价因紧张局势上涨"),
    (re.compile(r"ai boom.*memory chip|memory chip.*inflation", re.I), "AI热潮推高存储芯片价格与通胀压力"),
    (re.compile(r"stocks extend rally.*ai-led|ai-led rebound", re.I), "AI反弹带动股市延续涨势"),
    (re.compile(r"thai court sentences.*uyghur", re.I), "泰国法院判处两名维吾尔男子重刑"),
    (re.compile(r"tech stocks dive.*fed.*ai|fed bets.*ai rally", re.I), "美联储预期扰动AI行情，科技股下跌"),
    (re.compile(r"oil crunch.*asia.*coal|asia.*demand for coal", re.I), "石油供应紧张推高亚洲煤炭需求"),
    (re.compile(r"ukraine|russia", re.I), "俄乌局势出现新进展"),
    (re.compile(r"israel|iran", re.I), "中东局势继续影响市场"),
    (re.compile(r"nvidia|ai chip|artificial intelligence", re.I), "AI芯片与科技股受关注"),
    (re.compile(r"tariff|trade", re.I), "贸易政策变化牵动市场"),
]

SUMMARY_PATTERNS = [
    (re.compile(r"chinese chipmaker metax.*hong kong listing|metax.*hong kong listing", re.I), "沐曦计划赴港上市，借香港IPO热潮推进融资。"),
    (re.compile(r"hedge funds sold broader tech.*spacex ipo|spacex ipo.*jpmorgan data", re.I), "摩根大通数据显示，对冲基金在SpaceX IPO前减持科技股。"),
    (re.compile(r"asia gold.*india gold demand.*china premiums", re.I), "金价回落带动印度黄金需求回升，中国黄金升水收窄。"),
    (re.compile(r"pilot union.*european regulators.*labor loophole", re.I), "飞行员工会拟敦促欧洲监管机构堵住航空劳工规则漏洞。"),
    (re.compile(r"chinese robot appliance maker dreame tech.*hong kong", re.I), "追觅科技据悉考虑赴港IPO，硬件企业融资热度延续。"),
    (re.compile(r"humanoid robot manufacturer engineai.*hong kong ipo", re.I), "众擎机器人据悉提交香港IPO申请，机器人企业赴港融资升温。"),
    (re.compile(r"woodside.*pre-emptive right.*petrochina.*browse", re.I), "伍德赛德拟行使优先购买权，收购中石油Browse项目权益。"),
    (re.compile(r"london.*ai ecosystem.*elevenlabs", re.I), "ElevenLabs CEO称伦敦AI生态强劲，欧洲AI创业环境受关注。"),
    (re.compile(r"elliott mulls.*takeover.*very group", re.I), "Elliott据悉考虑收购英国电商金融集团The Very Group。"),
    (re.compile(r"anthropic.*data center leases.*google", re.I), "Anthropic寻求数据中心租约，并向Google寻求资金支持。"),
    (re.compile(r"dazn.*directv latin america.*world cup", re.I), "DAZN与DirecTV拉美在世界杯前达成体育频道合作。"),
    (re.compile(r"openai.*chinese propaganda|propaganda.*tariffs.*data centers", re.I), "OpenAI称中国宣传内容被用于影响关税和数据中心议题舆论。"),
    (re.compile(r"china inc.*quiet.*layoffs|quiet layoffs.*ai adoption", re.I), "北京推动AI应用时，部分中国企业以低调方式裁员。"),
    (re.compile(r"taiwan.*curbs.*ai chip.*exports.*china|ai chip exports.*china.*align", re.I), "台湾考虑配合美国，限制AI芯片出口至中国大陆。"),
    (re.compile(r"chinese consumer inflation.*stalls|consumer inflation.*oil shock", re.I), "油价冲击下，中国消费通胀仍意外停滞。"),
    (re.compile(r"byd chairman.*biggest automaker|world.?s biggest automaker.*shares slide", re.I), "比亚迪董事长称公司五年内有望成为全球最大车企。"),
    (re.compile(r"china.*taiwan.*spar.*coast guard|coast guard patrols east", re.I), "中台围绕海警在台湾以东巡逻的合法性发生争执。"),
    (re.compile(r"alibaba.*baidu.*pentagon|baidu.*alibaba.*pentagon|accused by pentagon.*chinese military", re.I), "五角大楼指称阿里巴巴、百度等协助中国军方。"),
    (re.compile(r"copper holds gain.*iran tensions.*china data|copper.*china data", re.I), "铜价受伊朗紧张缓和和中国经济数据共同影响。"),
    (re.compile(r"hengli.*west african|hengli.*middle eastern", re.I), "恒力寻求更多原油来源，关注能源供应链变化。"),
    (re.compile(r"us hits.*china.*hong kong|china.*hong kong.*sanction", re.I), "美国扩大制裁范围，波及中国和香港实体。"),
    (re.compile(r"tencent.*raises.*dual", re.I), "腾讯通过双币债融资，显示大型科技公司融资活跃。"),
    (re.compile(r"byd.*baidu.*alibaba|baidu.*alibaba", re.I), "美国称多家中国科技公司与军方存在关联。"),
    (re.compile(r"iron ore.*iran.*china", re.I), "铁矿石暂未受战事冲击，中国需求仍是关键。"),
    (re.compile(r"emerging-market stocks.*chinese e-commerce", re.I), "中国电商股走弱，拖累新兴市场风险偏好。"),
    (re.compile(r"china learns to live on less fuel|less fuel", re.I), "中国燃油需求放缓，缓解全球油市压力。"),
    (re.compile(r"beijing.*investment clampdown|investment clampdown", re.I), "投资监管趋严，企业扩张和市场预期受压。"),
    (re.compile(r"kenya airport", re.I), "中国企业拿下机场项目，海外基建继续推进。"),
    (re.compile(r"taiwan.*foreign ships|foreign ships.*taiwan", re.I), "中方查问外籍船舶，台海航运压力升温。"),
    (re.compile(r"fed.*rate|federal reserve.*rate", re.I), "市场关注美联储降息节奏和通胀判断。"),
    (re.compile(r"oil.*iran|iran.*oil", re.I), "地缘风险推高油市波动，供应预期受扰动。"),
    (re.compile(r"ukraine|russia", re.I), "俄乌相关消息影响安全局势和欧洲市场。"),
    (re.compile(r"israel|iran", re.I), "中东冲突升温，能源和避险资产受关注。"),
    (re.compile(r"nvidia|ai chip|artificial intelligence", re.I), "AI产业链消息继续影响科技股表现。"),
    (re.compile(r"tariff|trade", re.I), "贸易政策变化影响企业成本和市场预期。"),
]

DETAIL_PATTERNS = [
    (
        re.compile(r"chinese chipmaker metax.*hong kong listing|metax.*hong kong listing", re.I),
        "沐曦计划赴港上市，核心看点是中国芯片企业能否借香港IPO窗口补充资本。后续关注估值、募资规模、监管进展，以及国产芯片融资情绪是否继续回暖。",
    ),
    (
        re.compile(r"hedge funds sold broader tech.*spacex ipo|spacex ipo.*jpmorgan data", re.I),
        "摩根大通数据指向对冲基金在SpaceX IPO前减持更广泛科技股。重点看资金是否从二级市场科技股转向一级市场热门标的，以及AI和航天概念估值是否受影响。",
    ),
    (
        re.compile(r"asia gold.*india gold demand.*china premiums", re.I),
        "亚洲黄金市场中，价格回落提振印度需求，同时中国黄金升水收窄。重点看实物买盘是否延续、人民币金价表现，以及央行和消费者需求对金价的支撑。",
    ),
    (
        re.compile(r"pilot union.*european regulators.*labor loophole", re.I),
        "飞行员工会计划敦促欧洲监管机构堵住航空劳工规则漏洞。重点看航空公司用工成本、跨境运营安排，以及监管收紧是否影响欧洲航空业利润率。",
    ),
    (
        re.compile(r"chinese robot appliance maker dreame tech.*hong kong", re.I),
        "追觅科技据悉考虑赴港IPO，显示中国硬件和机器人相关企业仍在寻找融资窗口。后续关注估值、募资用途，以及港股对智能硬件标的接受度。",
    ),
    (
        re.compile(r"humanoid robot manufacturer engineai.*hong kong ipo", re.I),
        "众擎机器人据悉提交香港IPO申请，反映人形机器人企业融资热度。重点看商业化进度、订单质量和港股投资者对机器人赛道的估值定价。",
    ),
    (
        re.compile(r"woodside.*pre-emptive right.*petrochina.*browse", re.I),
        "伍德赛德拟行使优先购买权，收购中石油在Browse合资项目中的权益。重点看交易价格、项目天然气开发进度，以及中石油海外资产组合是否继续调整。",
    ),
    (
        re.compile(r"london.*ai ecosystem.*elevenlabs", re.I),
        "ElevenLabs CEO称伦敦AI生态从未如此强劲。重点看欧洲AI创业融资、人才流动和监管环境，以及伦敦能否继续吸引生成式AI公司扩张。",
    ),
    (
        re.compile(r"elliott mulls.*takeover.*very group", re.I),
        "Elliott据悉考虑以26.7亿美元收购英国The Very Group。重点看私募和激进投资者对英国消费金融、电商资产的估值判断，以及交易是否引发更多并购。",
    ),
    (
        re.compile(r"anthropic.*data center leases.*google", re.I),
        "Anthropic寻求数据中心租约，并向Google寻求资金支持。重点看AI算力租赁成本、云厂商绑定关系，以及大模型公司资本开支压力是否继续上升。",
    ),
    (
        re.compile(r"dazn.*directv latin america.*world cup", re.I),
        "DAZN与DirecTV拉美在世界杯前达成体育频道合作。重点看赛事版权、拉美付费电视分发，以及世界杯周期对体育流媒体商业化的拉动。",
    ),
    (
        re.compile(r"openai.*chinese propaganda|propaganda.*tariffs.*data centers", re.I),
        "报道聚焦OpenAI对信息影响活动的说法，涉及关税和数据中心争议。重点看美国监管回应、平台处置，以及相关叙事是否影响企业和政策讨论。",
    ),
    (
        re.compile(r"china inc.*quiet.*layoffs|quiet layoffs.*ai adoption", re.I),
        "报道指部分中国企业在推进AI采用时采取低调裁员。重点看AI替代岗位的速度、企业成本控制，以及北京推动技术升级与就业稳定之间的平衡。",
    ),
    (
        re.compile(r"taiwan.*curbs.*ai chip.*exports.*china|ai chip exports.*china.*align", re.I),
        "台湾考虑限制AI芯片出口至中国大陆，以便与美国管制方向保持一致。重点看半导体供应链、台企订单和中美科技限制是否进一步收紧。",
    ),
    (
        re.compile(r"chinese consumer inflation.*stalls|consumer inflation.*oil shock", re.I),
        "中国消费通胀在油价冲击下仍意外停滞，说明内需和价格传导偏弱。重点看货币政策空间、消费恢复和企业定价能力。",
    ),
    (
        re.compile(r"byd chairman.*biggest automaker|world.?s biggest automaker.*shares slide", re.I),
        "比亚迪董事长称公司五年内将成为全球最大车企，但股价同时承压。重点看销量扩张、价格战、海外市场和利润率能否支撑这一目标。",
    ),
    (
        re.compile(r"china.*taiwan.*spar.*coast guard|coast guard patrols east", re.I),
        "中台围绕海警在台湾以东巡逻的合法性互相交锋。重点看执法行动是否常态化、台海航运风险和双方后续政策表态。",
    ),
    (
        re.compile(r"alibaba.*baidu.*pentagon|baidu.*alibaba.*pentagon|accused by pentagon.*chinese military", re.I),
        "五角大楼指称阿里巴巴、百度等企业协助中国军方。重点看美国后续清单、投资限制、出口管制和企业海外业务受影响程度。",
    ),
    (
        re.compile(r"copper holds gain.*iran tensions.*china data|copper.*china data", re.I),
        "铜价在伊朗紧张缓和后保持涨幅，同时市场关注中国数据。重点看工业需求、库存变化和地缘风险是否继续扰动大宗商品。",
    ),
    (
        re.compile(r"hengli.*west african|hengli.*middle eastern", re.I),
        "报道指向中国民营炼化企业继续寻找多元原油来源。若采购扩大，可能影响中国炼厂成本、航运流向和中东以外供应商的议价空间。",
    ),
    (
        re.compile(r"us hits.*china.*hong kong|china.*hong kong.*sanction", re.I),
        "美国把部分中国和香港实体纳入制裁或限制范围，核心影响在跨境交易、融资与供应链合规，后续要看中方回应和企业实际受限程度。",
    ),
    (
        re.compile(r"tencent.*raises.*dual", re.I),
        "腾讯通过不同币种债券融资，说明大公司仍在利用国际债市补充资金。重点看融资成本、资金用途，以及市场对中国科技龙头信用的定价。",
    ),
    (
        re.compile(r"byd.*baidu.*alibaba|baidu.*alibaba", re.I),
        "美国点名中国科技公司，通常会带来出口管制、投资限制或采购合规压力。影响不一定立即显现，但会抬高企业海外业务不确定性。",
    ),
    (
        re.compile(r"iron ore.*iran.*china", re.I),
        "尽管中东局势紧张，铁矿石目前仍主要受中国钢铁需求和港口库存影响。若能源运输受扰，后续才可能传导到大宗商品价格。",
    ),
    (
        re.compile(r"emerging-market stocks.*chinese e-commerce", re.I),
        "中国电商股表现影响新兴市场指数情绪。投资者通常会借此判断中国消费、平台竞争和海外扩张压力是否继续拖累风险资产。",
    ),
    (
        re.compile(r"china learns to live on less fuel|less fuel", re.I),
        "中国燃油消费放缓可能来自新能源车替代、运输结构变化和经济动能调整。对全球油市来说，这会削弱长期需求增长预期。",
    ),
    (
        re.compile(r"beijing.*investment clampdown|investment clampdown", re.I),
        "北京收紧投资相关监管，会影响地方项目、企业扩张和资本进入节奏。短期看市场信心，长期看政策是否转向更谨慎的增长模式。",
    ),
    (
        re.compile(r"kenya airport", re.I),
        "中国企业获得肯尼亚机场改造项目，显示海外基建订单仍在推进。重点看融资安排、当地政治风险和项目是否带来后续运营机会。",
    ),
    (
        re.compile(r"taiwan.*foreign ships|foreign ships.*taiwan", re.I),
        "中方对台湾周边外籍船舶加强查问，说明海上执法和主权表态更频繁。市场关注航运安全、保险成本和台海紧张度变化。",
    ),
    (
        re.compile(r"fed.*rate|federal reserve.*rate", re.I),
        "美联储相关消息会影响美元、美债和全球风险资产。当前关键不是单次表态，而是通胀、就业数据是否支持更早降息。",
    ),
    (
        re.compile(r"oil.*iran|iran.*oil", re.I),
        "伊朗相关风险会直接影响石油供应预期和航运安全。若冲突扩大，油价、通胀预期和央行政策判断都可能被重新定价。",
    ),
    (
        re.compile(r"ukraine|russia", re.I),
        "俄乌局势消息通常影响欧洲安全、能源和军工板块。需要区分战场进展、外交表态和制裁变化，三者对市场影响不同。",
    ),
    (
        re.compile(r"israel|iran", re.I),
        "中东局势会牵动能源、航运和避险资产。若事件升级，油价和黄金可能先反应，随后影响通胀预期与全球股市风险偏好。",
    ),
    (
        re.compile(r"nvidia|ai chip|artificial intelligence", re.I),
        "AI芯片消息会影响科技股估值和供应链预期。重点看需求是否持续、出口限制是否变化，以及大厂资本开支有没有降温。",
    ),
    (
        re.compile(r"tariff|trade", re.I),
        "贸易与关税变化会直接影响企业成本、跨境订单和供应链布局。对中国相关资产来说，关键在限制范围和执行力度。",
    ),
]

PHRASE_REPLACEMENTS = [
    ("Exclusive:", "独家："),
    ("Breaking:", "突发："),
    ("China's", "中国"),
    ("Chinese", "中国"),
    ("China", "中国"),
    ("Hong Kong", "香港"),
    ("Taiwan", "台湾"),
    ("Beijing", "北京"),
    ("Shanghai", "上海"),
    ("United States", "美国"),
    ("U.S.", "美国"),
    ("US", "美国"),
    ("Federal Reserve", "美联储"),
    ("Fed", "美联储"),
    ("White House", "白宫"),
    ("Trump", "特朗普"),
    ("Ukraine", "乌克兰"),
    ("Russia", "俄罗斯"),
    ("Israel", "以色列"),
    ("Iran", "伊朗"),
    ("OPEC", "欧佩克"),
    ("NATO", "北约"),
    ("Tencent", "腾讯"),
    ("Alibaba", "阿里巴巴"),
    ("Baidu", "百度"),
    ("BYD", "比亚迪"),
    ("Huawei", "华为"),
    ("Nvidia", "英伟达"),
    ("Hengli", "恒力"),
    ("West African", "西非"),
    ("Middle Eastern", "中东"),
    ("emerging-market", "新兴市场"),
    ("Emerging-Market", "新兴市场"),
    ("e-commerce", "电商"),
    ("E-Commerce", "电商"),
    ("stocks", "股票"),
    ("Stocks", "股票"),
    ("shares", "股票"),
    ("Shares", "股票"),
    ("markets", "市场"),
    ("Markets", "市场"),
    ("market", "市场"),
    ("Market", "市场"),
    ("oil", "石油"),
    ("Oil", "石油"),
    ("fuel", "燃油"),
    ("Fuel", "燃油"),
    ("iron ore", "铁矿石"),
    ("Iron ore", "铁矿石"),
    ("tariff", "关税"),
    ("Tariff", "关税"),
    ("trade", "贸易"),
    ("Trade", "贸易"),
    ("sanctions", "制裁"),
    ("Sanctions", "制裁"),
    ("entities", "实体"),
    ("Entities", "实体"),
    ("raises", "筹集"),
    ("seeks", "寻求"),
    ("says", "称"),
    ("hits", "打击"),
    ("presses", "施压"),
    ("secures", "获得"),
    ("deal", "交易"),
    ("Deal", "交易"),
    ("airport", "机场"),
    ("Airport", "机场"),
    ("investment", "投资"),
    ("Investment", "投资"),
]


async def get_news(refresh: bool = False, allow_stale: bool = True, force: bool = False) -> dict[str, Any]:
    config = load_config()
    fetch_config = config.get("fetch", {})
    sqlite_path = resolve_sqlite_path(config)
    cache_ttl = int(fetch_config.get("cache_ttl_seconds", 600))
    min_refresh_interval = int(fetch_config.get("min_refresh_interval_seconds", cache_ttl))
    min_expires_at = datetime.now(UTC) + timedelta(seconds=min_refresh_interval)
    async with CACHE_LOCK:
        if not force and CACHE["data"] and datetime.now(UTC) < CACHE["expires_at"]:
            cached = ensure_detail_fields(dict(CACHE["data"]))
            cached["cached"] = True
            cached["fromStorage"] = False
            cached["throttled"] = refresh
            return cached

    stored = await load_latest_news(sqlite_path)
    if stored:
        stored = ensure_detail_fields(stored)
    stored_schema_valid = bool(stored and stored.get("schemaVersion") == NEWS_SCHEMA_VERSION)
    stored_is_fresh = bool(
        stored_schema_valid and effective_expires_at(stored, min_refresh_interval) > datetime.now(UTC)
    )
    if not force and stored and stored_schema_valid and ((allow_stale and not refresh) or stored_is_fresh):
        stored["cached"] = True
        stored["fromStorage"] = True
        stored["throttled"] = refresh
        stored["stale"] = not stored_is_fresh
        stored["expiresAt"] = max(parse_dt(stored.get("expiresAt", "")), min_expires_at).isoformat()
        async with CACHE_LOCK:
            CACHE["data"] = stored
            CACHE["expires_at"] = effective_expires_at(stored, min_refresh_interval)
        return stored

    enabled_sources = [source for source in config["sources"] if source.get("enabled")]
    days = int(fetch_config.get("days", 3))
    per_section = int(fetch_config.get("max_items_per_section", 60))
    since = datetime.now(UTC) - timedelta(days=days)
    request_state = RequestState(
        max_concurrency=int(fetch_config.get("max_concurrency", 6)),
        per_domain_concurrency=int(fetch_config.get("per_domain_concurrency", 2)),
        timeout=float(fetch_config.get("request_timeout_seconds", 8)),
        retries=int(fetch_config.get("retries", 1)),
        source_timeout=float(fetch_config.get("source_timeout_seconds", 10)),
        enable_gdelt_fallback=bool(fetch_config.get("enable_gdelt_fallback", False)),
        days=days,
    )

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(request_state.timeout),
    ) as client:
        coordinate_httpx_client(client, retries=False)
        tasks = [
            asyncio.wait_for(
                fetch_source(source, since, client, request_state),
                timeout=request_state.source_timeout,
            )
            for source in enabled_sources
            if source.get("domains")
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    raw_items: list[dict[str, Any]] = []
    errors: list[str] = []
    for result in results:
        if isinstance(result, Exception):
            errors.append(str(result))
        else:
            raw_items.extend(result)

    deduped_items = dedupe(raw_items)
    candidate_items = select_news_candidates(deduped_items, per_section)
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(request_state.timeout),
    ) as translate_client:
        coordinate_httpx_client(translate_client, retries=False)
        translated_titles = await translate_titles(candidate_items, translate_client, request_state)
    ranked = sorted(
        (enrich_item(item, translated_titles.get(item.get("title", ""))) for item in candidate_items),
        key=news_sort_key,
        reverse=True,
    )

    expires_at = datetime.now(UTC) + timedelta(seconds=cache_ttl)
    data = {
        "generatedAt": datetime.now(UTC).isoformat(),
        "savedAt": datetime.now(UTC).isoformat(),
        "expiresAt": expires_at.isoformat(),
        "schemaVersion": NEWS_SCHEMA_VERSION,
        "window": f"最近{days}天",
        "cached": False,
        "fromStorage": False,
        "throttled": False,
        "sources": [
            {
                "id": source.get("id"),
                "name": source.get("name"),
                "enabled": bool(source.get("enabled")),
                "note": source.get("note", ""),
            }
            for source in enabled_sources
        ],
        "errors": errors,
        "china": [item for item in ranked if item["section"] == "china"][:per_section],
        "world": [item for item in ranked if item["section"] == "world"][:per_section],
    }

    if not data["china"] and not data["world"] and stored:
        stored = ensure_detail_fields(stored)
        stored["cached"] = True
        stored["fromStorage"] = True
        stored["stale"] = True
        return stored

    data = ensure_detail_fields(data)
    await save_latest_news(sqlite_path, data)
    async with CACHE_LOCK:
        CACHE["data"] = data
        CACHE["expires_at"] = expires_at
    return data


class RequestState:
    def __init__(
        self,
        max_concurrency: int,
        per_domain_concurrency: int,
        timeout: float,
        retries: int,
        source_timeout: float,
        enable_gdelt_fallback: bool,
        days: int,
    ) -> None:
        self.global_sem = asyncio.Semaphore(max_concurrency)
        self.domain_sems: defaultdict[str, asyncio.Semaphore] = defaultdict(
            lambda: asyncio.Semaphore(per_domain_concurrency)
        )
        self.timeout = timeout
        self.retries = retries
        self.source_timeout = source_timeout
        self.enable_gdelt_fallback = enable_gdelt_fallback
        self.days = days


async def fetch_source(
    source: dict[str, Any],
    since: datetime,
    client: httpx.AsyncClient,
    request_state: RequestState,
) -> list[dict[str, Any]]:
    try:
        rss_items = await fetch_google_news(source, since, client, request_state)
        if rss_items:
            return rss_items

        if request_state.enable_gdelt_fallback:
            gdelt_items = await fetch_gdelt(source, since, client, request_state)
            if gdelt_items:
                return gdelt_items

        raise RuntimeError(f"最近{request_state.days}天没有抓到 Google News RSS 新闻")
    except Exception as error:
        raise RuntimeError(f"{source['name']}: {error}") from error


async def fetch_google_news(
    source: dict[str, Any],
    since: datetime,
    client: httpx.AsyncClient,
    request_state: RequestState,
) -> list[dict[str, Any]]:
    tasks: list[tuple[str, Any]] = []
    use_site_filter = bool(source.get("site_filter", True))
    domains = source.get("domains") or [""]
    for domain in domains:
        site_filter = f"site:{domain} " if use_site_filter and domain else ""
        for profile in SECTION_QUERY_PROFILES:
            params = {
                "q": f"{site_filter}({profile['query']}) when:{request_state.days}d",
                "hl": profile["hl"],
                "gl": profile["gl"],
                "ceid": profile["ceid"],
            }
            url = f"https://news.google.com/rss/search?{urlencode(params)}"
            tasks.append((profile["section"], fetch_text(url, "news.google.com", client, request_state)))

    results = await asyncio.gather(*(task for _, task in tasks), return_exceptions=True)
    items: list[dict[str, Any]] = []
    for (query_section, _), result in zip(tasks, results, strict=False):
        if isinstance(result, Exception):
            continue
        items.extend(parse_google_news_rss(result, source, query_section))

    return [item for item in items if parse_dt(item["publishedAt"]) >= since]


async def fetch_gdelt(
    source: dict[str, Any],
    since: datetime,
    client: httpx.AsyncClient,
    request_state: RequestState,
) -> list[dict[str, Any]]:
    domain_query = " OR ".join(f"domain:{domain}" for domain in source.get("domains", []))
    query = (
        f"({domain_query}) "
        "(China OR market OR economy OR Fed OR oil OR AI OR tariff OR Ukraine OR Israel)"
    )
    params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": "80",
        "sort": "DateDesc",
        "startdatetime": since.strftime("%Y%m%d%H%M%S"),
    }
    url = f"https://api.gdeltproject.org/api/v2/doc/doc?{urlencode(params)}"
    text = await fetch_text(url, "api.gdeltproject.org", client, request_state)
    data = json.loads(text)
    items = []
    for article in data.get("articles", []):
        published_at = parse_gdelt_seen_date(article.get("seendate", ""))
        items.append(
            {
                "id": article.get("url"),
                "source": source["name"],
                "title": clean_text(article.get("title", "")),
                "url": article.get("url"),
                "image": article.get("socialimage") or "",
                "domain": article.get("domain") or first_domain(source),
                "publishedAt": published_at,
                "language": article.get("language") or "",
            }
        )
    return [item for item in items if item["title"] and item["url"]]


async def fetch_text(
    url: str,
    domain: str,
    client: httpx.AsyncClient,
    request_state: RequestState,
) -> str:
    async with request_state.global_sem, request_state.domain_sems[domain]:
        await asyncio.sleep(random.uniform(0.08, 0.35))
        last_error: Exception | None = None
        for attempt in range(request_state.retries + 1):
            try:
                response = await client.get(url, headers=browser_like_headers())
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise httpx.HTTPStatusError(
                        f"HTTP {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                return response.text
            except (httpx.HTTPError, httpx.TimeoutException) as error:
                last_error = error
                if attempt >= request_state.retries:
                    break
                await asyncio.sleep(0.6 * (2**attempt) + random.uniform(0.1, 0.5))
        raise RuntimeError(f"{domain} 请求失败: {last_error!r}")


def browser_like_headers() -> dict[str, str]:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/rss+xml;q=0.8,*/*;q=0.7",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Upgrade-Insecure-Requests": "1",
    }


def parse_google_news_rss(xml_text: str, source: dict[str, Any], query_section: str = "") -> list[dict[str, Any]]:
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return []

    items: list[dict[str, Any]] = []
    for item in root.findall("./channel/item"):
        title = html.unescape(item.findtext("title") or "")
        title = re.sub(r"\s+-\s+[^-]+$", "", title).strip()
        link = html.unescape(item.findtext("link") or "")
        pub_date = item.findtext("pubDate") or ""
        source_name = item.findtext("source") or source["name"]

        if not title or not link:
            continue

        items.append(
            {
                "id": link,
                "source": normalize_source_name(source_name, source["name"]),
                "title": clean_text(title),
                "url": link,
                "image": "",
                "domain": first_domain(source),
                "publishedAt": parse_rfc2822_date(pub_date),
                "language": "English",
                "sourcePriority": float(source.get("priority", 0) or 0),
                "_querySection": query_section,
            }
        )
    return items


def select_news_candidates(items: list[dict[str, Any]], per_section: int) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {"china": [], "world": []}
    for item in items:
        if is_low_value_news(item):
            continue
        section = classify_section(item)
        text = f"{item.get('title', '')} {item.get('domain', '')}".lower()
        scored = dict(item)
        scored["_candidateSection"] = section
        source_priority = float(item.get("sourcePriority", 0) or 0)
        scored["_preScore"] = score_item(text, item.get("publishedAt", ""), section == "china") + source_priority
        buckets[section].append(scored)

    selected: list[dict[str, Any]] = []
    for section in ("china", "world"):
        ranked = sorted(
            buckets[section],
            key=news_sort_key,
            reverse=True,
        )
        for item in ranked[:per_section]:
            item.pop("_preScore", None)
            selected.append(item)
    return selected


def classify_section(item: dict[str, Any]) -> str:
    text = f"{item.get('title', '')} {item.get('domain', '')}".lower()
    if any(term in text for term in CHINA_TERMS):
        return "china"
    if item.get("_querySection") == "china":
        return "china"
    return "world"


def is_low_value_news(item: dict[str, Any]) -> bool:
    title = clean_text(item.get("title", ""))
    lower = title.lower()
    if LOW_VALUE_TITLE_RE.fullmatch(title):
        return True
    return bool(SPORTS_NOISE_RE.search(lower))


async def translate_titles(
    items: list[dict[str, Any]],
    client: httpx.AsyncClient,
    request_state: RequestState,
) -> dict[str, str]:
    titles = []
    seen = set()
    for item in items:
        title = clean_text(item.get("title", ""))
        if not title or title in seen:
            continue
        seen.add(title)
        if has_chinese(title):
            continue
        titles.append(title)

    translated: dict[str, str] = {}
    strict_titles: list[str] = []
    strict_counts: defaultdict[str, int] = defaultdict(int)
    seen_strict = set()
    for item in items:
        section = item.get("_candidateSection", "world")
        title = clean_text(item.get("title", ""))
        if title and title not in seen_strict and strict_counts[section] < STRICT_TRANSLATE_PER_SECTION:
            strict_counts[section] += 1
            seen_strict.add(title)
            strict_titles.append(title)

    for index in range(0, len(strict_titles), 6):
        batch = strict_titles[index : index + 6]
        try:
            batch_result = await translate_batch(batch, client, request_state)
        except Exception:
            batch_result = {}
        for title in batch:
            translated_value = batch_result.get(title, "")
            if looks_bad_translation(translated_value, title):
                translated_value = await translate_one_title(title, client, request_state)
            translated[title] = translated_value

    remaining_titles = [title for title in titles if title not in translated]
    for index in range(0, len(remaining_titles), TRANSLATE_BATCH_SIZE):
        batch = remaining_titles[index : index + TRANSLATE_BATCH_SIZE]
        try:
            batch_result = await translate_batch(batch, client, request_state)
            for title in batch:
                if looks_bad_translation(batch_result.get(title, ""), title):
                    batch_result[title] = await translate_one_title(title, client, request_state)
            translated.update(batch_result)
        except Exception:
            for title in batch:
                translated[title] = await translate_one_title(title, client, request_state)
        await asyncio.sleep(random.uniform(0.35, 0.9))
    return translated


async def translate_one_title(
    title: str,
    client: httpx.AsyncClient,
    request_state: RequestState,
) -> str:
    for attempt in range(TRANSLATE_RETRIES):
        try:
            translated = (await translate_batch([title], client, request_state)).get(title, "")
            if translated and not looks_bad_translation(translated, title):
                return translated
        except Exception:
            pass
        if attempt + 1 < TRANSLATE_RETRIES:
            await asyncio.sleep((0.5 * (2**attempt)) + random.uniform(0.1, 0.4))
    return ""


async def translate_batch(
    titles: list[str],
    client: httpx.AsyncClient,
    request_state: RequestState,
) -> dict[str, str]:
    if not titles:
        return {}

    params = {
        "client": "gtx",
        "sl": "auto",
        "tl": "zh-CN",
        "dt": "t",
        "q": "\n".join(titles),
    }
    async with request_state.global_sem, request_state.domain_sems[TRANSLATE_DOMAIN]:
        await asyncio.sleep(random.uniform(0.25, 0.65))
        response = await client.get(
            f"{TRANSLATE_URL}?{urlencode(params)}",
            headers=translate_headers(),
            timeout=min(request_state.timeout, 5.0),
        )
        response.raise_for_status()
        payload = response.json()

    pieces = payload[0] if payload and isinstance(payload[0], list) else []
    joined = "".join(piece[0] for piece in pieces if piece and piece[0])
    lines = [normalize_translated_title(line) for line in joined.splitlines() if line.strip()]
    if len(lines) != len(titles):
        if len(titles) == 1 and joined.strip():
            lines = [normalize_translated_title(joined)]
        else:
            raise RuntimeError("translation batch line mismatch")
    return {title: limit_text(line, 46) for title, line in zip(titles, lines, strict=False)}


def translate_headers() -> dict[str, str]:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://translate.google.com/",
    }


def normalize_translated_title(value: str) -> str:
    value = clean_text(value)
    value = value.replace("，消息人士称", "")
    value = value.replace(" - 路透社", "").replace(" - 彭博社", "")
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fffA-Za-z0-9])", "", value)
    value = re.sub(r"(?<=[A-Za-z0-9])\s+(?=[\u4e00-\u9fff])", "", value)
    value = value.replace("特朗普", "特朗普")
    return value.strip(" -—:：")


def looks_bad_translation(value: str, original_title: str = "") -> bool:
    if not value or not has_chinese(value):
        return True
    if is_generic_title(value):
        return True
    if english_residue_words(value, original_title):
        return True
    return bool(re.search(r"\b(after|with|over|sources|says|amid|loom|help|cuts|warns|based)\b", value, re.I))


def english_residue_words(value: str, original_title: str = "") -> list[str]:
    # Translation providers intentionally preserve company, product, and person names.
    # Treat those original proper nouns as valid while still rejecting untranslated prose.
    original_proper_nouns = {
        word.lower()
        for word in ENGLISH_RESIDUE_RE.findall(original_title)
        if (
            word.isupper()
            or any(char.isupper() for char in word[1:])
            or (word[:1].isupper() and word.lower() not in COMMON_ENGLISH_TITLE_WORDS)
        )
    }
    bad_words = []
    for word in ENGLISH_RESIDUE_RE.findall(value):
        normalized = re.sub(r"[^A-Z0-9]", "", word.upper())
        if normalized in ALLOWED_TITLE_ENGLISH:
            continue
        if word.lower() in original_proper_nouns:
            continue
        bad_words.append(word)
    return bad_words


def is_generic_title(value: str) -> bool:
    value = clean_text(value)
    if value in GENERIC_TITLES:
        return True
    generic_fragments = [
        "出现变化",
        "出现新变化",
        "出现新进展",
        "受关注",
        "影响市场",
        "牵动市场",
    ]
    generic_subjects = [
        "中国相关事件",
        "中国及港澳相关消息",
        "香港市场与政策消息",
        "国际要闻",
        "全球市场走势",
        "大宗能源",
        "贸易政策变化",
        "制裁与限制措施",
        "AI与芯片产业消息",
        "AI芯片与科技股",
    ]
    return any(subject in value for subject in generic_subjects) and any(
        fragment in value for fragment in generic_fragments
    )


def forced_title_translation(title: str) -> str:
    specific_patterns = [
        (re.compile(r"chinese chipmaker metax.*hong kong listing|metax.*hong kong listing", re.I), "中国芯片制造商沐曦计划赴港上市，借IPO热潮"),
        (re.compile(r"hedge funds sold broader tech.*spacex ipo|spacex ipo.*jpmorgan data", re.I), "摩根大通数据：对冲基金在SpaceX IPO前减持科技股"),
        (re.compile(r"asia gold.*india gold demand.*china premiums", re.I), "亚洲黄金：价格回落提振印度需求，中国黄金升水收窄"),
        (re.compile(r"pilot union.*european regulators.*labor loophole", re.I), "飞行员工会拟敦促欧洲监管机构堵住劳工漏洞"),
        (re.compile(r"chinese robot appliance maker dreame tech.*hong kong", re.I), "追觅科技据悉考虑赴港IPO"),
        (re.compile(r"humanoid robot manufacturer engineai.*hong kong ipo", re.I), "众擎机器人据悉已提交香港IPO申请"),
        (re.compile(r"woodside.*pre-emptive right.*petrochina.*browse", re.I), "伍德赛德行使优先购买权，拟买下中石油Browse项目权益"),
        (re.compile(r"london.*ai ecosystem.*elevenlabs", re.I), "ElevenLabs CEO称伦敦AI生态从未如此强劲"),
        (re.compile(r"elliott mulls.*takeover.*very group", re.I), "Elliott据悉考虑以26.7亿美元收购英国The Very Group"),
        (re.compile(r"anthropic.*data center leases.*google", re.I), "Anthropic寻求数据中心租约，并向Google寻求资金支持"),
        (re.compile(r"dazn.*directv latin america.*world cup", re.I), "DAZN与DirecTV拉美在世界杯前达成体育频道协议"),
        (re.compile(r"^commodities$", re.I), "大宗商品"),
        (re.compile(r"^stocks$", re.I), "股市"),
    ]
    for pattern, translated in specific_patterns:
        if pattern.search(title):
            return translated
    return ""


def repair_translated_title(original_title: str, translated_title: str) -> str:
    value = clean_text(translated_title)
    if not value:
        return value

    lower = original_title.lower()
    value = value.replace("MetaX", "沐曦").replace("metax", "沐曦")
    value = value.replace("JPMorgan", "摩根大通").replace("JPMORGAN", "摩根大通")
    value = re.sub(r"SpaceX\s*IPO", "SpaceX IPO", value, flags=re.I)
    value = re.sub(r"SpaceXIPO", "SpaceX IPO", value, flags=re.I)

    if "pilot union" in lower:
        value = value.replace("试点工会", "飞行员工会")
        value = value.replace("飞行员工会计划呼吁", "飞行员工会拟敦促")
    if "gold" in lower and "premium" in lower:
        value = value.replace("中国保费缓和", "中国黄金升水收窄")
        value = value.replace("中国保费下降", "中国黄金升水下降")
        value = value.replace("保费", "升水")
    if "broader tech" in lower:
        value = value.replace("更广泛的技术", "科技股")
        value = value.replace("出售了科技股", "减持科技股")
    if "hong kong listing" in lower or "hong kong ipo" in lower:
        value = value.replace("在香港上市", "赴港上市")
        value = value.replace("在香港IPO", "赴港IPO")
    if "seize on boom" in lower:
        value = value.replace("以抓住繁荣", "，借IPO热潮")
        value = value.replace("抓住繁荣", "借IPO热潮")
    if "dreame tech" in lower:
        value = value.replace("梦想科技", "追觅科技")

    return value


def fallback_chinese_title(title: str) -> str:
    forced = forced_title_translation(title)
    if forced:
        return limit_text(forced, 46)

    for pattern, translated in TITLE_PATTERNS:
        if pattern.search(title):
            return limit_text(translated, 46)

    translated = title
    for source, target in sorted(PHRASE_REPLACEMENTS, key=lambda pair: len(pair[0]), reverse=True):
        translated = re.sub(re.escape(source), target, translated)
    translated = re.sub(r"\s+", " ", translated)
    translated = translated.replace(" ,", "，").replace(",", "，")
    translated = translated.replace(" :", "：").replace(":", "：")
    translated = translated.replace(" - ", "：")
    translated = translated.strip(" -")
    if looks_bad_translation(translated):
        return generic_chinese_title(title)
    if translated == title and not has_chinese(translated):
        translated = f"{infer_topic(title, 'world')}：{compact_english_title(title)}"
    return limit_text(translated, 46)


def safe_chinese_title(original_title: str, candidate_title: str | None, section: str) -> str:
    candidate = repair_translated_title(original_title, clean_text(candidate_title or ""))
    if candidate and not looks_bad_translation(candidate, original_title):
        return limit_text(candidate, 46)

    return limit_text(clean_text(original_title or candidate), 90)


def generic_chinese_title(title: str) -> str:
    lower = title.lower()
    if any(term in lower for term in HONG_KONG_TERMS):
        return "香港市场与政策消息出现变化"
    if any(term in lower for term in ["sanction", "blacklist", "restriction"]):
        return "制裁与限制措施出现新变化"
    if any(term in lower for term in ["tariff", "trade", "export"]):
        return "贸易政策变化牵动市场"
    if any(term in lower for term in ["oil", "crude", "opec", "energy"]):
        return "大宗能源出现新变化"
    if any(term in lower for term in ["coal"]):
        return "煤炭需求和能源结构变化受关注"
    if re.search(r"\b(fed|rate|rates|inflation)\b", lower):
        return "宏观与流动性消息影响市场"
    if re.search(r"\b(ai|nvidia)\b|artificial intelligence|chip|semiconductor", lower):
        return "AI与芯片产业消息影响市场"
    if any(term in lower for term in ["ukraine", "russia"]):
        return "俄乌局势出现新进展"
    if any(term in lower for term in ["iran", "israel", "gaza"]):
        return "中东局势继续影响市场"
    if any(term in lower for term in ["china", "chinese", "beijing", "taiwan", "hong kong"]):
        return "中国相关事件出现新进展"
    if any(term in lower for term in ["stock", "share", "market", "bank"]):
        return "全球市场走势出现变化"
    return "国际要闻出现新变化"


def enrich_item(item: dict[str, Any], translated_title: str | None = None) -> dict[str, Any]:
    text = f"{item.get('title', '')} {item.get('domain', '')}".lower()
    section = classify_section(item)
    is_china = section == "china"
    original_title = item.get("title", "")
    chinese_title = safe_chinese_title(original_title, translated_title, section)
    translation_ok = title_translation_succeeded(original_title, chinese_title)
    topic = infer_topic(original_title, section)
    subject = infer_subject(original_title, section)
    enriched = dict(item)
    enriched.pop("_candidateSection", None)
    enriched.pop("_querySection", None)
    enriched["section"] = section
    enriched["topic"] = topic
    enriched["subject"] = subject
    enriched["originalTitle"] = original_title
    enriched["title"] = limit_text(chinese_title, 46)
    enriched["translationStatus"] = "translated" if translation_ok else "original"
    enriched["summary"] = make_summary(original_title, section, chinese_title) if translation_ok else ""
    enriched["detail"] = (
        make_detail(original_title, enriched["summary"], section, chinese_title) if translation_ok else ""
    )
    source_priority = float(item.get("sourcePriority", 0) or 0)
    enriched["score"] = score_item(text, item.get("publishedAt", ""), is_china) + source_priority
    return enriched


def make_chinese_title(title: str, section: str) -> str:
    return title


def make_summary(title: str, section: str, translated_title: str = "") -> str:
    lower = title.lower()
    cn = translated_title
    for pattern, summary in SUMMARY_PATTERNS:
        if pattern.search(title):
            return limit_text(summary, 50)

    if cn and not is_generic_title(cn):
        return limit_text(f"{headline_clause(cn)}，关注后续影响和市场反应。", 50)
    if any(term in lower or term in cn for term in ["sanction", "制裁", "blacklist", "限制"]):
        return "涉及制裁或限制措施，重点看企业合规和供应链影响。"
    if any(term in lower or term in cn for term in ["tariff", "trade", "关税", "贸易"]):
        return "贸易政策有变化，关注企业成本、订单和市场预期。"
    if any(term in lower or term in cn for term in ["world bank", "growth outlook", "gdp", "经济增长", "增长预期", "世界银行"]):
        return "全球增长预期下调，关注贸易、投资和企业盈利压力。"
    if any(term in lower or term in cn for term in ["kenya", "airport", "infrastructure", "肯尼亚", "机场", "基建"]):
        return "海外基建项目有进展，关注融资安排、施工推进和当地风险。"
    if any(term in lower or term in cn for term in ["oil", "opec", "energy", "crude", "石油", "原油", "能源"]):
        return "能源供需或地缘风险变化，关注油价和通胀传导。"
    if re.search(r"\b(fed|rate|rates|inflation)\b", lower) or any(
        term in cn for term in ["利率", "通胀", "美联储"]
    ):
        return "利率与通胀预期变化，可能影响股债汇和风险偏好。"
    if any(term in lower or term in cn for term in ["ukraine", "russia", "israel", "iran", "war", "乌克兰", "俄罗斯", "以色列", "伊朗", "冲突"]):
        return "地缘局势牵动市场，关注能源、避险资产和政策回应。"
    if re.search(r"\b(ai|nvidia)\b|artificial intelligence|chip|semiconductor", lower) or any(
        term in cn for term in ["AI", "芯片", "人工智能", "英伟达", "半导体"]
    ):
        return "科技产业链继续变化，关注芯片、AI需求和相关股表现。"
    if any(term in lower or term in cn for term in ["stock", "share", "market", "bank", "股票", "股市", "市场", "银行"]):
        return "市场表现出现变化，关注资金流向、估值和政策信号。"
    if section == "china":
        return "中国相关事件有进展，关注政策表态和企业实际影响。"
    return "国际要闻出现变化，关注后续政策、价格和市场反应。"


def make_detail(title: str, summary: str, section: str, translated_title: str = "") -> str:
    readable_title = translated_title or make_chinese_title(title, section)
    lower = title.lower()
    for pattern, detail in DETAIL_PATTERNS:
        if pattern.search(title):
            return limit_text(detail, 150)

    if any(term in lower or term in readable_title for term in ["sanction", "制裁", "blacklist", "限制"]):
        tail = "重点看限制范围、执行力度，以及相关企业融资、采购和跨境交易是否受影响。"
    elif any(term in lower or term in readable_title for term in ["oil", "energy", "crude", "石油", "原油", "能源"]):
        tail = "重点看供应是否受扰、油价如何反应，以及能源成本是否进一步传导到通胀。"
    elif any(term in lower or term in readable_title for term in ["fed", "rate", "inflation", "利率", "通胀", "美联储"]):
        tail = "重点看后续经济数据是否支持降息预期，以及美元、美债和股票市场如何重新定价。"
    elif any(term in lower or term in readable_title for term in ["ukraine", "russia", "israel", "iran", "war", "乌克兰", "俄罗斯", "以色列", "伊朗", "冲突"]):
        tail = "重点看冲突是否升级、外交斡旋是否推进，以及能源和避险资产是否继续波动。"
    elif re.search(r"\b(ai|chip|semiconductor)\b", lower) or any(
        term in readable_title for term in ["AI", "芯片", "人工智能", "半导体"]
    ):
        tail = "重点看需求是否延续、出口管制是否变化，以及科技龙头和供应链公司如何反应。"
    else:
        tail = "后续主要看政策表态、市场价格和相关企业是否受到实际影响。"
    return limit_text(f"{readable_title}。{summary}{tail}", 150)


def headline_clause(value: str) -> str:
    value = clean_text(value)
    value = value.strip("。；;，,：:")
    if len(value) <= 34:
        return value
    return limit_text(value, 34)


def ensure_detail_fields(data: dict[str, Any]) -> dict[str, Any]:
    data = prune_news_payload(data)
    for section in ("china", "world"):
        for item in data.get(section, []):
            original_title = item.get("originalTitle") or item.get("title", "")
            translated_title = item.get("title", "")
            item["topic"] = infer_topic(original_title, section)
            item["subject"] = infer_subject(original_title, section)
            repaired_title = safe_chinese_title(original_title, translated_title, section)
            translation_ok = title_translation_succeeded(original_title, repaired_title)
            repaired = repaired_title != translated_title
            if repaired:
                item["title"] = repaired_title
            item["translationStatus"] = "translated" if translation_ok else "original"
            if not translation_ok:
                item["summary"] = ""
                item["detail"] = ""
                continue
            if repaired or not item.get("summary"):
                item["summary"] = make_summary(original_title, section, repaired_title)
            if repaired or not item.get("detail"):
                item["detail"] = make_detail(original_title, item.get("summary", ""), section, repaired_title)
        data[section] = sorted(data.get(section, []), key=news_sort_key, reverse=True)
    return data


def prune_news_payload(data: dict[str, Any]) -> dict[str, Any]:
    cutoff = datetime.now(UTC) - timedelta(days=NEWS_RETENTION_DAYS)
    for section in ("china", "world"):
        data[section] = [
            item for item in data.get(section, [])
            if parse_dt(item.get("publishedAt", "")) >= cutoff
        ]
    return data


def news_sort_key(item: dict[str, Any]) -> tuple[float, datetime]:
    return (
        float(item.get("score", item.get("_preScore", 0)) or 0),
        parse_dt(item.get("publishedAt", "")),
    )


def title_translation_succeeded(original_title: str, display_title: str) -> bool:
    original = clean_text(original_title)
    display = clean_text(display_title)
    if not display:
        return False
    if has_chinese(original):
        return True
    if display == original:
        return False
    return has_chinese(display) and not looks_bad_translation(display, original)


INVESTMENT_TOPIC_RULES: list[tuple[str, list[str]]] = [
    (
        "宏观与流动性",
        [
            "fed",
            "federal reserve",
            "central bank",
            "rate",
            "inflation",
            "cpi",
            "ppi",
            "gdp",
            "pmi",
            "jobs",
            "employment",
            "unemployment",
            "productivity",
            "monetary",
            "fiscal",
            "美联储",
            "央行",
            "利率",
            "通胀",
            "财政",
            "就业",
            "失业",
            "经济增长",
        ],
    ),
    (
        "利率与信用",
        [
            "treasury",
            "yield",
            "bond",
            "credit",
            "spread",
            "default",
            "debt",
            "loan",
            "mortgage",
            "美债",
            "国债",
            "收益率",
            "信用",
            "利差",
            "债务",
            "违约",
            "贷款",
        ],
    ),
    (
        "大宗能源",
        [
            "oil",
            "crude",
            "opec",
            "natural gas",
            "lng",
            "coal",
            "diesel",
            "gasoline",
            "fuel",
            "refinery",
            "power",
            "electricity",
            "utility",
            "原油",
            "石油",
            "油价",
            "天然气",
            "液化天然气",
            "煤炭",
            "燃料",
            "炼油",
            "电力",
            "发电",
            "能源",
        ],
    ),
    (
        "大宗商品",
        [
            "commodity",
            "commodities",
            "copper",
            "aluminum",
            "aluminium",
            "iron ore",
            "gold",
            "silver",
            "nickel",
            "zinc",
            "tin",
            "steel",
            "metal",
            "grain",
            "corn",
            "soybean",
            "wheat",
            "sugar",
            "cotton",
            "fertilizer",
            "lithium",
            "铜",
            "铝",
            "铁矿",
            "黄金",
            "白银",
            "镍",
            "锌",
            "锡",
            "钢",
            "有色",
            "金属",
            "粮食",
            "农产品",
            "化肥",
            "锂",
            "碳酸锂",
        ],
    ),
    (
        "科技产业",
        [
            "ai",
            "artificial intelligence",
            "nvidia",
            "chip",
            "semiconductor",
            "software",
            "cloud",
            "data center",
            "tech",
            "芯片",
            "半导体",
            "人工智能",
            "英伟达",
            "算力",
            "数据中心",
            "科技",
        ],
    ),
    (
        "外汇与跨境资金",
        [
            "dollar",
            "yuan",
            "renminbi",
            "yen",
            "euro",
            "fx",
            "currency",
            "capital flow",
            "美元",
            "人民币",
            "日元",
            "欧元",
            "汇率",
            "外汇",
            "跨境资金",
            "资金流",
        ],
    ),
    (
        "中国资产",
        [
            "china",
            "chinese",
            "beijing",
            "shanghai",
            "shenzhen",
            "hong kong",
            "taiwan",
            "pboc",
            "tencent",
            "alibaba",
            "byd",
            "huawei",
            "中国",
            "内地",
            "香港",
            "台湾",
            "人民币",
            "央行",
            "港股",
            "A股",
            "腾讯",
            "阿里",
            "比亚迪",
            "华为",
        ],
    ),
    (
        "权益市场",
        [
            "stock",
            "share",
            "equity",
            "earnings",
            "nasdaq",
            "s&p",
            "dow",
            "ipo",
            "bank",
            "股票",
            "股市",
            "美股",
            "港股",
            "财报",
            "估值",
            "银行",
        ],
    ),
    (
        "消费与地产",
        [
            "consumer",
            "retail",
            "property",
            "real estate",
            "housing",
            "home sales",
            "消费",
            "零售",
            "地产",
            "房地产",
            "住房",
            "房价",
        ],
    ),
    (
        "地缘与供应链",
        [
            "tariff",
            "trade",
            "sanction",
            "export control",
            "supply chain",
            "war",
            "ukraine",
            "russia",
            "israel",
            "iran",
            "gaza",
            "nato",
            "关税",
            "贸易",
            "制裁",
            "出口管制",
            "供应链",
            "战争",
            "冲突",
            "乌克兰",
            "俄罗斯",
            "以色列",
            "伊朗",
            "中东",
        ],
    ),
]


def text_has_any(text: str, terms: list[str]) -> bool:
    return any(str(term).lower() in text for term in terms)


def pick_topic(text: str, terms: list[str], label: str) -> str:
    return label if text_has_any(text, terms) else ""


def infer_topic(title: str, section: str) -> str:
    lower = title.lower()
    geopolitical_topic = pick_topic(
        lower,
        [
            "tariff",
            "trade",
            "sanction",
            "export control",
            "supply chain",
            "war",
            "ukraine",
            "russia",
            "israel",
            "iran",
            "gaza",
            "nato",
            "关税",
            "贸易",
            "制裁",
            "出口管制",
            "供应链",
            "战争",
            "冲突",
            "乌克兰",
            "俄罗斯",
            "以色列",
            "伊朗",
            "中东",
        ],
        "地缘与供应链",
    )
    if geopolitical_topic:
        return geopolitical_topic
    for label, terms in INVESTMENT_TOPIC_RULES:
        if text_has_any(lower, terms):
            return label
    return "中国资产" if section == "china" else "国际要闻"


def infer_subject(title: str, section: str) -> str:
    lower = title.lower()
    priority_subjects = [
        (["tariff", "trade", "sanction", "关税", "贸易", "制裁"], "贸易与制裁"),
        (["ukraine", "russia"], "俄乌局势"),
        (["israel", "iran"], "中东局势"),
    ]
    for keywords, subject in priority_subjects:
        if text_has_any(lower, keywords):
            return subject

    subjects = [
        (HONG_KONG_TERMS, "港澳市场"),
        (["tencent"], "腾讯"),
        (["alibaba"], "阿里巴巴"),
        (["baidu"], "百度"),
        (["byd"], "比亚迪"),
        (["huawei"], "华为"),
        (["treasury", "yield", "bond", "美债", "国债", "收益率"], "债券利率"),
        (["fed", "federal reserve"], "美联储政策"),
        (["oil", "opec", "crude", "原油", "石油", "油价"], "油气价格"),
        (["coal", "煤炭"], "煤炭供需"),
        (["power", "electricity", "电力", "发电"], "电力结构"),
        (["copper", "aluminum", "iron ore", "gold", "铜", "铝", "铁矿", "黄金"], "商品价格"),
        (["ai", "chip", "nvidia", "semiconductor", "芯片", "AI", "半导体"], "AI芯片链"),
        (["china", "chinese", "beijing", "中国", "内地"], "中国相关事件"),
        (["stock", "share", "equity", "earnings", "股票", "股市", "财报"], "权益市场"),
        (["tariff", "trade", "sanction", "关税", "贸易", "制裁"], "贸易与制裁"),
        (["ukraine", "russia"], "俄乌局势"),
        (["israel", "iran"], "中东局势"),
    ]
    for keywords, subject in subjects:
        if text_has_any(lower, keywords):
            return subject
    return "这条新闻" if section == "world" else "中国及港澳相关消息"


def compact_english_title(title: str) -> str:
    words = re.sub(r"[^A-Za-z0-9$.'-]+", " ", title).split()
    return " ".join(words[:8])


def has_chinese(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def score_item(text: str, published_at: str, is_china: bool) -> float:
    term_hits = sum(1 for term in IMPORTANT_TERMS if term in text)
    hours_old = max(0.0, (datetime.now(UTC) - parse_dt(published_at)).total_seconds() / 3600)
    freshness = max(0.0, 72 - hours_old) / 72
    return term_hits * 8 + freshness * 10 + (3 if is_china else 0)


def dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for item in items:
        key = dedupe_key(item.get("title", ""))
        if not key:
            continue
        if key not in seen:
            copy = dict(item)
            copy["sources"] = [item.get("source", "")]
            copy["sourcePriority"] = float(item.get("sourcePriority", 0) or 0)
            seen[key] = copy
        else:
            sources = seen[key].setdefault("sources", [])
            if item.get("source") not in sources:
                sources.append(item.get("source"))
            seen[key]["sourcePriority"] = max(
                float(seen[key].get("sourcePriority", 0) or 0),
                float(item.get("sourcePriority", 0) or 0),
            )

    deduped = []
    for item in seen.values():
        item["source"] = " / ".join(source for source in item.get("sources", []) if source)
        deduped.append(item)
    return deduped


def render_markdown(news: dict[str, Any]) -> str:
    lines = [
        f"# {news.get('window', '近期')}新闻简报",
        "",
        f"生成时间：{format_dt(news['generatedAt'])}",
        "",
        "## 1. 中国及港澳新闻",
        "",
    ]
    for item in news["china"]:
        lines.extend(markdown_item(item))
    lines.extend(["", "## 2. 世界重要新闻", ""])
    for item in news["world"]:
        lines.extend(markdown_item(item))
    return "\n".join(lines) + "\n"


def markdown_item(item: dict[str, Any]) -> list[str]:
    return [
        f"- **[{item['title']}]({item['url']})**",
        f"  摘要：{item['summary']}",
        f"  内容：{item.get('detail', '')}",
        f"  来源：{item['source']}｜{format_dt(item['publishedAt'])}",
    ]


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def resolve_sqlite_path(config: dict[str, Any]) -> Path:
    configured = config.get("storage", {}).get("sqlite_path", "data/news.sqlite")
    path = Path(configured)
    return path if path.is_absolute() else ROOT_DIR / path


def effective_expires_at(data: dict[str, Any], ttl_seconds: int) -> datetime:
    saved_at = parse_dt(data.get("savedAt", ""))
    expires_at = parse_dt(data.get("expiresAt", ""))
    return max(expires_at, saved_at + timedelta(seconds=ttl_seconds))


async def load_latest_news(db_path: Path) -> dict[str, Any] | None:
    async with DB_LOCK:
        return await asyncio.to_thread(load_latest_news_sync, db_path)


async def save_latest_news(db_path: Path, data: dict[str, Any]) -> None:
    async with DB_LOCK:
        await asyncio.to_thread(save_latest_news_sync, db_path, data)


def load_latest_news_sync(db_path: Path) -> dict[str, Any] | None:
    if not db_path.exists():
        return None
    ensure_latest_table(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT payload_json FROM latest_news WHERE id = 1").fetchone()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except json.JSONDecodeError:
        return None


def save_latest_news_sync(db_path: Path, data: dict[str, Any]) -> None:
    ensure_latest_table(db_path)
    data = prune_news_payload(data)
    payload = json.dumps(data, ensure_ascii=False)
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM latest_news WHERE id <> 1")
        conn.execute(
            """
            INSERT INTO latest_news (id, generated_at, saved_at, expires_at, payload_json)
            VALUES (1, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                generated_at = excluded.generated_at,
                saved_at = excluded.saved_at,
                expires_at = excluded.expires_at,
                payload_json = excluded.payload_json
            """,
            (
                data.get("generatedAt", ""),
                data.get("savedAt", ""),
                data.get("expiresAt", ""),
                payload,
            ),
        )


def ensure_latest_table(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS latest_news (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                generated_at TEXT NOT NULL,
                saved_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )


def normalize_source_name(value: str, fallback: str) -> str:
    lower = value.lower()
    if "reuters" in lower:
        return "Reuters"
    if "bloomberg" in lower:
        return "Bloomberg"
    if "returns" in lower:
        return "Returns"
    if "bbc" in lower:
        return "BBC"
    if "associated press" in lower or lower == "ap":
        return "AP"
    if "financial times" in lower:
        return "Financial Times"
    if "wall street journal" in lower or "wsj" in lower:
        return "WSJ"
    if "new york times" in lower:
        return "New York Times"
    if "guardian" in lower:
        return "The Guardian"
    if "cnbc" in lower:
        return "CNBC"
    if "nikkei" in lower:
        return "Nikkei Asia"
    if "south china morning post" in lower or "scmp" in lower:
        return "SCMP"
    if "caixin" in lower:
        return "Caixin"
    return fallback


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).replace(" | Reuters", "").strip()


def dedupe_key(title: str) -> str:
    words = re.sub(r"[^a-z0-9\u4e00-\u9fa5]+", " ", title.lower()).split()
    return " ".join(word for word in words if len(word) > 3)[:120]


def limit_text(value: str, max_chars: int) -> str:
    chars = list(value)
    return "".join(chars[:max_chars]) + ("..." if len(chars) > max_chars else "")


def first_domain(source: dict[str, Any]) -> str:
    domains = source.get("domains") or [""]
    return domains[0]


def parse_dt(value: str) -> datetime:
    if not value:
        return datetime.now(UTC)
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return datetime.now(UTC)
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_rfc2822_date(value: str) -> str:
    from email.utils import parsedate_to_datetime

    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat()
    except (TypeError, ValueError):
        return datetime.now(UTC).isoformat()


def parse_gdelt_seen_date(value: str) -> str:
    if not value:
        return datetime.now(UTC).isoformat()
    try:
        parsed = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        return parsed.isoformat()
    except ValueError:
        return datetime.now(UTC).isoformat()


def format_dt(value: str) -> str:
    dt = parse_dt(value).astimezone(BEIJING_TZ)
    return dt.strftime("%Y-%m-%d %H:%M")
