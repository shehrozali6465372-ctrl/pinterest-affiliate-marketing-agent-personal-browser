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
    assert captured["actions"][0]["url"] == "https://www.amazon.com/s?k=3+tier+spice+rack"


def test_amazon_agent_tool_rejects_unverified_or_plain_product_url(monkeypatch):
    from services.ucos_browser import server
    monkeypatch.setattr(server, "execute_task", lambda _task: {"affiliate_link": "https://www.amazon.com/dp/B012345678"})
    with pytest.raises(ValueError, match="did not return a valid Amazon Associates affiliate URL"):
        server._amazon_product_tool_task({"keyword": "spice rack"})


def test_amazon_agent_tool_rejects_non_integer_timeout():
    from services.ucos_browser.server import _amazon_product_tool_task
    with pytest.raises(ValueError, match="timeout_ms must be an integer"):
        _amazon_product_tool_task({"keyword": "spice rack", "timeout_ms": True})


def test_amazon_search_url_is_marketplace_scoped_and_encodes_keyword():
    from services.ucos_browser.server import _amazon_search_url
    from urllib.parse import urlsplit, parse_qs

    url = _amazon_search_url("amazon.com", "drawer organizer & bins")
    parsed = urlsplit(url)
    assert parsed.scheme == "https"
    assert parsed.hostname == "www.amazon.com"
    assert parsed.path == "/s"
    assert parse_qs(parsed.query) == {"k": ["drawer organizer & bins"]}


def test_amazon_search_url_rejects_unapproved_marketplace():
    from services.ucos_browser.server import _amazon_search_url
    with pytest.raises(ValueError, match="unsupported Amazon marketplace"):
        _amazon_search_url("amazon.example", "test")


def test_amazon_verification_page_is_classified_without_bypass():
    from services.ucos_browser.server import _amazon_verification_challenge

    class Body:
        def inner_text(self, timeout):
            assert timeout == 2_000
            return "To discuss automated access to Amazon data, solve the robot check."

    class Page:
        def title(self):
            return "Amazon.com"
        def locator(self, selector):
            assert selector == "body"
            return Body()

    assert _amazon_verification_challenge(Page()) is True


def test_amazon_product_result_locator_uses_fallback_card_selector():
    from services.ucos_browser.server import _amazon_product_result_locator

    class Candidate:
        def is_visible(self):
            return True
        def get_attribute(self, name):
            assert name == "href"
            return "/dp/B012345678?ref=sr_1_1"

    class Empty:
        def count(self):
            return 0

    class Matches:
        def count(self):
            return 1
        def nth(self, index):
            assert index == 0
            return Candidate()

    class Page:
        def locator(self, selector):
            if selector == "h2 a[href*='/dp/']":
                return Matches()
            return Empty()

    assert _amazon_product_result_locator(Page()) is not None


def test_amazon_product_result_locator_ignores_non_product_links():
    from services.ucos_browser.server import _amazon_product_result_locator

    class Candidate:
        def is_visible(self):
            return True
        def get_attribute(self, name):
            return "/help/contact-us"

    class Matches:
        def count(self):
            return 1
        def nth(self, index):
            return Candidate()

    class Empty:
        def count(self):
            return 0

    class Page:
        def locator(self, selector):
            return Matches() if selector == "h2 a[href*='/dp/']" else Empty()

    assert _amazon_product_result_locator(Page()) is None
