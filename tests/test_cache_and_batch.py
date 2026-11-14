import json
import time
from types import SimpleNamespace

import pytest

from anime_hook import mcp_server
from anime_hook.cache import DiskCache


def test_disk_cache_hit_and_miss(tmp_path):
    cache = DiskCache(tmp_path)
    assert cache.get("missing") is None
    cache.set("key", {"value": 42})
    assert cache.get("key") == {"value": 42}


def test_disk_cache_ttl_expiration(tmp_path):
    cache = DiskCache(tmp_path, ttl_seconds=0.01)
    cache.set("key", "value")
    time.sleep(0.02)
    assert cache.get("key") is None


def test_disk_cache_corrupt_json_recovery(tmp_path):
    cache = DiskCache(tmp_path)
    path = cache._path_for("key")
    tmp_path.mkdir(exist_ok=True)
    path.write_text("{invalid", encoding="utf-8")
    assert cache.get("key") is None
    assert not path.exists()


@pytest.mark.asyncio
async def test_batch_filter_results_and_error_isolation(monkeypatch):
    class FakeClient:
        def __init__(self, proxy=None):
            self.proxy = proxy

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    class FakeRecommender:
        def __init__(self, client):
            self.analyzer = SimpleNamespace(
                analyze=lambda bundle: SimpleNamespace(
                    as_summary=lambda: {"hook_velocity_index": bundle},
                    warnings=[],
                )
            )

        async def resolve(self, title):
            if title == "broken":
                raise RuntimeError("lookup failed")
            return SimpleNamespace(
                title=SimpleNamespace(display=title),
                id=title,
                id_source="fake",
            )

        async def collect_evidence(self, profile, review_limit):
            return {"Fast": 90.0, "Slow": 40.0}[profile.title.display]

    monkeypatch.setattr(mcp_server, "AsyncAPIClient", FakeClient)
    monkeypatch.setattr(mcp_server, "Recommender", FakeRecommender)

    result = json.loads(
        await mcp_server.anime_batch_filter(
            ["Fast", "Slow", "broken"],
            min_hvi=60,
        )
    )
    assert [item["query"] for item in result["passed"]] == ["Fast"]
    assert [item["query"] for item in result["filtered_out"]] == ["Slow"]
    assert result["error_count"] == 1
    assert result["errors"][0]["error"] == "lookup failed"


@pytest.mark.asyncio
async def test_batch_filter_rejects_nan():
    with pytest.raises(ValueError, match="finite"):
        await mcp_server.anime_batch_filter(["Title"], min_hvi=float("nan"))
