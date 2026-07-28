from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import tempfile
import threading
import unicodedata
from pathlib import Path
from typing import Any, Iterable


ROOT_DIR = Path(__file__).resolve().parents[1]
WATCHLIST_PATH = ROOT_DIR / "config" / "game_region_watchlist.json"
WATCHLIST_SCHEMA_VERSION = 3
MAX_GAMES = 500
MAX_REGIONS = 100
MAX_IMPORT_BYTES = 1024 * 1024
SOURCE_KEYS = ("steam", "sensorTower", "qimai", "diandian")
SOURCE_LABELS = {
    "steam": "Steam",
    "sensorTower": "Sensor Tower",
    "qimai": "七麦",
    "diandian": "点点",
    "reported": "官方/媒体披露",
}
WATCHLIST_WRITE_LOCK = threading.RLock()
GAME_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
REGION_CODE_PATTERN = re.compile(r"^(?:global|[a-z]{2})$")
DEFAULT_REGION = {"code": "global", "name": "全球"}

IMPORT_SCHEMA = {
    "formats": ["json", "csv"],
    "modes": ["merge", "replace"],
    "maxGames": MAX_GAMES,
    "maxBytes": MAX_IMPORT_BYTES,
    "fields": [
        "id",
        "name",
        "nameZh",
        "publisher",
        "group",
        "platforms",
        "aliases",
        "steamAppId",
        "sensorTowerAppIds",
        "qimaiAppIds",
        "diandianAppIds",
    ],
}


class WatchlistError(RuntimeError):
    pass


class WatchlistValidationError(WatchlistError):
    pass


class WatchlistNotFoundError(WatchlistError):
    pass


def load_watchlist(path: Path = WATCHLIST_PATH) -> dict[str, Any]:
    raw = _read_watchlist_file(path)
    games = _normalize_games(raw.get("games"))
    regions = _normalize_regions(raw.get("regions"))
    return _catalog_payload(raw, games, regions)


def import_watchlist(
    *,
    content: str,
    data_format: str,
    mode: str,
    path: Path = WATCHLIST_PATH,
) -> dict[str, Any]:
    if not isinstance(content, str):
        raise WatchlistValidationError("导入正文必须是字符串。")
    if len(content.encode("utf-8")) > MAX_IMPORT_BYTES:
        raise WatchlistValidationError("导入正文不得超过 1 MiB。")

    normalized_format = clean_text(data_format).lower()
    normalized_mode = clean_text(mode).lower()
    if normalized_format not in {"json", "csv"}:
        raise WatchlistValidationError("导入格式仅支持 json 或 csv。")
    if normalized_mode not in {"merge", "replace"}:
        raise WatchlistValidationError("导入模式仅支持 merge 或 replace。")

    imported_records = _parse_import(content, normalized_format)
    imported_games = _normalize_games(imported_records)

    with WATCHLIST_WRITE_LOCK:
        raw = _read_watchlist_file(path)
        current_games = _normalize_games(raw.get("games"))
        if normalized_mode == "replace":
            next_games = imported_games
            added = len(imported_games)
            updated = 0
        else:
            next_games = list(current_games)
            positions = {game["id"]: index for index, game in enumerate(next_games)}
            added = 0
            updated = 0
            for game in imported_games:
                position = positions.get(game["id"])
                if position is None:
                    positions[game["id"]] = len(next_games)
                    next_games.append(game)
                    added += 1
                else:
                    next_games[position] = game
                    updated += 1
            _validate_identity_uniqueness(next_games)

        regions = _normalize_regions(raw.get("regions"))
        _write_watchlist_file(path, raw, next_games, regions)
        result = _catalog_payload({**raw, "schemaVersion": WATCHLIST_SCHEMA_VERSION}, next_games, regions)
        result["operation"] = {
            "mode": normalized_mode,
            "added": added,
            "updated": updated,
            "total": len(next_games),
        }
        return result


def delete_watchlist_game(game_id: str, *, path: Path = WATCHLIST_PATH) -> dict[str, Any]:
    normalized_id = clean_text(game_id).lower()
    with WATCHLIST_WRITE_LOCK:
        raw = _read_watchlist_file(path)
        current_games = _normalize_games(raw.get("games"))
        next_games = [game for game in current_games if game["id"] != normalized_id]
        if len(next_games) == len(current_games):
            raise WatchlistNotFoundError(f"关注游戏不存在：{normalized_id or game_id}")
        regions = _normalize_regions(raw.get("regions"))
        _write_watchlist_file(path, raw, next_games, regions)
        result = _catalog_payload({**raw, "schemaVersion": WATCHLIST_SCHEMA_VERSION}, next_games, regions)
        result["operation"] = {
            "mode": "delete",
            "deleted": normalized_id,
            "total": len(next_games),
        }
        return result


def update_watchlist_game(
    game_id: str,
    game: dict[str, Any],
    *,
    path: Path = WATCHLIST_PATH,
) -> dict[str, Any]:
    normalized_id = clean_text(game_id).lower()
    if not isinstance(game, dict):
        raise WatchlistValidationError("游戏资料必须是对象。")
    provided_id = clean_text(game.get("id") or game.get("watchlistId")).lower()
    if provided_id and provided_id != normalized_id:
        raise WatchlistValidationError("游戏 id 与请求路径不一致。")

    with WATCHLIST_WRITE_LOCK:
        raw = _read_watchlist_file(path)
        current_games = _normalize_games(raw.get("games"))
        position = next(
            (index for index, item in enumerate(current_games) if item["id"] == normalized_id),
            None,
        )
        if position is None:
            raise WatchlistNotFoundError(f"关注游戏不存在：{normalized_id or game_id}")

        replacement = _normalize_game({**game, "id": normalized_id}, position)
        next_games = list(current_games)
        next_games[position] = replacement
        _validate_identity_uniqueness(next_games)
        regions = _normalize_regions(raw.get("regions"))
        _write_watchlist_file(path, raw, next_games, regions)
        result = _catalog_payload({**raw, "schemaVersion": WATCHLIST_SCHEMA_VERSION}, next_games, regions)
        result["operation"] = {
            "mode": "update",
            "updated": normalized_id,
            "total": len(next_games),
        }
        return result


def create_watchlist_region(
    region: dict[str, Any],
    *,
    path: Path = WATCHLIST_PATH,
) -> dict[str, Any]:
    with WATCHLIST_WRITE_LOCK:
        raw = _read_watchlist_file(path)
        games = _normalize_games(raw.get("games"))
        current_regions = _normalize_regions(raw.get("regions"))
        next_regions = _normalize_regions([*current_regions, region])
        _write_watchlist_file(path, raw, games, next_regions)
        result = _catalog_payload({**raw, "schemaVersion": WATCHLIST_SCHEMA_VERSION}, games, next_regions)
        result["operation"] = {
            "mode": "region-create",
            "created": next_regions[-1]["code"],
            "total": len(next_regions),
        }
        return result


def update_watchlist_region(
    region_code: str,
    region: dict[str, Any],
    *,
    path: Path = WATCHLIST_PATH,
) -> dict[str, Any]:
    normalized_code = clean_text(region_code).lower()
    replacement = _normalize_region(region, 0)
    if normalized_code == "global" and replacement["code"] != "global":
        raise WatchlistValidationError("global 基础范围不能改为其他代码。")

    with WATCHLIST_WRITE_LOCK:
        raw = _read_watchlist_file(path)
        games = _normalize_games(raw.get("games"))
        current_regions = _normalize_regions(raw.get("regions"))
        position = next(
            (index for index, item in enumerate(current_regions) if item["code"] == normalized_code),
            None,
        )
        if position is None:
            raise WatchlistNotFoundError(f"关注国家不存在：{normalized_code or region_code}")
        next_regions = list(current_regions)
        next_regions[position] = replacement
        next_regions = _normalize_regions(next_regions)
        _write_watchlist_file(path, raw, games, next_regions)
        result = _catalog_payload({**raw, "schemaVersion": WATCHLIST_SCHEMA_VERSION}, games, next_regions)
        result["operation"] = {
            "mode": "region-update",
            "updated": replacement["code"],
            "previousCode": normalized_code,
            "total": len(next_regions),
        }
        return result


def delete_watchlist_region(
    region_code: str,
    *,
    path: Path = WATCHLIST_PATH,
) -> dict[str, Any]:
    normalized_code = clean_text(region_code).lower()
    if normalized_code == "global":
        raise WatchlistValidationError("global 是基础范围，不能删除。")

    with WATCHLIST_WRITE_LOCK:
        raw = _read_watchlist_file(path)
        games = _normalize_games(raw.get("games"))
        current_regions = _normalize_regions(raw.get("regions"))
        next_regions = [region for region in current_regions if region["code"] != normalized_code]
        if len(next_regions) == len(current_regions):
            raise WatchlistNotFoundError(f"关注国家不存在：{normalized_code or region_code}")
        _write_watchlist_file(path, raw, games, next_regions)
        result = _catalog_payload({**raw, "schemaVersion": WATCHLIST_SCHEMA_VERSION}, games, next_regions)
        result["operation"] = {
            "mode": "region-delete",
            "deleted": normalized_code,
            "total": len(next_regions),
        }
        return result


def filter_rows_for_watchlist(
    rows: Iterable[dict[str, Any]],
    *,
    source: str,
    catalog: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    active_catalog = catalog or load_watchlist()
    games = active_catalog.get("games") or []
    source_key = normalize_source_key(source)
    source_index: dict[str, dict[str, Any]] = {}
    alias_index: dict[str, dict[str, Any]] = {}

    for game in games:
        for source_id in (game.get("sourceIds") or {}).get(source_key, []):
            source_index[normalize_source_id(source_id)] = game
        for value in [game.get("name"), game.get("nameZh"), *(game.get("aliases") or [])]:
            token = normalize_match_text(value)
            if token:
                alias_index[token] = game

    filtered: list[dict[str, Any]] = []
    unmatched = 0
    ambiguous = 0
    for row in rows:
        if not isinstance(row, dict):
            unmatched += 1
            continue
        game = None
        row_source_id = normalize_source_id(row.get("appId", row.get("app_id")))
        source_has_ids = source_key in SOURCE_KEYS
        if row_source_id and source_has_ids:
            game = source_index.get(row_source_id)
            if game is None:
                unmatched += 1
                continue
        if game is None and (not row_source_id or not source_has_ids):
            candidates = {
                alias_index[token]["id"]
                for token in _row_match_tokens(row)
                if token in alias_index
            }
            if len(candidates) == 1:
                matched_id = next(iter(candidates))
                game = next(item for item in games if item["id"] == matched_id)
            elif len(candidates) > 1:
                ambiguous += 1
                continue
        if game is None:
            unmatched += 1
            continue
        item = dict(row)
        item["watchlistId"] = game["id"]
        item["watchlistName"] = game.get("name") or game.get("nameZh")
        item["watchlistNameZh"] = game.get("nameZh") or game.get("name")
        filtered.append(item)

    label = SOURCE_LABELS.get(source_key, clean_text(source) or "数据源")
    warnings = []
    if unmatched:
        warnings.append(f"{label}：排除 {unmatched} 条未关注记录。")
    if ambiguous:
        warnings.append(f"{label}：排除 {ambiguous} 条名称映射歧义记录。")
    return filtered, warnings


def normalize_source_key(value: Any) -> str:
    token = re.sub(r"[^a-z]", "", clean_text(value).lower())
    aliases = {
        "steam": "steam",
        "sensortower": "sensorTower",
        "sensor": "sensorTower",
        "qimai": "qimai",
        "diandian": "diandian",
        "reported": "reported",
    }
    return aliases.get(token, clean_text(value))


def normalize_source_id(value: Any) -> str:
    return clean_text(value).casefold()


def normalize_match_text(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", clean_text(value)).casefold()
    return "".join(character for character in normalized if character.isalnum())


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _read_watchlist_file(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise WatchlistValidationError(f"关注游戏配置不存在：{path}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise WatchlistValidationError(f"关注游戏配置无法读取：{error}") from error
    if not isinstance(raw, dict):
        raise WatchlistValidationError("关注游戏配置顶层必须是对象。")
    if "games" not in raw:
        raise WatchlistValidationError("关注游戏配置缺少 games。")
    return raw


def _catalog_payload(
    raw: dict[str, Any],
    games: list[dict[str, Any]],
    regions: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "schemaVersion": WATCHLIST_SCHEMA_VERSION,
        "revision": watchlist_revision(games, regions),
        "description": clean_text(raw.get("description")),
        "games": games,
        "regions": regions,
        "importSchema": IMPORT_SCHEMA,
    }


def watchlist_revision(
    games: Iterable[dict[str, Any]],
    regions: Iterable[dict[str, str]],
) -> str:
    canonical = json.dumps(
        {"games": list(games), "regions": list(regions)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _normalize_games(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise WatchlistValidationError("games 必须是数组。")
    if len(value) > MAX_GAMES:
        raise WatchlistValidationError(f"关注游戏最多 {MAX_GAMES} 款。")
    games = [_normalize_game(record, index) for index, record in enumerate(value)]
    _validate_identity_uniqueness(games)
    return games


def _normalize_game(record: Any, index: int) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise WatchlistValidationError(f"games[{index}] 必须是对象。")

    name = clean_text(record.get("name") or record.get("nameEn") or record.get("name_en"))
    name_zh = clean_text(record.get("nameZh") or record.get("name_zh") or record.get("中文名"))
    if not name and not name_zh:
        raise WatchlistValidationError(f"games[{index}] 缺少 name/nameZh。")

    explicit_id = clean_text(record.get("id") or record.get("watchlistId")).lower()
    game_id = _game_id(explicit_id, name, name_zh)
    app_id = _optional_positive_int(
        record.get("appId", record.get("app_id", record.get("steamAppId"))),
        field=f"games[{index}].appId",
    )
    source_ids = _normalize_source_ids(record, app_id)
    if app_id is None and source_ids["steam"]:
        app_id = _optional_positive_int(source_ids["steam"][0], field=f"games[{index}].sourceIds.steam")
    if app_id is not None:
        source_ids["steam"] = _dedupe([str(app_id), *source_ids["steam"]])

    aliases = _dedupe(_split_values(record.get("aliases") or record.get("alias")))
    platforms = _dedupe(_split_values(record.get("platforms") or record.get("platform")))
    return {
        "id": game_id,
        "name": name,
        "nameZh": name_zh,
        "publisher": clean_text(record.get("publisher") or record.get("developer")),
        "group": clean_text(record.get("group")) or "global",
        "platforms": platforms,
        "aliases": aliases,
        "appId": app_id,
        "sourceIds": source_ids,
    }


def _normalize_source_ids(record: dict[str, Any], app_id: int | None) -> dict[str, list[str]]:
    raw = record.get("sourceIds")
    source_ids: dict[str, list[str]] = {key: [] for key in SOURCE_KEYS}
    if raw not in (None, ""):
        if not isinstance(raw, dict):
            raise WatchlistValidationError("sourceIds 必须是对象。")
        for key, values in raw.items():
            source_key = normalize_source_key(key)
            if source_key not in source_ids:
                raise WatchlistValidationError(f"不支持的来源 ID：{key}")
            source_ids[source_key].extend(_split_values(values))

    flat_fields = {
        "steam": ("steamAppId", "steamAppIds"),
        "sensorTower": ("sensorTowerAppId", "sensorTowerAppIds", "sensor_tower_app_ids"),
        "qimai": ("qimaiAppId", "qimaiAppIds", "qimai_app_ids"),
        "diandian": ("diandianAppId", "diandianAppIds", "diandian_app_ids"),
    }
    for source, fields in flat_fields.items():
        for field in fields:
            if record.get(field) not in (None, ""):
                source_ids[source].extend(_split_values(record.get(field)))
    if app_id is not None:
        source_ids["steam"].insert(0, str(app_id))
    return {key: _dedupe(values) for key, values in source_ids.items()}


def _validate_identity_uniqueness(games: list[dict[str, Any]]) -> None:
    ids: dict[str, str] = {}
    source_ids: dict[tuple[str, str], str] = {}
    aliases: dict[str, str] = {}
    for game in games:
        game_id = game["id"]
        if game_id in ids:
            raise WatchlistValidationError(f"关注游戏 id 重复：{game_id}")
        ids[game_id] = game_id

        for source, values in (game.get("sourceIds") or {}).items():
            for value in values:
                key = (source, normalize_source_id(value))
                owner = source_ids.get(key)
                if owner and owner != game_id:
                    raise WatchlistValidationError(f"{source} 来源 ID 重复：{value}")
                source_ids[key] = game_id

        for value in [game.get("name"), game.get("nameZh"), *(game.get("aliases") or [])]:
            token = normalize_match_text(value)
            if not token:
                continue
            owner = aliases.get(token)
            if owner and owner != game_id:
                raise WatchlistValidationError(f"游戏名称/别名映射重复：{value}")
            aliases[token] = game_id


def _game_id(explicit_id: str, name: str, name_zh: str) -> str:
    if explicit_id:
        if not GAME_ID_PATTERN.fullmatch(explicit_id):
            raise WatchlistValidationError(f"游戏 id 非法：{explicit_id}")
        return explicit_id
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.casefold()).strip("-")[:80]
    if slug:
        return slug
    digest = hashlib.sha256((name_zh or name).encode("utf-8")).hexdigest()[:12]
    return f"game-{digest}"


def _optional_positive_int(value: Any, *, field: str) -> int | None:
    if value in (None, "", 0, "0"):
        return None
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as error:
        raise WatchlistValidationError(f"{field} 必须是正整数或空值。") from error
    if parsed <= 0:
        raise WatchlistValidationError(f"{field} 必须是正整数或空值。")
    return parsed


def _normalize_regions(value: Any) -> list[dict[str, str]]:
    if value is None:
        value = []
    if not isinstance(value, list):
        raise WatchlistValidationError("regions 必须是数组。")
    if len(value) > MAX_REGIONS:
        raise WatchlistValidationError(f"关注国家最多 {MAX_REGIONS} 个。")
    regions: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, record in enumerate(value):
        region = _normalize_region(record, index)
        if region["code"] in seen:
            raise WatchlistValidationError(f"关注国家代码重复：{region['code']}")
        seen.add(region["code"])
        regions.append(region)
    if "global" not in seen:
        if len(regions) >= MAX_REGIONS:
            raise WatchlistValidationError(f"关注国家最多 {MAX_REGIONS} 个（含全球）。")
        regions.insert(0, dict(DEFAULT_REGION))
    return regions


def _normalize_region(record: Any, index: int) -> dict[str, str]:
    if not isinstance(record, dict):
        raise WatchlistValidationError(f"regions[{index}] 必须是对象。")
    code = clean_text(record.get("code")).lower()
    name = clean_text(record.get("name"))
    if not REGION_CODE_PATTERN.fullmatch(code):
        raise WatchlistValidationError(f"国家代码非法：{code or '空值'}")
    if not name:
        raise WatchlistValidationError(f"regions[{index}] 缺少 name。")
    return {"code": code, "name": name}


def _parse_import(content: str, data_format: str) -> list[dict[str, Any]]:
    if data_format == "json":
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as error:
            raise WatchlistValidationError(f"JSON 无法解析：{error.msg}") from error
        records = payload.get("games") if isinstance(payload, dict) else payload
        if not isinstance(records, list):
            raise WatchlistValidationError("JSON 必须是游戏数组或含 games 数组的对象。")
        return records

    try:
        reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")))
        if not reader.fieldnames:
            raise WatchlistValidationError("CSV 缺少表头。")
        return [_csv_record(row) for row in reader]
    except csv.Error as error:
        raise WatchlistValidationError(f"CSV 无法解析：{error}") from error


def _csv_record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _first(row, "id", "watchlistId"),
        "name": _first(row, "name", "nameEn", "英文名", "游戏英文名"),
        "nameZh": _first(row, "nameZh", "name_zh", "中文名", "游戏中文名"),
        "publisher": _first(row, "publisher", "developer", "厂商", "发行商"),
        "group": _first(row, "group", "分组"),
        "platforms": _first(row, "platforms", "platform", "平台"),
        "aliases": _first(row, "aliases", "alias", "别名"),
        "steamAppId": _first(row, "steamAppId", "steam_app_id", "appId", "appid"),
        "sensorTowerAppIds": _first(row, "sensorTowerAppIds", "sensorTowerAppId", "sensor_tower_app_ids"),
        "qimaiAppIds": _first(row, "qimaiAppIds", "qimaiAppId", "qimai_app_ids"),
        "diandianAppIds": _first(row, "diandianAppIds", "diandianAppId", "diandian_app_ids"),
    }


def _first(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if record.get(key) not in (None, ""):
            return record[key]
    return ""


def _split_values(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = re.split(r"[|;；,\n]+", str(value))
    return [clean_text(item) for item in values if clean_text(item)]


def _dedupe(values: Iterable[Any]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        text = clean_text(value)
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _row_match_tokens(row: dict[str, Any]) -> set[str]:
    values = [
        row.get("game"),
        row.get("gameZh"),
        row.get("name"),
        row.get("nameZh"),
        row.get("app"),
        row.get("product"),
    ]
    return {token for value in values if (token := normalize_match_text(value))}


def _write_watchlist_file(
    path: Path,
    raw: dict[str, Any],
    games: list[dict[str, Any]],
    regions: list[dict[str, str]],
) -> None:
    data = dict(raw)
    data["schemaVersion"] = WATCHLIST_SCHEMA_VERSION
    data["games"] = games
    data["regions"] = _normalize_regions(regions)
    serialized = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    original_mode = path.stat().st_mode if path.exists() else None
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
            temporary_path = Path(handle.name)
        if original_mode is not None:
            os.chmod(temporary_path, original_mode)
        os.replace(temporary_path, path)
    except OSError as error:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise WatchlistError(f"关注游戏配置写入失败：{error}") from error
