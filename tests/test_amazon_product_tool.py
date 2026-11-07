

import pytest


def test_amazon_product_tool_rejects_non_amazon_and_marketplace_mismatch():
    from services.ucos_browser.server import _amazon_product_tool_task

    with pytest.raises(ValueError, match="HTTPS URL on the selected Amazon marketplace"):
        _amazon_product_tool_task({"product_url": "https://example.com/item"})
    with pytest.raises(ValueError, match="does not match marketplace"):
        _amazon_product_tool_task({
            "marketplace": "amazon.co.uk",
            "product_url": "https://www.amazon.com/dp/B012345678",
        })


def test_amazon_product_tool_rejects_unknown_fields():
    from services.ucos_browser.server import _amazon_product_tool_task

    with pytest.raises(ValueError, match="unsupported product fields"):
        _amazon_product_tool_task({
            "product_url": "https://www.amazon.com/dp/B012345678",
            "fields": ["title", "seller_private_data"],
        })


def test_amazon_product_tool_returns_partial_when_product_data_missing(monkeypatch):
    from services.ucos_browser import server

    captured = {}

    def fake_execute(task):
        captured.update(task)
        return {
            "product": {
                "title": "Example product",
                "price": None,
                "rating": "4.5 out of 5 stars",
                "availability": "In Stock",
            },
            "affiliate_link": None,
            "final_url": "https://www.amazon.com/dp/B012345678",
            "verified_at": "2026-11-06T00:00:00Z",
            "profile_ref": "amazon-primary",
            "session_reused": True,
            "duration_ms": 123,
            "evidence": {"title": {"selector": "#productTitle", "present": True}},
            "warnings": ["price unavailable on page"],
        }

    monkeypatch.setattr(server, "execute_task", fake_execute)
    result = server._amazon_product_tool_task({
        "product_url": "https://www.amazon.com/dp/B012345678",
    })
    assert result["status"] == "partial"
    assert result["product"]["price"] is None
    assert result["missing_fields"] == ["price", "affiliate_link"]
    assert result["affiliate_link"] is None
    assert captured["profile_ref"] == "amazon-primary"
    assert [a["type"] for a in captured["actions"]] == [
        "navigate", "amazon_product_details", "affiliate_link"
    ]


def test_amazon_product_tool_returns_affiliate_link_only_when_valid(monkeypatch):
    from services.ucos_browser import server

    link = "https://www.amazon.com/dp/B012345678?tag=approved-20&linkCode=ogi"

    def fake_execute(_task):
        return {
            "product": {
                "title": "Example product",
                "price": "$19.99",
                "rating": "4.5 out of 5 stars",
                "availability": "In Stock",
            },
            "affiliate_link": link,
            "final_url": "https://www.amazon.com/dp/B012345678",
            "verified_at": "2026-11-06T00:00:00Z",
            "profile_ref": "amazon-primary",
            "session_reused": True,
            "duration_ms": 123,
            "evidence": {},
            "warnings": [],
        }

    monkeypatch.setattr(server, "execute_task", fake_execute)
    result = server._amazon_product_tool_task({
        "product_url": "https://www.amazon.com/dp/B012345678",
    })
    assert result["status"] == "completed"
    assert result["affiliate_link"] == link
    assert result["affiliate_link_format_valid"] is True
    assert "format_only" in result["affiliate_link_verification_scope"]


def test_amazon_product_tool_rejects_untrusted_amazon_subdomain_and_profile():
    from services.ucos_browser.server import _amazon_product_tool_task

    with pytest.raises(ValueError, match="HTTPS URL on the selected Amazon marketplace"):
        _amazon_product_tool_task({"product_url": "https://evil.amazon.com/dp/B012345678"})
    with pytest.raises(ValueError, match="existing amazon-primary profile"):
        _amazon_product_tool_task({
            "product_url": "https://www.amazon.com/dp/B012345678",
            "profile_ref": "another-profile",
        })


def test_amazon_product_tool_rejects_non_boolean_link_flag_and_bad_fields():
    from services.ucos_browser.server import _amazon_product_tool_task

    with pytest.raises(ValueError, match="must be a boolean"):
        _amazon_product_tool_task({
            "product_url": "https://www.amazon.com/dp/B012345678",
            "generate_affiliate_link": "false",
        })
    with pytest.raises(ValueError, match="non-empty string"):
        _amazon_product_tool_task({
            "product_url": "https://www.amazon.com/dp/B012345678",
            "fields": ["title", ""],
        })


def test_amazon_product_tool_does_not_support_customer_review_data():
    from services.ucos_browser.server import _amazon_product_tool_task

    with pytest.raises(ValueError, match="unsupported product fields: review_count"):
        _amazon_product_tool_task({
            "product_url": "https://www.amazon.com/dp/B012345678",
            "fields": ["title", "review_count"],
        })
