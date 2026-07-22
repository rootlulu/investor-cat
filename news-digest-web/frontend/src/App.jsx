import { ArrowLeft, ArrowUpToLine, Boxes, Check, ExternalLink, FileText, Gamepad2, Landmark, LineChart, Newspaper, Pencil, RefreshCw, ShoppingBag, Snowflake, Trash2, X, Zap } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

const AUTO_REFRESH_MS = 30 * 60 * 1000;
const STATUS_POLL_MS = 3 * 1000;
const INITIAL_VISIBLE = 50;
const LOAD_MORE_SIZE = 25;
const BEIJING_TIME_ZONE = "Asia/Shanghai";
const BEIJING_TIME_OFFSET = "+08:00";

export default function App() {
  const path = window.location.pathname;
  const activePage = path.startsWith("/games")
    ? "games"
    : path.startsWith("/xueqiu")
      ? "xueqiu"
      : path.startsWith("/stocks")
        ? "stocks"
        : path.startsWith("/commodities")
          ? "commodities"
          : path.startsWith("/energy")
            ? "energy"
            : path.startsWith("/consumption")
              ? "consumption"
              : path.startsWith("/macro")
                ? "macro"
                : "news";

  useEffect(() => {
    document.title =
      activePage === "games"
        ? "全球与中国游戏 Top100"
        : activePage === "xueqiu"
          ? "雪球"
          : activePage === "stocks"
            ? "股票市场流动性与估值"
            : activePage === "commodities"
            ? "大宗商品监控"
            : activePage === "energy"
              ? "能源生产监控"
              : activePage === "consumption"
                ? "消费数据观察"
                : activePage === "macro"
                  ? "宏观指标看板"
                  : "最近一周新闻简报";
  }, [activePage]);

  if (activePage === "games") return <GamesPageV2 />;
  if (activePage === "xueqiu") return <XueqiuPage />;
  if (activePage === "stocks") return <StocksPage stockId={stockIdFromPath(path)} />;
  if (activePage === "commodities") return <CommoditiesPage />;
  if (activePage === "energy") return <EnergyPage />;
  if (activePage === "consumption") return <ConsumptionPage />;
  if (activePage === "macro") return <MacroPage />;
  return <NewsPage />;
}

function PageShell({ eyebrow, title, activePage, actions, status, children }) {
  return (
    <main className={`shell shell-${activePage}`}>
      <header className="topbar">
        <div className="topbar-main">
          <p className="eyebrow">{eyebrow}</p>
          <h1>{title}</h1>
          <nav className="page-nav" aria-label="页面导航">
            <NavLink activePage={activePage} page="news" href="/news" icon={<Newspaper size={16} />} label="资讯" />
            <NavLink activePage={activePage} page="stocks" href="/stocks" icon={<LineChart size={16} />} label="股票" />
            <NavLink activePage={activePage} page="commodities" href="/commodities" icon={<Boxes size={16} />} label="大宗" />
            <NavLink activePage={activePage} page="energy" href="/energy" icon={<Zap size={16} />} label="能源" />
            <NavLink activePage={activePage} page="consumption" href="/consumption" icon={<ShoppingBag size={16} />} label="消费" />
            <NavLink activePage={activePage} page="macro" href="/macro" icon={<Landmark size={16} />} label="宏观" />
            <NavLink activePage={activePage} page="games" href="/games" icon={<Gamepad2 size={16} />} label="游戏" />
            <NavLink activePage={activePage} page="xueqiu" href="/xueqiu" icon={<Snowflake size={16} />} label="雪球" />
          </nav>
        </div>
        <div className="actions">{actions}</div>
      </header>

      <section className="status" role="status">
        {status}
      </section>

      {children}

      <BackToTopButton />
    </main>
  );
}

function BackToTopButton() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const updateVisibility = () => setVisible(window.scrollY > 480);

    updateVisibility();
    window.addEventListener("scroll", updateVisibility, { passive: true });
    return () => window.removeEventListener("scroll", updateVisibility);
  }, []);

  const scrollToTop = useCallback(() => {
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  return (
    <button
      className={`back-to-top${visible ? " is-visible" : ""}`}
      type="button"
      title="回到顶部"
      aria-label="回到顶部"
      aria-hidden={!visible}
      tabIndex={visible ? 0 : -1}
      onClick={scrollToTop}
    >
      <ArrowUpToLine size={20} aria-hidden="true" />
    </button>
  );
}

function NavLink({ activePage, page, href, icon, label }) {
  return (
    <a className={activePage === page ? "active" : ""} href={href} aria-current={activePage === page ? "page" : undefined}>
      {icon}
      {label}
    </a>
  );
}

function stockIdFromPath(path) {
  const match = /^\/stocks\/([^/?#]+)/.exec(path);
  return match ? decodeURIComponent(match[1]) : "";
}

function initialStockTab(stockId) {
  if (stockId) return "watchlist";
  return new URLSearchParams(window.location.search).get("tab") === "watchlist" ? "watchlist" : "market";
}

function NewsPage() {
  const [news, setNews] = useState({ china: [], world: [] });
  const [visibleCounts, setVisibleCounts] = useState({ china: INITIAL_VISIBLE, world: INITIAL_VISIBLE });
  const [newIds, setNewIds] = useState(new Set());
  const [status, setStatus] = useState("正在获取近期新闻...");
  const [refreshing, setRefreshing] = useState(false);

  const knownNewsIds = useRef(new Set());
  const lastStatusText = useRef("");
  const lastRefreshFinishedAt = useRef("");

  const loadNews = useCallback(async ({ markNew = false } = {}) => {
    setStatus("正在读取本地快照...");

    try {
      const data = await getJson(`/api/news?t=${Date.now()}`);
      const nextNews = { china: data.china || [], world: data.world || [] };
      const previousIds = new Set(knownNewsIds.current);
      const nextIds = collectNewsIds(nextNews);

      setNews(nextNews);
      setVisibleCounts({ china: INITIAL_VISIBLE, world: INITIAL_VISIBLE });
      setNewIds(markNew ? difference(nextIds, previousIds) : new Set());
      knownNewsIds.current = nextIds;

      const statusText = buildNewsStatus(data, nextNews);
      lastStatusText.current = statusText;
      setStatus(statusText);
      return true;
    } catch (error) {
      setStatus(`获取失败：${error.message}`);
      return false;
    }
  }, []);

  const requestBackgroundRefresh = useBackgroundRefresh("news", refreshing, setRefreshing, setStatus, lastStatusText);
  useRefreshPolling("news", loadNews, setRefreshing, setStatus, lastStatusText, lastRefreshFinishedAt);

  useEffect(() => {
    loadNews({ markNew: false });
    const autoTimer = window.setInterval(() => requestBackgroundRefresh("timer", { force: false }), AUTO_REFRESH_MS);
    return () => window.clearInterval(autoTimer);
  }, [loadNews, requestBackgroundRefresh]);

  const loadMore = (section) => {
    setVisibleCounts((current) => ({
      ...current,
      [section]: Math.min((news[section] || []).length, current[section] + LOAD_MORE_SIZE)
    }));
  };
  const newCounts = {
    china: countNewItems(news.china, newIds),
    world: countNewItems(news.world, newIds)
  };

  return (
    <PageShell
      eyebrow="Bloomberg / Reuters / Returns / Google News"
      title="最近一周新闻简报"
      activePage="news"
      status={status}
      actions={
        <>
          <RefreshButton loading={refreshing} title="刷新新闻" onClick={requestBackgroundRefresh} />
          <a className="secondary-action" href="/api/markdown" target="_blank" rel="noreferrer" title="打开 Markdown 版本">
            <FileText size={16} aria-hidden="true" />
            Markdown
          </a>
        </>
      }
    >
      <section className="grid" aria-live="polite">
        <NewsColumn number="1" title="中国及港澳新闻" items={news.china} visibleCount={visibleCounts.china} newIds={newIds} newCount={newCounts.china} onLoadMore={() => loadMore("china")} />
        <NewsColumn number="2" title="世界重要新闻" items={news.world} visibleCount={visibleCounts.world} newIds={newIds} newCount={newCounts.world} onLoadMore={() => loadMore("world")} />
      </section>
    </PageShell>
  );
}

function NewsColumn({ number, title, items, visibleCount, newIds, newCount, onLoadMore }) {
  const visibleItems = items.slice(0, visibleCount);
  const remaining = Math.max(0, items.length - visibleItems.length);

  return (
    <section className="column">
      <div className="section-title">
        <span>{number}</span>
        <h2>{title}</h2>
        {newCount > 0 && (
          <strong className="new-count-badge" title={`新增 ${newCount} 条`} aria-label={`新增 ${newCount} 条`}>
            {newCount}
          </strong>
        )}
      </div>

      <div className="news-list">
        {!items.length ? (
          <p className="empty">暂未抓到符合条件的新闻。</p>
        ) : (
          <>
            {visibleItems.map((item) => (
              <NewsCard key={newsId(item)} item={item} isNew={newIds.has(newsId(item))} />
            ))}
            {remaining > 0 && (
              <button className="load-more-button" type="button" onClick={onLoadMore}>
                继续加载剩余 {remaining} 条
              </button>
            )}
          </>
        )}
      </div>
    </section>
  );
}

function NewsCard({ item, isNew }) {
  const title = item.title || "未命名新闻";
  const originalTitle = item.originalTitle && item.originalTitle !== title ? item.originalTitle : "";

  return (
    <article className={`news-card${isNew ? " is-new" : ""}`}>
      <div className="news-title-row">
        {isNew && <span className="news-new-dot" title="新增资讯" aria-label="新增资讯" />}
        <a className="news-title" href={item.url} title={originalTitle || title} target="_blank" rel="noreferrer">
          {title}
        </a>
      </div>
      {originalTitle && <p className="original-title">原标题：{originalTitle}</p>}
      {item.summary && <p className="summary">{item.summary}</p>}
      {item.detail && <p className="detail">{item.detail}</p>}
      <footer>
        <span className="source">{item.source || "公开来源"}</span>
        <time dateTime={item.publishedAt}>{formatTime(item.publishedAt)}</time>
      </footer>
    </article>
  );
}

function StocksPage({ stockId = "" }) {
  const [markets, setMarkets] = useState([]);
  const [institutionAllocation, setInstitutionAllocation] = useState({});
  const [watchlist, setWatchlist] = useState([]);
  const [newMarketKeys, setNewMarketKeys] = useState(new Set());
  const [snapshotAt, setSnapshotAt] = useState("");
  const [status, setStatus] = useState("正在获取股票数据...");
  const [refreshing, setRefreshing] = useState(false);
  const [importQuery, setImportQuery] = useState("");
  const [importStatus, setImportStatus] = useState("");
  const [importBusy, setImportBusy] = useState(false);
  const [selectedStockId, setSelectedStockId] = useState(stockId);
  const [watchlistActionStatus, setWatchlistActionStatus] = useState("");
  const [watchlistBusyId, setWatchlistBusyId] = useState("");
  const [editingStockId, setEditingStockId] = useState("");
  const [editingName, setEditingName] = useState("");
  const [stockTab, setStockTab] = useState(() => initialStockTab(stockId));

  const knownMarketSignatures = useRef(new Map());
  const lastStatusText = useRef("");
  const lastRefreshFinishedAt = useRef("");

  const loadStocks = useCallback(async ({ markNew = false } = {}) => {
    setStatus("正在读取本地快照...");

    try {
      const data = await getJson(`/api/stocks?t=${Date.now()}`);
      const watchData = await getJson(`/api/stock-watchlist?t=${Date.now()}`);
      const nextMarkets = data.markets || [];
      const nextWatchlist = watchData.items || [];
      const previousSignatures = new Map(knownMarketSignatures.current);
      const nextSignatures = collectMarketSignatures(nextMarkets);
      const changedKeys = new Set();

      if (markNew) {
        for (const [key, signature] of nextSignatures.entries()) {
          if (previousSignatures.get(key) !== signature) changedKeys.add(key);
        }
      }

      setMarkets(nextMarkets);
      setInstitutionAllocation(data.institutionIndustryAllocation || {});
      setWatchlist(nextWatchlist);
      setSelectedStockId((current) => {
        const desired = current || stockId;
        return desired && nextWatchlist.some((item) => item.id === desired) ? desired : "";
      });
      setSnapshotAt(data.generatedAt || "");
      setNewMarketKeys(changedKeys);
      knownMarketSignatures.current = nextSignatures;

      const statusText = `${buildStocksStatus(data)}；自选${nextWatchlist.length}只`;
      lastStatusText.current = statusText;
      setStatus(statusText);
      return true;
    } catch (error) {
      setStatus(`获取失败：${error.message}`);
      return false;
    }
  }, [stockId]);

  const updateStocksPath = useCallback((nextId = "", nextTab = "market") => {
    const nextLocation = nextId
      ? `/stocks/${encodeURIComponent(nextId)}`
      : nextTab === "watchlist"
        ? "/stocks?tab=watchlist"
        : "/stocks";
    if (`${window.location.pathname}${window.location.search}` !== nextLocation) {
      window.history.replaceState(null, "", nextLocation);
    }
  }, []);

  const selectStockTab = useCallback((nextTab) => {
    setStockTab(nextTab);
    updateStocksPath(nextTab === "watchlist" ? selectedStockId : "", nextTab);
  }, [selectedStockId, updateStocksPath]);

  const importStock = useCallback(async (event) => {
    event.preventDefault();
    const query = importQuery.trim();
    if (!query) {
      setImportStatus("请输入股票代码");
      return;
    }
    setWatchlistActionStatus("");
    setImportBusy(true);
    setImportStatus("正在导入并拉取数据...");
    try {
      const data = await getJson(`/api/stock-watchlist/import?t=${Date.now()}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query })
      });
      const nextWatchlist = data.items || [];
      const stock = data.stock || {};
      setWatchlist(nextWatchlist);
      setImportQuery("");
      const detailStatus = data.detailPrefetched ? "；后台已拉取详情数据" : data.detailPrefetchError ? "；详情数据拉取失败" : "";
      setImportStatus(`${data.imported ? "已导入" : "已存在"}：${stock.name || stock.symbol || query}${detailStatus}`);
      if (stock.id) {
        setStockTab("watchlist");
        setSelectedStockId(stock.id);
        updateStocksPath(stock.id, "watchlist");
      }
      const statusText = withWatchlistCount(lastStatusText.current || "自选股票已更新", nextWatchlist.length);
      lastStatusText.current = statusText;
      setStatus(statusText);
    } catch (error) {
      setImportStatus(`导入失败：${error.message}`);
    } finally {
      setImportBusy(false);
    }
  }, [importQuery, updateStocksPath]);

  const selectStock = useCallback(
    (item) => {
      if (!item?.id) return;
      setStockTab("watchlist");
      setSelectedStockId(item.id);
      setWatchlistActionStatus("");
      updateStocksPath(item.id, "watchlist");
    },
    [updateStocksPath]
  );

  const closeDetail = useCallback(() => {
    setSelectedStockId("");
    updateStocksPath("", "watchlist");
  }, [updateStocksPath]);

  const startEditStock = useCallback((item) => {
    setEditingStockId(item.id);
    setEditingName(item.name || item.symbol || "");
    setWatchlistActionStatus("");
  }, []);

  const cancelEditStock = useCallback(() => {
    setEditingStockId("");
    setEditingName("");
  }, []);

  const saveStockName = useCallback(
    async (item) => {
      const nextName = editingName.trim();
      if (!item?.id || !nextName) {
        setWatchlistActionStatus("名称不能为空");
        return;
      }
      setWatchlistBusyId(item.id);
      setWatchlistActionStatus("正在保存...");
      try {
        const data = await getJson(`/api/stock-watchlist/${encodeURIComponent(item.id)}?t=${Date.now()}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: nextName })
        });
        const nextWatchlist = data.items || [];
        setWatchlist(nextWatchlist);
        setEditingStockId("");
        setEditingName("");
        setWatchlistActionStatus(data.message || "已保存");
        const statusText = withWatchlistCount(lastStatusText.current || "自选股票已更新", nextWatchlist.length);
        lastStatusText.current = statusText;
        setStatus(statusText);
      } catch (error) {
        setWatchlistActionStatus(`保存失败：${error.message}`);
      } finally {
        setWatchlistBusyId("");
      }
    },
    [editingName]
  );

  const deleteStock = useCallback(
    async (item) => {
      if (!item?.id) return;
      const stockName = item.name || item.symbol || item.id;
      if (!window.confirm(`确定删除 ${stockName} 吗？`)) return;

      setWatchlistBusyId(item.id);
      setWatchlistActionStatus(`正在删除：${stockName}`);
      try {
        const data = await getJson(`/api/stock-watchlist/${encodeURIComponent(item.id)}?t=${Date.now()}`, {
          method: "DELETE"
        });
        const nextWatchlist = data.items || [];
        setWatchlist(nextWatchlist);
        setWatchlistActionStatus(`已删除：${stockName}`);
        if (selectedStockId === item.id) {
          setSelectedStockId("");
          updateStocksPath("", "watchlist");
        }
        if (editingStockId === item.id) {
          setEditingStockId("");
          setEditingName("");
        }
        const statusText = withWatchlistCount(lastStatusText.current || "自选股票已更新", nextWatchlist.length);
        lastStatusText.current = statusText;
        setStatus(statusText);
      } catch (error) {
        setWatchlistActionStatus(`删除失败：${error.message}`);
      } finally {
        setWatchlistBusyId("");
      }
    },
    [editingStockId, selectedStockId, updateStocksPath]
  );

  const requestBackgroundRefresh = useBackgroundRefresh("stocks", refreshing, setRefreshing, setStatus, lastStatusText);
  useRefreshPolling("stocks", loadStocks, setRefreshing, setStatus, lastStatusText, lastRefreshFinishedAt);

  useEffect(() => {
    loadStocks({ markNew: false });
    const autoTimer = window.setInterval(() => requestBackgroundRefresh("timer", { force: false }), AUTO_REFRESH_MS);
    return () => window.clearInterval(autoTimer);
  }, [loadStocks, requestBackgroundRefresh]);

  return (
    <PageShell
      eyebrow={stockTab === "market" ? "大盘 · A股 / 港股 / 美股" : "个股 · 自选股票"}
      title="股票市场流动性与估值"
      activePage="stocks"
      status={status}
      actions={<RefreshButton loading={refreshing} title="刷新股票数据" onClick={requestBackgroundRefresh} />}
    >
      <div className="stock-subtabs" role="tablist" aria-label="股票功能">
        <button
          id="stock-tab-market"
          className={stockTab === "market" ? "is-active" : ""}
          type="button"
          role="tab"
          aria-selected={stockTab === "market"}
          aria-controls="stock-panel-market"
          onClick={() => selectStockTab("market")}
        >
          <strong>大盘</strong>
          <span>A股 · 港股 · 美股 · 融资与机构占比</span>
        </button>
        <button
          id="stock-tab-watchlist"
          className={stockTab === "watchlist" ? "is-active" : ""}
          type="button"
          role="tab"
          aria-selected={stockTab === "watchlist"}
          aria-controls="stock-panel-watchlist"
          onClick={() => selectStockTab("watchlist")}
        >
          <strong>个股 <em>{watchlist.length}</em></strong>
          <span>自选股票 · 行情 · 公司详情</span>
        </button>
      </div>

      {stockTab === "market" ? (
        <div id="stock-panel-market" className="stock-tab-panel" role="tabpanel" aria-labelledby="stock-tab-market">
          <section className="market-grid" aria-live="polite">
            {!markets.length ? (
              <p className="empty">暂未取到市场流动性数据。</p>
            ) : (
              markets.map((market, index) => {
                const key = marketKey(market, index);
                return <MarketCard key={key} market={market} snapshotAt={snapshotAt} isNew={newMarketKeys.has(key)} />;
              })
            )}
          </section>
          <InstitutionIndustryAllocation allocation={institutionAllocation} />
        </div>
      ) : (
        <div id="stock-panel-watchlist" className="stock-tab-panel" role="tabpanel" aria-labelledby="stock-tab-watchlist">
          <WatchlistTable
            items={watchlist}
            importQuery={importQuery}
            importStatus={importStatus}
            importBusy={importBusy}
            selectedStockId={selectedStockId}
            actionStatus={watchlistActionStatus}
            busyId={watchlistBusyId}
            editingStockId={editingStockId}
            editingName={editingName}
            onImport={importStock}
            onImportQueryChange={setImportQuery}
            onSelectStock={selectStock}
            onStartEdit={startEditStock}
            onCancelEdit={cancelEditStock}
            onSaveEdit={saveStockName}
            onDelete={deleteStock}
            onEditingNameChange={setEditingName}
          />

          {selectedStockId && <StockWatchDetailEmbed stockId={selectedStockId} status={status} onClose={closeDetail} />}
        </div>
      )}
    </PageShell>
  );
}

function InstitutionIndustryAllocation({ allocation = {} }) {
  const categories = allocation.categories || [];
  const industries = allocation.industries || [];
  const errors = allocation.errors || [];

  return (
    <section className="institution-allocation" aria-labelledby="institution-allocation-title">
      <div className="institution-allocation-heading">
        <div>
          <p className="eyebrow">机构持仓结构</p>
          <h2 id="institution-allocation-title">各类资金的行业占比</h2>
          <p>{allocation.basis || "各类资金已披露持仓市值内的行业占比"}</p>
        </div>
        {allocation.reportDate && <span className="allocation-period">主口径截至 {allocation.reportDate}</span>}
      </div>

      {!categories.length || !industries.length ? (
        <p className="empty">机构行业占比暂未取到，市场总览仍可正常使用。</p>
      ) : (
        <>
          <div className="allocation-category-grid">
            {categories.map((category) => (
              <article className="allocation-category-card" key={category.id}>
                <header>
                  <strong>{category.label}</strong>
                  <span>{category.reportDate}</span>
                </header>
                <b>{formatMoney(category.totalMarketValue, "CNY")}</b>
                <p>
                  样本 {formatNumber(category.sampleCount, 0)}
                  {category.totalCount && category.totalCount !== category.sampleCount ? ` / ${formatNumber(category.totalCount, 0)}` : ""}
                </p>
                {category.coveragePct !== null && category.coveragePct !== undefined && (
                  <p>{category.coverageLabel} {formatPctPlain(category.coveragePct)}</p>
                )}
                <small>{category.note}</small>
                <a href={category.sourceUrl} target="_blank" rel="noreferrer">
                  {category.source} <ExternalLink size={12} aria-hidden="true" />
                </a>
              </article>
            ))}
          </div>

          <div className="allocation-table-wrap">
            <table className="allocation-table">
              <thead>
                <tr>
                  <th scope="col">申万一级行业</th>
                  {categories.map((category) => <th scope="col" key={category.id}>{category.label}</th>)}
                </tr>
              </thead>
              <tbody>
                {industries.map((industry) => (
                  <tr key={industry.name}>
                    <th scope="row">{industry.name}</th>
                    {categories.map((category) => {
                      const value = industry.values?.[category.id];
                      return (
                        <td key={category.id}>
                          {value ? (
                            <div className="allocation-value" title={`${industry.name} · ${category.label}：${formatPctPlain(value.sharePct)}，${formatMoney(value.marketValue, "CNY")}`}>
                              <span className="allocation-bar" style={{ width: `${Math.min(Number(value.sharePct) || 0, 100)}%` }} aria-hidden="true" />
                              <strong>{formatPctPlain(value.sharePct)}</strong>
                              <small>{formatMoney(value.marketValue, "CNY")}</small>
                            </div>
                          ) : (
                            <span className="allocation-missing">—</span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {!!errors.length && <p className="allocation-warning">部分来源本轮未取到：{errors.join("；")}</p>}
      {!!allocation.notes?.length && (
        <ul className="allocation-notes">
          {allocation.notes.map((note) => <li key={note}>{note}</li>)}
        </ul>
      )}
    </section>
  );
}

function WatchlistTable({
  items,
  importQuery,
  importStatus,
  importBusy,
  selectedStockId,
  actionStatus,
  busyId,
  editingStockId,
  editingName,
  onImport,
  onImportQueryChange,
  onSelectStock,
  onStartEdit,
  onCancelEdit,
  onSaveEdit,
  onDelete,
  onEditingNameChange
}) {
  const statusText = actionStatus || importStatus;
  return (
    <section className="watchlist-section" aria-live="polite">
      <div className="watchlist-toolbar">
        <div className="section-title compact watchlist-title">
          <span>{items.length}</span>
          <h2>自选股票</h2>
        </div>
        <form className="watchlist-import" onSubmit={onImport}>
          <input
            type="text"
            value={importQuery}
            onChange={(event) => onImportQueryChange(event.target.value)}
            placeholder="HK01104 / 603173 / MOMO"
            aria-label="导入股票代码"
            disabled={importBusy}
          />
          <button className="secondary-action" type="submit" disabled={importBusy}>
            {importBusy ? "导入中" : "导入"}
          </button>
          {statusText && <span>{statusText}</span>}
        </form>
      </div>
      <div className="stock-table-wrap">
        <table className="stock-table watchlist-table">
          <thead>
            <tr>
              <th>公司</th>
              <th>当前价</th>
              <th>涨跌幅</th>
              <th>成交量</th>
              <th>成交额</th>
              <th>总市值</th>
              <th>换手率</th>
              <th>PE</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {!items.length ? (
              <tr>
                <td colSpan="9" className="table-empty">
                  暂无自选股票。
                </td>
              </tr>
            ) : (
              items.map((item) => {
                const isSelected = selectedStockId === item.id;
                const isEditing = editingStockId === item.id;
                const isBusy = busyId === item.id;
                const stockName = item.name || item.symbol || item.id;
                const cacheText = item.detailCached ? (item.detailStale ? "详情待刷新" : "详情已预抓") : "详情待预抓";
                return (
                  <tr key={item.id} className={isSelected ? "is-selected" : ""}>
                    <td>
                      {isEditing ? (
                        <label className="watchlist-edit-cell">
                          <input
                            className="watchlist-edit-input"
                            value={editingName}
                            autoFocus
                            onChange={(event) => onEditingNameChange(event.target.value)}
                            onKeyDown={(event) => {
                              if (event.key === "Enter") onSaveEdit(item);
                              if (event.key === "Escape") onCancelEdit();
                            }}
                            disabled={isBusy}
                            aria-label={`编辑 ${stockName} 名称`}
                          />
                          <small>
                            {item.marketLabel} {item.symbol}
                          </small>
                        </label>
                      ) : (
                        <button className="watchlist-stock-link" type="button" onClick={() => onSelectStock(item)} aria-current={isSelected ? "true" : undefined}>
                          <strong>{stockName}</strong>
                          <small>
                            {item.marketLabel} {item.symbol}
                          </small>
                          <small className={`watchlist-cache-badge${item.detailCached && !item.detailStale ? " is-ready" : ""}`}>{cacheText}</small>
                        </button>
                      )}
                    </td>
                    <td>{formatNumber(item.price, priceDigits(item.price))}</td>
                    <td className={pctClass(item.changePct)}>{formatSignedChange(item.change, item.changePct)}</td>
                    <td>{formatVolume(item.volume)}</td>
                    <td>{formatMoney(item.amount)}</td>
                    <td>{formatMoney(item.marketCap)}</td>
                    <td>{formatPctPlain(item.turnoverRate)}</td>
                    <td>{formatNumber(item.pe, 2)}</td>
                    <td className="watchlist-actions-cell">
                      <div className="watchlist-actions">
                        {isEditing ? (
                          <>
                            <button className="icon-action" type="button" title="保存名称" aria-label="保存名称" disabled={isBusy} onClick={() => onSaveEdit(item)}>
                              <Check size={15} aria-hidden="true" />
                            </button>
                            <button className="icon-action" type="button" title="取消编辑" aria-label="取消编辑" disabled={isBusy} onClick={onCancelEdit}>
                              <X size={15} aria-hidden="true" />
                            </button>
                          </>
                        ) : (
                          <>
                            <button className="icon-action" type="button" title={`编辑 ${stockName}`} aria-label={`编辑 ${stockName}`} disabled={isBusy} onClick={() => onStartEdit(item)}>
                              <Pencil size={15} aria-hidden="true" />
                            </button>
                            <button className="icon-action danger-action" type="button" title={`删除 ${stockName}`} aria-label={`删除 ${stockName}`} disabled={isBusy} onClick={() => onDelete(item)}>
                              <Trash2 size={15} aria-hidden="true" />
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function XueqiuPage() {
  const [influencers, setInfluencers] = useState([]);
  const [activities, setActivities] = useState([]);
  const [summary, setSummary] = useState({});
  const [todayLabel, setTodayLabel] = useState("");
  const [newIds, setNewIds] = useState(new Set());
  const [status, setStatus] = useState("正在获取雪球大V动态...");
  const [refreshing, setRefreshing] = useState(false);
  const [importQuery, setImportQuery] = useState("");
  const [importStatus, setImportStatus] = useState("");
  const [importBusy, setImportBusy] = useState(false);
  const [removingIds, setRemovingIds] = useState(new Set());
  const [filter, setFilter] = useState("all");

  const knownSignatures = useRef(new Map());
  const lastStatusText = useRef("");
  const lastRefreshFinishedAt = useRef("");

  const applyXueqiuData = useCallback((data, { markNew = false } = {}) => {
    const nextActivities = data.activities || [];
    const previousSignatures = new Map(knownSignatures.current);
    const nextSignatures = collectXueqiuSignatures(nextActivities);
    const changedIds = new Set();

    if (markNew) {
      for (const [key, signature] of nextSignatures.entries()) {
        if (previousSignatures.get(key) !== signature) changedIds.add(key);
      }
    }

    setInfluencers(data.influencers || []);
    setActivities(nextActivities);
    setSummary(data.summary || {});
    setTodayLabel(data.todayLabel || "");
    setNewIds(changedIds);
    knownSignatures.current = nextSignatures;

    const statusText = buildXueqiuStatus(data);
    lastStatusText.current = statusText;
    setStatus(statusText);
  }, []);

  const loadXueqiu = useCallback(async ({ markNew = false } = {}) => {
    setStatus("正在读取本地快照...");
    try {
      const data = await getJson(`/api/xueqiu?t=${Date.now()}`);
      applyXueqiuData(data, { markNew });
      return true;
    } catch (error) {
      setStatus(`获取失败：${error.message}`);
      return false;
    }
  }, [applyXueqiuData]);

  const importInfluencer = useCallback(async (event) => {
    event.preventDefault();
    const query = importQuery.trim();
    if (!query) {
      setImportStatus("请输入雪球大V主页链接、用户ID或昵称");
      return;
    }
    setImportBusy(true);
    setImportStatus("正在导入...");
    try {
      const data = await getJson(`/api/xueqiu/import?t=${Date.now()}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query })
      });
      applyXueqiuData(data, { markNew: false });
      const influencer = data.influencer || {};
      setImportQuery("");
      setImportStatus(`${data.imported ? "已导入" : "已存在"}：${influencer.name || query}`);
    } catch (error) {
      setImportStatus(`导入失败：${error.message}`);
    } finally {
      setImportBusy(false);
    }
  }, [applyXueqiuData, importQuery]);

  const removeInfluencer = useCallback(async (influencer) => {
    const id = influencer.id;
    if (!id || removingIds.has(id)) return;
    setRemovingIds((current) => new Set([...current, id]));
    setImportStatus(`正在移除：${influencer.name || influencer.userId}`);
    try {
      const data = await getJson(`/api/xueqiu/influencers/${encodeURIComponent(id)}?t=${Date.now()}`, { method: "DELETE" });
      applyXueqiuData(data, { markNew: false });
      setImportStatus(`已移除：${influencer.name || influencer.userId}`);
    } catch (error) {
      setImportStatus(`移除失败：${error.message}`);
    } finally {
      setRemovingIds((current) => {
        const next = new Set(current);
        next.delete(id);
        return next;
      });
    }
  }, [applyXueqiuData, removingIds]);

  const requestBackgroundRefresh = useBackgroundRefresh("xueqiu", refreshing, setRefreshing, setStatus, lastStatusText);
  useRefreshPolling("xueqiu", loadXueqiu, setRefreshing, setStatus, lastStatusText, lastRefreshFinishedAt);

  useEffect(() => {
    loadXueqiu({ markNew: false });
    const autoTimer = window.setInterval(() => requestBackgroundRefresh("timer", { force: false }), AUTO_REFRESH_MS);
    return () => window.clearInterval(autoTimer);
  }, [loadXueqiu, requestBackgroundRefresh]);

  const filteredActivities = filter === "all" ? activities : activities.filter((item) => item.kind === filter);

  return (
    <PageShell
      eyebrow="今日大V动态 / 帖子 / 评论 / 回复"
      title="雪球"
      activePage="xueqiu"
      status={status}
      actions={<RefreshButton loading={refreshing} title="刷新雪球动态" onClick={requestBackgroundRefresh} />}
    >
      <section className="xueqiu-overview" aria-label="雪球概览">
        <Kpi label="大V" value={`${summary.influencerCount || influencers.length || 0} 位`} />
        <Kpi label="今日动态" value={`${summary.activityCount || activities.length || 0} 条`} />
        <Kpi label="帖子" value={`${summary.postCount || 0} 条`} />
        <Kpi label="评论/回复" value={`${(summary.commentCount || 0) + (summary.replyCount || 0)} 条`} />
      </section>

      <section className="watchlist-section xueqiu-import-section" aria-live="polite">
        <div className="watchlist-toolbar">
          <div className="section-title compact watchlist-title">
            <span>{influencers.length}</span>
            <h2>导入大V</h2>
          </div>
          <form className="watchlist-import xueqiu-import" onSubmit={importInfluencer}>
            <input
              type="text"
              value={importQuery}
              onChange={(event) => setImportQuery(event.target.value)}
              placeholder="雪球主页链接 / 用户ID / 昵称"
              aria-label="导入雪球大V"
              disabled={importBusy}
            />
            <button className="secondary-action" type="submit" disabled={importBusy}>
              {importBusy ? "导入中" : "导入"}
            </button>
            {importStatus && <span>{importStatus}</span>}
          </form>
        </div>
        <XueqiuInfluencerList influencers={influencers} removingIds={removingIds} onRemove={removeInfluencer} />
      </section>

      <section className="xueqiu-feed-section" aria-live="polite">
        <div className="xueqiu-feed-head">
          <div className="section-title compact watchlist-title">
            <span>{filteredActivities.length}</span>
            <h2>{todayLabel ? `${todayLabel}动态` : "今日动态"}</h2>
          </div>
          <XueqiuFilterTabs activeFilter={filter} summary={summary} total={activities.length} onChange={setFilter} />
        </div>
        <div className="xueqiu-feed-list">
          {!filteredActivities.length ? (
            <p className="empty">暂未取到符合条件的雪球动态。</p>
          ) : (
            filteredActivities.map((item) => <XueqiuActivityCard key={xueqiuActivityId(item)} item={item} isNew={newIds.has(xueqiuActivityId(item))} />)
          )}
        </div>
      </section>
    </PageShell>
  );
}

function XueqiuInfluencerList({ influencers, removingIds, onRemove }) {
  if (!influencers.length) return <p className="table-empty xueqiu-empty-inline">暂无雪球大V。</p>;
  return (
    <div className="xueqiu-influencer-list">
      {influencers.map((influencer) => (
        <article key={influencer.id} className={`xueqiu-influencer-card${influencer.activityError ? " has-error" : ""}`}>
          <div>
            <a href={influencer.profileUrl} target="_blank" rel="noreferrer">
              <strong>{influencer.name || influencer.userId}</strong>
              <ExternalLink size={13} aria-hidden="true" />
            </a>
            <small>{[influencer.verified ? "已认证" : "", formatFollowers(influencer.followersCount), influencer.description].filter(Boolean).join(" / ")}</small>
            {influencer.activityError && <span>{influencer.activityError}</span>}
          </div>
          <div className="xueqiu-influencer-side">
            <b>{influencer.activityCount || 0}</b>
            <button className="icon-action" type="button" title={`移除 ${influencer.name || influencer.userId}`} onClick={() => onRemove(influencer)} disabled={removingIds.has(influencer.id)}>
              <Trash2 size={15} aria-hidden="true" />
            </button>
          </div>
        </article>
      ))}
    </div>
  );
}

function XueqiuFilterTabs({ activeFilter, summary, total, onChange }) {
  const tabs = [
    { id: "all", label: "全部", count: total },
    { id: "post", label: "帖子", count: summary.postCount || 0 },
    { id: "comment", label: "评论", count: summary.commentCount || 0 },
    { id: "reply", label: "回复", count: summary.replyCount || 0 },
    { id: "repost", label: "转发", count: summary.repostCount || 0 }
  ];
  return (
    <div className="xueqiu-filter-tabs" role="tablist" aria-label="雪球动态筛选">
      {tabs.map((tab) => (
        <button key={tab.id} className={activeFilter === tab.id ? "active" : ""} type="button" onClick={() => onChange(tab.id)}>
          {tab.label}
          <span>{tab.count}</span>
        </button>
      ))}
    </div>
  );
}

function XueqiuActivityCard({ item, isNew }) {
  return (
    <article className={`xueqiu-card${isNew ? " is-new" : ""}`}>
      <header>
        <span className={`activity-type ${item.kind || "post"}`}>{item.kindLabel || "动态"}</span>
        <a href={item.url || "#"} target="_blank" rel="noreferrer">
          {item.influencerName || "雪球用户"}
          <ExternalLink size={13} aria-hidden="true" />
        </a>
        <time dateTime={item.publishedAt}>{formatTime(item.publishedAt)}</time>
      </header>
      <p>{item.text}</p>
      {item.targetTitle && <blockquote>{item.targetTitle}</blockquote>}
      {item.note && <small className="xueqiu-note">{item.note}</small>}
      <footer>
        <span className="source">{item.source || "雪球"}</span>
        <span>
          {[
            item.replyCount ? `评论 ${formatNumber(item.replyCount, 0)}` : "",
            item.retweetCount ? `转发 ${formatNumber(item.retweetCount, 0)}` : "",
            item.likeCount ? `赞 ${formatNumber(item.likeCount, 0)}` : ""
          ].filter(Boolean).join(" / ") || "暂无互动数据"}
        </span>
      </footer>
    </article>
  );
}

function StockWatchDetailEmbed({ stockId, status, onClose }) {
  const [detail, setDetail] = useState(null);
  const [detailStatus, setDetailStatus] = useState("正在读取半小时缓存...");
  const [detailRefreshing, setDetailRefreshing] = useState(false);

  const loadDetail = useCallback(async ({ refresh = false } = {}) => {
    setDetailStatus(refresh ? "正在强制刷新公司详情..." : "正在读取已预抓取的公司详情...");
    try {
      const params = new URLSearchParams({ t: Date.now().toString(), refresh: String(refresh) });
      const data = await getJson(`/api/stock-watchlist/${encodeURIComponent(stockId)}?${params}`);
      setDetail(data);
      setDetailStatus(buildWatchDetailStatusV2(data));
      return true;
    } catch (error) {
      setDetailStatus(`获取失败：${error.message}`);
      return false;
    }
  }, [stockId]);

  const refreshDetail = useCallback(async () => {
    setDetailRefreshing(true);
    try {
      await loadDetail({ refresh: true });
    } finally {
      setDetailRefreshing(false);
    }
  }, [loadDetail]);

  useEffect(() => {
    setDetail(null);
    loadDetail();
  }, [loadDetail]);

  const stock = detail?.stock || {};
  const sections = detail?.sections || {};

  return (
    <section className="watchlist-detail-embed" aria-live="polite">
      <div className="watchlist-detail-head">
        <div>
          <p className="market-label">
            {stock.marketLabel || "自选股票"} {stock.symbol || stockId}
          </p>
          <h2>{stock.name || "公司详情"}</h2>
          <p className="stock-detail-status">{detailStatus || status}</p>
        </div>
        <div className="watchlist-detail-actions">
          <RefreshButton loading={detailRefreshing} title="刷新公司详情" onClick={refreshDetail} />
          <button className="secondary-action" type="button" title="收起详情" onClick={onClose}>
            <X size={16} aria-hidden="true" />
            收起
          </button>
        </div>
      </div>
      {!detail ? (
        <p className="empty">正在加载公司详情。</p>
      ) : (
        <section className="stock-detail-layout">
          <StockDetailHero stock={stock} />
          <StockDetailPanel title="做空、基金与股东" source={joinSources(sections.shortInterest, sections.fundHoldings, sections.shareholders)} errors={sectionErrors(sections.shortInterest, sections.fundHoldings, sections.shareholders)}>
            <ShortAndHolderSection shortInterest={sections.shortInterest} fundHoldings={sections.fundHoldings} shareholders={sections.shareholders} />
          </StockDetailPanel>
          <StockDetailPanel title="最近资讯" source={sections.news?.source} errors={sectionErrors(sections.news)}>
            <LinkList items={sections.news?.items} empty="暂无资讯。" limit={20} />
          </StockDetailPanel>
          <StockDetailPanel title="社区热帖" source={sections.socialPosts?.source} errors={sectionErrors(sections.socialPosts)}>
            <LinkList items={sections.socialPosts?.items} empty="暂无热帖。" showHeat />
          </StockDetailPanel>
          <StockDetailPanel title="资金流向" source={sections.capitalFlow?.source} errors={sectionErrors(sections.capitalFlow)}>
            <CapitalFlowTable items={sections.capitalFlow?.items} />
          </StockDetailPanel>
          <StockDetailPanel title="公司动态" source={sections.announcements?.source} errors={sectionErrors(sections.announcements)}>
            <LinkList items={sections.announcements?.items} empty="暂无公司动态。" />
          </StockDetailPanel>
          <StockDetailPanel title="券商评级与目标价" source={sections.ratings?.source} errors={sectionErrors(sections.ratings)}>
            <RatingTable items={sections.ratings?.items} />
          </StockDetailPanel>
          <StockDetailPanel title="股东分布比例" source={joinSources(sections.shareholderDistribution, sections.shareholders)} errors={sectionErrors(sections.shareholderDistribution, sections.shareholders)}>
            <ShareholderDistributionSection distribution={sections.shareholderDistribution} shareholders={sections.shareholders} />
          </StockDetailPanel>
        </section>
      )}
    </section>
  );
}

function StockWatchDetail({ stockId, status }) {
  const [detail, setDetail] = useState(null);
  const [detailStatus, setDetailStatus] = useState("正在获取公司详情...");
  const [detailRefreshing, setDetailRefreshing] = useState(false);

  const loadDetail = useCallback(async ({ refresh = false } = {}) => {
    setDetailStatus("正在读取公司详情...");
    try {
      const params = new URLSearchParams({ t: Date.now().toString(), refresh: String(refresh) });
      const data = await getJson(`/api/stock-watchlist/${encodeURIComponent(stockId)}?${params}`);
      setDetail(data);
      setDetailStatus(buildWatchDetailStatus(data));
      return true;
    } catch (error) {
      setDetailStatus(`获取失败：${error.message}`);
      return false;
    }
  }, [stockId]);

  const refreshDetail = useCallback(async () => {
    setDetailRefreshing(true);
    try {
      await loadDetail({ refresh: true });
    } finally {
      setDetailRefreshing(false);
    }
  }, [loadDetail]);

  useEffect(() => {
    loadDetail();
  }, [loadDetail]);

  const stock = detail?.stock || {};
  const sections = detail?.sections || {};

  return (
    <PageShell
      eyebrow={`${stock.marketLabel || "自选股票"} / ${stock.symbol || stockId}`}
      title={stock.name || "公司详情"}
      activePage="stocks"
      status={detailStatus || status}
      actions={
        <>
          <a className="secondary-action" href="/stocks" title="返回自选股票">
            <ArrowLeft size={16} aria-hidden="true" />
            返回
          </a>
          <RefreshButton loading={detailRefreshing} title="刷新公司详情" onClick={refreshDetail} />
        </>
      }
    >
      {!detail ? (
        <p className="empty">正在加载公司详情。</p>
      ) : (
        <section className="stock-detail-layout">
          <StockDetailHero stock={stock} />
          <StockDetailPanel title="做空、基金与股东" source={joinSources(sections.shortInterest, sections.fundHoldings, sections.shareholders)} errors={sectionErrors(sections.shortInterest, sections.fundHoldings, sections.shareholders)}>
            <ShortAndHolderSection shortInterest={sections.shortInterest} fundHoldings={sections.fundHoldings} shareholders={sections.shareholders} />
          </StockDetailPanel>
          <StockDetailPanel title="最近资讯" source={sections.news?.source} errors={sectionErrors(sections.news)}>
            <LinkList items={sections.news?.items} empty="暂无资讯。" limit={20} />
          </StockDetailPanel>
          <StockDetailPanel title="社区热帖" source={sections.socialPosts?.source} errors={sectionErrors(sections.socialPosts)}>
            <LinkList items={sections.socialPosts?.items} empty="暂无热帖。" showHeat />
          </StockDetailPanel>
          <StockDetailPanel title="资金流向" source={sections.capitalFlow?.source} errors={sectionErrors(sections.capitalFlow)}>
            <CapitalFlowTable items={sections.capitalFlow?.items} />
          </StockDetailPanel>
          <StockDetailPanel title="公司动态" source={sections.announcements?.source} errors={sectionErrors(sections.announcements)}>
            <LinkList items={sections.announcements?.items} empty="暂无公司动态。" />
          </StockDetailPanel>
          <StockDetailPanel title="券商评级与目标价" source={sections.ratings?.source} errors={sectionErrors(sections.ratings)}>
            <RatingTable items={sections.ratings?.items} />
          </StockDetailPanel>
          <StockDetailPanel title="股东分布比例" source={joinSources(sections.shareholderDistribution, sections.shareholders)} errors={sectionErrors(sections.shareholderDistribution, sections.shareholders)}>
            <ShareholderDistributionSection distribution={sections.shareholderDistribution} shareholders={sections.shareholders} />
          </StockDetailPanel>
        </section>
      )}
    </PageShell>
  );
}

function StockDetailHero({ stock }) {
  return (
    <section className="stock-detail-hero">
      <div>
        <p className="market-label">
          {stock.marketLabel} {stock.symbol} {stock.industry ? ` / ${stock.industry}` : ""}
        </p>
        <h2>{stock.name || stock.symbol}</h2>
        {stock.quoteUrl && (
          <a href={stock.quoteUrl} target="_blank" rel="noreferrer">
            <ExternalLink size={14} aria-hidden="true" />
            东方财富
          </a>
        )}
      </div>
      <div className="stock-detail-kpis">
        <Kpi label="当前价" value={formatNumber(stock.price, priceDigits(stock.price))} />
        <Kpi label="涨跌幅" value={formatSignedChange(stock.change, stock.changePct)} />
        <Kpi label="成交额" value={formatMoney(stock.amount)} />
        <Kpi label="总市值" value={formatMoney(stock.marketCap)} />
        <Kpi label="换手率" value={formatPctPlain(stock.turnoverRate)} />
        <Kpi label="PE" value={formatNumber(stock.pe, 2)} />
      </div>
    </section>
  );
}

function StockDetailPanel({ title, source, errors, children }) {
  return (
    <section className="stock-detail-panel">
      <div className="stock-detail-panel-head">
        <h2>{title}</h2>
        {source && <span>{source}</span>}
      </div>
      {Array.isArray(errors) && errors.length > 0 && <p className="stock-source-error">{errors.join("；")}</p>}
      {children}
    </section>
  );
}

function ShortAndHolderSection({ shortInterest, fundHoldings, shareholders }) {
  const shortRows = shortInterest?.items || [];
  const fundRows = fundHoldings?.items || [];
  const holderRows = shareholders?.items || [];
  const holdingRows = fundRows.length ? fundRows : holderRows;
  const holdingHeading = fundRows.length ? "基金/机构 Top5" : "权益披露 Top5";
  const holdingEmpty = fundRows.length ? "暂无基金或机构持仓数据。" : "暂无权益披露持仓数据。";
  return (
    <div className="stock-three-column">
      <div className="stock-mini-section">
        <h3>做空/融券</h3>
        {shortInterest?.note && <p className="stock-muted-text">{shortInterest.note}</p>}
        <SimpleMetricList
          items={shortRows.slice(0, 5).map((item) => ({
            label: item.date || "最新",
            value: hasValue(item.shortRatio)
              ? formatPctPlain(item.shortRatio)
              : hasValue(item.shortBalance)
                ? formatMoney(item.shortBalance)
                : hasValue(item.shortTurnover)
                  ? formatMoney(item.shortTurnover)
                  : "暂无",
            detail: [
              item.holder ? `披露方 ${item.holder}` : "",
              hasValue(item.shortTurnover) ? `短卖成交额 ${formatMoney(item.shortTurnover)}` : "",
              hasValue(item.shortVolume) ? `短卖股数 ${formatVolume(item.shortVolume)}` : "",
              hasValue(item.turnover) ? `总成交额 ${formatMoney(item.turnover)}` : "",
              hasValue(item.financingBalance) ? `融资余额 ${formatMoney(item.financingBalance)}` : "",
              item.source
            ]
              .filter(Boolean)
              .join(" / ")
          }))}
          empty="暂无做空或融券数据。"
        />
      </div>
      <div className="stock-mini-section">
        <h3>{holdingHeading}</h3>
        <SimpleMetricList
          items={holdingRows.slice(0, 5).map((item) => ({
            label: item.name,
            value: hasValue(item.ratio) ? formatPctPlain(item.ratio) : formatMoney(item.marketValue),
            detail: [item.date, hasValue(item.shares) ? `持股 ${formatVolume(item.shares)}` : "", item.source].filter(Boolean).join(" / ")
          }))}
          empty={holdingEmpty}
        />
      </div>
      <div className="stock-mini-section">
        <h3>主要股东</h3>
        <SimpleMetricList
          items={holderRows.slice(0, 10).map((item) => ({
            label: item.name,
            value: hasValue(item.ratio) ? formatPctPlain(item.ratio) : formatVolume(item.shares),
            detail: [item.date, item.change].filter(Boolean).join(" / ")
          }))}
          empty="暂无股东数据。"
        />
      </div>
    </div>
  );
}

function ShareholderDistributionSection({ distribution, shareholders }) {
  const distributionRows = distribution?.items || [];
  const holderRows = shareholders?.items || [];
  return (
    <div className="stock-two-column">
      <div className="stock-mini-section">
        <h3>股东户数</h3>
        <SimpleMetricList
          items={distributionRows.slice(0, 8).map((item) => ({
            label: item.date || "最新",
            value: hasValue(item.holderCount) ? formatVolume(item.holderCount) : "暂无",
            detail: [
              hasValue(item.avgHolding) ? `户均持股 ${formatVolume(item.avgHolding)}` : "",
              hasValue(item.avgMarketValue) ? `户均市值 ${formatMoney(item.avgMarketValue)}` : "",
              hasValue(item.changePct) ? `变化 ${formatPct(item.changePct)}` : ""
            ]
              .filter(Boolean)
              .join(" / ")
          }))}
          empty="暂无股东户数数据。"
        />
      </div>
      <div className="stock-mini-section">
        <h3>前十大股东占比</h3>
        <SimpleMetricList
          items={holderRows.slice(0, 10).map((item) => ({
            label: item.name,
            value: hasValue(item.ratio) ? formatPctPlain(item.ratio) : formatVolume(item.shares),
            detail: [item.date, hasValue(item.shares) ? `持股 ${formatVolume(item.shares)}` : ""].filter(Boolean).join(" / ")
          }))}
          empty="暂无股东占比数据。"
        />
      </div>
    </div>
  );
}

function SimpleMetricList({ items, empty }) {
  if (!items?.length) return <p className="table-empty">{empty}</p>;
  return (
    <ul className="stock-metric-list">
      {items.map((item, index) => (
        <li key={`${item.label}-${index}`}>
          <span>{item.label}</span>
          <strong>{item.value}</strong>
          {item.detail && <small>{item.detail}</small>}
        </li>
      ))}
    </ul>
  );
}

function LinkList({ items, empty, showHeat = false, limit = 15 }) {
  if (!items?.length) return <p className="table-empty">{empty}</p>;
  return (
    <div className="stock-link-list">
      {items.slice(0, limit).map((item, index) => (
        <a key={`${item.url || item.title}-${index}`} href={item.url || "#"} target="_blank" rel="noreferrer">
          <strong>{item.title || "未命名"}</strong>
          <span>
            {[item.source, item.author, formatTime(item.publishedAt), showHeat && item.heat ? `热度 ${formatNumber(item.heat, 0)}` : ""].filter(Boolean).join(" / ")}
          </span>
        </a>
      ))}
    </div>
  );
}

function CapitalFlowTable({ items }) {
  if (!items?.length) return <p className="table-empty">暂无资金流向。</p>;
  return (
    <div className="stock-table-wrap">
      <table className="stock-table stock-detail-table">
        <thead>
          <tr>
            <th>日期</th>
            <th>主力净流入</th>
            <th>主力占比</th>
            <th>大单净流入</th>
            <th>收盘</th>
            <th>涨跌幅</th>
          </tr>
        </thead>
        <tbody>
          {items.slice(0, 15).map((item) => (
            <tr key={item.date}>
              <td>{item.date}</td>
              <td className={pctClass(item.mainNetInflow)}>{formatMoney(item.mainNetInflow, item.currency)}</td>
              <td className={pctClass(item.mainNetRatio)}>{formatPctPlain(item.mainNetRatio)}</td>
              <td className={pctClass(item.largeNetInflow)}>{formatMoney(item.largeNetInflow, item.currency)}</td>
              <td>{formatNumber(item.close, priceDigits(item.close))}</td>
              <td className={pctClass(item.changePct)}>{formatPct(item.changePct)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RatingTable({ items }) {
  if (!items?.length) return <p className="table-empty">暂无评级与目标价。</p>;
  return (
    <div className="stock-table-wrap">
      <table className="stock-table stock-detail-table">
        <thead>
          <tr>
            <th>日期</th>
            <th>券商</th>
            <th>评级</th>
            <th>目标价</th>
            <th>标题</th>
          </tr>
        </thead>
        <tbody>
          {items.slice(0, 15).map((item, index) => (
            <tr key={`${item.date}-${item.title}-${index}`}>
              <td>{item.date || "未知"}</td>
              <td>
                <strong>{item.broker || "公开来源"}</strong>
                <small>{item.analyst || ""}</small>
              </td>
              <td>{item.rating || "暂无"}</td>
              <td>{item.targetPriceText || formatNumber(item.targetPrice, 2)}</td>
              <td>
                {item.url ? (
                  <a className="source-link" href={item.url} target="_blank" rel="noreferrer">
                    {item.title || "查看研报"}
                  </a>
                ) : (
                  item.title || "暂无标题"
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MarketCard({ market, snapshotAt, isNew }) {
  const indices = market.indices || [];
  const marketTime = market.dataTimestamp || snapshotAt;

  return (
    <article className={`market-card${isNew ? " is-new" : ""}`}>
      <div className="market-card-head">
        <div>
          <p className="market-label">{market.currencyName ? `${market.currencyName}计价` : market.currency || ""}</p>
          <h2>{market.name || "-"}</h2>
        </div>
        <div className="market-meta">
          <time dateTime={marketTime || undefined}>{formatTime(marketTime)}</time>
          <span>{market.source || "公开来源"}</span>
        </div>
      </div>

      <div className="market-kpis">
        <Kpi label={market.marketCapLabel || "当前总市值"} value={formatMoney(market.marketCap, market.currency)} />
        <Kpi label="总市值 / GDP" value={formatPctPlain(market.marketCapToGdpPct)} />
        <Kpi label="今日成交额" value={formatMoney(market.turnover, market.currency)} />
        <Kpi label="成交额 / 总市值" value={formatPctPlain(market.turnoverToMarketCapPct)} />
        <Kpi label="成交额分位" value={formatPercentile(market.turnoverPercentile, market.turnoverPercentileSample, market.turnoverPercentileNote)} />
        <Kpi label="融资余额" value={formatMoney(market.financingBalance, market.currency)} />
        <Kpi label={`融资 / ${market.financingToMarketCapBasis || "市值"}`} value={formatPctPlain(market.financingToMarketCapPct)} />
        <Kpi label="融资占比分位" value={formatPercentile(market.financingPercentile, market.financingPercentileSample, market.financingPercentileNote)} />
        <Kpi label="PE" value={formatNumber(market.pe, 2)} />
        <Kpi label="PE 分位" value={formatPercentile(market.pePercentile, market.pePercentileSample, market.pePercentileNote)} />
        <Kpi label="覆盖股票数" value={`${market.includedCount || 0}/${market.totalCount || 0}`} />
      </div>

      <p className="market-note">{buildMarketNote(market)}</p>

      <div className="stock-table-wrap">
        <table className="stock-table index-table">
          <thead>
            <tr>
              <th>主要指数</th>
              <th>K线</th>
              <th>点位</th>
              <th>涨跌幅</th>
              <th>成交量</th>
            </tr>
          </thead>
          <tbody>
            {!indices.length ? (
              <tr>
                <td colSpan="5" className="table-empty">
                  暂无指数数据
                </td>
              </tr>
            ) : (
              indices.map((item) => (
                <tr key={item.symbol || item.name}>
                  <td>
                    <strong>{item.name || "-"}</strong>
                    <small>{item.symbol || ""}</small>
                  </td>
                  <td>
                    <TrendSparkline item={item} />
                  </td>
                  <td>{formatNumber(item.close, 2)}</td>
                  <td className={pctClass(item.changePct)}>{formatPct(item.changePct)}</td>
                  <td>{formatVolume(item.volume)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </article>
  );
}

function CommoditiesPage() {
  const [items, setItems] = useState([]);
  const [newKeys, setNewKeys] = useState(new Set());
  const [status, setStatus] = useState("正在获取大宗商品数据...");
  const [refreshing, setRefreshing] = useState(false);

  const knownSignatures = useRef(new Map());
  const lastStatusText = useRef("");
  const lastRefreshFinishedAt = useRef("");

  const loadCommodities = useCallback(async ({ markNew = false } = {}) => {
    setStatus("正在读取本地快照...");

    try {
      const data = await getJson(`/api/commodities?t=${Date.now()}`);
      const nextItems = data.items || [];
      const previousSignatures = new Map(knownSignatures.current);
      const nextSignatures = collectCommoditySignatures(nextItems);
      const changedKeys = new Set();

      if (markNew) {
        for (const [key, signature] of nextSignatures.entries()) {
          if (previousSignatures.get(key) !== signature) changedKeys.add(key);
        }
      }

      setItems(nextItems);
      setNewKeys(changedKeys);
      knownSignatures.current = nextSignatures;

      const statusText = buildCommoditiesStatus(data);
      lastStatusText.current = statusText;
      setStatus(statusText);
      return true;
    } catch (error) {
      setStatus(`获取失败：${error.message}`);
      return false;
    }
  }, []);

  const requestBackgroundRefresh = useBackgroundRefresh("commodities", refreshing, setRefreshing, setStatus, lastStatusText);
  useRefreshPolling("commodities", loadCommodities, setRefreshing, setStatus, lastStatusText, lastRefreshFinishedAt);

  useEffect(() => {
    loadCommodities({ markNew: false });
    const autoTimer = window.setInterval(() => requestBackgroundRefresh("timer", { force: false }), AUTO_REFRESH_MS);
    return () => window.clearInterval(autoTimer);
  }, [loadCommodities, requestBackgroundRefresh]);

  const sectors = groupBySector(items);

  return (
    <PageShell
      eyebrow="现货 / 期货 / 升贴水 / 库存"
      title="大宗商品监控"
      activePage="commodities"
      status={status}
      actions={<RefreshButton loading={refreshing} title="刷新大宗商品数据" onClick={requestBackgroundRefresh} />}
    >
      <section className="commodity-summary" aria-label="大宗商品概览">
        <Kpi label="覆盖品种" value={`${items.length} 个`} />
        <Kpi label="国内期货" value={`${items.filter((item) => hasValue(item.domesticFuturePrice)).length} 个`} />
        <Kpi label="国际期货" value={`${items.filter((item) => hasValue(item.globalFuturePrice)).length} 个`} />
        <Kpi label="有现货价格" value={`${items.filter((item) => hasValue(item.spotPrice)).length} 个`} />
        <Kpi label="升水品种" value={`${items.filter((item) => Number(item.basis) > 0).length} 个`} />
        <Kpi label="库存K线" value={`${items.filter((item) => (item.inventoryHistory || []).length > 1).length} 个`} />
      </section>

      <section className="commodity-board" aria-live="polite">
        {!items.length ? (
          <p className="empty">暂未取到大宗商品数据。</p>
        ) : (
          sectors.map(([sector, rows]) => (
            <CommoditySection key={sector} sector={sector} items={rows} newKeys={newKeys} />
          ))
        )}
      </section>
    </PageShell>
  );
}

function CommoditySection({ sector, items, newKeys }) {
  return (
    <section className="commodity-section">
      <div className="section-title compact">
        <span>{items.length}</span>
        <h2>{sector}</h2>
      </div>
      <div className="stock-table-wrap">
        <table className="stock-table commodity-table">
          <thead>
            <tr>
              <th>品种</th>
              <th>现货</th>
              <th>国内期货</th>
              <th>国际期货</th>
              <th>现货升贴水</th>
              <th>内外盘差</th>
              <th>库存</th>
              <th>更新/来源</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => {
              const hasSpot = hasValue(item.spotPrice);
              const hasDomesticFuture = hasValue(item.domesticFuturePrice);
              const hasGlobalFuture = hasValue(item.globalFuturePrice);
              const hasBenchmarkFuture = hasValue(item.benchmarkFuturePrice);
              const hasBasis = hasValue(item.basis);
              const hasCrossMarketSpread = hasValue(item.crossMarketSpread);
              const hasInventory = hasValue(item.inventory);
              const sourceDate = item.spotDate || item.domesticFutureDate || item.globalFutureDate || item.benchmarkFutureDate || item.inventoryDate || "";
              const sourceText = [item.source, item.note].filter(Boolean).join("；");

              return (
                <tr key={item.id} className={newKeys.has(item.id) ? "is-new-row" : ""}>
                  <td>
                    <strong>{item.name}</strong>
                    {(item.spotName || item.domesticFutureName || item.globalFutureName || item.benchmarkFutureName) && <small>{item.spotName || item.domesticFutureName || item.globalFutureName || item.benchmarkFutureName}</small>}
                  </td>
                  <td>
                    {hasSpot && (
                      <>
                        {formatPrice(item.spotPrice, item.spotUnit || item.unit)}
                        {(item.spotRange || hasValue(item.spotChange)) && <small>{item.spotRange || formatChange(item.spotChange)}</small>}
                        <MiniKline history={item.spotHistory} label={`${item.name}现货价格K线`} />
                      </>
                    )}
                  </td>
                  <td>
                    {hasDomesticFuture && (
                      <>
                        {formatPrice(item.domesticFuturePrice, item.unit)}
                        {(item.domesticFutureName || item.domesticFutureSymbol || hasValue(item.domesticFutureChangePct)) && (
                          <small className={pctClass(item.domesticFutureChangePct)}>
                            {[item.domesticFutureName || item.domesticFutureSymbol, hasValue(item.domesticFutureChangePct) ? formatPct(item.domesticFutureChangePct) : ""].filter(Boolean).join(" ")}
                          </small>
                        )}
                        <MiniKline history={item.domesticFutureHistory} label={`${item.name}期货价格K线`} valueKey="close" />
                      </>
                    )}
                  </td>
                  <td>
                    {(hasGlobalFuture || hasBenchmarkFuture) && (
                      <>
                        {formatGlobalPrice(hasGlobalFuture ? item.globalFuturePrice : item.benchmarkFuturePrice)}
                        <small className={pctClass(hasGlobalFuture ? item.globalFutureChangePct : item.benchmarkFutureChangePct)}>
                          {hasGlobalFuture
                            ? [item.globalFutureName || item.globalFutureSymbol, hasValue(item.globalFutureChangePct) ? formatPct(item.globalFutureChangePct) : ""].filter(Boolean).join(" ")
                            : [`上游基准 ${item.benchmarkFutureName || item.benchmarkFutureSymbol}`.trim(), hasValue(item.benchmarkFutureChangePct) ? formatPct(item.benchmarkFutureChangePct) : ""].filter(Boolean).join(" ")}
                        </small>
                      </>
                    )}
                  </td>
                  <td className={pctClass(item.basis)}>
                    {hasBasis && (
                      <>
                        {formatBasis(item.basis, item.unit)}
                        {(hasValue(item.basisPct) || item.basisSource || item.basisFutureContract) && (
                          <small>{hasValue(item.basisPct) ? `${formatPctPlain(item.basisPct)}${item.basisFutureContract ? ` / ${item.basisFutureContract}合约` : ""}` : item.basisSource}</small>
                        )}
                      </>
                    )}
                  </td>
                  <td className={pctClass(item.crossMarketSpread)}>
                    {hasCrossMarketSpread && (
                      <>
                        {formatCrossMarketSpread(item.crossMarketSpread)}
                        {hasValue(item.crossMarketSpreadPct) && <small>{formatPctPlain(item.crossMarketSpreadPct)}</small>}
                      </>
                    )}
                  </td>
                  <td>
                    {hasInventory && (
                      <>
                        {formatInventory(item)}
                        {hasValue(item.inventoryChange) && <small className={pctClass(item.inventoryChange)}>{formatInventoryChange(item)}</small>}
                        <MiniKline history={item.inventoryHistory} label={`${item.name}库存K线`} />
                        {item.inventoryDate && <small>{item.inventoryDate}</small>}
                      </>
                    )}
                  </td>
                  <td>
                    {sourceDate}
                    {sourceText && <small>{sourceText}</small>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function EnergyPage() {
  const [energyData, setEnergyData] = useState({ summary: {}, sections: [] });
  const [newKeys, setNewKeys] = useState(new Set());
  const [status, setStatus] = useState("正在获取能源数据...");
  const [refreshing, setRefreshing] = useState(false);

  const knownSignatures = useRef(new Map());
  const lastStatusText = useRef("");
  const lastRefreshFinishedAt = useRef("");

  const loadEnergy = useCallback(async ({ markNew = false } = {}) => {
    setStatus("正在读取本地快照...");

    try {
      const data = await getJson(`/api/energy?t=${Date.now()}`);
      const nextSections = data.sections || [];
      const previousSignatures = new Map(knownSignatures.current);
      const nextSignatures = collectEnergySignatures(nextSections);
      const changedKeys = new Set();

      if (markNew) {
        for (const [key, signature] of nextSignatures.entries()) {
          if (previousSignatures.get(key) !== signature) changedKeys.add(key);
        }
      }

      setEnergyData(data);
      setNewKeys(changedKeys);
      knownSignatures.current = nextSignatures;

      const statusText = buildEnergyStatus(data);
      lastStatusText.current = statusText;
      setStatus(statusText);
      return true;
    } catch (error) {
      setStatus(`获取失败：${error.message}`);
      return false;
    }
  }, []);

  const requestBackgroundRefresh = useBackgroundRefresh("energy", refreshing, setRefreshing, setStatus, lastStatusText);
  useRefreshPolling("energy", loadEnergy, setRefreshing, setStatus, lastStatusText, lastRefreshFinishedAt);

  useEffect(() => {
    loadEnergy({ markNew: false });
    const autoTimer = window.setInterval(() => requestBackgroundRefresh("timer", { force: false }), AUTO_REFRESH_MS);
    return () => window.clearInterval(autoTimer);
  }, [loadEnergy, requestBackgroundRefresh]);

  const summary = energyData.summary || {};
  const sections = energyData.sections || [];

  return (
    <PageShell
      eyebrow="国家统计局 / 煤炭 / 天然气 / 电力"
      title="能源生产监控"
      activePage="energy"
      status={status}
      actions={<RefreshButton loading={refreshing} title="刷新能源数据" onClick={requestBackgroundRefresh} />}
    >
      <section className="energy-overview" aria-label="能源数据概览">
        <Kpi label="最新月份" value={formatMonth(summary.latestPeriod)} />
        <Kpi label="指标覆盖" value={`${summary.rowCount || 0} 项`} />
        <Kpi label="煤炭 / 油气" value={`${summary.coalCount || 0} / ${summary.oilGasCount || 0}`} />
        <Kpi label="电力结构" value={`${summary.powerCount || 0} 项`} />
        <Kpi label="K线覆盖" value={`${summary.klineCount || 0} 项`} />
      </section>

      <section className="energy-layout" aria-live="polite">
        {!sections.length ? (
          <p className="empty">暂未取到能源数据。</p>
        ) : (
          sections.map((section) => <EnergySection key={section.id} section={section} newKeys={newKeys} />)
        )}
      </section>
    </PageShell>
  );
}

function EnergySection({ section, newKeys }) {
  const rows = section.rows || [];

  return (
    <section className="energy-section">
      <div className="section-title compact">
        <span>{section.rowCount || rows.length}</span>
        <h2>{section.name}</h2>
      </div>
      <div className="stock-table-wrap">
        <table className="stock-table energy-table">
          <thead>
            <tr>
              <th>指标</th>
              <th>月份</th>
              <th>K线</th>
              <th>当月值</th>
              <th>同比</th>
              <th>环比</th>
              <th>累计值</th>
              <th>累计同比</th>
              <th>近月明细</th>
              <th>来源/说明</th>
            </tr>
          </thead>
          <tbody>
            {!rows.length ? (
              <tr>
                <td colSpan="10" className="table-empty">
                  暂无该能源分类数据。
                </td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr key={row.id} className={newKeys.has(row.id) ? "is-new-row" : ""}>
                  <td>
                    <strong>{row.name}</strong>
                    <span className="energy-row-tags">
                      <span>{row.category}</span>
                      <span>{row.id}</span>
                    </span>
                  </td>
                  <td>{row.periodLabel || formatMonth(row.period)}</td>
                  <td>
                    <EnergyKline row={row} />
                  </td>
                  <td>{formatEnergyValue(row.value, row.unit)}</td>
                  <td className={pctClass(row.yoy)}>{formatPct(row.yoy)}</td>
                  <td className={pctClass(row.mom)}>{formatPct(row.mom)}</td>
                  <td>
                    {formatEnergyValue(row.cumulativeValue, row.unit)}
                    {row.cumulativePeriodLabel && <small>{row.cumulativePeriodLabel}</small>}
                  </td>
                  <td className={pctClass(row.cumulativeYoy)}>{formatPct(row.cumulativeYoy)}</td>
                  <td>
                    <EnergyHistory row={row} />
                  </td>
                  <td>
                    {row.sourceUrl ? (
                      <a className="source-link" href={row.sourceUrl} target="_blank" rel="noreferrer">
                        <ExternalLink size={12} aria-hidden="true" />
                        {row.source || "国家统计局"}
                      </a>
                    ) : (
                      row.source || "国家统计局"
                    )}
                    <small>{row.note || ""}</small>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function EnergyKline({ row }) {
  const points = Array.isArray(row.history) ? row.history.filter((point) => Number.isFinite(Number(point.close ?? point.value))) : [];
  if (points.length < 2) return <span className="sparkline-empty">暂无</span>;
  return <MiniKline history={row.history} label={`${row.name || "能源指标"}近月K线`} />;
}

function EnergyHistory({ row }) {
  const points = (row.history || []).slice(-3);
  if (!points.length) return <span className="sparkline-empty">暂无</span>;

  return (
    <div className="energy-history">
      {points.map((point, index) => (
        <span key={`${row.id}-${point.period || index}`}>
          <b>{point.periodLabel || formatMonth(point.period)}</b>
          {formatEnergyPoint(point, row.unit)}
        </span>
      ))}
    </div>
  );
}

function ConsumptionPage() {
  const [consumptionData, setConsumptionData] = useState({ summary: {}, sections: [] });
  const [newKeys, setNewKeys] = useState(new Set());
  const [status, setStatus] = useState("正在获取消费数据...");
  const [refreshing, setRefreshing] = useState(false);

  const knownSignatures = useRef(new Map());
  const lastStatusText = useRef("");
  const lastRefreshFinishedAt = useRef("");

  const loadConsumption = useCallback(async ({ markNew = false } = {}) => {
    setStatus("正在读取本地快照...");

    try {
      const data = await getJson(`/api/consumption?t=${Date.now()}`);
      const nextSections = data.sections || [];
      const previousSignatures = new Map(knownSignatures.current);
      const nextSignatures = collectConsumptionSignatures(nextSections);
      const changedKeys = new Set();

      if (markNew) {
        for (const [key, signature] of nextSignatures.entries()) {
          if (previousSignatures.get(key) !== signature) changedKeys.add(key);
        }
      }

      setConsumptionData(data);
      setNewKeys(changedKeys);
      knownSignatures.current = nextSignatures;

      const statusText = buildConsumptionStatus(data);
      lastStatusText.current = statusText;
      setStatus(statusText);
      return true;
    } catch (error) {
      setStatus(`获取失败：${error.message}`);
      return false;
    }
  }, []);

  const requestBackgroundRefresh = useBackgroundRefresh("consumption", refreshing, setRefreshing, setStatus, lastStatusText);
  useRefreshPolling("consumption", loadConsumption, setRefreshing, setStatus, lastStatusText, lastRefreshFinishedAt);

  useEffect(() => {
    loadConsumption({ markNew: false });
    const autoTimer = window.setInterval(() => requestBackgroundRefresh("timer", { force: false }), AUTO_REFRESH_MS);
    return () => window.clearInterval(autoTimer);
  }, [loadConsumption, requestBackgroundRefresh]);

  const summary = consumptionData.summary || {};
  const sections = consumptionData.sections || [];

  return (
    <PageShell
      eyebrow="国家统计局 / 海关总署 / 中汽协 / 权威媒体"
      title="消费数据观察"
      activePage="consumption"
      status={status}
      actions={<RefreshButton loading={refreshing} title="刷新消费数据" onClick={requestBackgroundRefresh} />}
    >
      <section className="consumption-overview" aria-label="消费数据概览">
        <Kpi label="最新月份" value={formatMonth(summary.latestPeriod)} />
        <Kpi label="分类覆盖" value={`${summary.categoryCount || 0} 类`} />
        <Kpi label="必选 / 可选" value={`${summary.requiredCount || 0} / ${summary.optionalCount || 0}`} />
        <Kpi label="境内 / 海外" value={`${summary.domesticCount || 0} / ${summary.overseasCount || 0}`} />
        <Kpi label="数据来源" value={`${summary.sourceCount || 0} 个`} />
      </section>

      <section className="consumption-layout" aria-live="polite">
        {!sections.length ? (
          <p className="empty">暂未取到消费数据。</p>
        ) : (
          sections.map((section) => <ConsumptionSection key={section.id} section={section} newKeys={newKeys} />)
        )}
      </section>
    </PageShell>
  );
}

function ConsumptionSection({ section, newKeys }) {
  const projects = buildConsumptionProjects(section);

  return (
    <section className="consumption-section">
      <div className="section-title compact">
        <span>{section.rowCount || 0}</span>
        <h2>{section.name}</h2>
      </div>
      <div className="consumption-projects">
        {projects.map((project) => (
          <ConsumptionProject key={`${section.id}-${project.category}`} project={project} newKeys={newKeys} />
        ))}
      </div>
    </section>
  );
}

function ConsumptionProject({ project, newKeys }) {
  const rows = project.rows || [];
  const regionGroups = buildConsumptionRegionGroups(project);
  return (
    <section className="consumption-project">
      <header className="consumption-project-head">
        <div>
          <span className="consumption-project-kicker">消费项目</span>
          <h3>{project.category}</h3>
        </div>
        <div className="consumption-project-meta">
          <span className="is-domestic">{project.domesticCount || 0} 境内</span>
          <span className="is-overseas">{project.overseasCount || 0} 海外</span>
          {project.onlineCount > 0 && <span className="is-online">{project.onlineCount} 线上</span>}
          {project.offlineCount > 0 && <span className="is-offline">{project.offlineCount} 线下</span>}
          <span>{rows.length} 项</span>
        </div>
      </header>
      <div className="consumption-region-groups">
        {regionGroups.map((group) => (
          <ConsumptionRegionGroup key={`${project.category}-${group.id}`} group={group} newKeys={newKeys} />
        ))}
      </div>
    </section>
  );
}

function ConsumptionRegionGroup({ group, newKeys }) {
  const rows = group.rows || [];
  return (
    <section className={`consumption-region-group ${group.id === "overseas" ? "is-overseas" : "is-domestic"}`}>
      <header className="consumption-region-head">
        <div>
          <span>{group.label}</span>
          <strong>{rows.length} 项</strong>
        </div>
        <small>{group.subtitle}</small>
      </header>
      <div className="stock-table-wrap">
        <table className="stock-table consumption-table consumption-region-table">
          <thead>
            <tr>
              <th>指标</th>
              <th>月份</th>
              <th>K线</th>
              <th>数据</th>
              <th>同比</th>
              <th>环比</th>
              <th>近月明细</th>
              <th>来源/说明</th>
            </tr>
          </thead>
          <tbody>
            {!rows.length ? (
              <tr>
                <td colSpan="8" className="table-empty">
                  暂无该区域数据。
                </td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr key={row.id} className={newKeys.has(row.id) ? "is-new-row" : ""}>
                  <td>
                    <strong>{row.metric}</strong>
                    <span className="consumption-row-tags">
                      {row.channelLabel && <span className={`channel-${row.channel || "other"}`}>{row.channelLabel}</span>}
                      {row.segmentLabel && <span>{row.segmentLabel}</span>}
                      <span>{row.id}</span>
                    </span>
                  </td>
                  <td>{row.periodLabel || formatMonth(row.period)}</td>
                  <td>
                    <ConsumptionKline row={row} />
                  </td>
                  <td>{formatConsumptionValue(row.value, row.unit)}</td>
                  <td className={pctClass(row.yoy)}>{formatPct(row.yoy)}</td>
                  <td className={pctClass(row.mom)}>{formatPct(row.mom)}</td>
                  <td>
                    <ConsumptionHistory row={row} />
                  </td>
                  <td>
                    {row.sourceUrl ? (
                      <a className="source-link" href={row.sourceUrl} target="_blank" rel="noreferrer">
                        <ExternalLink size={12} aria-hidden="true" />
                        {row.source || "公开来源"}
                      </a>
                    ) : (
                      row.source || "公开来源"
                    )}
                    <small>{row.note || ""}</small>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ConsumptionHistory({ row }) {
  const points = (row.history || []).slice(-2);
  if (!points.length) return <span className="sparkline-empty">暂无</span>;

  return (
    <div className="consumption-history">
      {points.map((point, index) => (
        <span key={`${row.id}-${point.period || index}`}>
          <b>{point.periodLabel || formatMonth(point.period)}</b>
          {formatConsumptionPoint(point, row.unit)}
        </span>
      ))}
    </div>
  );
}

function ConsumptionKline({ row }) {
  const series = consumptionKlineSeries(row);
  const detailPoints = (row.history || []).slice(-9);
  const tooltipText = detailPoints.map((point) => `${point.periodLabel || formatMonth(point.period)}：${formatConsumptionPoint(point, row.unit)}`).join("\n");

  if (series.points.length < 1) {
    return (
      <span className="consumption-kline-wrap" title={tooltipText || "暂无近月明细"} tabIndex="0">
        <span className="sparkline-empty">暂无</span>
        {tooltipText && <ConsumptionKlineTooltip row={row} points={detailPoints} />}
      </span>
    );
  }

  const width = 168;
  const height = 42;
  const padding = 4;
  const values = series.points.flatMap((point, index) => {
    const previous = index === 0 ? point.value : series.points[index - 1].value;
    return [previous, point.value];
  });
  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const flatPadding = (Math.abs(rawMax) || 1) * 0.05;
  const min = rawMin === rawMax ? rawMin - flatPadding : rawMin;
  const max = rawMin === rawMax ? rawMax + flatPadding : rawMax;
  const span = max - min || 1;
  const innerWidth = width - padding * 2;
  const candleWidth = Math.max(3, Math.min(8, innerWidth / series.points.length - 2));
  const step = innerWidth / Math.max(series.points.length - 1, 1);
  const yFor = (value) => height - padding - ((value - min) / span) * (height - padding * 2);
  const first = series.points[0];
  const last = series.points[series.points.length - 1];
  const up = last.value >= first.value;

  return (
    <span className="consumption-kline-wrap" title={tooltipText} tabIndex="0">
      <svg className={`macro-kline consumption-kline ${up ? "up-line" : "down-line"}`} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${row.metric || "消费指标"}${series.label}K线，${first.period}至${last.period}`}>
        <title>{tooltipText}</title>
        <path className="sparkline-grid" d={`M${padding},${height - padding}H${width - padding}`} />
        {series.points.map((point, index) => {
          const previous = index === 0 ? point.value : series.points[index - 1].value;
          const openY = yFor(previous);
          const closeY = yFor(point.value);
          const highY = Math.min(openY, closeY);
          const lowY = Math.max(openY, closeY);
          const x = series.points.length === 1 ? width / 2 : padding + index * step;
          const rectY = Math.min(openY, closeY);
          const rectHeight = Math.max(2, Math.abs(closeY - openY));
          return (
            <g key={`${point.period}-${index}`} className={point.value >= previous ? "candle-up" : "candle-down"}>
              <path d={`M${x.toFixed(1)},${highY.toFixed(1)}V${lowY.toFixed(1)}`} />
              <rect x={(x - candleWidth / 2).toFixed(1)} y={rectY.toFixed(1)} width={candleWidth.toFixed(1)} height={rectHeight.toFixed(1)} rx="1" />
            </g>
          );
        })}
      </svg>
      <ConsumptionKlineTooltip row={row} points={detailPoints} label={series.label} />
    </span>
  );
}

function ConsumptionKlineTooltip({ row, points, label = "近月" }) {
  if (!points.length) return null;

  return (
    <span className="consumption-kline-tooltip" role="tooltip">
      <strong>{row.metric || row.category} · {label}</strong>
      {points.map((point, index) => (
        <span key={`${row.id}-tooltip-${point.period || index}`}>
          <b>{point.periodLabel || formatMonth(point.period)}</b>
          {formatConsumptionPoint(point, row.unit)}
        </span>
      ))}
    </span>
  );
}

function GamesPageV2() {
  const [gameData, setGameData] = useState({});
  const [selectedProvider, setSelectedProvider] = useState("qimai");
  const [selectedCountry, setSelectedCountry] = useState("cn");
  const [newKeys, setNewKeys] = useState(new Set());
  const [status, setStatus] = useState("正在获取游戏榜单数据...");
  const [refreshing, setRefreshing] = useState(false);

  const knownSignatures = useRef(new Map());
  const lastStatusText = useRef("");
  const lastRefreshFinishedAt = useRef("");

  const loadGames = useCallback(async ({ markNew = false } = {}) => {
    setStatus("正在读取本地快照...");

    try {
      const data = await getJson(`/api/games?t=${Date.now()}`);
      const previousSignatures = new Map(knownSignatures.current);
      const nextSignatures = collectGameDashboardSignatures(data);
      const changedKeys = new Set();

      if (markNew) {
        for (const [key, signature] of nextSignatures.entries()) {
          if (previousSignatures.get(key) !== signature) changedKeys.add(key);
        }
      }

      setGameData(data);
      setSelectedProvider((current) => {
        const providers = data.rankProviders || [];
        return current && providers.some((provider) => provider.id === current) ? current : providers[0]?.id || "qimai";
      });
      setSelectedCountry((current) => {
        const countries = data.countries || [];
        return current && countries.some((country) => country.code === current) ? current : countries[0]?.code || "";
      });
      setNewKeys(changedKeys);
      knownSignatures.current = nextSignatures;

      const statusText = buildGamesStatusV2(data);
      lastStatusText.current = statusText;
      setStatus(statusText);
      return true;
    } catch (error) {
      setStatus(`获取失败：${error.message}`);
      return false;
    }
  }, []);

  const requestBackgroundRefresh = useBackgroundRefresh("games", refreshing, setRefreshing, setStatus, lastStatusText);
  useRefreshPolling("games", loadGames, setRefreshing, setStatus, lastStatusText, lastRefreshFinishedAt);

  useEffect(() => {
    loadGames({ markNew: false });
    const autoTimer = window.setInterval(() => requestBackgroundRefresh("timer", { force: false }), AUTO_REFRESH_MS);
    return () => window.clearInterval(autoTimer);
  }, [loadGames, requestBackgroundRefresh]);

  const markets = gameData.markets || [];
  const rankProviders = gameData.rankProviders || [];
  const countries = gameData.countries || [];
  const selectedRankProvider = rankProviders.find((provider) => provider.id === selectedProvider) || rankProviders[0] || {};
  const selectedProviderCountry =
    (selectedRankProvider.countries || []).find((country) => country.code === selectedCountry) || selectedRankProvider.countries?.[0] || {};
  const summary = gameData.summary || {};

  return (
    <PageShell
      eyebrow="Sensor Tower 流水 / 点点榜单 / 七麦榜单"
      title="全球与中国游戏 Top100"
      activePage="games"
      status={status}
      actions={<RefreshButton loading={refreshing} title="刷新游戏榜单" onClick={requestBackgroundRefresh} />}
    >
      <section className="game-overview" aria-label="游戏数据概览">
        <Kpi label="全球 Top100" value={`${summary.globalTopCount || 0}/${summary.rankLimit || 100}`} />
        <Kpi label="中国 Top100" value={`${summary.chinaTopCount || 0}/${summary.rankLimit || 100}`} />
        <Kpi label="披露流水" value={`${summary.reportedRevenueRows || 0} 条`} />
        <Kpi label="ST 兜底" value={`${summary.sensorTowerRevenueRows || 0} 条`} />
        <Kpi label="30国榜单" value={`${summary.rankingRows || 0} 条`} />
      </section>

      <GameProviderStatusGridV2 statuses={gameData.providerStatus || []} />

      <GameMarketTablesV2 markets={markets} newKeys={newKeys} />

      <section className="game-controls" aria-label="国家榜筛选">
        <div className="game-provider-tabs" role="tablist" aria-label="榜单来源">
          {rankProviders.map((provider) => (
            <button
              key={provider.id}
              className={provider.id === selectedRankProvider.id ? "active" : ""}
              type="button"
              onClick={() => setSelectedProvider(provider.id)}
            >
              {provider.name}
            </button>
          ))}
        </div>
        <label className="select-control">
          <span>消费能力前30国家/地区</span>
          <select value={selectedProviderCountry.code || ""} onChange={(event) => setSelectedCountry(event.target.value)}>
            {countries.map((country) => (
              <option key={country.code} value={country.code}>
                {country.marketRank ? `${country.marketRank}. ` : ""}
                {country.name}
              </option>
            ))}
          </select>
        </label>
        <div className="game-month-meta">
          <strong>{selectedRankProvider.name || "点点/七麦榜单"}</strong>
          <span>{summarizeProviderCountryV2(selectedProviderCountry)}</span>
        </div>
      </section>

      <GameProviderRankingsV2 provider={selectedRankProvider} country={selectedProviderCountry} newKeys={newKeys} />
    </PageShell>
  );
}

function GameProviderStatusGridV2({ statuses }) {
  return (
    <section className="game-provider-grid" aria-label="三方数据接入状态">
      {statuses.map((status) => (
        <article key={status.id} className={`game-provider-card ${status.status || ""}`}>
          <p className="market-label">{status.role}</p>
          <h2>{status.name}</h2>
          <strong>{providerStatusLabelV2(status.status)}</strong>
          <span>{status.message}</span>
          {status.homeUrl && (
            <a href={status.homeUrl} target="_blank" rel="noreferrer">
              打开来源
            </a>
          )}
        </article>
      ))}
    </section>
  );
}

function GameMarketTablesV2({ markets, newKeys }) {
  return (
    <section className="game-market-grid" aria-label="全球与中国游戏Top100">
      {markets.map((market) => (
        <GameTop100TableV2 key={market.id} market={market} newKeys={newKeys} />
      ))}
    </section>
  );
}

function GameTop100TableV2({ market, newKeys }) {
  const rows = market?.top100 || [];

  return (
    <section className="game-section game-top100">
      <div className="game-chart-head">
        <div>
          <p className="market-label">{market?.description}</p>
          <h2>{market?.name} Top100</h2>
        </div>
        <span>{rows.length}/{market?.rankLimit || 100}</span>
      </div>
      <div className="stock-table-wrap">
        <table className="stock-table game-table">
          <thead>
            <tr>
              <th>排名</th>
              <th>游戏</th>
              <th>采用流水</th>
              <th>七麦榜单</th>
              <th>点点榜单</th>
            </tr>
          </thead>
          <tbody>
            {!rows.length ? (
              <tr>
                <td colSpan="5" className="table-empty">
                  待导入官方/媒体披露流水或 Sensor Tower 兜底流水数据
                </td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr key={gameMarketRowKeyV2(market, row)} className={newKeys.has(gameMarketRowKeyV2(market, row)) ? "is-new-row" : ""}>
                  <td>{row.rank || "-"}</td>
                  <td>
                    <div className="game-app-cell">
                      {row.artworkUrl && <img src={row.artworkUrl} alt="" loading="lazy" />}
                      <div>
                        <strong>
                          {row.sourceUrl ? (
                            <a href={row.sourceUrl} target="_blank" rel="noreferrer">
                              {displayGameNameV2(row)}
                            </a>
                          ) : (
                            displayGameNameV2(row)
                          )}
                        </strong>
                        <small>{gameTop100SublineV2(row)}</small>
                      </div>
                    </div>
                  </td>
                  <td>
                    <strong>{formatRevenue(row.revenue)}</strong>
                    <small>{formatRevenueSourceV2(row)}</small>
                    {row.downloads && <small>下载 {formatDownloads(row.downloads)}</small>}
                  </td>
                  <RankSnapshotCellV2 rankings={row.rankings?.qimai} />
                  <RankSnapshotCellV2 rankings={row.rankings?.diandian} />
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function RankSnapshotCellV2({ rankings }) {
  return (
    <td>
      <div className="rank-snapshot">
        <span>免费 {formatRankSnapshotV2(rankings?.free)}</span>
        <span>畅销 {formatRankSnapshotV2(rankings?.grossing)}</span>
      </div>
    </td>
  );
}

function GameProviderRankingsV2({ provider, country, newKeys }) {
  const charts = country?.charts || [];

  return (
    <section className="game-country-panel" aria-label="点点与七麦国家榜">
      <div className="section-title compact">
        <span>{country?.rowCount || 0}</span>
        <h2>
          {provider?.name || "榜单来源"} · {country?.name || "国家榜单"}
        </h2>
      </div>
      <div className="game-rank-grid">
        {charts.map((chart) => (
          <GameChartTableV2 key={`${provider?.id}-${country?.code}-${chart.id}`} chart={chart} provider={provider} country={country} newKeys={newKeys} />
        ))}
      </div>
    </section>
  );
}

function GameChartTableV2({ chart, provider, country, newKeys }) {
  const rows = chart?.rows || [];

  return (
    <section className="game-chart">
      <div className="game-chart-head">
        <h3>{chart.name}</h3>
        <time dateTime={chart.updatedAt || undefined}>{formatTime(chart.updatedAt)}</time>
      </div>
      <div className="stock-table-wrap">
        <table className="stock-table game-rank-table">
          <thead>
            <tr>
              <th>排名</th>
              <th>游戏</th>
              <th>发行商</th>
            </tr>
          </thead>
          <tbody>
            {!rows.length ? (
              <tr>
                <td colSpan="3" className="table-empty">
                  待导入 {provider?.name || "该来源"} {country?.name || ""} {chart.name}
                </td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr
                  key={gameProviderRowKeyV2(provider, country, chart, row)}
                  className={newKeys.has(gameProviderRowKeyV2(provider, country, chart, row)) ? "is-new-row" : ""}
                >
                  <td>{row.rank || "-"}</td>
                  <td>
                    <div className="game-app-cell">
                      {row.artworkUrl && <img src={row.artworkUrl} alt="" loading="lazy" />}
                      <div>
                        <strong>
                          {row.url ? (
                            <a href={row.url} target="_blank" rel="noreferrer">
                              {displayGameNameV2(row)}
                            </a>
                          ) : (
                            displayGameNameV2(row)
                          )}
                        </strong>
                        <small>{gameRankingSublineV2(row)}</small>
                      </div>
                    </div>
                  </td>
                  <td>
                    {row.publisher || "-"}
                    <small>{row.platform || chart.source || ""}</small>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function MacroPage() {
  const [countries, setCountries] = useState([]);
  const [newKeys, setNewKeys] = useState(new Set());
  const [status, setStatus] = useState("正在获取宏观指标...");
  const [refreshing, setRefreshing] = useState(false);

  const knownSignatures = useRef(new Map());
  const lastStatusText = useRef("");
  const lastRefreshFinishedAt = useRef("");

  const loadMacro = useCallback(async ({ markNew = false } = {}) => {
    setStatus("正在读取本地快照...");

    try {
      const data = await getJson(`/api/macro?t=${Date.now()}`);
      const nextCountries = data.countries || [];
      const previousSignatures = new Map(knownSignatures.current);
      const nextSignatures = collectMacroSignatures(nextCountries);
      const changedKeys = new Set();

      if (markNew) {
        for (const [key, signature] of nextSignatures.entries()) {
          if (previousSignatures.get(key) !== signature) changedKeys.add(key);
        }
      }

      setCountries(nextCountries);
      setNewKeys(changedKeys);
      knownSignatures.current = nextSignatures;

      const statusText = buildMacroStatus(data);
      lastStatusText.current = statusText;
      setStatus(statusText);
      return true;
    } catch (error) {
      setStatus(`获取失败：${error.message}`);
      return false;
    }
  }, []);

  const requestBackgroundRefresh = useBackgroundRefresh("macro", refreshing, setRefreshing, setStatus, lastStatusText);
  useRefreshPolling("macro", loadMacro, setRefreshing, setStatus, lastStatusText, lastRefreshFinishedAt);

  useEffect(() => {
    loadMacro({ markNew: false });
    const autoTimer = window.setInterval(() => requestBackgroundRefresh("timer", { force: false }), AUTO_REFRESH_MS);
    return () => window.clearInterval(autoTimer);
  }, [loadMacro, requestBackgroundRefresh]);

  const china = countries.find((country) => country.id === "china");
  const overview = summarizeMacro(countries);

  return (
    <PageShell
      eyebrow="利率 / PPI / PMI / 就业 / 增长"
      title="宏观指标看板"
      activePage="macro"
      status={status}
      actions={<RefreshButton loading={refreshing} title="刷新宏观指标" onClick={requestBackgroundRefresh} />}
    >
      <section className="macro-overview" aria-label="宏观概览">
        <Kpi label="重点国家/地区" value={`${countries.length} 个`} />
        <Kpi label="中国指标" value={`${countMacroItems(china)} 个`} />
        <Kpi label="待接入实时项" value={`${overview.pending} 个`} />
        <Kpi label="指标分组" value={`${overview.groups} 组`} />
      </section>

      <section className="macro-layout" aria-live="polite">
        {!countries.length ? (
          <p className="empty">暂未取到宏观指标数据。</p>
        ) : (
          countries.map((country) => <MacroCountry key={country.id} country={country} newKeys={newKeys} />)
        )}
      </section>
    </PageShell>
  );
}

function MacroCountry({ country, newKeys }) {
  const focusClass = country.focus ? " focus" : "";

  return (
    <article className={`macro-country${focusClass}`}>
      <header className="macro-country-head">
        <div>
          <p className="market-label">{country.focus ? "主要跟踪" : "全球对比"}</p>
          <h2>{country.name}</h2>
        </div>
        <span>{country.source || "公开来源"}</span>
      </header>

      <div className="macro-groups">
        {(country.groups || []).map((group) => (
          <section key={group.name} className="macro-group">
            <div className="section-title compact">
              <span>{group.items?.length || 0}</span>
              <h3>{group.name}</h3>
            </div>
            <div className="stock-table-wrap">
              <table className="stock-table macro-table">
                <thead>
                  <tr>
                    <th>指标</th>
                    <th>K线</th>
                    <th>最新</th>
                    <th>下次预测</th>
                    <th>前值</th>
                    <th>期数</th>
                    <th>来源/说明</th>
                  </tr>
                </thead>
                <tbody>
                  {(group.items || []).map((item) => {
                    const key = macroItemKey(country, group, item);
                    return (
                      <tr key={key} className={newKeys.has(key) ? "is-new-row" : ""}>
                        <td>
                          <strong>{item.name}</strong>
                          <small>{item.category}</small>
                        </td>
                        <td>
                          <MacroKline item={item} />
                        </td>
                        <td className={macroValueClass(item)}>{formatMacroValue(item)}</td>
                        <td className={`macro-forecast-cell${hasMacroForecast(item) ? "" : " is-empty"}`}>
                          <strong>{formatMacroForecast(item)}</strong>
                          <small>{macroForecastDetails(item)}</small>
                        </td>
                        <td>{formatMacroPrevious(item)}</td>
                        <td>{item.period || "未知"}</td>
                        <td>
                          {item.source || "公开来源"}
                          <small>{item.note || ""}</small>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        ))}
      </div>
    </article>
  );
}

function RefreshButton({ loading, title, onClick }) {
  return (
    <button className={`primary-action${loading ? " is-loading" : ""}`} type="button" title={title} onClick={onClick} disabled={loading} aria-busy={loading}>
      <RefreshCw size={16} aria-hidden="true" />
      {loading ? "刷新中" : "刷新"}
    </button>
  );
}

function Kpi({ label, value }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function refreshStatusText(fallback, state, defaultMessage) {
  return `${fallback}；${state?.message || defaultMessage}`;
}

function useBackgroundRefresh(kind, refreshing, setRefreshing, setStatus, lastStatusText) {
  const refreshingRef = useRef(refreshing);

  useEffect(() => {
    refreshingRef.current = refreshing;
  }, [refreshing]);

  return useCallback(
    async (reason = "manual", { force = reason === "manual" } = {}) => {
      if (typeof reason !== "string") {
        reason = "manual";
        force = true;
      }
      if (refreshingRef.current) return;
      const fallback = lastStatusText.current || "正在等待本地快照";
      refreshingRef.current = true;
      setRefreshing(true);
      setStatus(`${fallback}；正在启动后台刷新`);

      try {
        const params = new URLSearchParams({ reason, force: String(force), t: Date.now().toString() });
        const state = await getJson(`/api/refresh/${kind}?${params}`, { method: "POST" });
        if (state.status === "running") {
          setStatus(refreshStatusText(fallback, state, "后台刷新中"));
        } else if (state.status === "skipped") {
          refreshingRef.current = false;
          setRefreshing(false);
          setStatus(refreshStatusText(fallback, state, "半小时内不重复抓取"));
        } else if (state.status === "done" || state.status === "error") {
          refreshingRef.current = false;
          setRefreshing(false);
          setStatus(refreshStatusText(fallback, state, state.status === "done" ? "后台刷新完成" : "后台刷新失败"));
        }
      } catch {
        refreshingRef.current = false;
        setRefreshing(false);
        setStatus(lastStatusText.current ? `${lastStatusText.current}；后台刷新启动失败` : "后台刷新启动失败，请确认后端服务已启动");
      }
    },
    [kind, lastStatusText, setRefreshing, setStatus]
  );
}

function useRefreshPolling(kind, loadData, setRefreshing, setStatus, lastStatusText, lastRefreshFinishedAt) {
  const pollRefreshStatus = useCallback(async () => {
    try {
      const statusData = await getJson(`/api/refresh-status?t=${Date.now()}`);
      const refresh = statusData[kind];
      if (!refresh) return;

      const fallback = lastStatusText.current || "已读取本地快照";
      if (refresh.status === "running") {
        setRefreshing(true);
        setStatus(refreshStatusText(fallback, refresh, "后台刷新中"));
        return;
      }

      if (refresh.finishedAt && refresh.finishedAt !== lastRefreshFinishedAt.current) {
        lastRefreshFinishedAt.current = refresh.finishedAt;
        try {
          if (refresh.refreshed) {
            await loadData({ markNew: true });
          } else if (refresh.status === "skipped") {
            await loadData({ markNew: false });
            setStatus(refreshStatusText(lastStatusText.current || fallback, refresh, "半小时内已有快照"));
          } else if (refresh.status === "error") {
            await loadData({ markNew: false });
            setStatus(refreshStatusText(lastStatusText.current || fallback, refresh, "后台刷新失败"));
          }
        } finally {
          setRefreshing(false);
        }
      }
    } catch {
      // Keep the current snapshot on transient polling failures.
    }
  }, [kind, lastRefreshFinishedAt, lastStatusText, loadData, setRefreshing, setStatus]);

  useEffect(() => {
    const statusTimer = window.setInterval(pollRefreshStatus, STATUS_POLL_MS);
    pollRefreshStatus();
    return () => window.clearInterval(statusTimer);
  }, [pollRefreshStatus]);
}

function TrendSparkline({ item }) {
  const points = Array.isArray(item.trend) ? item.trend.map(Number).filter((value) => Number.isFinite(value)) : [];
  if (points.length < 2) return <span className="sparkline-empty">暂无</span>;

  const width = 96;
  const height = 30;
  const padding = 2;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || Math.max(Math.abs(max), 1) * 0.01;
  const step = (width - padding * 2) / Math.max(points.length - 1, 1);
  const d = points
    .map((value, index) => {
      const x = padding + index * step;
      const y = height - padding - ((value - min) / span) * (height - padding * 2);
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const up = points[points.length - 1] >= points[0];

  return (
    <svg
      className={`sparkline ${up ? "up-line" : "down-line"}`}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`${item.name || "指数"}近60日K线`}
    >
      <path className="sparkline-grid" d={`M${padding},${height - padding}H${width - padding}`} />
      <path className="sparkline-path" d={d} />
    </svg>
  );
}

function MacroKline({ item }) {
  const points = Array.isArray(item.history)
    ? item.history
        .map((point) => ({ period: point.period, value: Number(point.value) }))
        .filter((point) => Number.isFinite(point.value))
    : [];

  if (points.length < 2) return <span className="sparkline-empty">暂无</span>;

  const width = 120;
  const height = 34;
  const padding = 3;
  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || Math.max(Math.abs(max), 1) * 0.01;
  const innerWidth = width - padding * 2;
  const candleWidth = Math.max(4, Math.min(10, innerWidth / points.length - 3));
  const step = innerWidth / Math.max(points.length - 1, 1);
  const yFor = (value) => height - padding - ((value - min) / span) * (height - padding * 2);
  const last = points[points.length - 1];
  const first = points[0];
  const up = last.value >= first.value;

  return (
    <svg
      className={`macro-kline ${up ? "up-line" : "down-line"}`}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`${item.name || "指标"}历史K线，${first.period}至${last.period}`}
    >
      <path className="sparkline-grid" d={`M${padding},${height - padding}H${width - padding}`} />
      {points.map((point, index) => {
        const previous = index === 0 ? point.value : points[index - 1].value;
        const openY = yFor(previous);
        const closeY = yFor(point.value);
        const highY = Math.min(openY, closeY);
        const lowY = Math.max(openY, closeY);
        const x = padding + index * step;
        const rectY = Math.min(openY, closeY);
        const rectHeight = Math.max(2, Math.abs(closeY - openY));
        const rising = point.value >= previous;
        return (
          <g key={`${point.period}-${index}`} className={rising ? "candle-up" : "candle-down"}>
            <path d={`M${x.toFixed(1)},${highY.toFixed(1)}V${lowY.toFixed(1)}`} />
            <rect x={(x - candleWidth / 2).toFixed(1)} y={rectY.toFixed(1)} width={candleWidth.toFixed(1)} height={rectHeight.toFixed(1)} rx="1" />
          </g>
        );
      })}
    </svg>
  );
}

function MiniKline({ history, label, valueKey = "value" }) {
  const points = Array.isArray(history)
    ? history
        .map((point) => {
          const close = Number(point.close ?? point[valueKey] ?? point.value);
          return {
            period: point.date || point.period || "",
            open: Number(point.open),
            high: Number(point.high),
            low: Number(point.low),
            close
          };
        })
        .filter((point) => Number.isFinite(point.close))
    : [];

  if (points.length < 2) return null;

  const width = 112;
  const height = 32;
  const padding = 3;
  const values = points.flatMap((point, index) => {
    const previousClose = index === 0 ? point.close : points[index - 1].close;
    const open = Number.isFinite(point.open) ? point.open : previousClose;
    const high = Number.isFinite(point.high) ? point.high : Math.max(open, point.close);
    const low = Number.isFinite(point.low) ? point.low : Math.min(open, point.close);
    return [open, high, low, point.close];
  });
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || Math.max(Math.abs(max), 1) * 0.01;
  const innerWidth = width - padding * 2;
  const candleWidth = Math.max(2.4, Math.min(6, innerWidth / points.length - 1.4));
  const step = innerWidth / Math.max(points.length - 1, 1);
  const yFor = (value) => height - padding - ((value - min) / span) * (height - padding * 2);
  const first = points[0];
  const last = points[points.length - 1];
  const up = last.close >= first.close;

  return (
    <svg className={`macro-kline commodity-mini-kline ${up ? "up-line" : "down-line"}`} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${label}，${first.period}至${last.period}`}>
      <path className="sparkline-grid" d={`M${padding},${height - padding}H${width - padding}`} />
      {points.map((point, index) => {
        const previousClose = index === 0 ? point.close : points[index - 1].close;
        const open = Number.isFinite(point.open) ? point.open : previousClose;
        const high = Number.isFinite(point.high) ? point.high : Math.max(open, point.close);
        const low = Number.isFinite(point.low) ? point.low : Math.min(open, point.close);
        const openY = yFor(open);
        const closeY = yFor(point.close);
        const highY = yFor(high);
        const lowY = yFor(low);
        const x = padding + index * step;
        const rectY = Math.min(openY, closeY);
        const rectHeight = Math.max(1.6, Math.abs(closeY - openY));
        return (
          <g key={`${point.period}-${index}`} className={point.close >= open ? "candle-up" : "candle-down"}>
            <path d={`M${x.toFixed(1)},${highY.toFixed(1)}V${lowY.toFixed(1)}`} />
            <rect x={(x - candleWidth / 2).toFixed(1)} y={rectY.toFixed(1)} width={candleWidth.toFixed(1)} height={rectHeight.toFixed(1)} rx="0.8" />
          </g>
        );
      })}
    </svg>
  );
}

async function getJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let message = `请求失败 (${response.status})`;
    try {
      const payload = await response.json();
      message = payload.detail || payload.message || message;
    } catch {
      try {
        const text = await response.text();
        if (text) message = text;
      } catch {
        // Keep the generic HTTP message.
      }
    }
    throw new Error(message);
  }
  return response.json();
}

function buildNewsStatus(data, news) {
  const cacheHint = data.cached ? "；缓存" : "";
  const storageHint = data.fromStorage ? "；SQLite" : "";
  const throttleHint = data.throttled ? "；半小时内不重复抓取" : "";
  const staleHint = data.stale ? "；旧快照" : "";
  const countHint = `；已预取：中国及港澳${news.china.length}条、世界${news.world.length}条`;
  const sources = (data.sources || []).map((source) => source.name).join("、") || "公开来源";
  const errorHint = data.errors?.length ? `；部分来源异常：${data.errors.join("；")}` : "";
  return `已更新：${formatTime(data.generatedAt)}${cacheHint}${storageHint}${throttleHint}${staleHint}${countHint}；来源：${sources}${errorHint}`;
}

function buildStocksStatus(data) {
  return buildGenericStatus(data, data.source || "公开来源");
}

function withWatchlistCount(status, count) {
  return `${status.replace(/；自选\d+只$/, "")}；自选${count}只`;
}

function buildWatchDetailStatus(data) {
  const stock = data.stock || {};
  const errorHint = data.errors?.length ? `；部分来源异常${data.errors.length}项` : "";
  return `已更新：${formatTime(data.generatedAt)}；${stock.name || stock.symbol || "公司"}；来源：东方财富 / Google/Bing News / 股吧 / 雪球${errorHint}`;
}

function buildWatchDetailStatusV2(data) {
  const stock = data.stock || {};
  const cacheHint = data.cached ? "；缓存命中" : "";
  const staleHint = data.stale ? "；旧缓存" : "";
  const cacheTime = data.cacheUpdatedAt ? `；缓存时间：${formatTime(data.cacheUpdatedAt)}` : "";
  const errorHint = data.errors?.length ? `；部分来源异常${data.errors.length}项` : "";
  return `已更新：${formatTime(data.generatedAt)}${cacheHint}${staleHint}${cacheTime}；${stock.name || stock.symbol || "公司"}；来源：东方财富 / AAStocks / HKEX / Google/Bing News / 股吧 / 雪球${errorHint}`;
}

function buildCommoditiesStatus(data) {
  const count = data.items?.length ? `；覆盖${data.items.length}个品种` : "";
  return `${buildGenericStatus(data, data.source || "公开来源")}${count}`;
}

function buildEnergyStatus(data) {
  const summary = data.summary || {};
  const count = summary.rowCount ? `；覆盖${summary.categoryCount || 0}类、${summary.rowCount}项；K线${summary.klineCount || 0}项` : "";
  return `${buildGenericStatus(data, data.source || "国家统计局")}${count}`;
}

function buildConsumptionStatus(data) {
  const summary = data.summary || {};
  const count = summary.rowCount ? `；覆盖${summary.categoryCount || 0}类、${summary.rowCount}项；必选${summary.requiredCount || 0}项，可选${summary.optionalCount || 0}项` : "";
  return `${buildGenericStatus(data, data.source || "公开来源")}${count}`;
}

function buildMacroStatus(data) {
  const countries = data.countries || [];
  const itemCount = countries.reduce((sum, country) => sum + countMacroItems(country), 0);
  const count = itemCount ? `；覆盖${countries.length}个国家/地区、${itemCount}个指标` : "";
  return `${buildGenericStatus(data, data.source || "公开来源")}${count}`;
}

function buildGamesStatusV2(data) {
  const summary = data.summary || {};
  const usableStatuses = new Set(["imported", "public_fallback", "credentials_present"]);
  const statusCount = (data.providerStatus || []).filter((item) => usableStatuses.has(item.status)).length;
  const statusTotal = (data.providerStatus || []).length || 4;
  const count = `；全球Top100 ${summary.globalTopCount || 0}款；中国Top100 ${summary.chinaTopCount || 0}款；披露流水${summary.reportedRevenueRows || 0}条；30国榜单${summary.rankingRows || 0}条；已接入${statusCount}/${statusTotal}个来源`;
  return `${buildGenericStatus(data, data.source || "官方/媒体流水 / Sensor Tower / 点点数据 / 七麦数据")}${count}`;
}

function buildXueqiuStatus(data) {
  const summary = data.summary || {};
  const count = `；大V${summary.influencerCount || 0}位；今日动态${summary.activityCount || 0}条；帖子${summary.postCount || 0}条；评论/回复${(summary.commentCount || 0) + (summary.replyCount || 0)}条`;
  return `${buildGenericStatus(data, data.source || "雪球公开主页/API")}${count}`;
}

function collectGameDashboardSignatures(data) {
  const map = new Map();
  (data.markets || []).forEach((market) => {
    (market.top100 || []).forEach((row) => {
      map.set(
        gameMarketRowKeyV2(market, row),
        [row.rank, row.game, row.gameZh, row.publisher, JSON.stringify(row.revenue || null), row.source, row.sourceType, row.downloads, JSON.stringify(row.rankings || {})].join("|")
      );
    });
  });

  (data.rankProviders || []).forEach((provider) => {
    (provider.countries || []).forEach((country) => {
      (country.charts || []).forEach((chart) => {
        (chart.rows || []).forEach((row) => {
          map.set(
            gameProviderRowKeyV2(provider, country, chart, row),
            [row.rank, row.game, row.gameZh, row.publisher, row.appId, row.updatedAt].join("|")
          );
        });
      });
    });
  });

  return map;
}

function gameMarketRowKeyV2(market, row) {
  return `market:${market?.id || ""}:${row.appId || row.game || ""}:${row.rank || ""}`;
}

function gameProviderRowKeyV2(provider, country, chart, row) {
  return `rank:${provider?.id || ""}:${country?.code || ""}:${chart?.id || ""}:${row.appId || row.game || ""}:${row.rank || ""}`;
}

function displayGameNameV2(row) {
  return row?.gameZh || row?.game || "-";
}

function gameEnglishNameV2(row) {
  if (!row?.gameZh || !row?.game || row.gameZh === row.game) return "";
  return row.game;
}

function gameTop100SublineV2(row) {
  return [gameEnglishNameV2(row), row?.publisher || "未知厂商", row?.genre, row?.month ? formatMonth(row.month) : ""].filter(Boolean).join(" · ");
}

function gameRankingSublineV2(row) {
  return [gameEnglishNameV2(row), row?.appId ? `App ID ${row.appId}` : row?.genre || "Games"].filter(Boolean).join(" · ");
}

function providerStatusLabelV2(status) {
  if (status === "imported") return "已导入";
  if (status === "public_fallback") return "公开兜底";
  if (status === "credentials_present") return "已配置授权";
  if (status === "optional") return "可选增强";
  if (status === "needs_login_or_export") return "待登录/导出";
  return "待授权/导入";
}

function formatRevenueSourceV2(row) {
  const typeLabels = {
    official: "官方披露",
    media: "权威媒体",
    reported: "披露数据",
    sensor_tower: "Sensor Tower估算",
    estimate: "估算数据"
  };
  const typeLabel = typeLabels[row?.sourceType] || "流水来源";
  const source = row?.source && row.source !== typeLabel ? ` · ${row.source}` : "";
  const alternatives = (row?.revenueAlternatives || []).length > 1 ? ` · 已比对${row.revenueAlternatives.length}个来源` : "";
  return `${typeLabel}${source}${alternatives}`;
}

function summarizeProviderCountryV2(country) {
  if (!country?.charts?.length) return "等待点点/七麦国家榜数据";
  const parts = country.charts.map((chart) => `${chart.name}${chart.rowCount || chart.rows?.length || 0}条`);
  return parts.join("；");
}

function formatRankSnapshotV2(rows) {
  if (!rows?.length) return "待导入";
  return rows
    .slice(0, 4)
    .map((row) => `${row.country || row.countryCode?.toUpperCase() || ""} #${row.rank}`)
    .join(" / ");
}

function buildGamesStatus(data) {
  const summary = data.summary || {};
  const countryCount = summary.countryCount || data.countryRankings?.length || 0;
  const rankingRows = summary.rankingRows || 0;
  const imported = summary.importedCommercialPoints ?? summary.importedDataPoints ?? 0;
  const count = `；覆盖${countryCount}个国家/地区、${rankingRows}条公开榜单；商业数据${imported}项；Sensor Tower流水${summary.sensorTowerRevenueRows || 0}款`;
  return `${buildGenericStatus(data, data.source || "Sensor Tower / 点点数据 / 七麦数据")}${count}`;
}

function buildGenericStatus(data, source) {
  const cacheHint = data.cached ? "；缓存" : "";
  const storageHint = data.fromStorage ? "；SQLite" : "";
  const throttleHint = data.throttled ? "；半小时内不重复抓取" : "";
  const staleHint = data.stale ? "；旧快照" : "";
  const errorHint = data.errors?.length ? `；部分数据异常：${data.errors.join("；")}` : "";
  return `已更新：${formatTime(data.generatedAt)}${cacheHint}${storageHint}${throttleHint}${staleHint}；来源：${source}${errorHint}`;
}

function collectNewsIds(news) {
  return new Set([...(news.china || []), ...(news.world || [])].map(newsId));
}

function collectXueqiuSignatures(activities) {
  const map = new Map();
  (activities || []).forEach((item) => {
    map.set(xueqiuActivityId(item), [item.kind, item.text, item.targetTitle, item.publishedAt, item.replyCount, item.retweetCount, item.likeCount].join("|"));
  });
  return map;
}

function xueqiuActivityId(item) {
  return item.id || `${item.influencerId || item.influencerName}-${item.kind}-${item.publishedAt}-${item.text}`;
}

function countNewItems(items = [], newIds = new Set()) {
  return items.reduce((count, item) => count + (newIds.has(newsId(item)) ? 1 : 0), 0);
}

function newsId(item) {
  return item.id || item.url || `${item.title}-${item.publishedAt}`;
}

function difference(nextIds, previousIds) {
  const result = new Set();
  for (const id of nextIds) {
    if (!previousIds.has(id)) result.add(id);
  }
  return result;
}

function collectMarketSignatures(markets) {
  const map = new Map();
  markets.forEach((market, index) => map.set(marketKey(market, index), marketSignature(market)));
  return map;
}

function marketKey(market, index = 0) {
  return market.id || market.name || `market-${index}`;
}

function marketSignature(market) {
  return [
    market.marketCap,
    market.turnover,
    market.turnoverToMarketCapPct,
    market.financingBalance,
    market.financingToMarketCapPct,
    market.financingPercentile,
    market.pe,
    market.marketCapToGdpPct,
    ...(market.indices || []).map((item) => `${item.symbol}:${item.close}:${item.changePct}`)
  ].join("|");
}

function collectCommoditySignatures(items) {
  const map = new Map();
  items.forEach((item) =>
    map.set(
      item.id,
      [
        item.spotPrice,
        item.domesticFuturePrice,
        item.globalFuturePrice,
        item.benchmarkFuturePrice,
        item.basis,
        item.basisFutureContract,
        item.crossMarketSpread,
        item.inventory,
        item.inventoryChange,
        JSON.stringify(item.spotHistory || []),
        JSON.stringify(item.domesticFutureHistory || []),
        JSON.stringify(item.inventoryHistory || [])
      ].join("|")
    )
  );
  return map;
}

function collectEnergySignatures(sections) {
  const map = new Map();
  (sections || []).forEach((section) => {
    (section.rows || []).forEach((row) => {
      map.set(
        row.id,
        [
          row.period,
          row.value,
          row.yoy,
          row.mom,
          row.cumulativeValue,
          row.cumulativeYoy,
          JSON.stringify(row.history || [])
        ].join("|")
      );
    });
  });
  return map;
}

function collectConsumptionSignatures(sections) {
  const map = new Map();
  flattenConsumptionRows(sections).forEach((row) => {
    map.set(row.id, [row.period, row.value, row.yoy, row.mom, JSON.stringify(row.history || [])].join("|"));
  });
  return map;
}

function flattenConsumptionRows(sections) {
  return (sections || []).flatMap((section) => (section.groups || []).flatMap((group) => group.rows || []));
}

function buildConsumptionProjects(section) {
  const projects = new Map();

  (section.groups || []).forEach((group) => {
    (group.rows || []).forEach((row) => {
      const category = row.category || "未分类";
      if (!projects.has(category)) {
        projects.set(category, { category, rows: [], domesticCount: 0, overseasCount: 0, onlineCount: 0, offlineCount: 0 });
      }
      const project = projects.get(category);
      project.rows.push(row);
      if (row.geography === "overseas") {
        project.overseasCount += 1;
      } else if (row.geography === "domestic") {
        project.domesticCount += 1;
      }
      if (isOnlineConsumption(row)) {
        project.onlineCount += 1;
      } else if (isOfflineConsumption(row)) {
        project.offlineCount += 1;
      }
    });
  });

  return Array.from(projects.values())
    .sort((left, right) => {
      const categoryRank = { 社零总览: 0 };
      const rankDiff = (categoryRank[left.category] ?? 10) - (categoryRank[right.category] ?? 10);
      if (rankDiff !== 0) return rankDiff;
      return left.category.localeCompare(right.category, "zh-CN");
    })
    .map((project) => ({
      ...project,
      rows: project.rows.slice().sort(sortConsumptionRows)
    }));
}

function buildConsumptionRegionGroups(project) {
  const rows = project.rows || [];
  const groups = [
    { id: "domestic", label: "境内", subtitle: "国内消费与价格口径", rows: [] },
    { id: "overseas", label: "海外/进口", subtitle: "进口供给与海外需求口径", rows: [] }
  ];
  const groupMap = new Map(groups.map((group) => [group.id, group]));

  rows.forEach((row) => {
    const group = groupMap.get(row.geography) || groupMap.get("domestic");
    group.rows.push(row);
  });

  return groups.filter((group) => group.rows.length > 0);
}

function sortConsumptionRows(left, right) {
  const geographyRank = { domestic: 0, overseas: 1 };
  const channelRank = {
    total_retail: 0,
    total_retail_ytd: 1,
    retail_ex_auto: 2,
    limited_retail: 3,
    goods_retail: 4,
    catering: 5,
    online_retail: 6,
    online_goods: 7,
    online_services: 8,
    offline_retail_estimated: 9
  };
  const geographyDiff = (geographyRank[left.geography] ?? 2) - (geographyRank[right.geography] ?? 2);
  if (geographyDiff !== 0) return geographyDiff;
  const channelDiff = (channelRank[left.id] ?? 20) - (channelRank[right.id] ?? 20);
  if (channelDiff !== 0) return channelDiff;
  return (left.metric || "").localeCompare(right.metric || "", "zh-CN");
}

function isOnlineConsumption(row) {
  return String(row.channel || "").startsWith("online");
}

function isOfflineConsumption(row) {
  return row.channel === "offline";
}

function collectMacroSignatures(countries) {
  const map = new Map();
  countries.forEach((country) => {
    (country.groups || []).forEach((group) => {
      (group.items || []).forEach((item) => {
        map.set(
          macroItemKey(country, group, item),
          [item.value, item.previous, item.period, item.forecast, item.forecastProbability, item.forecastPeriod, JSON.stringify(item.history || [])].join("|")
        );
      });
    });
  });
  return map;
}

function collectGameSignatures(rows, sources) {
  const map = new Map();
  rows.forEach((row) => {
    const values = (sources || []).map((source) => {
      const metric = gameMetric(row, source.id);
      const revenue = metric?.revenue && typeof metric.revenue === "object" ? `${metric.revenue.amount ?? ""}:${metric.revenue.currency ?? ""}` : metric?.revenue ?? "";
      return `${source.id}:${metric?.dau ?? ""}:${metric?.downloads ?? ""}:${revenue}:${metric?.rank ?? ""}:${metric?.grossingRank ?? ""}:${metric?.note ?? ""}`;
    });
    map.set(gameRowKey(row), [row.rank, row.game, row.publisher, row.genre, row.platform, row.country, row.countryCode, ...values].join("|"));
  });
  return map;
}

function macroItemKey(country, group, item) {
  return `${country.id || country.name}:${group.name}:${item.id || item.name}`;
}

function gameRowKey(row) {
  return `${row.month || ""}:${row.rank || ""}:${row.game || ""}`;
}

function countMacroItems(country) {
  if (!country) return 0;
  return (country.groups || []).reduce((sum, group) => sum + (group.items || []).length, 0);
}

function summarizeMacro(countries) {
  const groupNames = new Set();
  let pending = 0;
  countries.forEach((country) => {
    (country.groups || []).forEach((group) => {
      groupNames.add(`${country.id}:${group.name}`);
      (group.items || []).forEach((item) => {
        if (item.value === null || item.value === undefined || item.value === "") pending += 1;
      });
    });
  });
  return { groups: groupNames.size, pending };
}

function summarizeGameMonth(rows, sources) {
  const imported = rows.reduce(
    (sum, row) => sum + (sources || []).reduce((sourceSum, source) => sourceSum + gameMetricPointCount(gameMetric(row, source.id)), 0),
    0
  );
  return `${rows.length}款游戏，${imported}项商业数据`;
}

function summarizeCountryRanking(ranking) {
  if (!ranking?.charts?.length) return "公开榜单暂不可用";
  const chartNames = ranking.charts.map((chart) => `${chart.name}${chart.rows?.length || 0}条`).join("、");
  return chartNames || "公开榜单暂不可用";
}

function countGameSourceRows(rows, sourceId) {
  return rows.filter((row) => gameMetricPointCount(gameMetric(row, sourceId)) > 0).length;
}

function averageGameSourceDau(rows, sourceId) {
  const values = rows
    .map((row) => gameMetric(row, sourceId)?.dau)
    .filter((value) => value !== null && value !== undefined && !Number.isNaN(Number(value)))
    .map(Number);
  if (!values.length) return null;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function gameMetric(row, sourceId) {
  return row.metrics?.[sourceId] || {};
}

function gameMetricPointCount(metric) {
  if (!metric) return 0;
  return ["dau", "downloads", "revenue", "rank", "grossingRank"].reduce((sum, key) => {
    const value = metric[key];
    return sum + (value !== null && value !== undefined && value !== "" ? 1 : 0);
  }, 0);
}

function gameMetricValues(row, sources) {
  return (sources || [])
    .map((source) => gameMetric(row, source.id)?.dau)
    .filter((value) => value !== null && value !== undefined && !Number.isNaN(Number(value)))
    .map(Number);
}

function formatGameAverage(row, sources) {
  const values = gameMetricValues(row, sources);
  if (!values.length) return "暂无";
  return formatDau(values.reduce((sum, value) => sum + value, 0) / values.length);
}

function formatGameDelta(row, sources) {
  const values = gameMetricValues(row, sources);
  if (values.length < 2) return "暂无";
  return formatDau(Math.max(...values) - Math.min(...values));
}

function groupBySector(items) {
  const groups = new Map();
  items.forEach((item) => {
    const sector = item.sector || "其他";
    if (!groups.has(sector)) groups.set(sector, []);
    groups.get(sector).push(item);
  });
  return Array.from(groups.entries());
}

function buildMarketNote(market) {
  const gdp = market.gdp?.label ? `GDP口径：${market.gdp.label}` : "";
  const universe = market.universe ? `样本：${market.universe}` : "";
  const turnoverSource = market.turnoverPercentileSource ? `成交额分位：${market.turnoverPercentileSource}` : "";
  const financingSource = market.financingSource ? `融资：${market.financingSource}` : "";
  const financingPercentileSource = market.financingPercentileSource ? `融资占比分位：${market.financingPercentileSource}` : "";
  const peSource = market.pePercentileSource ? `PE分位：${market.pePercentileSource}` : "";
  return [market.note, financingSource, financingPercentileSource, turnoverSource, peSource, universe, gdp].filter(Boolean).join("；") || "暂无补充说明。";
}

function joinSources(...sections) {
  const sources = [];
  sections.forEach((section) => {
    const source = section?.source;
    if (source && !sources.includes(source)) sources.push(source);
  });
  return sources.join(" / ");
}

function sectionErrors(...sections) {
  const errors = [];
  sections.forEach((section) => {
    if (!section) return;
    if (section.error) errors.push(section.error);
    if (Array.isArray(section.errors)) errors.push(...section.errors);
  });
  return errors;
}

function formatTime(value) {
  if (!value) return "未知";
  const date = parseDisplayDate(value);
  if (!date) return "未知";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: BEIJING_TIME_ZONE,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).format(date);
}

function parseDisplayDate(value) {
  const text = String(value).trim();
  if (!text) return null;
  let normalized = text
    .replace(/^(\d{4})\/(\d{1,2})\/(\d{1,2})/, (_, year, month, day) => `${year}-${month.padStart(2, "0")}-${day.padStart(2, "0")}`)
    .replace(" ", "T");
  const hasExplicitZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(normalized);
  const isDateOnly = /^\d{4}-\d{2}-\d{2}$/.test(normalized);
  const hasClock = /T\d{1,2}:\d{2}/.test(normalized);

  if (!hasExplicitZone && isDateOnly) {
    normalized = `${normalized}T00:00:00${BEIJING_TIME_OFFSET}`;
  } else if (!hasExplicitZone && hasClock) {
    normalized = `${normalized}${BEIJING_TIME_OFFSET}`;
  }

  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

function hasValue(value) {
  return value !== null && value !== undefined && value !== "" && !Number.isNaN(Number(value));
}

function formatPct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "暂无";
  const number = Number(value);
  return `${number > 0 ? "+" : ""}${number.toFixed(2)}%`;
}

function formatSignedChange(change, pct) {
  if ((change === null || change === undefined || Number.isNaN(Number(change))) && (pct === null || pct === undefined || Number.isNaN(Number(pct)))) return "暂无";
  const changeText = change === null || change === undefined || Number.isNaN(Number(change)) ? "--" : `${Number(change) > 0 ? "+" : ""}${formatNumber(change, priceDigits(change))}`;
  const pctText = pct === null || pct === undefined || Number.isNaN(Number(pct)) ? "--" : formatPct(pct);
  return `${changeText} (${pctText})`;
}

function formatPctPlain(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "暂无";
  return `${Number(value).toFixed(2)}%`;
}

function formatPercentile(value, sample, note = "") {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return note || (sample ? `样本${sample}，不足` : "样本不足");
  return `${Number(value).toFixed(1)}%`;
}

function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "暂无";
  return Number(value).toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function formatConsumptionValue(value, unit) {
  if (!hasValue(value)) return unit === "%" ? "价格分项" : "暂无";
  const digits = unit === "万辆" ? 1 : unit === "万亿元" || unit === "%" ? 2 : 0;
  return `${formatNumber(value, digits)}${unit ? ` ${unit}` : ""}`;
}

function formatEnergyValue(value, unit) {
  if (!hasValue(value)) return "暂无";
  const digits = Math.abs(Number(value)) >= 100 ? 0 : 1;
  return `${formatNumber(value, digits)}${unit ? ` ${unit}` : ""}`;
}

function formatEnergyPoint(point, unit) {
  const valueText = hasValue(point.value) ? formatEnergyValue(point.value, unit) : "";
  const yoyText = hasValue(point.yoy) ? `同比${formatPct(point.yoy)}` : "";
  const momText = hasValue(point.mom) ? `环比${formatPct(point.mom)}` : "";
  return [valueText, yoyText, momText].filter(Boolean).join(" / ") || "暂无";
}

function formatConsumptionPoint(point, unit) {
  const valueText = hasValue(point.value) ? formatConsumptionValue(point.value, unit) : "";
  const yoyText = hasValue(point.yoy) ? `同比${formatPct(point.yoy)}` : "";
  const momText = hasValue(point.mom) ? `环比${formatPct(point.mom)}` : "";
  return [valueText, yoyText, momText].filter(Boolean).join(" / ") || "暂无";
}

function consumptionKlineSeries(row) {
  const history = Array.isArray(row.history) ? row.history : [];
  let firstAvailable = null;
  const hasCumulativePeriod = history.some((point) => String(point.periodLabel || "").includes("累计") || String(point.periodLabel || "").includes("全年"));
  const candidates = [
    { key: "value", label: row.unit === "%" ? "价格分项" : "数据", unit: row.unit },
    { key: "yoy", label: "同比", unit: "%" },
    { key: "mom", label: "环比", unit: "%" }
  ];
  const orderedCandidates = hasCumulativePeriod ? [candidates[1], candidates[0], candidates[2]] : candidates;

  for (const candidate of orderedCandidates) {
    const points = history
      .map((point) => ({
        period: point.periodLabel || point.period || "",
        value: Number(point[candidate.key])
      }))
      .filter((point) => Number.isFinite(point.value));
    if (points.length >= 2) {
      return { ...candidate, points };
    }
    if (!firstAvailable && points.length > 0) {
      firstAvailable = { ...candidate, points };
    }
  }

  return firstAvailable || { ...orderedCandidates[0], points: [] };
}

function priceDigits(value) {
  const number = Number(value);
  if (Number.isNaN(number)) return 2;
  if (Math.abs(number) < 10) return 3;
  return 2;
}

function formatPrice(value, unit) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "暂无";
  return `${formatNumber(value, Number(value) >= 100 ? 0 : 2)} ${unit || ""}`.trim();
}

function formatGlobalPrice(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "暂无";
  return formatNumber(value, Number(value) >= 100 ? 0 : 2);
}

function formatBasis(value, unit) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "暂无";
  const number = Number(value);
  return `${number > 0 ? "+" : ""}${formatNumber(number, Math.abs(number) >= 100 ? 0 : 2)} ${unit || ""}`.trim();
}

function formatCrossMarketSpread(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "暂无";
  const number = Number(value);
  return `${number > 0 ? "+" : ""}${formatNumber(number, Math.abs(number) >= 100 ? 0 : 2)}`;
}

function formatChange(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "";
  const number = Number(value);
  return `${number > 0 ? "+" : ""}${formatNumber(number, Math.abs(number) >= 100 ? 0 : 2)}`;
}

function formatInventory(item) {
  if (item.inventory === null || item.inventory === undefined || Number.isNaN(Number(item.inventory))) {
    return item.inventorySource || "暂无公开库存";
  }
  return `${formatNumber(item.inventory, 0)} ${item.inventoryUnit || ""}`.trim();
}

function formatInventoryChange(item) {
  if (!hasValue(item.inventoryChange)) return "";
  const unit = item.inventoryUnit ? ` ${item.inventoryUnit}` : "";
  const pct = hasValue(item.inventoryChangePct) ? ` (${formatPctPlain(item.inventoryChangePct)})` : "";
  return `日变动 ${formatChange(item.inventoryChange)}${unit}${pct}`;
}

function formatMacroValue(item) {
  if (item.value === null || item.value === undefined || item.value === "") return "待接入";
  return `${item.value}${item.unit ? ` ${item.unit}` : ""}`;
}

function formatMacroPrevious(item) {
  if (item.previous === null || item.previous === undefined || item.previous === "") return "暂无";
  return `${item.previous}${item.unit ? ` ${item.unit}` : ""}`;
}

function hasMacroForecast(item) {
  return item.forecast !== null && item.forecast !== undefined && item.forecast !== "";
}

function formatMacroForecast(item) {
  if (!hasMacroForecast(item)) return "暂无";
  return `${item.forecast}${item.unit ? ` ${item.unit}` : ""}`;
}

function macroForecastDetails(item) {
  if (!hasMacroForecast(item)) return "";
  const parts = [];
  if (item.forecastProbability) parts.push(`概率 ${item.forecastProbability}`);
  if (item.forecastPeriod) parts.push(item.forecastPeriod);
  return parts.join(" / ");
}

function macroValueClass(item) {
  if (item.value === null || item.value === undefined || item.previous === null || item.previous === undefined) return "";
  const current = Number.parseFloat(String(item.value));
  const previous = Number.parseFloat(String(item.previous));
  if (Number.isNaN(current) || Number.isNaN(previous) || current === previous) return "";
  const higher = current > previous;
  if (item.polarity === "lower_good") return higher ? "down" : "up";
  return higher ? "up" : "down";
}

function pctClass(value) {
  const number = Number(value);
  if (Number.isNaN(number)) return "";
  return number > 0 ? "up" : number < 0 ? "down" : "";
}

function formatMoney(value, currency) {
  if (value === null || value === undefined || value === "" || Number.isNaN(Number(value))) return "暂无";
  const number = Number(value);
  const unit = currency ? ` ${currency}` : "";
  const abs = Math.abs(number);
  const sign = number < 0 ? "-" : "";
  if (abs >= 1_000_000_000_000) return `${sign}${(abs / 1_000_000_000_000).toFixed(2)}万亿${unit}`;
  if (abs >= 100_000_000) return `${sign}${(abs / 100_000_000).toFixed(2)}亿${unit}`;
  if (abs >= 10_000) return `${sign}${(abs / 10_000).toFixed(2)}万${unit}`;
  return `${sign}${abs.toFixed(0)}${unit}`;
}

function formatMonth(value) {
  if (!value) return "未知月份";
  const match = /^(\d{4})-(\d{2})$/.exec(value);
  return match ? `${match[1]}年${Number(match[2])}月` : value;
}

function formatRevenue(value) {
  if (!value) return "待导入";
  if (typeof value === "object") {
    if (value.amount === null || value.amount === undefined || Number.isNaN(Number(value.amount))) {
      return value.raw || "待导入";
    }
    return formatMoney(value.amount, value.currency || "USD");
  }
  return formatMoney(value, "USD");
}

function formatDownloads(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "待导入";
  return `${formatVolume(value)} 次`;
}

function formatDau(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "待导入";
  return `${formatVolume(value)} 人`;
}

function formatVolume(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "暂无";
  const number = Number(value);
  if (number >= 100_000_000) return `${(number / 100_000_000).toFixed(2)}亿`;
  if (number >= 10_000) return `${(number / 10_000).toFixed(2)}万`;
  return number.toFixed(0);
}

function formatFollowers(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "";
  return `粉丝 ${formatVolume(value)}`;
}
