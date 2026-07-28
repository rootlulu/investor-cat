---
name: latest-snapshot-only
description: Enforce this project's hard persistence rule that database tables, JSON stores, caches, and refresh jobs keep only the latest snapshot and replace older data. Use before modifying SQLite schemas, INSERT/UPSERT logic, cache files, background refresh behavior, snapshot/history tables, or any data-retention code in news-digest-web.
---

# Latest Snapshot Only

## Hard Rule

Keep only the latest usable snapshot. When new data arrives, replace the old data. Do not append periodic snapshots or retain dated historical rows unless the user explicitly asks for history and approves a bounded retention policy.

## Implementation Rules

- For global snapshots, store one row with a stable primary key such as `id = 1`; use `INSERT ... ON CONFLICT(id) DO UPDATE`, and remove any stray rows where `id <> 1`.
- For entity snapshots, use the stable entity identifier as the unique key, for example `market_id` or `stock_id`; do not use date, timestamp, or captured time as the conflict key.
- If a table already has `snapshot_date` or `captured_at`, treat those fields as metadata on the latest row and update them during the UPSERT.
- Avoid `AUTOINCREMENT` snapshot/history tables for refresh output. If an existing table has one, add a stable unique index, prune older rows per entity before creating the index, and make future writes conflict on the stable key.
- For JSON cache files, store entries in a dictionary keyed by stable ID and replace the entry in place. Remove entries when the tracked item is deleted.
- Do not create timestamped cache files, rotating snapshot files, or ever-growing append-only logs for normal refresh data.

## Validation Checklist

- Search for `INSERT INTO`, `ON CONFLICT`, `CREATE TABLE`, `DELETE FROM`, `history`, `snapshot`, and JSON write paths before changing persistence code.
- Confirm latest tables contain one row, and entity-scoped snapshot tables contain one row per entity.
- Confirm SQLite unique indexes match the stable replacement key, not a timestamp/date key.
- Run a small overwrite test when changing UPSERT logic: write the same stable key twice with different dates or values and verify only the newest row remains.
- After pruning accumulated SQLite rows, run `VACUUM` when appropriate so the database file shrinks instead of keeping free pages.
