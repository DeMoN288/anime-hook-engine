"""Anime Hook & Drama Intelligence Engine MCP Server.

Provides tools for AI agents to analyze anime opening pacing, Hook Velocity Index (HVI),
DramaScore, and fetch fast-paced recommendations.
"""
from __future__ import annotations

import asyncio
import json
import math

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


@mcp.tool()
async def anime_resolve_title(
    title: str,
    proxy: str | None = None,
) -> str:
    """Resolve an anime title or ID into canonical metadata without review scraping.

    Args:
        title: Anime title in English/Russian or MAL/Shikimori ID.
        proxy: Optional HTTP/SOCKS5 proxy URL. Defaults to ANIME_HOOK_PROXY when unset.
    """
    if not title.strip():
        raise ValueError("title must be non-empty")
    async with AsyncAPIClient(proxy=proxy) as client:
        rec = Recommender(client)
        profile = await rec.resolve(title)
        return json.dumps(
            {
                "title": profile.title.display,
                "id": profile.id,
                "id_source": profile.id_source,
                "score": profile.score,
                "episodes": profile.episodes,
                "genres": profile.genres,
                "synopsis": profile.synopsis,
            },
            indent=2,
            ensure_ascii=False,
        )


@mcp.tool()
async def anime_compare_hooks(
    titles: list[str],
    review_limit: int = 10,
    proxy: str | None = None,
) -> str:
    """Compare 2-5 anime titles side-by-side by Hook Velocity Index (HVI).

    Args:
        titles: List of 2-5 anime titles or IDs to compare.
        review_limit: Maximum reviews to analyze per title (1-30, default 10).
        proxy: Optional HTTP/SOCKS5 proxy URL. Defaults to ANIME_HOOK_PROXY when unset.
    """
    if not 1 <= review_limit <= 30:
        raise ValueError("review_limit must be between 1 and 30")
    cleaned = [t.strip() for t in titles if t.strip()]
    if not 2 <= len(cleaned) <= 5:
        raise ValueError("titles must contain between 2 and 5 non-empty entries")

    results: list[dict[str, object]] = []
    async with AsyncAPIClient(proxy=proxy) as client:
        rec = Recommender(client)
        for query in cleaned:
            profile = await rec.resolve(query)
            bundle = await rec.collect_evidence(profile, review_limit=review_limit)
            report = rec.analyzer.analyze(bundle)
            results.append(
                {
                    "query": query,
                    "title": profile.title.display,
                    "id": f"{profile.id_source}:{profile.id}",
                    **report.as_summary(),
                    "warnings": report.warnings,
                }
            )

    results.sort(key=lambda r: float(r.get("hook_velocity_index", 0.0)), reverse=True)
    return json.dumps({"comparison": results}, indent=2, ensure_ascii=False)


@mcp.tool()
async def anime_batch_filter(
    titles: list[str],
    min_hvi: float = 60.0,
    review_limit: int = 10,
    proxy: str | None = None,
) -> str:
    """Filter 1-10 anime titles by minimum Hook Velocity Index with per-item error isolation.

    Args:
        titles: List of 1-10 anime titles or IDs to evaluate.
        min_hvi: Minimum acceptable Hook Velocity Index (0-100, default 60.0).
        review_limit: Maximum reviews to analyze per title (1-30, default 10).
        proxy: Optional HTTP/SOCKS5 proxy URL. Defaults to ANIME_HOOK_PROXY when unset.
    """
    if not math.isfinite(min_hvi) or not 0.0 <= min_hvi <= 100.0:
        raise ValueError("min_hvi must be a finite number between 0 and 100")
    if not 1 <= review_limit <= 30:
        raise ValueError("review_limit must be between 1 and 30")
    cleaned = [t.strip() for t in titles if t.strip()]
    if not 1 <= len(cleaned) <= 10:
        raise ValueError("titles must contain between 1 and 10 non-empty entries")

    sem = asyncio.Semaphore(3)
    passed: list[dict[str, object]] = []
    filtered_out: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []

    async with AsyncAPIClient(proxy=proxy) as client:
        rec = Recommender(client)

        async def _eval(query: str) -> None:
            async with sem:
                try:
                    profile = await rec.resolve(query)
                    bundle = await rec.collect_evidence(profile, review_limit=review_limit)
                    report = rec.analyzer.analyze(bundle)
                    summary = report.as_summary()
                    hvi = float(summary.get("hook_velocity_index", 0.0))
                    entry: dict[str, object] = {
                        "query": query,
                        "title": profile.title.display,
                        "id": f"{profile.id_source}:{profile.id}",
                        **summary,
                        "warnings": report.warnings,
                    }
                    if hvi >= min_hvi:
                        passed.append(entry)
                    else:
                        filtered_out.append(entry)
                except Exception as exc:  # noqa: BLE001 - isolate per-item failure
                    errors.append({"query": query, "error": str(exc)})

        await asyncio.gather(*(_eval(q) for q in cleaned))

    passed.sort(key=lambda r: float(r.get("hook_velocity_index", 0.0)), reverse=True)
    return json.dumps(
        {
            "min_hvi": min_hvi,
            "passed_count": len(passed),
            "filtered_out_count": len(filtered_out),
            "error_count": len(errors),
            "passed": passed,
            "filtered_out": filtered_out,
            "errors": errors,
        },
        indent=2,
        ensure_ascii=False,
    )


def main() -> None:
    """Run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
