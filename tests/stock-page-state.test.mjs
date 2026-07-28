import assert from "node:assert/strict";
import test from "node:test";

import {
  loadStockPageSources,
  stockSectionViewState
} from "../frontend/src/stock-page-state.js";

test("V156 stock snapshot renders before a delayed watchlist", async () => {
  let resolveWatchlist;
  const watchlistRequest = new Promise((resolve) => {
    resolveWatchlist = resolve;
  });
  const events = [];
  let resolveStocksApplied;
  const stocksApplied = new Promise((resolve) => {
    resolveStocksApplied = resolve;
  });

  const loading = loadStockPageSources({
    fetchStocks: async () => ({ markets: [{ id: "a_share" }] }),
    fetchWatchlist: async () => watchlistRequest,
    onStocks: (data) => {
      events.push(["stocks", data.markets.length]);
      resolveStocksApplied();
    },
    onWatchlist: (data) => events.push(["watchlist", data.items.length])
  });

  await stocksApplied;
  assert.deepEqual(events, [["stocks", 1]]);

  resolveWatchlist({ items: [{ id: "sh-600000" }] });
  const result = await loading;

  assert.deepEqual(events, [["stocks", 1], ["watchlist", 1]]);
  assert.equal(result.stocks.ok, true);
  assert.equal(result.watchlist.ok, true);
});

test("V156 watchlist failure does not invalidate a rendered stock snapshot", async () => {
  const events = [];

  const result = await loadStockPageSources({
    fetchStocks: async () => ({ markets: [{ id: "a_share" }] }),
    fetchWatchlist: async () => {
      throw new Error("watchlist timeout");
    },
    onStocks: () => events.push("stocks"),
    onWatchlistError: (error) => events.push(error.message)
  });

  assert.deepEqual(events, ["stocks", "watchlist timeout"]);
  assert.equal(result.stocks.ok, true);
  assert.equal(result.watchlist.ok, false);
});

test("V157 unresolved stock snapshot uses loading semantics instead of empty semantics", () => {
  assert.equal(stockSectionViewState({ loading: true, hasData: false }), "loading");
  assert.equal(stockSectionViewState({ loading: false, hasData: false }), "empty");
  assert.equal(stockSectionViewState({ loading: true, hasData: true }), "ready");
});
