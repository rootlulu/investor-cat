from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import sqlite3
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .xueqiu_service import (
    XUEQIU_COMMENT_TIMELINE_APIS,
    XUEQIU_FETCH_LIMIT,
    XUEQIU_TIMELINE_APIS,
    create_xueqiu_session,
    fetch_activity_rows,
    influencer_public_fields,
    is_xueqiu_auth_error,
    load_influencers_config,
    normalize_error,
    normalize_text,
    parse_activity_row,
)


ROOT_DIR = Path(__file__).resolve().parents[1]
XUEQIU_RESEARCH_DB_PATH = ROOT_DIR / "data" / "xueqiu_research.sqlite"
XUEQIU_RESEARCH_PAGE_SIZE = XUEQIU_FETCH_LIMIT
XUEQIU_RESEARCH_PAGES_PER_STREAM = 25
XUEQIU_RESEARCH_REQUEST_DELAY_SECONDS = 0.8
XUEQIU_RESEARCH_STREAMS = ("posts", "comments")
XUEQIU_RESEARCH_ACTIVE_STATES = ("queued", "running")
XUEQIU_RESEARCH_JOB_STATES = {
    "queued",
    "running",
    "partial",
    "ready",
    "paused_auth",
    "cancelled",
    "interrupted",
    "failed",
}
XUEQIU_RESEARCH_KINDS = {"post", "comment", "reply", "repost"}

LOGGER = logging.getLogger(__name__)
RESEARCH_TASKS: dict[str, asyncio.Task[None]] = {}
RESEARCH_TASK_LOCK = asyncio.Lock()
RESEARCH_DB_LOCK = threading.Lock()
RESEARCH_CRAWL_SEMAPHORE = threading.Semaphore(1)


class XueqiuResearchError(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def research_db_path(db_path: Path | str | None = None) -> Path:
    return Path(db_path) if db_path is not None else XUEQIU_RESEARCH_DB_PATH


def connect_research_db(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = research_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def ensure_research_db(db_path: Path | str | None = None) -> None:
    path = research_db_path(db_path)
    with RESEARCH_DB_LOCK, connect_research_db(path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS research_items (
                id TEXT PRIMARY KEY,
                influencer_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                influencer_name TEXT NOT NULL,
                kind TEXT NOT NULL,
                activity_id TEXT NOT NULL DEFAULT '',
                status_id TEXT NOT NULL DEFAULT '',
                comment_id TEXT NOT NULL DEFAULT '',
                text TEXT NOT NULL DEFAULT '',
                target_title TEXT NOT NULL DEFAULT '',
                original_url TEXT NOT NULL DEFAULT '',
                profile_url TEXT NOT NULL DEFAULT '',
                media_json TEXT NOT NULL DEFAULT '[]',
                source TEXT NOT NULL DEFAULT '雪球',
                published_at TEXT NOT NULL DEFAULT '',
                reply_count REAL,
                retweet_count REAL,
                like_count REAL,
                content_hash TEXT NOT NULL,
                first_fetched_at TEXT NOT NULL,
                last_fetched_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS research_items_influencer_date
                ON research_items(influencer_id, published_at DESC);
            CREATE INDEX IF NOT EXISTS research_items_kind
                ON research_items(kind, published_at DESC);

            CREATE TABLE IF NOT EXISTS research_cursors (
                influencer_id TEXT NOT NULL,
                stream TEXT NOT NULL,
                next_page INTEGER NOT NULL DEFAULT 1,
                complete INTEGER NOT NULL DEFAULT 0,
                last_signature TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (influencer_id, stream)
            );

            CREATE TABLE IF NOT EXISTS research_jobs (
                id TEXT PRIMARY KEY,
                influencer_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                influencer_name TEXT NOT NULL,
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                started_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                finished_at TEXT NOT NULL DEFAULT '',
                pages_fetched INTEGER NOT NULL DEFAULT 0,
                items_seen INTEGER NOT NULL DEFAULT 0,
                items_upserted INTEGER NOT NULL DEFAULT 0,
                post_pages INTEGER NOT NULL DEFAULT 0,
                comment_pages INTEGER NOT NULL DEFAULT 0,
                stop_reason TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                cancel_requested INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS research_jobs_influencer_created
                ON research_jobs(influencer_id, created_at DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS research_jobs_one_active_per_influencer
                ON research_jobs(influencer_id)
                WHERE status IN ('queued', 'running');
            """
        )
        try:
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS research_items_fts USING fts5(
                    item_id UNINDEXED,
                    influencer_id UNINDEXED,
                    text,
                    target_title,
                    tokenize='trigram'
                )
                """
            )
        except sqlite3.OperationalError as error:
            raise XueqiuResearchError("当前 SQLite 不支持 FTS5 trigram，无法建立中文研究索引") from error


def recover_interrupted_jobs(db_path: Path | str | None = None) -> int:
    ensure_research_db(db_path)
    stamp = now_iso()
    with connect_research_db(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE research_jobs
            SET status = 'interrupted', updated_at = ?, finished_at = ?,
                stop_reason = 'service_restart',
                error = CASE WHEN error = '' THEN '服务重启，任务可继续' ELSE error END
            WHERE status IN ('queued', 'running')
            """,
            (stamp, stamp),
        )
        return cursor.rowcount


async def initialize_research_runtime() -> None:
    await asyncio.to_thread(recover_interrupted_jobs)


def validate_mode(mode: str) -> str:
    normalized = normalize_text(mode).lower()
    if normalized not in {"full", "incremental"}:
        raise ValueError("mode 必须是 full 或 incremental")
    return normalized


def find_research_influencer(influencer_id: str) -> dict[str, Any]:
    wanted = normalize_text(influencer_id)
    for influencer in load_influencers_config():
        if wanted in {normalize_text(influencer.get("id")), normalize_text(influencer.get("userId"))}:
            return influencer
    raise ValueError(f"未找到已导入的雪球大V：{wanted}")


def ensure_profile_cursors(conn: sqlite3.Connection, influencer_id: str) -> None:
    stamp = now_iso()
    for stream in XUEQIU_RESEARCH_STREAMS:
        conn.execute(
            """
            INSERT OR IGNORE INTO research_cursors
                (influencer_id, stream, next_page, complete, last_signature, updated_at)
            VALUES (?, ?, 1, 0, '', ?)
            """,
            (influencer_id, stream, stamp),
        )


def create_research_job_sync(
    influencer_id: str,
    mode: str,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    normalized_mode = validate_mode(mode)
    influencer = find_research_influencer(influencer_id)
    public = influencer_public_fields(influencer)
    ensure_research_db(db_path)
    stamp = now_iso()

    with connect_research_db(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        active = conn.execute(
            """
            SELECT * FROM research_jobs
            WHERE influencer_id = ? AND status IN ('queued', 'running')
            ORDER BY created_at DESC LIMIT 1
            """,
            (public["id"],),
        ).fetchone()
        if active:
            conn.commit()
            result = job_row_to_public(active)
            result["_created"] = False
            return result

        ensure_profile_cursors(conn, public["id"])
        complete_rows = conn.execute(
            "SELECT complete FROM research_cursors WHERE influencer_id = ?",
            (public["id"],),
        ).fetchall()
        already_complete = normalized_mode == "full" and len(complete_rows) == 2 and all(row["complete"] for row in complete_rows)
        job_id = f"xqr-{uuid.uuid4().hex}"
        status = "ready" if already_complete else "queued"
        finished_at = stamp if already_complete else ""
        stop_reason = "already_complete" if already_complete else ""
        conn.execute(
            """
            INSERT INTO research_jobs (
                id, influencer_id, user_id, influencer_name, mode, status,
                created_at, updated_at, finished_at, stop_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                public["id"],
                public["userId"],
                public["name"],
                normalized_mode,
                status,
                stamp,
                stamp,
                finished_at,
                stop_reason,
            ),
        )
        row = conn.execute("SELECT * FROM research_jobs WHERE id = ?", (job_id,)).fetchone()
        conn.commit()

    result = job_row_to_public(row)
    result["_created"] = True
    return result


def set_research_job_status_sync(
    job_id: str,
    status: str,
    db_path: Path | str | None = None,
    *,
    stop_reason: str = "",
    error: str = "",
) -> dict[str, Any]:
    if status not in XUEQIU_RESEARCH_JOB_STATES:
        raise ValueError(f"未知任务状态：{status}")
    ensure_research_db(db_path)
    stamp = now_iso()
    finished_at = stamp if status not in XUEQIU_RESEARCH_ACTIVE_STATES else ""
    with connect_research_db(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE research_jobs
            SET status = ?, updated_at = ?,
                started_at = CASE WHEN ? = 'running' AND started_at = '' THEN ? ELSE started_at END,
                finished_at = CASE WHEN ? != '' THEN ? ELSE finished_at END,
                stop_reason = CASE WHEN ? != '' THEN ? ELSE stop_reason END,
                error = CASE WHEN ? != '' THEN ? ELSE error END
            WHERE id = ?
            """,
            (
                status,
                stamp,
                status,
                stamp,
                finished_at,
                finished_at,
                stop_reason,
                stop_reason,
                error,
                error,
                job_id,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError(f"未找到研究任务：{job_id}")
    return get_research_job_sync(job_id, db_path)


def cancel_research_job_sync(job_id: str, db_path: Path | str | None = None) -> dict[str, Any]:
    ensure_research_db(db_path)
    stamp = now_iso()
    with connect_research_db(db_path) as conn:
        row = conn.execute("SELECT status FROM research_jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise ValueError(f"未找到研究任务：{job_id}")
        if row["status"] == "queued":
            conn.execute(
                """
                UPDATE research_jobs
                SET status = 'cancelled', cancel_requested = 1, updated_at = ?,
                    finished_at = ?, stop_reason = 'cancelled_by_user'
                WHERE id = ?
                """,
                (stamp, stamp, job_id),
            )
        elif row["status"] == "running":
            conn.execute(
                "UPDATE research_jobs SET cancel_requested = 1, updated_at = ? WHERE id = ?",
                (stamp, job_id),
            )
    return get_research_job_sync(job_id, db_path)


def get_research_job_sync(job_id: str, db_path: Path | str | None = None) -> dict[str, Any]:
    ensure_research_db(db_path)
    with connect_research_db(db_path) as conn:
        row = conn.execute("SELECT * FROM research_jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        raise ValueError(f"未找到研究任务：{job_id}")
    return job_row_to_public(row)


def job_row_to_public(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {}
    status = row["status"]
    return {
        "id": row["id"],
        "influencerId": row["influencer_id"],
        "userId": row["user_id"],
        "influencerName": row["influencer_name"],
        "mode": row["mode"],
        "status": status,
        "createdAt": row["created_at"],
        "startedAt": row["started_at"],
        "updatedAt": row["updated_at"],
        "finishedAt": row["finished_at"],
        "pagesFetched": row["pages_fetched"],
        "itemsSeen": row["items_seen"],
        "itemsUpserted": row["items_upserted"],
        "postPages": row["post_pages"],
        "commentPages": row["comment_pages"],
        "stopReason": row["stop_reason"],
        "error": row["error"],
        "cancelRequested": bool(row["cancel_requested"]),
        "active": status in XUEQIU_RESEARCH_ACTIVE_STATES,
        "authRequired": status == "paused_auth",
        "resumable": status in {"partial", "paused_auth", "interrupted", "failed", "cancelled"},
    }


def fetch_research_page(session: Any, stream: str, influencer: dict[str, Any], page: int) -> list[dict[str, Any]]:
    if stream == "posts":
        urls = XUEQIU_TIMELINE_APIS
    elif stream == "comments":
        urls = XUEQIU_COMMENT_TIMELINE_APIS
    else:
        raise ValueError(f"未知研究流：{stream}")

    errors: list[Exception] = []
    for url in urls:
        try:
            return fetch_activity_rows(session, url, influencer, XUEQIU_RESEARCH_PAGE_SIZE, page)
        except Exception as error:
            errors.append(error)
    if errors:
        raise errors[0]
    return []


def page_signature(activities: list[dict[str, Any]], rows: list[dict[str, Any]]) -> str:
    identifiers = [normalize_text(item.get("id")) for item in activities if normalize_text(item.get("id"))]
    if not identifiers:
        identifiers = [
            hashlib.sha1(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]
            for row in rows
        ]
    payload = "|".join(identifiers)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest() if payload else ""


def normalize_research_items(rows: list[dict[str, Any]], influencer: dict[str, Any]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = parse_activity_row(row, influencer)
        if item and item.get("id"):
            by_id[str(item["id"])] = item
    return list(by_id.values())


def save_research_page_sync(
    job_id: str,
    influencer: dict[str, Any],
    stream: str,
    page: int,
    rows: list[dict[str, Any]],
    activities: list[dict[str, Any]],
    signature: str,
    complete: bool,
    db_path: Path | str | None = None,
    *,
    update_cursor: bool = True,
) -> int:
    stamp = now_iso()
    new_count = 0
    with connect_research_db(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        for item in activities:
            item_id = normalize_text(item.get("id"))
            existed = conn.execute("SELECT 1 FROM research_items WHERE id = ?", (item_id,)).fetchone() is not None
            media_json = json.dumps(item.get("media") or [], ensure_ascii=False, separators=(",", ":"))
            content_hash = hashlib.sha1(
                json.dumps(
                    {
                        "text": item.get("text") or "",
                        "targetTitle": item.get("targetTitle") or "",
                        "media": item.get("media") or [],
                        "publishedAt": item.get("publishedAt") or "",
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
            conn.execute(
                """
                INSERT INTO research_items (
                    id, influencer_id, user_id, influencer_name, kind,
                    activity_id, status_id, comment_id, text, target_title,
                    original_url, profile_url, media_json, source, published_at,
                    reply_count, retweet_count, like_count, content_hash,
                    first_fetched_at, last_fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    influencer_id = excluded.influencer_id,
                    user_id = excluded.user_id,
                    influencer_name = excluded.influencer_name,
                    kind = excluded.kind,
                    activity_id = excluded.activity_id,
                    status_id = excluded.status_id,
                    comment_id = excluded.comment_id,
                    text = excluded.text,
                    target_title = excluded.target_title,
                    original_url = excluded.original_url,
                    profile_url = excluded.profile_url,
                    media_json = excluded.media_json,
                    source = excluded.source,
                    published_at = excluded.published_at,
                    reply_count = excluded.reply_count,
                    retweet_count = excluded.retweet_count,
                    like_count = excluded.like_count,
                    content_hash = excluded.content_hash,
                    last_fetched_at = excluded.last_fetched_at
                """,
                (
                    item_id,
                    normalize_text(item.get("influencerId") or influencer.get("id")),
                    normalize_text(item.get("userId") or influencer.get("userId")),
                    normalize_text(item.get("influencerName") or influencer.get("name")),
                    normalize_text(item.get("kind") or "post"),
                    normalize_text(item.get("activityId")),
                    normalize_text(item.get("statusId")),
                    normalize_text(item.get("commentId")),
                    normalize_text(item.get("text")),
                    normalize_text(item.get("targetTitle")),
                    normalize_text(item.get("originalUrl") or item.get("url")),
                    normalize_text(item.get("profileUrl")),
                    media_json,
                    normalize_text(item.get("source") or "雪球"),
                    normalize_text(item.get("publishedAt")),
                    item.get("replyCount"),
                    item.get("retweetCount"),
                    item.get("likeCount"),
                    content_hash,
                    stamp,
                    stamp,
                ),
            )
            conn.execute("DELETE FROM research_items_fts WHERE item_id = ?", (item_id,))
            conn.execute(
                "INSERT INTO research_items_fts(item_id, influencer_id, text, target_title) VALUES (?, ?, ?, ?)",
                (
                    item_id,
                    normalize_text(item.get("influencerId") or influencer.get("id")),
                    normalize_text(item.get("text")),
                    normalize_text(item.get("targetTitle")),
                ),
            )
            if not existed:
                new_count += 1

        if update_cursor:
            conn.execute(
                """
                UPDATE research_cursors
                SET next_page = ?, complete = ?, last_signature = ?, updated_at = ?
                WHERE influencer_id = ? AND stream = ?
                """,
                (
                    page + 1,
                    int(complete),
                    signature,
                    stamp,
                    normalize_text(influencer.get("id")),
                    stream,
                ),
            )

        page_column = "post_pages" if stream == "posts" else "comment_pages"
        conn.execute(
            f"""
            UPDATE research_jobs
            SET pages_fetched = pages_fetched + 1,
                items_seen = items_seen + ?,
                items_upserted = items_upserted + ?,
                {page_column} = {page_column} + 1,
                updated_at = ?
            WHERE id = ?
            """,
            (len(rows), new_count, stamp, job_id),
        )
        conn.commit()
    return new_count


def get_research_cursor_sync(
    influencer_id: str,
    stream: str,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    ensure_research_db(db_path)
    with connect_research_db(db_path) as conn:
        ensure_profile_cursors(conn, influencer_id)
        row = conn.execute(
            "SELECT * FROM research_cursors WHERE influencer_id = ? AND stream = ?",
            (influencer_id, stream),
        ).fetchone()
    return {
        "stream": stream,
        "nextPage": row["next_page"],
        "complete": bool(row["complete"]),
        "lastSignature": row["last_signature"],
        "updatedAt": row["updated_at"],
    }


def mark_research_cursor_complete_sync(
    influencer_id: str,
    stream: str,
    page: int,
    signature: str,
    db_path: Path | str | None = None,
) -> None:
    stamp = now_iso()
    with connect_research_db(db_path) as conn:
        conn.execute(
            """
            UPDATE research_cursors
            SET next_page = ?, complete = 1, last_signature = ?, updated_at = ?
            WHERE influencer_id = ? AND stream = ?
            """,
            (max(1, page), signature, stamp, influencer_id, stream),
        )


def job_cancel_requested_sync(job_id: str, db_path: Path | str | None = None) -> bool:
    with connect_research_db(db_path) as conn:
        row = conn.execute(
            "SELECT status, cancel_requested FROM research_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
    return not row or row["status"] == "cancelled" or bool(row["cancel_requested"])


def claim_research_job_sync(job_id: str, db_path: Path | str | None = None) -> dict[str, Any] | None:
    stamp = now_iso()
    with connect_research_db(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE research_jobs
            SET status = 'running', started_at = CASE WHEN started_at = '' THEN ? ELSE started_at END,
                updated_at = ?, finished_at = '', stop_reason = '', error = ''
            WHERE id = ? AND status = 'queued' AND cancel_requested = 0
            """,
            (stamp, stamp, job_id),
        )
        if cursor.rowcount != 1:
            return None
    return get_research_job_sync(job_id, db_path)


def run_research_crawl_sync(
    job_id: str,
    db_path: Path | str | None = None,
    *,
    pages_per_stream: int = XUEQIU_RESEARCH_PAGES_PER_STREAM,
) -> None:
    with RESEARCH_CRAWL_SEMAPHORE:
        _run_research_crawl_unlocked_sync(
            job_id,
            db_path,
            pages_per_stream=pages_per_stream,
        )


def _run_research_crawl_unlocked_sync(
    job_id: str,
    db_path: Path | str | None = None,
    *,
    pages_per_stream: int = XUEQIU_RESEARCH_PAGES_PER_STREAM,
) -> None:
    pages_per_stream = max(1, min(int(pages_per_stream), XUEQIU_RESEARCH_PAGES_PER_STREAM))
    claimed = claim_research_job_sync(job_id, db_path)
    if not claimed:
        return
    influencer = {
        "id": claimed["influencerId"],
        "userId": claimed["userId"],
        "name": claimed["influencerName"],
        "profileUrl": f"https://xueqiu.com/u/{claimed['userId']}",
    }

    session: Any | None = None
    try:
        session = create_xueqiu_session()
        if claimed["mode"] == "full":
            completed = run_full_research_crawl_sync(job_id, influencer, session, db_path, pages_per_stream)
            if job_cancel_requested_sync(job_id, db_path):
                set_research_job_status_sync(job_id, "cancelled", db_path, stop_reason="cancelled_by_user")
            elif completed:
                set_research_job_status_sync(job_id, "ready", db_path, stop_reason="complete")
            else:
                set_research_job_status_sync(job_id, "partial", db_path, stop_reason="batch_limit")
        else:
            completed = run_incremental_research_crawl_sync(job_id, influencer, session, db_path, pages_per_stream)
            if job_cancel_requested_sync(job_id, db_path):
                set_research_job_status_sync(job_id, "cancelled", db_path, stop_reason="cancelled_by_user")
            elif completed:
                set_research_job_status_sync(job_id, "ready", db_path, stop_reason="incremental_complete")
            else:
                set_research_job_status_sync(job_id, "partial", db_path, stop_reason="batch_limit")
    except Exception as error:
        message = normalize_error(error)
        current = get_research_job_sync(job_id, db_path)
        if job_cancel_requested_sync(job_id, db_path):
            set_research_job_status_sync(job_id, "cancelled", db_path, stop_reason="cancelled_by_user")
        elif is_xueqiu_auth_error(message):
            set_research_job_status_sync(job_id, "paused_auth", db_path, stop_reason="auth_required", error=message)
        elif current["pagesFetched"] > 0:
            set_research_job_status_sync(job_id, "partial", db_path, stop_reason="source_error", error=message)
        else:
            set_research_job_status_sync(job_id, "failed", db_path, stop_reason="source_error", error=message)
    finally:
        close_session = getattr(session, "close", None)
        if callable(close_session):
            try:
                close_session()
            except Exception as error:
                LOGGER.warning("关闭雪球研究请求会话失败：%s", normalize_error(error))


def run_full_research_crawl_sync(
    job_id: str,
    influencer: dict[str, Any],
    session: Any,
    db_path: Path | str | None,
    pages_per_stream: int,
) -> bool:
    all_complete = True
    for stream in XUEQIU_RESEARCH_STREAMS:
        cursor = get_research_cursor_sync(influencer["id"], stream, db_path)
        if cursor["complete"]:
            continue
        stream_complete = False
        all_complete = False
        next_page = int(cursor["nextPage"])
        overlap_page = next_page - 1 if next_page > 1 else None
        page = overlap_page or next_page
        previous_signature = cursor["lastSignature"]
        seen_signatures: set[str] = set()

        for _ in range(pages_per_stream):
            if job_cancel_requested_sync(job_id, db_path):
                return False
            rows = fetch_research_page(session, stream, influencer, page)
            activities = normalize_research_items(rows, influencer)
            signature = page_signature(activities, rows)

            if overlap_page is not None and page == overlap_page and signature == previous_signature:
                page = next_page
                time.sleep(XUEQIU_RESEARCH_REQUEST_DELAY_SECONDS)
                continue

            if signature and (signature == previous_signature or signature in seen_signatures):
                mark_research_cursor_complete_sync(influencer["id"], stream, page, signature, db_path)
                stream_complete = True
                break
            seen_signatures.add(signature)

            short_page = len(rows) < XUEQIU_RESEARCH_PAGE_SIZE
            save_research_page_sync(
                job_id,
                influencer,
                stream,
                page,
                rows,
                activities,
                signature,
                short_page,
                db_path,
                update_cursor=True,
            )
            previous_signature = signature
            if short_page:
                stream_complete = True
                break
            page += 1
            time.sleep(XUEQIU_RESEARCH_REQUEST_DELAY_SECONDS)

        if not stream_complete:
            all_complete = False

    if all_complete:
        return True
    return all(get_research_cursor_sync(influencer["id"], stream, db_path)["complete"] for stream in XUEQIU_RESEARCH_STREAMS)


def run_incremental_research_crawl_sync(
    job_id: str,
    influencer: dict[str, Any],
    session: Any,
    db_path: Path | str | None,
    pages_per_stream: int,
) -> bool:
    all_complete = True
    for stream in XUEQIU_RESEARCH_STREAMS:
        stream_complete = False
        seen_signatures: set[str] = set()
        for page in range(1, pages_per_stream + 1):
            if job_cancel_requested_sync(job_id, db_path):
                return False
            rows = fetch_research_page(session, stream, influencer, page)
            activities = normalize_research_items(rows, influencer)
            signature = page_signature(activities, rows)
            if signature and signature in seen_signatures:
                stream_complete = True
                break
            seen_signatures.add(signature)
            new_count = save_research_page_sync(
                job_id,
                influencer,
                stream,
                page,
                rows,
                activities,
                signature,
                False,
                db_path,
                update_cursor=False,
            )
            if len(rows) < XUEQIU_RESEARCH_PAGE_SIZE or new_count == 0:
                stream_complete = True
                break
            time.sleep(XUEQIU_RESEARCH_REQUEST_DELAY_SECONDS)
        if not stream_complete:
            all_complete = False
    return all_complete


def get_research_profile_sync(
    influencer_id: str,
    db_path: Path | str | None = None,
    *,
    profile_hint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ensure_research_db(db_path)
    wanted = normalize_text(influencer_id)
    current_profiles = {item["id"]: influencer_public_fields(item) for item in load_influencers_config()}
    profile = profile_hint or current_profiles.get(wanted) or {}

    with connect_research_db(db_path) as conn:
        aggregate = conn.execute(
            """
            SELECT COUNT(*) AS item_count,
                   SUM(CASE WHEN kind = 'post' THEN 1 ELSE 0 END) AS post_count,
                   SUM(CASE WHEN kind = 'comment' THEN 1 ELSE 0 END) AS comment_count,
                   SUM(CASE WHEN kind = 'reply' THEN 1 ELSE 0 END) AS reply_count,
                   SUM(CASE WHEN kind = 'repost' THEN 1 ELSE 0 END) AS repost_count,
                   MIN(NULLIF(published_at, '')) AS earliest_at,
                   MAX(NULLIF(published_at, '')) AS latest_at,
                   MAX(influencer_name) AS influencer_name,
                   MAX(user_id) AS user_id,
                   MAX(profile_url) AS profile_url
            FROM research_items WHERE influencer_id = ?
            """,
            (wanted,),
        ).fetchone()
        cursors = conn.execute(
            "SELECT * FROM research_cursors WHERE influencer_id = ? ORDER BY stream",
            (wanted,),
        ).fetchall()
        latest_job = conn.execute(
            "SELECT * FROM research_jobs WHERE influencer_id = ? ORDER BY created_at DESC LIMIT 1",
            (wanted,),
        ).fetchone()
        if not profile and latest_job:
            profile = {
                "id": wanted,
                "userId": latest_job["user_id"],
                "name": latest_job["influencer_name"],
                "profileUrl": f"https://xueqiu.com/u/{latest_job['user_id']}",
            }
        if not profile and aggregate["item_count"]:
            profile = {
                "id": wanted,
                "userId": aggregate["user_id"],
                "name": aggregate["influencer_name"],
                "profileUrl": aggregate["profile_url"],
            }

    complete = len(cursors) == 2 and all(bool(row["complete"]) for row in cursors)
    item_count = int(aggregate["item_count"] or 0)
    latest_job_public = job_row_to_public(latest_job) if latest_job else None
    attention_states = {"paused_auth", "failed", "interrupted", "cancelled"}
    if latest_job_public and (
        latest_job_public["active"]
        or (not complete and latest_job_public["status"] in attention_states)
    ):
        state = latest_job_public["status"]
    else:
        state = "ready" if complete else "partial" if item_count else "not_started"
    return {
        **profile,
        "id": profile.get("id") or wanted,
        "imported": wanted in current_profiles,
        "itemCount": item_count,
        "postCount": int(aggregate["post_count"] or 0),
        "commentCount": int(aggregate["comment_count"] or 0),
        "replyCount": int(aggregate["reply_count"] or 0),
        "repostCount": int(aggregate["repost_count"] or 0),
        "earliestAt": aggregate["earliest_at"] or "",
        "latestAt": aggregate["latest_at"] or "",
        "coverageComplete": complete,
        "state": state,
        "cursors": [
            {
                "stream": row["stream"],
                "nextPage": row["next_page"],
                "complete": bool(row["complete"]),
                "updatedAt": row["updated_at"],
            }
            for row in cursors
        ],
        "latestJob": latest_job_public,
        "canContinue": bool(item_count and not complete),
    }


def list_research_profiles_sync(db_path: Path | str | None = None) -> list[dict[str, Any]]:
    ensure_research_db(db_path)
    profiles: dict[str, dict[str, Any]] = {
        item["id"]: influencer_public_fields(item) for item in load_influencers_config()
    }
    with connect_research_db(db_path) as conn:
        rows = conn.execute(
            """
            SELECT influencer_id, MAX(user_id) AS user_id, MAX(influencer_name) AS influencer_name
            FROM (
                SELECT influencer_id, user_id, influencer_name FROM research_items
                UNION ALL
                SELECT influencer_id, user_id, influencer_name FROM research_jobs
            )
            GROUP BY influencer_id
            """
        ).fetchall()
    for row in rows:
        profiles.setdefault(
            row["influencer_id"],
            {
                "id": row["influencer_id"],
                "userId": row["user_id"],
                "name": row["influencer_name"],
                "profileUrl": f"https://xueqiu.com/u/{row['user_id']}",
            },
        )
    return [
        get_research_profile_sync(profile_id, db_path, profile_hint=profile)
        for profile_id, profile in profiles.items()
    ]


def get_research_overview_sync(db_path: Path | str | None = None) -> dict[str, Any]:
    profiles = list_research_profiles_sync(db_path)
    active_jobs = [
        profile["latestJob"]
        for profile in profiles
        if (profile.get("latestJob") or {}).get("active")
    ]
    return {
        "generatedAt": now_iso(),
        "profiles": profiles,
        "jobs": active_jobs,
        "summary": {
            "profileCount": len(profiles),
            "indexedProfileCount": sum(1 for profile in profiles if profile["itemCount"]),
            "itemCount": sum(profile["itemCount"] for profile in profiles),
            "activeJobCount": len(active_jobs),
        },
    }


def item_row_to_public(row: sqlite3.Row, *, score: float | None = None) -> dict[str, Any]:
    try:
        media = json.loads(row["media_json"] or "[]")
    except json.JSONDecodeError:
        media = []
    result = {
        "itemId": row["id"],
        "influencerId": row["influencer_id"],
        "userId": row["user_id"],
        "influencer": row["influencer_name"],
        "kind": row["kind"],
        "publishedAt": row["published_at"],
        "text": row["text"],
        "targetTitle": row["target_title"],
        "originalUrl": row["original_url"],
        "profileUrl": row["profile_url"],
        "media": media if isinstance(media, list) else [],
        "source": row["source"],
        "replyCount": row["reply_count"],
        "retweetCount": row["retweet_count"],
        "likeCount": row["like_count"],
        "untrustedEvidence": True,
    }
    if score is not None:
        result["score"] = score
    return result


def build_fts_query(query: str) -> str:
    raw_parts = re.findall(
        r"\d{4}年|[A-Za-z0-9][A-Za-z0-9._%+-]*|[\u4e00-\u9fff]+",
        query,
    )
    terms: list[str] = []
    seen: set[str] = set()
    chinese_breaks = re.compile(
        r"(?:请问|麻烦|能否|可以|以及|分别|是多少|多少|什么|如何|怎么|为何|为什么|大概|一下|[和与及的呀吗呢])"
    )
    for raw_part in raw_parts:
        parts = chinese_breaks.split(raw_part) if re.fullmatch(r"[\u4e00-\u9fff]+", raw_part) else [raw_part]
        for part in parts:
            normalized = normalize_text(part).strip("_-+.%")
            key = normalized.casefold()
            if len(normalized) < 3 or key in seen:
                continue
            seen.add(key)
            terms.append(normalized)
    return " OR ".join(
        f'"{term.replace(chr(34), chr(34) * 2)}"'
        for term in terms[:8]
    )


def search_research_evidence_sync(
    query: str,
    *,
    influencer_id: str = "",
    kind: str = "",
    limit: int = 20,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    normalized_query = normalize_text(query)
    if not normalized_query:
        raise ValueError("搜索词不能为空")
    if len(normalized_query) > 200:
        raise ValueError("搜索词不能超过 200 个字符")
    if not 1 <= int(limit) <= 50:
        raise ValueError("limit 必须在 1 到 50 之间")
    normalized_kind = normalize_text(kind).lower()
    if normalized_kind and normalized_kind not in XUEQIU_RESEARCH_KINDS:
        raise ValueError("kind 必须是 post/comment/reply/repost")
    ensure_research_db(db_path)

    filters: list[str] = []
    filter_params: list[Any] = []
    if influencer_id:
        filters.append("i.influencer_id = ?")
        filter_params.append(normalize_text(influencer_id))
    if normalized_kind:
        filters.append("i.kind = ?")
        filter_params.append(normalized_kind)
    where_suffix = f" AND {' AND '.join(filters)}" if filters else ""
    fts_query = build_fts_query(normalized_query)

    with connect_research_db(db_path) as conn:
        if fts_query:
            rows = conn.execute(
                f"""
                SELECT i.*, -bm25(research_items_fts) AS relevance
                FROM research_items_fts
                JOIN research_items i ON i.id = research_items_fts.item_id
                WHERE research_items_fts MATCH ?{where_suffix}
                ORDER BY bm25(research_items_fts), i.published_at DESC
                LIMIT ?
                """,
                [fts_query, *filter_params, int(limit)],
            ).fetchall()
        else:
            like = f"%{normalized_query}%"
            rows = conn.execute(
                f"""
                SELECT i.*, 1.0 AS relevance
                FROM research_items i
                WHERE (i.text LIKE ? OR i.target_title LIKE ?){where_suffix}
                ORDER BY i.published_at DESC
                LIMIT ?
                """,
                [like, like, *filter_params, int(limit)],
            ).fetchall()
    items = [item_row_to_public(row, score=float(row["relevance"] or 0.0)) for row in rows]
    return {
        "query": normalized_query,
        "count": len(items),
        "items": items,
        "untrustedEvidence": True,
    }


def get_research_item_sync(item_id: str, db_path: Path | str | None = None) -> dict[str, Any]:
    ensure_research_db(db_path)
    with connect_research_db(db_path) as conn:
        row = conn.execute("SELECT * FROM research_items WHERE id = ?", (normalize_text(item_id),)).fetchone()
    if not row:
        raise ValueError(f"未找到研究语料：{item_id}")
    return item_row_to_public(row)


async def start_research_crawl(influencer_id: str, mode: str = "full") -> dict[str, Any]:
    async with RESEARCH_TASK_LOCK:
        job = await asyncio.to_thread(create_research_job_sync, influencer_id, mode)
        created = bool(job.pop("_created", False))
        if created and job["status"] == "queued":
            task = asyncio.create_task(asyncio.to_thread(run_research_crawl_sync, job["id"]))
            RESEARCH_TASKS[job["id"]] = task

            def discard_task(_task: asyncio.Task[None], job_id: str = job["id"]) -> None:
                RESEARCH_TASKS.pop(job_id, None)

            task.add_done_callback(discard_task)
        return job


async def get_research_overview() -> dict[str, Any]:
    return await asyncio.to_thread(get_research_overview_sync)


async def get_research_job(job_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(get_research_job_sync, job_id)


async def cancel_research_job(job_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(cancel_research_job_sync, job_id)


async def search_research_evidence(
    query: str,
    *,
    influencer_id: str = "",
    kind: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        search_research_evidence_sync,
        query,
        influencer_id=influencer_id,
        kind=kind,
        limit=limit,
    )


async def get_research_item(item_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(get_research_item_sync, item_id)
