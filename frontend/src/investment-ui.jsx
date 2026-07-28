import { summarizeStatusText } from "./status-utils.js";

export const QUALITY_METHOD_LABELS = {
  observed: "实测",
  derived: "派生",
  estimated: "估算",
  proxy: "代理"
};

export const QUALITY_STATUS_LABELS = {
  ok: "正常",
  stale: "陈旧",
  partial: "部分",
  empty: "空",
  unsupported: "不支持",
  error: "错误",
  unavailable: "不可用",
  invalid: "无效"
};

const INVESTMENT_CHAIN_LABELS = {
  agriculture: "农业",
  aluminum: "铝产业",
  apparel: "服装",
  automotive: "汽车",
  base_metals: "基本金属",
  battery: "电池",
  biofuel: "生物燃料",
  chemicals: "化工",
  chlor_alkali: "氯碱",
  coal: "煤炭",
  coal_chemicals: "煤化工",
  construction: "建筑",
  consumer_goods: "消费品",
  edible_oil: "食用油",
  electronics: "电子",
  energy_transition_materials: "能源转型材料",
  feed: "饲料",
  ferrous: "黑色产业链",
  fertilizers: "化肥",
  food: "食品",
  gas: "天然气",
  gas_chemicals: "气头化工",
  galvanized_steel: "镀锌钢",
  generation: "发电",
  glass: "玻璃",
  grain: "谷物",
  infrastructure: "基建",
  jewelry: "珠宝",
  lithium: "锂",
  livestock: "养殖",
  manufacturing: "制造业",
  monetary: "货币属性",
  new_energy: "新能源",
  nuclear: "核电",
  oil: "原油",
  oilseeds: "油籽",
  olefins: "烯烃",
  packaging: "包装",
  plastics: "塑料",
  polyester: "聚酯",
  power: "电力",
  power_grid: "电网",
  precious_metals: "贵金属",
  primary_supply: "一次供给",
  processed_supply: "加工供给",
  property: "地产",
  refining: "炼化",
  renewables: "可再生能源",
  residential_energy: "居民能源",
  shipping: "航运",
  silicon: "硅产业",
  solar: "光伏",
  solder: "焊料",
  starch: "淀粉",
  steel: "钢铁",
  stainless_steel: "不锈钢",
  textiles: "纺织",
  throughput: "加工量",
  tires: "轮胎",
  transport: "交通运输",
  wind: "风电"
};


export function DataStatus({ status, quality }) {
  const { text, problem, summary, hasDetails, failed } = summarizeStatusText(status);
  const qualitySummary = quality && typeof quality === "object" ? quality : null;
  const qualityBadges = qualitySummary ? [
    ["status", "stale"],
    ["status", "partial"],
    ["status", "empty"],
    ["status", "unsupported"],
    ["status", "error"],
    ["status", "invalid"],
    ["status", "unavailable"],
    ["method", "estimated"],
    ["method", "proxy"]
  ] : [];
  const hasQualityProblems = qualityBadges.some(([, value]) => Number(qualitySummary?.[value] || 0) > 0);

  return (
    <section className={`status${problem || hasQualityProblems ? " has-warning" : ""}`} role="status">
      {hasDetails ? (
        <details open={failed}>
          <summary>
            <span>{summary}</span>
            <span className="status-more">{problem ? "查看异常" : "数据详情"}</span>
          </summary>
          <p>{text}</p>
        </details>
      ) : (
        <p>{text}</p>
      )}
      {qualitySummary ? (
        <div className="quality-summary" aria-label="数据质量摘要">
          <span className="quality-summary-label">数据质量</span>
          <span className="quality-badge is-neutral">共 {Number(qualitySummary.total || 0)}</span>
          {Number(qualitySummary.legacy || 0) > 0 ? <span className="quality-badge is-warning">旧口径 {qualitySummary.legacy}</span> : null}
          {qualityBadges.map(([kind, value]) => (
            <QualityBadge key={`${kind}-${value}`} kind={kind} value={value} count={Number(qualitySummary[value] || 0)} />
          ))}
          {!hasQualityProblems && !Number(qualitySummary.legacy || 0) ? <span className="quality-badge is-ok">状态完整</span> : null}
        </div>
      ) : null}
    </section>
  );
}


export function InvestmentChainTags({ tags, className, limit = 3, ariaLabel = "产业链标签" }) {
  const visibleTags = (Array.isArray(tags) ? tags : []).filter(Boolean).slice(0, limit);
  if (!visibleTags.length) return null;
  return (
    <span className={className} aria-label={ariaLabel}>
      {visibleTags.map((tag) => <span key={tag}>{investmentChainLabel(tag)}</span>)}
    </span>
  );
}


export function ReleaseCalendarNote({ calendar }) {
  if (!calendar) return null;
  const frequencyLabels = {
    daily: "每日",
    event: "事件驱动",
    monthly: "每月",
    quarterly: "每季",
    tenday: "每旬",
    trading_daily: "交易日"
  };
  const nextScheduledAt = calendar.nextScheduledAt ? new Date(calendar.nextScheduledAt) : null;
  const nextLabel = nextScheduledAt && !Number.isNaN(nextScheduledAt.getTime())
    ? new Intl.DateTimeFormat("zh-CN", {
        timeZone: "Asia/Shanghai",
        month: "numeric",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false
      }).format(nextScheduledAt)
    : "";
  const frequency = frequencyLabels[calendar.frequency] || calendar.frequency || "按来源节奏";
  const label = nextLabel
    ? `下次发布 ${nextLabel}（${frequency}）`
    : `${frequency} · ${calendar.scheduleStatus === "verified_2026" ? "官方日历" : "来源规则"}`;

  return (
    <small className="release-calendar-note">
      {calendar.sourceUrl ? (
        <a href={calendar.sourceUrl} target="_blank" rel="noreferrer">{label}</a>
      ) : label}
    </small>
  );
}


function QualityBadge({ kind, value, count }) {
  const labels = kind === "method" ? QUALITY_METHOD_LABELS : QUALITY_STATUS_LABELS;
  if (!labels[value] || !count) return null;
  return <span className={qualityBadgeClass(kind, value)}>{labels[value]} {count}</span>;
}


export function qualityBadgeClass(kind, value) {
  const warning = kind === "method"
    ? value === "estimated" || value === "proxy"
    : value !== "ok";
  return `quality-badge quality-${kind}${warning ? " is-warning" : " is-ok"}`;
}


function investmentChainLabel(tag) {
  return INVESTMENT_CHAIN_LABELS[tag] || String(tag || "").replaceAll("_", " · ");
}
