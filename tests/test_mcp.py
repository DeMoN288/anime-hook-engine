import pytest
from anime_hook.mcp_server import anime_analyze_hook, anime_recommend_fast_paced

@pytest.mark.asyncio
async def test_mcp_anime_analyze_hook():
    res = await anime_analyze_hook("Sword Art Online", review_limit=3)
    assert "title" in res
    assert "hook_velocity_index" in res

@pytest.mark.asyncio
async def test_mcp_anime_recommend():
    res = await anime_recommend_fast_paced("Solo Leveling", limit=2)
    assert "seed_title" in res
    assert "recommendations" in res
