


def test_amazon_product_tool_http_requires_bearer_auth(monkeypatch):
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen
    import json
    import threading
    from services.ucos_browser import server as module

    monkeypatch.setenv("UCOS_BROWSER_AGENT_TOKEN", "agent-tool-test")
    httpd = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps({
            "product_url": "https://www.amazon.com/dp/B012345678"
        }).encode()
        request = Request(
            f"http://127.0.0.1:{httpd.server_port}/tool/amazon/product",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urlopen(request, timeout=3)
        except HTTPError as exc:
            assert exc.code == 401
        else:
            raise AssertionError("agent tool endpoint must require bearer authentication")
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)


def test_amazon_product_tool_http_dispatches_and_wraps_result(monkeypatch):
    from urllib.request import Request, urlopen
    import json
    import threading
    from services.ucos_browser import server as module

    monkeypatch.setenv("UCOS_BROWSER_AGENT_TOKEN", "agent-tool-test")
    monkeypatch.setenv("UCOS_AMAZON_AGENT_ACCESS_APPROVED", "true")
    monkeypatch.setenv("UCOS_AMAZON_AGENT_USER_AGENT", "UCOSPersonalBrowser Agent/UCOSPersonalBrowser")
    monkeypatch.setattr(module, "_amazon_product_tool_task", lambda payload: {
        "status": "partial",
        "product": {"title": "Example"},
        "affiliate_link": None,
    })
    monkeypatch.setattr(module, "_record_task_run", lambda *args, **kwargs: None)
    httpd = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps({
            "product_url": "https://www.amazon.com/dp/B012345678"
        }).encode()
        request = Request(
            f"http://127.0.0.1:{httpd.server_port}/tool/amazon/product",
            data=body,
            headers={
                "Authorization": "Bearer agent-tool-test",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=3) as response:
            payload = json.loads(response.read().decode())
        assert payload["state"] == "completed"
        assert payload["result"]["status"] == "partial"
        assert payload["result"]["affiliate_link"] is None
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)


def test_amazon_product_tool_http_fails_closed_without_policy_approval(monkeypatch):
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen
    import json
    import threading
    from services.ucos_browser import server as module

    monkeypatch.setenv("UCOS_BROWSER_AGENT_TOKEN", "agent-tool-test")
    monkeypatch.delenv("UCOS_AMAZON_AGENT_ACCESS_APPROVED", raising=False)
    httpd = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            f"http://127.0.0.1:{httpd.server_port}/tool/amazon/product",
            data=json.dumps({"product_url": "https://www.amazon.com/dp/B012345678"}).encode(),
            headers={
                "Authorization": "Bearer agent-tool-test",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            urlopen(request, timeout=3)
        except HTTPError as exc:
            assert exc.code == 403
            body = json.loads(exc.read().decode())
            assert body["state"] == "blocked"
        else:
            raise AssertionError("Amazon agent endpoint must fail closed without policy approval")
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)


def test_amazon_product_tool_http_requires_agent_identifying_user_agent(monkeypatch):
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen
    import json
    import threading
    from services.ucos_browser import server as module

    monkeypatch.setenv("UCOS_BROWSER_AGENT_TOKEN", "agent-tool-test")
    monkeypatch.setenv("UCOS_AMAZON_AGENT_ACCESS_APPROVED", "true")
    monkeypatch.delenv("UCOS_AMAZON_AGENT_USER_AGENT", raising=False)
    httpd = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            f"http://127.0.0.1:{httpd.server_port}/tool/amazon/product",
            data=json.dumps({"product_url": "https://www.amazon.com/dp/B012345678"}).encode(),
            headers={
                "Authorization": "Bearer agent-tool-test",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            urlopen(request, timeout=3)
        except HTTPError as exc:
            assert exc.code == 403
        else:
            raise AssertionError("Amazon agent route must require its identifying User-Agent")
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)


def test_browser_http_rejects_non_json_content_type(monkeypatch):
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen
    import json
    import threading
    from services.ucos_browser import server as module

    monkeypatch.setenv("UCOS_BROWSER_TOKEN", "agent-tool-test")
    httpd = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            f"http://127.0.0.1:{httpd.server_port}/execute",
            data=json.dumps({"actions": []}).encode(),
            headers={"Authorization": "Bearer agent-tool-test"},
            method="POST",
        )
        try:
            urlopen(request, timeout=3)
        except HTTPError as exc:
            assert exc.code == 400
            body = json.loads(exc.read().decode())
            assert body["error"] == "Content-Type must be application/json"
        else:
            raise AssertionError("browser endpoint must reject non-JSON request bodies")
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)


def test_agent_token_cannot_access_operator_execute_endpoint(monkeypatch):
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen
    import json
    import threading
    from services.ucos_browser import server as module

    monkeypatch.setenv("UCOS_BROWSER_TOKEN", "operator-only-token")
    monkeypatch.setenv("UCOS_BROWSER_AGENT_TOKEN", "agent-only-token")
    httpd = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            f"http://127.0.0.1:{httpd.server_port}/execute",
            data=json.dumps({"url": "https://example.com", "actions": []}).encode(),
            headers={"Authorization": "Bearer agent-only-token", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            urlopen(request, timeout=3)
        except HTTPError as exc:
            assert exc.code == 401
        else:
            raise AssertionError("agent token must not authorize the operator browser endpoint")
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)


def test_operator_token_cannot_access_agent_tool_endpoint(monkeypatch):
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen
    import json
    import threading
    from services.ucos_browser import server as module

    monkeypatch.setenv("UCOS_BROWSER_TOKEN", "operator-only-token")
    monkeypatch.setenv("UCOS_BROWSER_AGENT_TOKEN", "agent-only-token")
    httpd = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            f"http://127.0.0.1:{httpd.server_port}/tool/product/research",
            data=json.dumps({"source": "not-configured", "search_query": "test"}).encode(),
            headers={"Authorization": "Bearer operator-only-token", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            urlopen(request, timeout=3)
        except HTTPError as exc:
            assert exc.code == 401
        else:
            raise AssertionError("operator token must not authorize agent tool endpoints")
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)
