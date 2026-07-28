const INVENTORY_FIELDS = [
  "inventory",
  "inventoryUnit",
  "inventoryDate",
  "inventorySource",
  "inventorySourceUrl",
  "inventoryChange",
  "inventoryChangePct",
  "inventoryHistory",
  "inventoryType",
  "inventoryTypeLabel",
  "quality",
  "exchange"
];

function hasInventory(row) {
  return row && row.inventory !== null && row.inventory !== undefined && Number.isFinite(Number(row.inventory));
}

function inventoryMarket(row) {
  return row?.market || row?.inventoryMarket || "domestic";
}

function legacyDomesticInventory(item) {
  if (!hasInventory(item)) return null;
  return {
    ...Object.fromEntries(INVENTORY_FIELDS.map((key) => [key, item[key]])),
    market: "domestic",
    marketLabel: "国内"
  };
}

export function listCommodityInventories(item, market) {
  const rows = (item?.inventorySeries || []).filter(
    (row) => hasInventory(row) && inventoryMarket(row) === market
  );
  if (rows.length) return rows;

  const selected = item?.inventoryByMarket?.[market];
  if (hasInventory(selected)) return [selected];
  const legacy = market === "domestic" ? legacyDomesticInventory(item || {}) : null;
  return legacy ? [legacy] : [];
}

export function selectCommodityInventory(item, market) {
  const selected = item?.inventoryByMarket?.[market];
  if (hasInventory(selected)) return selected;
  return listCommodityInventories(item, market)[0] || null;
}
