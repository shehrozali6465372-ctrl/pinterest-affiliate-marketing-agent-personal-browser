"""Tests for encrypted, Neon-backed browser session snapshots."""
import sys
from types import SimpleNamespace

import pytest

from services.ucos_browser import profile_persistence as persistence
from services.ucos_browser import server as browser_server


class _Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.result = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=None):
        statement = " ".join(sql.lower().split())
        if "select encrypted_state" in statement:
            self.result = (
                (self.rows[params[0]],) if params[0] in self.rows else None
            )
        elif "select 1 from browser_profile_states" in statement:
            self.result = (1,) if params[0] in self.rows else None
        elif "insert into browser_profile_states" in statement:
            self.rows[params[0]] = bytes(params[1])
            self.result = None
        elif "delete from browser_profile_states" in statement:
            self.rows.pop(params[0], None)
            self.result = None
        else:
            self.result = None

    def fetchone(self):
        return self.result


class _Connection:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return _Cursor(self.rows)


class _FakeBrowserContext:
    def __init__(self):
        self.cookies = []
        self.scripts = []

    def add_cookies(self, cookies):
        self.cookies.extend(cookies)

    def add_init_script(self, script=None, path=None):
        self.scripts.append(script)


@pytest.fixture
def encrypted_store(monkeypatch):
    cryptography = pytest.importorskip("cryptography.fernet")
    key = cryptography.Fernet.generate_key().decode("ascii")
    rows = {}
    connection = _Connection(rows)
    monkeypatch.setenv("DATABASE_URL", "postgresql://test.invalid/test")
    monkeypatch.setenv("UCOS_BROWSER_STATE_ENCRYPTION_KEY", key)
    monkeypatch.setenv("UCOS_BROWSER_REQUIRE_DURABLE_PROFILE", "true")
    monkeypatch.setitem(
        sys.modules,
        "psycopg",
        SimpleNamespace(connect=lambda _dsn, connect_timeout: connection),
    )
    return rows, key


def test_encrypted_session_state_round_trips_without_plaintext(encrypted_store):
    rows, _key = encrypted_store
    state = {
        "cookies": [{
            "name": "session",
            "value": "secret-cookie-value",
            "domain": ".example.test",
            "path": "/",
            "expires": -1,
            "httpOnly": True,
            "secure": True,
            "sameSite": "Lax",
        }],
        "origins": [{
            "origin": "https://example.test",
            "localStorage": [
                {"name": "access", "value": "secret-local-storage-value"},
                {"name": persistence._RESTORE_MARKER, "value": "1"},
            ],
        }],
    }

    assert persistence.save_profile_state("account-1", state) is True
    encrypted = rows["account-1"]
    assert b"secret-cookie-value" not in encrypted
    assert b"secret-local-storage-value" not in encrypted
    restored = persistence.load_profile_state("account-1")
    assert restored == {
        "cookies": state["cookies"],
        "origins": [{
            "origin": "https://example.test",
            "localStorage": [{"name": "access", "value": "secret-local-storage-value"}],
        }],
    }
    assert persistence.has_profile_state("account-1") is True
    assert persistence.has_profile_state("missing") is False


def test_wrong_encryption_key_fails_closed(encrypted_store, monkeypatch):
    persistence.save_profile_state(
        "account-1",
        {"cookies": [{"name": "sid", "value": "sensitive"}], "origins": []},
    )
    cryptography = pytest.importorskip("cryptography.fernet")
    monkeypatch.setenv(
        "UCOS_BROWSER_STATE_ENCRYPTION_KEY",
        cryptography.Fernet.generate_key().decode("ascii"),
    )
    with pytest.raises(RuntimeError, match="could not be decrypted"):
        persistence.load_profile_state("account-1")


def test_local_storage_restore_is_origin_scoped_and_script_safe():
    context = _FakeBrowserContext()
    state = {
        "cookies": [{"name": "sid", "value": "secret", "domain": ".example.test", "path": "/"}],
        "origins": [{
            "origin": "https://example.test",
            "localStorage": [{"name": "x", "value": "</script><script>alert(1)</script>"}],
        }],
    }
    persistence.restore_storage_state(context, state)
    assert context.cookies == state["cookies"]
    assert len(context.scripts) == 1
    assert "sessionStorage.getItem(marker)" in context.scripts[0]
    assert "</script>" not in context.scripts[0]
    assert "https://example.test" in context.scripts[0]


def test_required_mode_without_database_and_encryption_key_fails_closed(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("UCOS_BROWSER_STATE_DATABASE_URL", raising=False)
    monkeypatch.delenv("UCOS_BROWSER_STATE_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("UCOS_BROWSER_REQUIRE_DURABLE_PROFILE", "true")
    assert persistence.is_configured() is False
    with pytest.raises(RuntimeError, match="requires DATABASE_URL"):
        persistence.load_profile_state("account-1")


def test_optional_mode_without_store_does_not_claim_persistence(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("UCOS_BROWSER_STATE_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("UCOS_BROWSER_REQUIRE_DURABLE_PROFILE", "false")
    assert persistence.is_configured() is False
    assert persistence.load_profile_state("account-1") is None
    assert persistence.save_profile_state(
        "account-1", {"cookies": [], "origins": []}
    ) is False


def test_writable_default_profile_directory_is_not_certified_as_durable(monkeypatch, tmp_path):
    monkeypatch.delenv("UCOS_BROWSER_PROFILE_DIR", raising=False)
    monkeypatch.delenv("UCOS_BROWSER_REQUIRE_DURABLE_PROFILE", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("UCOS_BROWSER_STATE_ENCRYPTION_KEY", raising=False)
    original_path = browser_server.Path
    monkeypatch.setattr(
        browser_server,
        "Path",
        lambda value: tmp_path if str(value) == "/var/data/ucos-browser/profiles" else original_path(value),
    )
    path, persistent = browser_server._profile_dir("account-1")
    assert path.startswith(str(tmp_path))
    assert persistent is False



def test_browser_specific_database_url_is_preferred(monkeypatch):
    monkeypatch.setenv("UCOS_BROWSER_STATE_DATABASE_URL", "postgresql://session-db.example/test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://shared-db.example/app")
    monkeypatch.setenv("UCOS_BROWSER_STATE_ENCRYPTION_KEY", "configured-key")
    captured = {}
    monkeypatch.setitem(
        sys.modules,
        "psycopg",
        SimpleNamespace(
            connect=lambda dsn, connect_timeout: captured.update(
                dsn=dsn, connect_timeout=connect_timeout
            ) or object()
        ),
    )

    persistence._connect()
    assert captured == {
        "dsn": "postgresql://session-db.example/test",
        "connect_timeout": 3,
    }


def test_browser_specific_database_url_enables_store_without_shared_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("UCOS_BROWSER_STATE_DATABASE_URL", "postgresql://session-db.example/test")
    monkeypatch.setenv("UCOS_BROWSER_STATE_ENCRYPTION_KEY", "configured-key")
    assert persistence.is_configured() is True



def test_database_self_test_round_trips_encrypted_state_and_cleans_up(encrypted_store):
    rows, _key = encrypted_store
    assert persistence.self_test() is True
    assert rows == {}


def test_startup_self_test_failure_stops_service_when_durability_required(monkeypatch):
    monkeypatch.setenv("UCOS_BROWSER_SESSION_SELF_TEST", "true")
    monkeypatch.setenv("UCOS_BROWSER_REQUIRE_DURABLE_PROFILE", "true")

    def fail():
        raise RuntimeError("simulated Neon connection failure")

    monkeypatch.setattr(browser_server.profile_persistence, "self_test", fail)
    with pytest.raises(RuntimeError, match="startup self-test failed"):
        browser_server._run_profile_persistence_startup_self_test()


def test_startup_self_test_is_opt_in_when_durability_is_not_required(monkeypatch):
    monkeypatch.delenv("UCOS_BROWSER_SESSION_SELF_TEST", raising=False)
    monkeypatch.delenv("UCOS_BROWSER_REQUIRE_DURABLE_PROFILE", raising=False)

    def should_not_run():
        raise AssertionError("self-test must remain opt-in outside durable-required mode")

    monkeypatch.setattr(browser_server.profile_persistence, "self_test", should_not_run)
    browser_server._run_profile_persistence_startup_self_test()



def test_new_browser_runtime_restores_saved_neon_state_on_each_creation(monkeypatch, tmp_path):
    saved_state = {
        "cookies": [{
            "name": "session",
            "value": "restored-cookie",
            "domain": ".example.test",
            "path": "/",
            "expires": -1,
            "httpOnly": True,
            "secure": True,
            "sameSite": "Lax",
        }],
        "origins": [{
            "origin": "https://example.test",
            "localStorage": [{"name": "access", "value": "restored-local-storage"}],
        }],
    }
    load_calls = []
    contexts = []

    class FakePage:
        def __init__(self):
            self.timeout = None

        def set_default_timeout(self, timeout):
            self.timeout = timeout

        def is_closed(self):
            return False

    class FakeContext:
        def __init__(self):
            self.cookies = []
            self.scripts = []
            self.routes = []
            self.pages = [FakePage()]

        def route(self, pattern, handler):
            self.routes.append((pattern, handler))

        def add_cookies(self, cookies):
            self.cookies.extend(cookies)

        def add_init_script(self, script=None, path=None):
            self.scripts.append(script)

        def close(self):
            return None

        def new_page(self):
            page = FakePage()
            self.pages.append(page)
            return page

    class FakeChromium:
        def launch_persistent_context(self, **kwargs):
            assert kwargs["headless"] is True
            context = FakeContext()
            contexts.append(context)
            return context

    class FakePlaywright:
        def __init__(self):
            self.chromium = FakeChromium()

        def stop(self):
            return None

    class FakePlaywrightFactory:
        def start(self):
            return FakePlaywright()

    monkeypatch.setitem(
        sys.modules,
        "playwright.sync_api",
        SimpleNamespace(sync_playwright=lambda: FakePlaywrightFactory()),
    )
    monkeypatch.setattr(browser_server, "_profile_dir", lambda _ref: (str(tmp_path), False))
    monkeypatch.setattr(persistence, "is_configured", lambda: True)

    def load(profile_ref):
        load_calls.append(profile_ref)
        return saved_state

    monkeypatch.setattr(persistence, "load_profile_state", load)
    monkeypatch.setenv("UCOS_BROWSER_STATE_ENCRYPTION_KEY", "test-key")
    previous_runtime = browser_server._BROWSER_RUNTIME
    browser_server._BROWSER_RUNTIME = None
    try:
        first, created = browser_server._get_browser_runtime("amazon-primary", 5000)
        assert created is True
        assert first["persistent_profile"] is True
        assert first["profile_persistence_backend"] == "neon_postgres"
        assert contexts[0].cookies == saved_state["cookies"]
        assert "restored-local-storage" in contexts[0].scripts[0]
        assert len(contexts[0].routes) == 1
        assert contexts[0].routes[0][0] == "**/*"

        browser_server._close_browser_runtime()
        second, recreated = browser_server._get_browser_runtime("amazon-primary", 5000)
        assert recreated is True
        assert second["persistent_profile"] is True
        assert contexts[1].cookies == saved_state["cookies"]
        assert "restored-local-storage" in contexts[1].scripts[0]
        assert load_calls == ["amazon-primary", "amazon-primary"]
    finally:
        browser_server._close_browser_runtime()
        browser_server._BROWSER_RUNTIME = previous_runtime
