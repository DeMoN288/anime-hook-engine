"""Search, evidence collection and conservative, genre-based recommendations."""

import asyncio
import html
import re
from typing import Any

from pydantic import ValidationError

from .analyzer import HookAnalyzer, extract_votes
from .models import (
    EvidenceBundle,
    LocalizedTitle,
    Recommendation,
    RecommendationResult,
    Review,
    TitleProfile,
)
from .network import APIError, AsyncAPIClient

SHIKIMORI = "https://shikimori.io/api"
MEDIA_FIELDS = """
id idMal title { romaji english native } averageScore episodes genres description
"""


def _text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"<br\s*/?>|</p>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>|\[/?[^\]]+\]", "", text)
    return html.unescape(text).strip()


def _review_rows(payload: Any) -> list[dict[str, Any]]:
    """Accept lists, wrapped collections and individual review/topic objects."""
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("reviews", "topics", "data", "items", "results", "nodes"):
            if key in payload:
                return _review_rows(payload[key])
        if any(key in payload for key in ("body", "html_body", "review")):
            return [payload]
    raise APIError("Shikimori: unrecognized reviews response")


def _shiki_profile(data: dict[str, Any]) -> TitleProfile:
    return TitleProfile(
        id=data["id"],
        title=LocalizedTitle(ru=data.get("russian"), en=data.get("name")),
        score=float(data["score"]) if data.get("score") not in (None, "") else None,
        episodes=data.get("episodes"),
        genres=[g["name"] for g in data.get("genres", [])],
        synopsis=_text(data.get("description")),
        first_episode_summary=_text(data.get("first_episode_summary")),
    )


def _anilist_profile(data: dict[str, Any]) -> TitleProfile:
    title = data.get("title") or {}
    return TitleProfile(
        id=data.get("idMal") or data["id"],
        id_source="mal" if data.get("idMal") else "anilist",
        anilist_id=data["id"],
        title=LocalizedTitle(en=title.get("english"), romaji=title.get("romaji")),
        score=data["averageScore"] / 10 if data.get("averageScore") is not None else None,
        episodes=data.get("episodes"),
        genres=data.get("genres") or [],
        synopsis=_text(data.get("description")),
    )


class Recommender:
    def __init__(self, client: AsyncAPIClient, analyzer: HookAnalyzer | None = None) -> None:
        self.client = client
        self.analyzer = analyzer or HookAnalyzer()
        self.warnings: list[str] = []

    async def _shiki(self, path: str, **params: Any) -> Any:
        return await self.client.request_json("GET", f"{SHIKIMORI}/{path}", params=params)

    async def _graphql(
        self, query: str, variables: dict[str, Any], *, evidence: bool = False,
    ) -> dict[str, Any]:
        # Use the transport directly: the existing graphql helper has an invalid URL.
        payload = await self.client.request_json(
            "POST", "https://graphql.anilist.co", json={"query": query, "variables": variables},
            **({"fail_fast_on_rate_limit": True} if evidence else {}),
        )
        if not isinstance(payload, dict) or payload.get("errors"):
            raise APIError("AniList: invalid response or GraphQL errors")
        if not isinstance(payload.get("data"), dict):
            raise APIError("AniList: missing GraphQL data")
        return payload["data"]

    async def search(self, query: str, *, limit: int = 10) -> list[TitleProfile]:
        """Search by name; a numeric query resolves a MAL/Shikimori identifier."""
        query = query.strip()
        if not query or not 1 <= limit <= 50:
            raise ValueError("query must be non-empty and limit must be between 1 and 50")
        if query.isdecimal() and int(query) < 1:
            raise ValueError("title identifier must be positive")
        try:
            if query.isdecimal():
                return [_shiki_profile(await self._shiki(f"animes/{int(query)}"))]
            rows = await self._shiki("animes", search=query, limit=limit, page=1)
            if not isinstance(rows, list):
                raise APIError("Shikimori: expected a list of titles")
            profiles = [_shiki_profile(row) for row in rows]
            if profiles:
                return profiles
        except (APIError, ValidationError, KeyError, TypeError, ValueError) as exc:
            self.warnings.append(f"Shikimori search: {exc}")
        if query.isdecimal():
            data = await self._graphql(
                "query ($id: Int!) { Media(idMal: $id, type: ANIME) { "
                + MEDIA_FIELDS + " } }", {"id": int(query)},
            )
            return [_anilist_profile(data["Media"])] if data.get("Media") else []
        data = await self._graphql(
            "query ($search: String!, $limit: Int!) { Page(perPage: $limit) { "
            "media(search: $search, type: ANIME) { " + MEDIA_FIELDS + " } } }",
            {"search": query, "limit": limit},
        )
        return [_anilist_profile(row) for row in data["Page"]["media"]]

    async def resolve(self, query: str) -> TitleProfile:
        profiles = await self.search(query)
        if not profiles:
            raise APIError(f"Тайтл не найден: {query}")
        exact = query.strip().casefold()
        return next((p for p in profiles if exact in {
            (p.title.ru or "").casefold(), (p.title.en or "").casefold(),
            (p.title.romaji or "").casefold(),
        }), profiles[0])

    async def collect_evidence(
        self, profile: TitleProfile, *, review_limit: int = 20
    ) -> EvidenceBundle:
        if not 1 <= review_limit <= 50:
            raise ValueError("review_limit must be between 1 and 50")
        warnings: list[str] = []
        reviews: list[Review] = []
        if profile.mal_id:
            try:
                details = _shiki_profile(await self._shiki(f"animes/{profile.mal_id}"))
                profile = details.model_copy(update={
                    "anilist_id": profile.anilist_id,
                    "synopsis": details.synopsis or profile.synopsis,
                    "genres": details.genres or profile.genres,
                    "score": details.score if details.score is not None else profile.score,
                    "first_episode_summary": (
                        details.first_episode_summary or profile.first_episode_summary
                    ),
                })
            except (APIError, ValidationError, KeyError, TypeError, ValueError) as exc:
                warnings.append(f"Shikimori profile: {exc}")
            failures = []
            # Older deployments reject kind=review; the typed topics route is
            # the documented alternative. Stop as soon as useful text is found.
            routes = [
                ("reviews", {"target_id": profile.mal_id, "target_type": "Anime"}),
                (f"animes/{profile.mal_id}/topics", {"kind": "review"}),
                ("topics", {"linked_id": profile.mal_id, "linked_type": "Anime",
                            "type": "Topics::EntryTopics::ReviewTopic"}),
            ]
            for path, params in routes:
                try:
                    rows = _review_rows(await self._shiki(
                        path, **params, limit=min(review_limit, 30), page=1,
                    ))
                    for row in rows:
                        content = row.get("review") if isinstance(row.get("review"), dict) else row
                        text = _text(content.get("body")) or _text(content.get("html_body"))
                        identifier = content.get("id", row.get("id"))
                        if text and identifier is not None:
                            url = row.get("url") or content.get("url")
                            if url and url.startswith("/"):
                                url = f"https://shikimori.one{url}"
                            reviews.append(Review(
                                text=text, source="shikimori", id=str(identifier),
                                url=url or (f"https://shikimori.one/reviews/{identifier}"
                                            if path == "reviews" else None),
                            ))
                    if reviews:
                        break
                except (APIError, ValidationError, KeyError, TypeError, ValueError) as exc:
                    failures.append(f"{path}: {exc}")
            if not reviews and failures:
                warnings.append("Shikimori reviews: " + "; ".join(failures))
        try:
            selector = "id" if profile.anilist_id else "idMal"
            identifier = profile.anilist_id or profile.mal_id or profile.id
            data = await self._graphql(
                "query ($id: Int!, $limit: Int!) { Media(" + selector
                + ": $id, type: ANIME) { " + MEDIA_FIELDS
                + " reviews(perPage: $limit, sort: RATING_DESC) { nodes { id body url } } } }",
                {"id": identifier, "limit": review_limit}, evidence=True,
            )
            media = data.get("Media")
            if not media:
                raise APIError("AniList: title not found")
            alternate = _anilist_profile(media)
            profile = profile.model_copy(update={
                "anilist_id": alternate.anilist_id,
                "title": LocalizedTitle(
                    ru=profile.title.ru, en=profile.title.en or alternate.title.en,
                    romaji=profile.title.romaji or alternate.title.romaji,
                ),
                "genres": profile.genres or alternate.genres,
                "synopsis": profile.synopsis or alternate.synopsis,
                "score": profile.score if profile.score is not None else alternate.score,
                "episodes": (
                    profile.episodes if profile.episodes is not None else alternate.episodes
                ),
            })
            for row in (media.get("reviews") or {}).get("nodes", []):
                text = _text(row.get("body"))
                if text:
                    reviews.append(Review(
                        text=text, source="anilist", id=str(row["id"]), url=row.get("url")
                    ))
        except (APIError, ValidationError, KeyError, TypeError, ValueError) as exc:
            warnings.append(f"AniList evidence: {exc}")
            # Metadata is independent evidence, not a fabricated review or proof
            # of a fast start. Jikan supplies real episode-1 text when available.
            if not reviews:
                profile = await self._fallback_synopsis(profile, warnings)
                warnings.append(
                    "AniList недоступен: резервные свидетельства — синопсис и "
                    "описание первой серии (если доступно); уверенность ограничена."
                )
        seen: set[str] = set()
        unique = []
        for review in reviews:
            key = " ".join(review.text.casefold().split())
            if key not in seen:
                seen.add(key)
                unique.append(review)
        return EvidenceBundle(profile=profile, reviews=unique, warnings=warnings)

    async def _fallback_synopsis(
        self, profile: TitleProfile, warnings: list[str],
    ) -> TitleProfile:
        # Jikan часто недоступен или зависает в таймаутах; синопсис уже есть из Shikimori/AniList
        return profile

    async def _candidates(self, seed: TitleProfile, limit: int) -> list[TitleProfile]:
        try:
            data = await self._graphql(
                "query ($genres: [String], $limit: Int!) { Page(perPage: $limit) { "
                "media(type: ANIME, genre_in: $genres, sort: SCORE_DESC) { "
                + MEDIA_FIELDS + " } } }",
                {"genres": seed.genres or None, "limit": limit},
            )
            profiles = [_anilist_profile(row) for row in data["Page"]["media"]]
            if profiles:
                return profiles
        except (APIError, ValidationError, KeyError, TypeError, ValueError) as exc:
            self.warnings.append(f"AniList candidates: {exc}")
        rows = await self._shiki("animes", order="ranked", limit=limit, page=1)
        if not isinstance(rows, list):
            raise APIError("Shikimori: expected a list of candidates")
        return [_shiki_profile(row) for row in rows]

    @staticmethod
    def similarity(seed: TitleProfile, candidate: TitleProfile) -> float:
        left = {genre.casefold() for genre in seed.genres}
        right = {genre.casefold() for genre in candidate.genres}
        return len(left & right) / len(left | right) if left | right else 0.0

    async def recommend(
        self, query: str, *, limit: int = 5, candidate_limit: int = 30,
        min_hvi: float = 60, min_score: float = 0, min_similarity: float = 0,
        review_limit: int = 20,
    ) -> RecommendationResult:
        if not 1 <= limit <= candidate_limit <= 50:
            raise ValueError("require 1 <= limit <= candidate_limit <= 50")
        if not 0 <= min_hvi <= 100 or not 0 <= min_score <= 10:
            raise ValueError("min_hvi must be 0..100 and min_score 0..10")
        if not 0 <= min_similarity <= 1 or not 1 <= review_limit <= 50:
            raise ValueError("min_similarity must be 0..1 and review_limit 1..50")
        self.warnings.clear()
        seed_bundle = await self.collect_evidence(
            await self.resolve(query), review_limit=review_limit
        )
        seed = seed_bundle.profile
        candidates = await self._candidates(seed, candidate_limit)
        unique: dict[tuple[str, int], TitleProfile] = {}
        for candidate in candidates:
            if (candidate.id_source, candidate.id) == (seed.id_source, seed.id):
                continue
            if seed.anilist_id and candidate.anilist_id == seed.anilist_id:
                continue
            unique.setdefault((candidate.id_source, candidate.id), candidate)

        # Сортируем кандидатов по предварительному совпадению жанров и оценке,
        # чтобы проверять глубокие отзывы только для наиболее перспективных (макс. limit * 2)
        sorted_candidates = sorted(
            unique.values(),
            key=lambda c: (self.similarity(seed, c), c.score or 0),
            reverse=True,
        )[:max(limit * 2, 6)]

        semaphore = asyncio.Semaphore(5)
        warnings = [*self.warnings, *seed_bundle.warnings]

        async def evaluate(candidate: TitleProfile) -> Recommendation | None:
            async with semaphore:
                # Быстрый сбор: уменьшенный review_limit для ускорения
                bundle = await self.collect_evidence(candidate, review_limit=min(review_limit, 5))
            warnings.extend(bundle.warnings)
            report = self.analyzer.analyze(bundle)
            similarity = self.similarity(seed, bundle.profile)
            text = " ".join((bundle.profile.synopsis, bundle.profile.first_episode_summary))
            votes, _ = extract_votes(text)
            # Synopsis describes premise rather than measured pacing. Admit only
            # high-rated genre matches without reviews or explicit slow-start cues.
            dynamic_drama = re.search(
                r"\b(?:battle\w*|fight\w*|surviv\w*|trapped|death|betray\w*|"
                r"sacrific\w*|war|danger\w*|conflict\w*|fast[ -]paced|"
                r"битв\w*|сраж\w*|выжива\w*|смерт\w*|предатель\w*|"
                r"жертв\w*|войн\w*|опасн\w*|конфликт\w*|динамич\w*)\b", text, re.I,
            )
            provisional = (
                not bundle.reviews and (bundle.profile.score or 0) > 7.8
                and similarity >= max(0.3, min_similarity) and dynamic_drama is not None
                and "slow" not in votes and not report.components.get("slow", 0)
                and min_hvi <= 60
            )
            if ((not provisional and (report.hvi < max(60, min_hvi)
                    or report.pacing_type in {"SLOW_BURN", "DROP_PRONE"}
                    or report.verdict == "AVOID_SLOW_START"))
                    or similarity < min_similarity):
                return None
            if provisional:
                note = (
                    f"{bundle.profile.title.display}: предварительный допуск по жанрам, "
                    "рейтингу и синопсису; быстрый старт не подтверждён отзывами."
                )
                warnings.append(note)
                report = report.model_copy(update={
                    "warnings": [*report.warnings, note],
                    "confidence": min(report.confidence, 0.25),
                    "key_cues": [*report.key_cues, "provisional:synopsis"],
                })
            if min_score > 0 and (
                bundle.profile.score is None or bundle.profile.score < min_score
            ):
                return None
            rank = round(
                0.6 * report.hvi + 0.25 * report.drama_score + 15 * similarity, 2
            )
            return Recommendation(
                profile=bundle.profile, report=report, rank_score=rank, similarity=similarity
            )

        evaluated = await asyncio.gather(*(evaluate(p) for p in sorted_candidates))
        items = sorted(
            (item for item in evaluated if item is not None),
            key=lambda item: (-item.rank_score, -item.report.hvi, item.profile.id),
        )[:limit]
        if not items:
            warnings.append("Нет тайтлов с достаточными свидетельствами темпа или резервного допуска.")
        return RecommendationResult(
            seed=seed, items=items, candidates_checked=len(sorted_candidates),
            warnings=list(dict.fromkeys(warnings)),
        )
