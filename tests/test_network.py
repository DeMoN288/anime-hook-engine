import httpx
import pytest

from anime_hook.network import APIError, AsyncAPIClient


@pytest.mark.asyncio
async def test_client_timeout_and_graphql_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "graphql.anilist.co"
        return httpx.Response(200, json={"data": {"Media": {"id": 1}}})

    async with AsyncAPIClient(
        timeout=12.5,
        transport=httpx.MockTransport(handler),
        host_intervals={},
    ) as client:
        assert client._client(None).timeout.read == 12.5
        data = await client.graphql("query { Media { id } }", {})
        assert data == {"Media": {"id": 1}}


@pytest.mark.asyncio
async def test_client_graphql_errors_raise_api_error():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errors": [{"message": "Bad query"}]})

    async with AsyncAPIClient(
        transport=httpx.MockTransport(handler),
        host_intervals={},
    ) as client:
        with pytest.raises(APIError, match="Bad query"):
            await client.graphql("query { bad }", {})


@pytest.mark.asyncio
async def test_client_rate_limit_fail_fast():
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "10"})

    async with AsyncAPIClient(
        retries=3,
        transport=httpx.MockTransport(handler),
        host_intervals={},
    ) as client:
        with pytest.raises(APIError, match="HTTP 429"):
            await client.request_json(
                "GET", "https://example.com/api", fail_fast_on_rate_limit=True
            )
        assert calls == 1
        with pytest.raises(APIError, match="host cooldown"):
            await client.request_json(
                "GET", "https://example.com/api", fail_fast_on_rate_limit=True
            )
