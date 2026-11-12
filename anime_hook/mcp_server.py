"""Anime Hook & Drama Intelligence Engine MCP Server.

Provides tools for AI agents to analyze anime opening pacing, Hook Velocity Index (HVI),
DramaScore, and fetch fast-paced recommendations.
"""
from __future__ import annotations

import json

from mcp.server.mcpserver import MCPServer

from .network import AsyncAPIClient
from .recommender import Recommender

mcp = MCPServer("anime-hook-engine")


@mcp.tool()
async def anime_analyze_hook(
    title: str,
    proxy: str | None = None,
    review_limit: int = 15,
) -> str:
    """Analyze the opening pace and emotional hooks of an anime title.

    Calculates:
    - Hook Velocity Index (HVI, 0-100): measures early engagement and speed.
    - DramaScore (0-100): measures emotional stakes (tragedy, betrayal, sacrifice).
    - Pacing Type: (INSTANT_HOOK, STEADY_FAST, SLOW_BURN, DROP_PRONE).
    - Verdict: (MUST_WATCH, GOOD_PACE, AVOID_SLOW_START).

    Args:
        title: Anime title in English/Russian or MAL/Shikimori ID (e.g. "Solo Leveling").
        proxy: Optional HTTP/SOCKS5 proxy URL (defaults to ANIME_HOOK_PROXY / fallback).
        review_limit: Maximum reviews to analyze (default 15).
    """
    async with AsyncAPIClient(proxy=proxy) as client:
        rec = Recommender(client)
        profile = await rec.resolve(title)
        bundle = await rec.collect_evidence(profile, review_limit=review_limit)
        report = rec.analyzer.analyze(bundle)

        res = {
            "title": profile.title.display,
            "id": profile.id,
            "id_source": profile.id_source,
            "score": profile.score,
            "episodes": profile.episodes,
            "genres": profile.genres,
            "hook_velocity_index": report.hvi,
            "drama_score": report.drama_score,
            "pacing_type": report.pacing_type,
            "verdict": report.verdict,
            "confidence": report.confidence,
            "key_cues": report.key_cues,
            "review_snippets": report.review_snippets,
            "components": report.components,
            "warnings": report.warnings,
        }
        return json.dumps(res, indent=2, ensure_ascii=False)


@mcp.tool()
async def anime_recommend_fast_paced(
    seed_title: str,
    limit: int = 5,
    min_hvi: float = 60.0,
    proxy: str | None = None,
) -> str:
    """Recommend similar anime titles with high initial Hook Velocity Index (HVI).

    Filters out slow-burn and drop-prone series, returning high-tempo, action-packed titles.

    Args:
        seed_title: Reference title you liked (e.g. "Solo Leveling", "Attack on Titan").
        limit: Number of recommendations to return (1-10, default 5).
        min_hvi: Minimum acceptable Hook Velocity Index (0-100, default 60.0).
        proxy: Optional HTTP/SOCKS5 proxy URL (defaults to ANIME_HOOK_PROXY / fallback).
    """
    async with AsyncAPIClient(proxy=proxy) as client:
        rec = Recommender(client)
        result = await rec.recommend(
            seed_title,
            limit=min(max(limit, 1), 10),
            candidate_limit=12,
            min_hvi=min_hvi,
            review_limit=5,
        )

        items = []
        for rank, item in enumerate(result.items, 1):
            items.append({
                "rank": rank,
                "title": item.profile.title.display,
                "id": f"{item.profile.id_source}:{item.profile.id}",
                "rank_score": item.rank_score,
                "similarity_pct": round(item.similarity * 100, 1),
                "hvi": item.report.hvi,
                "drama_score": item.report.drama_score,
                "pacing": item.report.pacing_type,
                "verdict": item.report.verdict,
                "genres": item.profile.genres,
                "review_snippets": item.report.review_snippets,
            })

        output = {
            "seed_title": result.seed.title.display,
            "recommendations": items,
            "candidates_checked": result.candidates_checked,
            "warnings": result.warnings,
        }
        return json.dumps(output, indent=2, ensure_ascii=False)


def main() -> None:
    """Run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
