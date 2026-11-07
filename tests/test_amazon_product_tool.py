import pytest


def test_amazon_agent_tool_requires_keyword_and_existing_profile():
    from services.ucos_browser.server import _amazon_product_tool_task
    with pytest.raises(ValueError, match="keyword is required"):
        _amazon_product_tool_task({})
    with pytest.raises(ValueError, match="existing amazon-primary profile"):
        _amazon_product_tool_task({"keyword": "spice rack", "profile_ref": "other"})
    with pytest.raises(ValueError, match="supported Amazon marketplace"):
        _amazon_product_tool_task({"keyword": "spice rack", "marketplace": "shop.example"})


def test_amazon_agent_tool_runs_search_select_sitestripe_and_returns_url_only(monkeypatch):
    from services.ucos_browser import server
    captured = {}
    url = "https://www.amazon.com/dp/B012345678?tag=verified-20&linkCode=ogi"
    def fake_execute(task):
        captured.update(task)
        return {"affiliate_link": url, "final_url": "https://www.amazon.com/dp/B012345678", "product": {"title": "must not leak"}}
    monkeypatch.setattr(server, "execute_task", fake_execute)
    result = server._amazon_product_tool_task({"keyword": "3 tier spice rack"})
    assert result == {"affiliate_url": url}
    assert captured["profile_ref"] == "amazon-primary"
    assert [a["type"] for a in captured["actions"]] == [
        "navigate", "amazon_search_select", "amazon_sitestripe_get_link", "affiliate_link"
    ]
    assert captured["actions"][1]["keyword"] == "3 tier spice rack"


def test_amazon_agent_tool_rejects_unverified_or_plain_product_url(monkeypatch):
    from services.ucos_browser import server
    monkeypatch.setattr(server, "execute_task", lambda _task: {"affiliate_link": "https://www.amazon.com/dp/B012345678"})
    with pytest.raises(ValueError, match="did not return a valid Amazon Associates affiliate URL"):
        server._amazon_product_tool_task({"keyword": "spice rack"})


def test_amazon_agent_tool_rejects_non_integer_timeout():
    from services.ucos_browser.server import _amazon_product_tool_task
    with pytest.raises(ValueError, match="timeout_ms must be an integer"):
        _amazon_product_tool_task({"keyword": "spice rack", "timeout_ms": True})
