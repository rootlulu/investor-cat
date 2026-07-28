function settledRequest(fetcher) {
  return Promise.resolve()
    .then(fetcher)
    .then(
      (data) => ({ ok: true, data }),
      (error) => ({ ok: false, error })
    );
}

export async function loadStockPageSources({
  fetchStocks,
  fetchWatchlist,
  onStocks,
  onStocksError,
  onWatchlist,
  onWatchlistError
}) {
  const stocksRequest = settledRequest(fetchStocks);
  const watchlistRequest = settledRequest(fetchWatchlist);

  const stocks = await stocksRequest;
  if (stocks.ok) {
    await onStocks?.(stocks.data);
  } else {
    await onStocksError?.(stocks.error);
  }

  const watchlist = await watchlistRequest;
  if (watchlist.ok) {
    await onWatchlist?.(watchlist.data);
  } else {
    await onWatchlistError?.(watchlist.error);
  }

  return { stocks, watchlist };
}

export function stockSectionViewState({ loading, hasData }) {
  if (hasData) return "ready";
  return loading ? "loading" : "empty";
}
