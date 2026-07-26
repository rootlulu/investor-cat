from concurrent.futures import ThreadPoolExecutor
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src import xueqiu_research_service as research
from src.xueqiu_service import XueqiuApiError


INFLUENCER = {
    "id": "user-10001",
    "userId": "10001",
    "name": "游戏研究员",
    "profileUrl": "https://xueqiu.com/u/10001",
}


def make_rows(stream: str, page: int, count: int) -> list[dict]:
    rows = []
    for index in range(count):
        source_id = f"{stream}-{page}-{index}"
        row = {
            "id": source_id,
            "text": f"2026年心动小镇 {stream} 第{page}页第{index}条 PC 40 移动端 60",
            "created_at": 1784995200000 - (page * 1000 + index),
            "user": {"id": "10001"},
        }
        if stream == "comments":
            row["comment_id"] = source_id
            row["type"] = "comment"
            row["status_id"] = f"status-{page}-{index}"
        rows.append(row)
    return rows


class XueqiuResearchStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "research.sqlite"
        research.ensure_research_db(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_full_crawl_persists_cursor_and_resumes(self) -> None:
        def fetch_page(_session, stream, _influencer, page):
            return make_rows(stream, page, 20 if page == 1 else 1 if page == 2 else 0)

        with (
            patch.object(research, "load_influencers_config", return_value=[INFLUENCER]),
            patch.object(research, "create_xueqiu_session", return_value=object()),
            patch.object(research, "fetch_research_page", side_effect=fetch_page),
            patch.object(research.time, "sleep"),
        ):
            first = research.create_research_job_sync("user-10001", "full", self.db_path)
            research.run_research_crawl_sync(first["id"], self.db_path, pages_per_stream=1)
            first_done = research.get_research_job_sync(first["id"], self.db_path)
            self.assertEqual(first_done["status"], "partial")
            self.assertFalse(research.get_research_profile_sync("user-10001", self.db_path)["coverageComplete"])

            second = research.create_research_job_sync("user-10001", "full", self.db_path)
            research.run_research_crawl_sync(second["id"], self.db_path, pages_per_stream=3)

        second_done = research.get_research_job_sync(second["id"], self.db_path)
        profile = research.get_research_profile_sync("user-10001", self.db_path)
        self.assertEqual(second_done["status"], "ready")
        self.assertTrue(profile["coverageComplete"])
        self.assertEqual(profile["itemCount"], 42)
        self.assertEqual(profile["postCount"], 21)
        self.assertEqual(profile["commentCount"], 21)

    def test_duplicate_rows_do_not_grow_item_count(self) -> None:
        def fetch_page(_session, stream, _influencer, page):
            return make_rows(stream, page, 2) if page == 1 else []

        with (
            patch.object(research, "load_influencers_config", return_value=[INFLUENCER]),
            patch.object(research, "create_xueqiu_session", return_value=object()),
            patch.object(research, "fetch_research_page", side_effect=fetch_page),
            patch.object(research.time, "sleep"),
        ):
            full = research.create_research_job_sync("user-10001", "full", self.db_path)
            research.run_research_crawl_sync(full["id"], self.db_path)
            before = research.get_research_profile_sync("user-10001", self.db_path)["itemCount"]
            incremental = research.create_research_job_sync("user-10001", "incremental", self.db_path)
            research.run_research_crawl_sync(incremental["id"], self.db_path)

        after = research.get_research_profile_sync("user-10001", self.db_path)["itemCount"]
        self.assertEqual(before, 4)
        self.assertEqual(after, before)

    def test_auth_error_pauses_without_losing_progress(self) -> None:
        calls = 0

        def fetch_page(_session, stream, _influencer, page):
            nonlocal calls
            calls += 1
            if calls == 1:
                return make_rows(stream, page, 2)
            raise XueqiuApiError("login required")

        with (
            patch.object(research, "load_influencers_config", return_value=[INFLUENCER]),
            patch.object(research, "create_xueqiu_session", return_value=object()),
            patch.object(research, "fetch_research_page", side_effect=fetch_page),
            patch.object(research.time, "sleep"),
        ):
            job = research.create_research_job_sync("user-10001", "full", self.db_path)
            research.run_research_crawl_sync(job["id"], self.db_path)

        paused = research.get_research_job_sync(job["id"], self.db_path)
        profile = research.get_research_profile_sync("user-10001", self.db_path)
        self.assertEqual(paused["status"], "paused_auth")
        self.assertGreaterEqual(profile["itemCount"], 2)
        self.assertFalse(profile["coverageComplete"])
        self.assertEqual(profile["state"], "paused_auth")

    def test_cancel_preserves_items_and_cursor(self) -> None:
        with patch.object(research, "load_influencers_config", return_value=[INFLUENCER]):
            job = research.create_research_job_sync("user-10001", "full", self.db_path)
            research.cancel_research_job_sync(job["id"], self.db_path)
            research.run_research_crawl_sync(job["id"], self.db_path)

        cancelled = research.get_research_job_sync(job["id"], self.db_path)
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(research.get_research_profile_sync("user-10001", self.db_path)["itemCount"], 0)

    def test_only_one_active_job_per_influencer(self) -> None:
        with patch.object(research, "load_influencers_config", return_value=[INFLUENCER]):
            first = research.create_research_job_sync("user-10001", "full", self.db_path)
            second = research.create_research_job_sync("user-10001", "incremental", self.db_path)

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["status"], "queued")

    def test_search_returns_citable_evidence_and_validates_limit(self) -> None:
        def fetch_page(_session, stream, _influencer, page):
            return make_rows(stream, page, 2) if page == 1 else []

        with (
            patch.object(research, "load_influencers_config", return_value=[INFLUENCER]),
            patch.object(research, "create_xueqiu_session", return_value=object()),
            patch.object(research, "fetch_research_page", side_effect=fetch_page),
            patch.object(research.time, "sleep"),
        ):
            job = research.create_research_job_sync("user-10001", "full", self.db_path)
            research.run_research_crawl_sync(job["id"], self.db_path)

        result = research.search_research_evidence_sync(
            "心动小镇",
            influencer_id="user-10001",
            kind="post",
            limit=10,
            db_path=self.db_path,
        )
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["items"][0]["influencer"], "游戏研究员")
        self.assertIn("originalUrl", result["items"][0])
        self.assertIn("media", result["items"][0])
        with self.assertRaises(ValueError):
            research.search_research_evidence_sync("心动小镇", limit=51, db_path=self.db_path)

        natural_query = research.search_research_evidence_sync(
            "2026年心动小镇PC和移动端流水占比分别是多少呀",
            influencer_id="user-10001",
            limit=10,
            db_path=self.db_path,
        )
        self.assertEqual(natural_query["count"], 4)
        fts_query = research.build_fts_query("2026年心动小镇PC和移动端流水占比分别是多少呀")
        self.assertIn('"2026年"', fts_query)
        self.assertIn('"心动小镇"', fts_query)
        self.assertIn('"移动端流水占比"', fts_query)

    def test_session_is_closed_and_cancel_wins_over_auth_error(self) -> None:
        class Session:
            closed = False

            def close(self) -> None:
                self.closed = True

        session = Session()

        def cancel_then_fail(_session, _stream, _influencer, _page):
            research.cancel_research_job_sync(job["id"], self.db_path)
            raise XueqiuApiError("login required")

        with (
            patch.object(research, "load_influencers_config", return_value=[INFLUENCER]),
            patch.object(research, "create_xueqiu_session", return_value=session),
            patch.object(research, "fetch_research_page", side_effect=cancel_then_fail),
        ):
            job = research.create_research_job_sync("user-10001", "full", self.db_path)
            research.run_research_crawl_sync(job["id"], self.db_path)

        self.assertTrue(session.closed)
        self.assertEqual(research.get_research_job_sync(job["id"], self.db_path)["status"], "cancelled")

    def test_recover_marks_running_jobs_interrupted(self) -> None:
        with patch.object(research, "load_influencers_config", return_value=[INFLUENCER]):
            job = research.create_research_job_sync("user-10001", "full", self.db_path)
        research.set_research_job_status_sync(job["id"], "running", self.db_path)

        research.recover_interrupted_jobs(self.db_path)

        recovered = research.get_research_job_sync(job["id"], self.db_path)
        self.assertEqual(recovered["status"], "interrupted")
        self.assertEqual(recovered["stopReason"], "service_restart")

    def test_research_crawls_are_globally_single_flight(self) -> None:
        active = 0
        max_active = 0
        state_lock = threading.Lock()

        def run_unlocked(*_args, **_kwargs) -> None:
            nonlocal active, max_active
            with state_lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.05)
            with state_lock:
                active -= 1

        with patch.object(
            research,
            "_run_research_crawl_unlocked_sync",
            side_effect=run_unlocked,
        ) as run:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(research.run_research_crawl_sync, f"job-{index}")
                    for index in range(2)
                ]
                for future in futures:
                    future.result(timeout=1)

        self.assertEqual(run.call_count, 2)
        self.assertEqual(max_active, 1)


if __name__ == "__main__":
    unittest.main()
