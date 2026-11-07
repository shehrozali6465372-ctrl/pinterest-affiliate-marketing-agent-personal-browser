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


def test_amazon_product_result_locator_uses_fallback_title_link():
    from services.ucos_browser.server import _amazon_product_result_locator

    class Candidate:
        def is_visible(self):
            return True
        def get_attribute(self, name):
            return {
                "aria-hidden": None,
                "href": "/dp/B012345678?ref=sr_1_1",
            }.get(name)
        def inner_text(self, timeout):
            assert timeout == 1_000
            return "3-Tier Spice Rack Organizer"

    class Empty:
        def count(self):
            return 0

    class Matches:
        def count(self):
            return 1
        def nth(self, index):
            assert index == 0
            return candidate

    candidate = Candidate()

    class Page:
        def locator(self, selector):
            if selector == "h2 a[href*='/dp/']":
                return Matches()
            return Empty()

    assert _amazon_product_result_locator(Page()) is candidate


def test_amazon_product_result_locator_skips_aria_hidden_image_and_uses_title():
    from services.ucos_browser.server import _amazon_product_result_locator

    class Candidate:
        def __init__(self, href, *, aria_hidden=None, label=""):
            self.href = href
            self.aria_hidden = aria_hidden
            self.label = label
        def is_visible(self):
            return True
        def get_attribute(self, name):
            return {"aria-hidden": self.aria_hidden, "href": self.href}.get(name)
        def inner_text(self, timeout):
            return self.label

    image = Candidate(
        "/dp/B012345678/image",
        aria_hidden="true",
        label="",
    )
    title = Candidate(
        "/dp/B012345678/title",
        label="3-Tier Spice Rack Organizer",
    )

    class Matches:
        def __init__(self, candidates):
            self.candidates = candidates
        def count(self):
            return len(self.candidates)
        def nth(self, index):
            return self.candidates[index]

    class Empty:
        def count(self):
            return 0

    class Page:
        def locator(self, selector):
            if selector == "div[data-component-type='s-search-result'] h2 a[href*='/dp/']":
                return Matches([image])
            if selector == "div[data-component-type='s-search-result'] a.a-link-normal.a-text-normal[href*='/dp/']":
                return Matches([title])
            return Empty()

    assert _amazon_product_result_locator(Page()) is title


def test_amazon_product_result_locator_rejects_non_product_and_unlabelled_links():
    from services.ucos_browser.server import _amazon_product_result_locator

    class Candidate:
        def is_visible(self):
            return True
        def get_attribute(self, name):
            return {
                "aria-hidden": None,
                "href": "/help/contact-us",
            }.get(name)
        def inner_text(self, timeout):
            return "Contact us"

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


def test_amazon_product_result_url_resolves_and_scopes_to_marketplace():
    from services.ucos_browser.server import _amazon_product_result_url

    url = _amazon_product_result_url(
        "https://www.amazon.com/s?k=drawer+organizer",
        "/brand/product/dp/B012345678/ref=sr_1_1",
        "amazon.com",
    )
    assert url == "https://www.amazon.com/brand/product/dp/B012345678/ref=sr_1_1"


@pytest.mark.parametrize(
    "href",
    [
        "https://attacker.example/dp/B012345678",
        "http://www.amazon.com/dp/B012345678",
        "https://www.amazon.co.uk/dp/B012345678",
        "https://user@www.amazon.com/dp/B012345678",
        "/help/contact-us",
    ],
)
def test_amazon_product_result_url_rejects_unsafe_or_cross_marketplace_hrefs(href):
    from services.ucos_browser.server import _amazon_product_result_url

    with pytest.raises(ValueError, match="safe product URL"):
        _amazon_product_result_url(
            "https://www.amazon.com/s?k=drawer+organizer",
            href,
            "amazon.com",
        )


def test_amazon_search_select_navigates_to_validated_product_href_without_click(monkeypatch):
    from services.ucos_browser import server

    class Response:
        status = 200

    class Candidate:
        def __init__(self, page):
            self.page = page
        def is_visible(self):
            return True
        def get_attribute(self, name):
            return {
                "aria-hidden": None,
                "href": "/brand/product/dp/B012345678/ref=sr_1_1",
            }.get(name)
        def inner_text(self, timeout):
            assert timeout == 1_000
            return "3-Tier Spice Rack Organizer"
        def click(self, *args, **kwargs):
            self.page.click_calls += 1
            raise AssertionError("Amazon product result should be navigated by validated href")

    class Matches:
        def __init__(self, candidate):
            self.candidate = candidate
        def count(self):
            return 1
        def nth(self, index):
            assert index == 0
            return self.candidate

    class Empty:
        def count(self):
            return 0

    class Page:
        def __init__(self):
            self.url = "https://www.amazon.com/"
            self.goto_calls = []
            self.click_calls = 0
            self.candidate = Candidate(self)
        def goto(self, url, *, wait_until, timeout):
            assert wait_until == "domcontentloaded"
            assert timeout == 30_000
            self.goto_calls.append(url)
            self.url = url
            return Response()
        def wait_for_load_state(self, state, *, timeout):
            assert state == "domcontentloaded"
            assert timeout == 30_000
        def locator(self, selector):
            if selector == "div[data-component-type='s-search-result'] h2 a[href*='/dp/']":
                return Matches(self.candidate)
            return Empty()

    page = Page()
    runtime = {
        "page": page,
        "context": type("Context", (), {"pages": [page]})(),
        "state_store_enabled": False,
        "disk_persistent": False,
        "persistent_profile": False,
        "profile_persistence_backend": "test",
        "last_used": 0,
    }
    monkeypatch.setattr(server, "_get_browser_runtime", lambda *args: (runtime, False))
    monkeypatch.setattr(server, "validate_url", lambda value: str(value))
    monkeypatch.setattr(server, "_assert_public_page", lambda _page: None)
    monkeypatch.setattr(server, "_amazon_verification_challenge", lambda _page: False)

    result = server._execute_task_on_browser_thread({
        "profile_ref": "amazon-primary",
        "timeout_ms": 30_000,
        "actions": [
            {"type": "navigate", "url": "https://www.amazon.com/s?k=drawer+organizer"},
            {"type": "amazon_search_select", "keyword": "drawer organizer"},
        ],
    })

    assert page.goto_calls == [
        "https://www.amazon.com/s?k=drawer+organizer",
        "https://www.amazon.com/brand/product/dp/B012345678/ref=sr_1_1",
    ]
    assert page.click_calls == 0
    assert result["final_url"] == page.url
    assert result["events"][-1]["type"] == "amazon_search_and_first_result_selected"
