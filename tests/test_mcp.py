import json
from unittest.mock import AsyncMock, patch

import pytest

from anime_hook.mcp_server import anime_analyze_hook, anime_recommend_fast_paced
from anime_hook.models import (
    EvidenceBundle,
    HookReport,
    LocalizedTitle,
    Recommendation,
    RecommendationResult,
    Review,
    TitleProfile,
)


@pytest.mark.asyncio
async def test_mcp_anime_analyze_hook():
    profile = TitleProfile(
        id=11757,
        title=LocalizedTitle(ru="Мастера Меча Онлайн", en="Sword Art Online"),
        score=7.23,
        episodes=25,
        genres=["Action", "Fantasy"],
    )
    bundle = EvidenceBundle(
        profile=profile,
        reviews=[Review(text="Hooked from the first episode!", source="anilist", id="1")],
    )
    with (
        patch("anime_hook.mcp_server.Recommender.resolve", AsyncMock(return_value=profile)),
        patch(
            "anime_hook.mcp_server.Recommender.collect_evidence",
            AsyncMock(return_value=bundle),
        ),
    ):
        raw = await anime_analyze_hook("Sword Art Online", review_limit=3)

    data = json.loads(raw)
    assert data["title"] == "Мастера Меча Онлайн"
    assert data["hook_velocity_index"] >= 60
    assert data["pacing_type"] == "INSTANT_HOOK"


@pytest.mark.asyncio
async def test_mcp_anime_recommend():
    seed = TitleProfile(id=1, title=LocalizedTitle(en="Solo Leveling"), genres=["Action"])
    cand = TitleProfile(
        id=2,
        id_source="anilist",
        title=LocalizedTitle(en="Test Action"),
        genres=["Action"],
    )
    report = HookReport(
        hvi=80.0,
        drama_score=60.0,
        pacing_type="INSTANT_HOOK",
        verdict="MUST_WATCH",
    )
    result = RecommendationResult(
        seed=seed,
        items=[Recommendation(profile=cand, report=report, rank_score=80.0, similarity=1.0)],
        candidates_checked=1,
    )
    with patch("anime_hook.mcp_server.Recommender.recommend", AsyncMock(return_value=result)):
        raw = await anime_recommend_fast_paced("Solo Leveling", limit=2)

    data = json.loads(raw)
    assert data["seed_title"] == "Solo Leveling"
    assert len(data["recommendations"]) == 1
    assert data["recommendations"][0]["verdict"] == "MUST_WATCH"
