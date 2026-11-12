import json

import httpx
import pytest

from anime_hook.network import AsyncAPIClient
from anime_hook.recommender import Recommender


def _mock_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "shikimori.io/api/animes/11757" in url:
            return httpx.Response(
                200,
                json={
                    "id": 11757,
                    "name": "Sword Art Online",
                    "russian": "Мастера Меча Онлайн",
                    "score": "7.23",
                    "episodes": 25,
                    "genres": [{"name": "Action"}, {"name": "Fantasy"}],
                    "description": "Смертельная игра в виртуальной реальности.",
                },
            )
        if "shikimori.io/api/animes?" in url:
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 11757,
                        "name": "Sword Art Online",
                        "russian": "Мастера Меча Онлайн",
                        "score": "7.23",
                        "episodes": 25,
                        "genres": [{"name": "Action"}, {"name": "Fantasy"}],
                    }
                ],
            )
        if "shikimori.io/api/topics" in url:
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 10,
                        "body": "Захватывает с первой серии, отличное начало!",
                        "url": "/topics/10",
                    }
                ],
            )
        if "graphql.anilist.co" in url:
            body = json.loads(request.content)
            query = body["query"]
            if "reviews(" in query:
                assert "siteUrl" in query
                assert " url " not in query
                mid = body["variables"]["id"]
                if mid == 102:
                    reviews = [
                        {
                            "id": 2,
                            "body": "Very slow start, boring beginning.",
                            "siteUrl": None,
                        }
                    ]
                else:
                    reviews = [
                        {
                            "id": 1,
                            "body": "Hooked from the first episode, emotional peak!",
                            "siteUrl": "https://anilist.co/review/1",
                        }
                    ]
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "Media": {
                                "id": mid,
                                "idMal": None if mid in (101, 102) else 11757,
                                "title": {"english": f"Title {mid}", "romaji": f"Title {mid}"},
                                "averageScore": 84,
                                "episodes": 12,
                                "genres": ["Action", "Fantasy"],
                                "description": "Fast battle and survival.",
                                "reviews": {"nodes": reviews},
                            }
                        }
                    },
                )
            if "genre_in" in query:
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "Page": {
                                "media": [
                                    {
                                        "id": 101,
                                        "idMal": None,
                                        "title": {"english": "Fast Show", "romaji": "Fast Show"},
                                        "averageScore": 85,
                                        "episodes": 12,
                                        "genres": ["Action", "Fantasy"],
                                        "description": "Deadly battle from episode 1.",
                                    },
                                    {
                                        "id": 102,
                                        "idMal": None,
                                        "title": {"english": "Slow Show", "romaji": "Slow Show"},
                                        "averageScore": 82,
                                        "episodes": 24,
                                        "genres": ["Action", "Fantasy"],
                                        "description": "Slow world building.",
                                    },
                                ]
                            }
                        }
                    },
                )
        return httpx.Response(404)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_recommender_collects_reviews_and_filters_slow():
    async with AsyncAPIClient(transport=_mock_transport(), host_intervals={}) as client:
        rec = Recommender(client)
        result = await rec.recommend("Sword Art Online", limit=5, candidate_limit=5)

    assert result.seed.title.ru == "Мастера Меча Онлайн"
    titles = [item.profile.title.display for item in result.items]
    assert titles == ["Fast Show"]
    assert result.items[0].report.verdict in {"GOOD_PACE", "MUST_WATCH"}
    assert result.items[0].similarity == 1.0


@pytest.mark.asyncio
async def test_recommender_validation_errors():
    async with AsyncAPIClient(transport=_mock_transport(), host_intervals={}) as client:
        rec = Recommender(client)
        with pytest.raises(ValueError):
            await rec.search("   ")
        with pytest.raises(ValueError):
            await rec.recommend("SAO", limit=10, candidate_limit=5)
