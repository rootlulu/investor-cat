from pathlib import Path
import json


def test_start_scripts_live_under_scripts_and_resolve_repository_root():
    for name in ("dev.sh", "start.sh", "start-dev.sh", "start-news-digest-web.sh"):
        script = Path("scripts", name).read_text(encoding="utf-8")

        assert 'ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"' in script
        assert 'cd "$ROOT_DIR"' in script


def test_v39_uvicorn_reload_watches_source_only():
    script = Path("scripts/start-dev.sh").read_text(encoding="utf-8")

    assert "--reload-dir src" in script
    assert "--reload-dir ." not in script


def test_v70_development_servers_bind_loopback_by_default():
    script = Path("scripts/start-dev.sh").read_text(encoding="utf-8")
    vite_config = Path("vite.config.js").read_text(encoding="utf-8")
    package = json.loads(Path("package.json").read_text(encoding="utf-8"))

    assert 'HOST="${HOST:-127.0.0.1}"' in script
    assert 'process.env.NEWS_DIGEST_HOST || "127.0.0.1"' in vite_config
    assert "--host 127.0.0.1" in package["scripts"]["preview"]


def test_v70_vite_forwards_original_client_address_to_write_guard():
    vite_config = Path("vite.config.js").read_text(encoding="utf-8")

    assert "xfwd: true" in vite_config
