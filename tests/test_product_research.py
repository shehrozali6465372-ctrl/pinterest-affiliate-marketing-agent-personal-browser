import json
import threading

import pytest


def test_product_research_validates_query_and_url_exclusivity():
    from services.ucos_browser import product_research as module

    with pytest.raises(ValueError, match="exactly one"):
        module.validate_request({"source": "catalog", "marketplace": "US"})
    with pytest.raises(ValueError, match="exactly one"):
        module.validate_request({
            "source": "catalog", "marketplace": "US",
            "search_query": "spice rack", "product_url": "https://shop.example/item",
        })


def test_product_research_rejects_review_fields():
    from services.ucos_browser import product_research as module

    with pytest.raises(ValueError, match="unsupported field"):
        module.validate_request({
            "source": "catalog", "marketplace": "US",
            "search_query": "spice rack", "fields": ["title", "review_count"],
        })


def test_product_research_uses_registered_adapter_and_returns_normalized_records():
    from services.ucos_browser import product_research as module

    def adapter(request):
        assert request.search_query == "3 tier spice rack"
        return [module.ProductRecord(
            title="Three-tier spice rack", price="$19.99", currency="USD",
            product_url="https://shop.example/products/rack",
            image_url="https://cdn.shop.example/rack.jpg", category="Kitchen",
            brand="Example", specifications={"tiers": 3}, availability="In stock",
            affiliate_link="https://shop.example/affiliate/abc",
            affiliate_link_status="provider_confirmed", evidence={"source": "catalog-api"},
        )]

    module.register_adapter("test-catalog", adapter)
    try:
        result = module.research({
            "source": "test-catalog", "marketplace": "US",
            "search_query": "3 tier spice rack", "limit": 2,
        })
    finally:
        module.unregister_adapter("test-catalog")

    assert result["status"] == "completed"
    assert result["result_count"] == 1
    assert result["customer_reviews_collected"] is False
    product = result["products"][0]["product"]
    assert product["affiliate_link_status"] == "provider_confirmed"
    assert "review_count" not in product


def test_product_research_marks_missing_affiliate_link_partial():
    from services.ucos_browser import product_research as module

    module.register_adapter("no-link", lambda request: [module.ProductRecord(title="Item")])
    try:
        result = module.research({
            "source": "no-link", "marketplace": "US", "search_query": "item",
            "fields": ["title"], "require_affiliate_link": True,
        })
    finally:
        module.unregister_adapter("no-link")
    assert result["status"] == "partial"
    assert result["products"][0]["missing_fields"] == ["affiliate_link"]


def test_product_research_rejects_unconfigured_provider():
    from services.ucos_browser import product_research as module

    with pytest.raises(module.ProviderNotConfigured, match="not configured"):
        module.research({
            "source": "not-installed", "marketplace": "US", "search_query": "item",
        })


def test_product_research_http_requires_bearer_auth(monkeypatch):
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen
    from services.ucos_browser import server as module

    monkeypatch.setenv("UCOS_BROWSER_AGENT_TOKEN", "research-test-token")
    httpd = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            f"http://127.0.0.1:{httpd.server_port}/tool/product/research",
            data=json.dumps({"source": "missing", "marketplace": "US", "search_query": "item"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with pytest.raises(HTTPError) as exc:
            urlopen(request, timeout=3)
        assert exc.value.code == 401
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)


def test_product_research_http_returns_503_when_source_not_configured(monkeypatch):
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen
    from services.ucos_browser import server as module

    monkeypatch.setenv("UCOS_BROWSER_AGENT_TOKEN", "research-test-token")
    httpd = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            f"http://127.0.0.1:{httpd.server_port}/tool/product/research",
            data=json.dumps({"source": "missing", "marketplace": "US", "search_query": "item"}).encode(),
            headers={"Authorization": "Bearer research-test-token", "Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(HTTPError) as exc:
            urlopen(request, timeout=3)
        assert exc.value.code == 503
        body = json.loads(exc.value.read().decode())
        assert body["state"] == "unavailable"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)


def test_product_research_never_returns_unverified_affiliate_link():
    from services.ucos_browser import product_research as module

    module.register_adapter("unverified-link", lambda request: [module.ProductRecord(
        title="Item", affiliate_link="https://shop.example/affiliate/guess",
        affiliate_link_status="unverified",
    )])
    try:
        result = module.research({
            "source": "unverified-link", "marketplace": "US", "search_query": "item",
            "fields": ["title"], "require_affiliate_link": True,
        })
    finally:
        module.unregister_adapter("unverified-link")
    product = result["products"][0]
    assert product["product"]["affiliate_link"] is None
    assert product["product"]["affiliate_link_status"] == "unverified"
    assert "affiliate_link" in product["missing_fields"]


def test_product_research_rejects_insecure_provider_urls():
    from services.ucos_browser import product_research as module

    module.register_adapter("bad-url", lambda request: [module.ProductRecord(
        title="Item", product_url="http://shop.example/item",
    )])
    try:
        with pytest.raises(ValueError, match="non-HTTPS"):
            module.research({
                "source": "bad-url", "marketplace": "US", "search_query": "item",
                "fields": ["title", "product_url"], "require_affiliate_link": False,
            })
    finally:
        module.unregister_adapter("bad-url")


@pytest.mark.parametrize("url", [
    "http://shop.example/item",
    "https://localhost/item",
    "https://127.0.0.1/item",
    "https://[::1]/item",
    "https://user:pass@shop.example/item",
    "https://shop.example:8443/item",
])
def test_product_research_rejects_non_public_or_unsafe_input_urls(url):
    from services.ucos_browser import product_research as module

    with pytest.raises(ValueError, match="HTTPS public-domain"):
        module.validate_request({
            "source": "catalog", "marketplace": "US", "product_url": url,
        })


def test_product_research_rejects_invalid_source_and_marketplace_identifiers():
    from services.ucos_browser import product_research as module

    for payload in (
        {"source": "bad source", "marketplace": "US", "search_query": "item"},
        {"source": "catalog", "marketplace": "amazon.com", "search_query": "item"},
    ):
        with pytest.raises(ValueError):
            module.validate_request(payload)


def test_product_research_rejects_oversized_provider_evidence():
    from services.ucos_browser import product_research as module

    module.register_adapter("large-evidence", lambda request: [module.ProductRecord(
        title="Item", evidence={"blob": "x" * 20_000},
    )])
    try:
        with pytest.raises(ValueError, match="oversized evidence"):
            module.research({
                "source": "large-evidence", "marketplace": "US", "search_query": "item",
                "fields": ["title"], "require_affiliate_link": False,
            })
    finally:
        module.unregister_adapter("large-evidence")
