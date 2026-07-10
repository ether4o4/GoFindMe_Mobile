import httpx
import pytest

from app.providers import CrtSh


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_crtsh_normalizes_subdomains():
    def handler(request):
        assert "crt.sh" in str(request.url)
        return httpx.Response(200, json=[
            {"name_value": "www.example.com\nexample.com"},
            {"name_value": "*.example.com"},
            {"name_value": "api.example.com"},
        ])

    async with _client(handler) as client:
        res = await CrtSh().lookup(client, None, "example.com", "domain")
    assert res.ok
    assert res.summary["found"] is True
    assert "api.example.com" in res.summary["subdomains"]
    assert "www.example.com" in res.summary["subdomains"]


async def test_crtsh_handles_error_status():
    def handler(request):
        return httpx.Response(429, text="rate limited")

    async with _client(handler) as client:
        res = await CrtSh().lookup(client, None, "example.com", "domain")
    assert not res.ok
    assert res.error == "rate_limited"


@pytest.mark.network
async def test_crtsh_live():
    """Real call through the configured proxy/CA — proves the outbound path."""
    from app.providers import make_client
    async with make_client() as client:
        res = await CrtSh().lookup(client, None, "example.com", "domain")
    assert res.ok
