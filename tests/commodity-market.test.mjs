import assert from "node:assert/strict";
import test from "node:test";

import { selectCommodityInventory } from "../frontend/src/commodity-market.js";

test("V150 market rows never reuse inventory from another market", () => {
  const item = {
    inventory: 26_924,
    inventoryUnit: "吨",
    inventoryDate: "2026-07-28",
    inventorySource: "东方财富期货库存（CU仓单）",
    inventorySeries: [
      { market: "domestic", inventory: 26_924, inventoryUnit: "吨" },
      { market: "international", inventory: 268_775, inventoryUnit: "吨", exchange: "LME" }
    ]
  };

  assert.equal(selectCommodityInventory(item, "domestic").inventory, 26_924);
  assert.equal(selectCommodityInventory(item, "international").inventory, 268_775);
});

test("V150 legacy domestic inventory is never used as overseas inventory", () => {
  const legacyItem = {
    inventory: 26_924,
    inventoryUnit: "吨",
    inventoryDate: "2026-07-28",
    inventorySource: "东方财富期货库存（CU仓单）"
  };

  assert.equal(selectCommodityInventory(legacyItem, "domestic").inventory, 26_924);
  assert.equal(selectCommodityInventory(legacyItem, "international"), null);
});
