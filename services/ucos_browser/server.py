"""UCOS Personal Browser worker.

A bounded, authenticated Playwright browser worker for UCOS. It executes
explicit navigation/extraction actions and returns structured evidence.
It does not accept credentials, arbitrary JavaScript, file uploads, or
CAPTCHA/anti-bot bypass instructions.
"""
from __future__ import annotations

import hmac
import ipaddress
import json
import logging
import math
import os
import socket
import time
import threading
import re
import uuid
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

try:
    from . import profile_persistence
except ImportError:  # direct execution or tests importing server.py by file path
    try:
        import profile_persistence
    except ImportError:
        import importlib.util
        _profile_module_path = Path(__file__).with_name("profile_persistence.py")
        _profile_spec = importlib.util.spec_from_file_location(
            "ucos_browser_profile_persistence", _profile_module_path
        )
        if _profile_spec is None or _profile_spec.loader is None:
            raise RuntimeError("UCOS browser profile persistence module is unavailable")
        profile_persistence = importlib.util.module_from_spec(_profile_spec)
        _profile_spec.loader.exec_module(profile_persistence)

try:
    from . import product_research
except ImportError:  # direct file-path imports used by the service's test harness
    try:
        import product_research
    except ImportError:
        import importlib.util
        _research_module_path = Path(__file__).with_name("product_research.py")
        _research_spec = importlib.util.spec_from_file_location(
            "ucos_browser_product_research", _research_module_path
        )
        if _research_spec is None or _research_spec.loader is None:
            raise RuntimeError("UCOS product research module is unavailable")
        import sys
        product_research = importlib.util.module_from_spec(_research_spec)
        sys.modules[_research_spec.name] = product_research
        _research_spec.loader.exec_module(product_research)


LOG = logging.getLogger("ucos.browser")
MAX_ACTIONS = 20
MAX_TEXT = 200_000
MAX_LINKS = 2_000
DEFAULT_TIMEOUT_MS = 30_000
_BROWSER_SLOTS = threading.BoundedSemaphore(1)
_SESSION_LOCK = threading.RLock()
_BROWSER_RUNTIME = None
SESSION_IDLE_TTL_SECONDS = 15 * 60


def _is_public_host(hostname: str) -> bool:
    host = hostname.strip("[]").lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        return False
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("target host could not be resolved") from exc
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        if addr.is_loopback or addr.is_private or addr.is_link_local or addr.is_reserved or addr.is_multicast:
            return False
    return True


def validate_url(value: str) -> str:
    url = str(value or "").strip()
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("url must be an absolute HTTP(S) URL")
    if not _is_public_host(parsed.hostname):
        raise ValueError("private or local network targets are blocked")
    return url


def _assert_public_page(page) -> None:
    validate_url(page.url)


def _guard_browser_request(route) -> None:
    """Apply the public-network URL policy to every browser network request.

    This covers redirects and subresources as well as top-level navigation.
    Network-level egress controls are still required to eliminate DNS-rebinding
    and resolution-to-connect time-of-check/time-of-use gaps.
    """
    try:
        validate_url(route.request.url)
    except (TypeError, ValueError):
        route.abort("blockedbyclient")
        return
    route.continue_()


_AMAZON_MARKETPLACE_DOMAINS = {
    "amazon.com", "amazon.co.uk", "amazon.de", "amazon.fr", "amazon.ca",
    "amazon.co.jp", "amazon.in", "amazon.it", "amazon.es", "amazon.nl",
    "amazon.se", "amazon.pl", "amazon.com.au", "amazon.com.br", "amazon.com.mx",
    "amazon.com.be", "amazon.ae", "amazon.sa", "amazon.sg", "amazon.com.tr",
    "amazon.eg",
}


def _is_amazon_affiliate_link(value: str) -> bool:
    """Accept only HTTPS Amazon Associates links, not ordinary product URLs."""
    try:
        parsed = urlsplit(str(value or "").strip())
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme != "https" or not host:
            return False
        if parsed.username or parsed.password or parsed.port:
            return False
        if host == "amzn.to":
            return bool(parsed.path.strip("/"))
        is_marketplace = any(
            host in {domain, "www." + domain}
            for domain in _AMAZON_MARKETPLACE_DOMAINS
        )
        tags = parse_qs(parsed.query, keep_blank_values=False).get("tag", [])
        return is_marketplace and any(str(tag).strip() for tag in tags)
    except (TypeError, ValueError):
        return False


_AFFILIATE_CLIPBOARD_CANDIDATE_SCRIPT = """() => {
    // Accept only a recent clipboard write observed by our Amazon
    // SiteStripe capture hook. DOM links/inputs and selected text
    // are not provenance: they may contain stale or unrelated URLs.
    const state = window.__ucosAffiliateClipboardState;
    if (!state || typeof state.text !== 'string' || !state.text.trim()) return [];
    const ageMs = Date.now() - Number(state.updatedAt || 0);
    const source = String(state.source || '');
    const validSource = source === 'clipboard.writeText'
        || source === 'clipboard.write'
        || source === 'document.execCommand';
    if (!validSource || !Number.isFinite(ageMs) || ageMs < 0 || ageMs > 300000) return [];
    return [state.text.trim()];
}"""


_AFFILIATE_CLIPBOARD_CAPTURE_SCRIPT = r"""
(() => {
  const host = String(location.hostname || '').toLowerCase();
  const amazonMarketplaceDomains = [
    'amazon.com', 'amazon.co.uk', 'amazon.de', 'amazon.fr', 'amazon.ca',
    'amazon.co.jp', 'amazon.in', 'amazon.it', 'amazon.es', 'amazon.nl',
    'amazon.se', 'amazon.pl', 'amazon.com.au', 'amazon.com.br', 'amazon.com.mx',
    'amazon.com.be', 'amazon.ae', 'amazon.sa', 'amazon.sg', 'amazon.com.tr',
    'amazon.eg'
  ];
  const amazonHost = host === 'amzn.to' || amazonMarketplaceDomains.some(
    domain => host === domain || host.endsWith('.' + domain)
  );
  if (!amazonHost || window.__ucosAffiliateClipboardInstalled) return;
  const state = { text: '', source: '', updatedAt: 0 };
  Object.defineProperty(window, '__ucosAffiliateClipboardState', {
    configurable: false, enumerable: false, value: state
  });
  Object.defineProperty(window, '__ucosAffiliateClipboardInstalled', {
    configurable: false, enumerable: false, value: true
  });
  const remember = (value, source) => {
    if (typeof value !== 'string') return;
    const text = value.trim();
    if (!text) return;
    state.text = text;
    state.source = source;
    state.updatedAt = Date.now();
  };
  const shim = {
    writeText: async value => { remember(String(value ?? ''), 'clipboard.writeText'); },
    readText: async () => state.text,
    write: async items => {
      for (const item of (items || [])) {
        try {
          if (item && item.types && item.types.includes('text/plain')) {
            const blob = await item.getType('text/plain');
            remember(await blob.text(), 'clipboard.write');
          }
        } catch (_) {}
      }
    },
    read: async () => []
  };
  try {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true, enumerable: true, value: shim
    });
  } catch (_) {
    try {
      Object.defineProperty(navigator.clipboard, 'writeText', {
        configurable: true, value: shim.writeText
      });
    } catch (_) {}
  }
  try {
    const originalExecCommand = Document.prototype.execCommand;
    Document.prototype.execCommand = function(command, ...args) {
      if (String(command).toLowerCase() === 'copy') {
        let text = '';
        const active = document.activeElement;
        if (active && /^(INPUT|TEXTAREA)$/.test(active.tagName)) {
          const value = String(active.value || '');
          const start = active.selectionStart;
          const end = active.selectionEnd;
          text = Number.isInteger(start) && Number.isInteger(end) && end > start
            ? value.slice(start, end) : value;
        }
        if (!text) text = String(window.getSelection ? window.getSelection() : '');
        remember(text, 'document.execCommand');
        return true;
      }
      return originalExecCommand.apply(this, [command, ...args]);
    };
  } catch (_) {}
})();
"""


def _focused_element_state(page) -> dict:
    """Return best-effort focus metadata without failing a successful navigation click."""
    try:
        return page.evaluate("""() => {
            const e = document.activeElement;
            const tag = (e?.tagName || '').toLowerCase();
            const type = (e?.getAttribute('type') || '').toLowerCase();
            const nonTextInputTypes = new Set([
                'button', 'submit', 'reset', 'checkbox', 'radio', 'file', 'image', 'hidden'
            ]);
            const editable = !!e && (
                e.isContentEditable ||
                tag === 'textarea' ||
                (tag === 'input' && !nonTextInputTypes.has(type))
            );
            return {
                editable,
                tag,
                type,
                password: tag === 'input' && type === 'password',
                placeholder: e?.getAttribute('placeholder') || '',
                label: e?.getAttribute('aria-label') || e?.getAttribute('name') || ''
            };
        }""".strip())
    except Exception as exc:
        # A click or Enter may navigate and destroy the old execution context.
        # Focus details only drive the optional typing panel; they must not
        # turn a completed click/navigation into a failed browser task.
        LOG.debug(
            "browser focus metadata unavailable after page transition (%s)",
            type(exc).__name__,
        )
        return {
            "editable": False,
            "tag": "",
            "type": "",
            "password": False,
            "placeholder": "",
            "label": "",
            "unavailable": True,
        }


def _resolve_form_selector(page, selector: str):
    """Resolve a user-supplied form locator without masking Playwright errors."""
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    requested = selector.strip()
    if not requested or len(requested) > 500:
        raise ValueError("selector is required and must be <= 500 chars")

    # Keep the caller's selector first, then use stable semantic fallbacks for
    # known login controls. No CAPTCHA or anti-bot control is bypassed.
    candidates = [(requested, page.locator(requested).first)]
    if requested == "#ap_email":
        candidates += [
            ("input#ap_email", page.locator("input#ap_email").first),
            ("input[name='email']", page.locator("input[name='email']").first),
            ("input[type='email']", page.locator("input[type='email']").first),
            ("label:has-text('Email')", page.get_by_label(re.compile(r"email", re.I)).first),
        ]
    elif requested == "#ap_password":
        candidates += [
            ("input#ap_password", page.locator("input#ap_password").first),
            ("input[name='password']", page.locator("input[name='password']").first),
            ("input[type='password']", page.locator("input[type='password']").first),
            ("label:has-text('Password')", page.get_by_label(re.compile(r"password", re.I)).first),
        ]
    elif requested == "#signInSubmit":
        candidates += [
            ("input#signInSubmit", page.locator("input#signInSubmit").first),
            ("button#signInSubmit", page.locator("button#signInSubmit").first),
            ("input[type='submit']", page.locator("input[type='submit']").first),
            ("button[type='submit']", page.locator("button[type='submit']").first),
        ]

    last_error = None
    for candidate, locator in candidates:
        try:
            locator.wait_for(state="visible", timeout=3_000)
            return locator, candidate
        except (PlaywrightTimeoutError, PlaywrightError) as exc:
            last_error = exc
            continue

    raise ValueError(
        f"selector not found or not visible on current page: {requested}; "
        "use Inspect to identify the current form control"
    ) from last_error


def _profile_ref(value: str) -> str:
    ref = re.sub(r"[^A-Za-z0-9._-]", "-", str(value or "").strip())
    if not ref or len(ref) > 80:
        raise ValueError("profile_ref must be 1..80 safe characters")
    return ref


def _profile_dir(profile_ref: str) -> tuple[str, bool]:
    configured = os.getenv("UCOS_BROWSER_PROFILE_DIR", "").strip()
    durable_required = profile_persistence.durable_required()
    state_store_configured = profile_persistence.is_configured()
    if durable_required and not configured and not state_store_configured:
        raise RuntimeError(
            "durable browser profile storage is required; configure UCOS_BROWSER_PROFILE_DIR "
            "to a persistent volume or set DATABASE_URL and UCOS_BROWSER_STATE_ENCRYPTION_KEY"
        )
    root = Path(configured or "/var/data/ucos-browser/profiles")
    path = root / _profile_ref(profile_ref)
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        # A writable default path does not prove that Render mounted durable storage.
        return str(path), bool(configured)
    except OSError as exc:
        if configured:
            raise RuntimeError("configured browser profile directory is not writable") from exc
        if durable_required and not state_store_configured:
            raise RuntimeError(
                "durable browser profile storage is required; configure UCOS_BROWSER_PROFILE_DIR "
                "to a persistent volume or set DATABASE_URL and UCOS_BROWSER_STATE_ENCRYPTION_KEY"
            ) from exc
        fallback = Path("/tmp/ucos-browser/profiles") / _profile_ref(profile_ref)
        fallback.mkdir(parents=True, exist_ok=True)
        if state_store_configured:
            LOG.info(
                "local Chromium profile path %s is not writable; using ephemeral runtime profile %s "
                "with encrypted Postgres session snapshots",
                root,
                fallback,
            )
        else:
            LOG.warning(
                "browser profile storage %s is not writable; using ephemeral fallback %s",
                root,
                fallback,
            )
        return str(fallback), False


def _amazon_agent_user_agent() -> str | None:
    """Return an explicitly identified Amazon-agent UA, or fail closed."""
    value = os.getenv("UCOS_AMAZON_AGENT_USER_AGENT", "").strip()
    if not value:
        return None
    if len(value) > 256 or "\r" in value or "\n" in value:
        return None
    if "Agent/UCOSPersonalBrowser" not in value:
        return None
    return value


def _close_browser_runtime_locked() -> None:
    global _BROWSER_RUNTIME
    runtime = _BROWSER_RUNTIME
    _BROWSER_RUNTIME = None
    if not runtime:
        return
    try:
        runtime["context"].close()
    except Exception:
        LOG.exception("failed to close browser context")
    try:
        runtime["pw"].stop()
    except Exception:
        LOG.exception("failed to stop Playwright runtime")


def _close_browser_runtime() -> None:
    with _SESSION_LOCK:
        _close_browser_runtime_locked()


def _get_browser_runtime(profile_ref: str, timeout: int) -> tuple[dict, bool]:
    global _BROWSER_RUNTIME
    now = time.monotonic()
    with _SESSION_LOCK:
        runtime = _BROWSER_RUNTIME
        if runtime and (
            runtime["profile_ref"] != profile_ref
            or now - runtime["last_used"] > SESSION_IDLE_TTL_SECONDS
        ):
            _close_browser_runtime_locked()
            runtime = None

        if runtime:
            page = runtime["page"]
            if page.is_closed():
                page = runtime["context"].new_page()
                runtime["page"] = page
            page.set_default_timeout(timeout)
            runtime["last_used"] = now
            return runtime, False

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Playwright is required by the UCOS Personal Browser worker") from exc

        profile_dir, disk_persistent = _profile_dir(profile_ref)
        state_store_enabled = profile_persistence.is_configured()
        saved_state = profile_persistence.load_profile_state(profile_ref) if state_store_enabled else None
        pw = sync_playwright().start()
        try:
            context_options = {
                "user_data_dir": profile_dir,
                "headless": True,
                "args": ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--no-zygote"],
                "ignore_https_errors": False,
                "accept_downloads": False,
            }
            # If the Amazon agent route is ever approved, every browser HTTP(S)
            # request must visibly identify this agent per Amazon Agent Terms.
            agent_ua = _amazon_agent_user_agent()
            if agent_ua:
                context_options["user_agent"] = agent_ua
            context = pw.chromium.launch_persistent_context(**context_options)
            if saved_state:
                profile_persistence.restore_storage_state(context, saved_state)
            # Enforce URL policy for redirects and every HTTP(S) subresource,
            # not only the initial top-level navigation.
            context.route("**/*", _guard_browser_request)
            # Preserve storage-restoration ordering; clipboard capture is additive.
            context.add_init_script(_AFFILIATE_CLIPBOARD_CAPTURE_SCRIPT)
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(timeout)
        except Exception:
            try:
                pw.stop()
            except Exception:
                LOG.exception("failed to stop Playwright after launch failure")
            raise

        runtime = {
            "profile_ref": profile_ref,
            "disk_persistent": disk_persistent,
            "state_store_enabled": state_store_enabled,
            "persistent_profile": bool(disk_persistent or state_store_enabled),
            "profile_persistence_backend": (
                "neon_postgres" if state_store_enabled and not disk_persistent
                else "disk+neon_postgres" if state_store_enabled
                else "disk" if disk_persistent
                else "ephemeral"
            ),
            "profile_dir": profile_dir,
            "pw": pw,
            "context": context,
            "page": page,
            "last_used": now,
        }
        _BROWSER_RUNTIME = runtime
        return runtime, True





def _execute_task_on_browser_thread(task: dict) -> dict:
    requested_url = str(task.get("url", "")).strip()
    url = validate_url(requested_url) if requested_url else ""
    profile_ref = _profile_ref(task.get("profile_ref", "default"))
    actions = task.get("actions") or [{"type": "extract"}]
    if not isinstance(actions, list) or len(actions) > MAX_ACTIONS:
        raise ValueError(f"actions must be a list of at most {MAX_ACTIONS} items")
    timeout = max(1_000, min(int(task.get("timeout_ms", DEFAULT_TIMEOUT_MS)), 60_000))
    started = time.monotonic()
    result = {"url": url, "title": "", "text": "", "links": [], "screenshot": None, "events": []}
    if not _BROWSER_SLOTS.acquire(blocking=False):
        raise RuntimeError("browser worker is busy; retry the task")
    try:
        runtime, created = _get_browser_runtime(profile_ref, timeout)
        page = runtime["page"]
        explicit_navigation = any(
            str(action.get("type", "")).strip().lower() == "navigate"
            for action in actions
            if isinstance(action, dict)
        )
        if created and url and not explicit_navigation:
            response = page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            _assert_public_page(page)
            result["events"].append({
                "type": "navigate",
                "status": response.status if response else None,
                "url": page.url,
                "reason": "session_init",
            })

        for action in actions:
            kind = str(action.get("type", "")).strip().lower()
            if kind == "navigate":
                target = validate_url(action.get("url", ""))
                response = page.goto(target, wait_until="domcontentloaded", timeout=timeout)
                _assert_public_page(page)
                result["events"].append({
                    "type": "navigate",
                    "status": response.status if response else None,
                    "url": page.url,
                })
            elif kind in {"back", "forward", "reload"}:
                if kind == "back":
                    response = page.go_back(wait_until="domcontentloaded", timeout=timeout)
                elif kind == "forward":
                    response = page.go_forward(wait_until="domcontentloaded", timeout=timeout)
                else:
                    response = page.reload(wait_until="domcontentloaded", timeout=timeout)
                _assert_public_page(page)
                result["events"].append({
                    "type": kind,
                    "status": response.status if response else None,
                    "url": page.url,
                })
            elif kind == "new_tab":
                if len(runtime["context"].pages) >= 10:
                    raise ValueError("maximum of 10 tabs per profile reached")
                page = runtime["context"].new_page()
                page.set_default_timeout(timeout)
                runtime["page"] = page
                target = str(action.get("url", "")).strip()
                if target:
                    response = page.goto(validate_url(target), wait_until="domcontentloaded", timeout=timeout)
                    _assert_public_page(page)
                result["events"].append({"type": "new_tab", "url": page.url})
            elif kind == "switch_tab":
                try:
                    index = int(action.get("index", -1))
                except (TypeError, ValueError):
                    raise ValueError("tab index must be an integer")
                pages = [p for p in runtime["context"].pages if not p.is_closed()]
                if index < 0 or index >= len(pages):
                    raise ValueError(f"tab index out of range; open tabs: 0..{max(0, len(pages)-1)}")
                page = pages[index]
                page.set_default_timeout(timeout)
                runtime["page"] = page
                result["events"].append({"type": "switch_tab", "index": index, "url": page.url})
            elif kind == "close_tab":
                pages = [p for p in runtime["context"].pages if not p.is_closed()]
                if len(pages) <= 1:
                    raise ValueError("cannot close the last open tab")
                page.close()
                pages = [p for p in runtime["context"].pages if not p.is_closed()]
                runtime["page"] = pages[-1]
                page = runtime["page"]
                result["events"].append({"type": "close_tab", "url": page.url})
            elif kind == "list_tabs":
                pages = [p for p in runtime["context"].pages if not p.is_closed()]
                result["tabs"] = [{"index": i, "url": p.url, "title": p.title()[:160], "active": p == page} for i, p in enumerate(pages)]
                result["events"].append({"type": "list_tabs", "count": len(pages)})
            elif kind in {"click_at", "tap"}:
                try:
                    x = float(action.get("x"))
                    y = float(action.get("y"))
                except (TypeError, ValueError):
                    raise ValueError("click_at requires numeric x and y viewport coordinates")
                if not math.isfinite(x) or not math.isfinite(y):
                    raise ValueError("click_at coordinates must be finite numbers")
                viewport = page.viewport_size or page.evaluate(
                    "() => ({width: window.innerWidth, height: window.innerHeight})"
                )
                width, height = int(viewport["width"]), int(viewport["height"])
                if x < 0 or y < 0 or x >= width or y >= height:
                    raise ValueError(
                        f"click_at coordinates must be within the {width}x{height} viewport"
                    )
                # Keep the agent action path latency-bounded: the request
                # interceptor already enforces the public-network policy for
                # navigation, redirects and subresources. Re-resolving the
                # current page hostname and evaluating focus metadata after a
                # click adds network/renderer round-trips and can stall while
                # the clicked page is navigating.
                page.mouse.click(x, y)
                result["viewport"] = {"width": width, "height": height}
                result["events"].append({
                    "type": "click_at", "x": round(x, 2), "y": round(y, 2)
                })
            elif kind == "scroll":
                try:
                    delta_x = float(action.get("delta_x", 0))
                    delta_y = float(action.get("delta_y", 0))
                except (TypeError, ValueError):
                    raise ValueError("scroll requires numeric delta_x and delta_y")
                if (
                    not math.isfinite(delta_x) or not math.isfinite(delta_y)
                    or abs(delta_x) > 5000 or abs(delta_y) > 5000
                ):
                    raise ValueError("scroll deltas must be finite and within +/-5000")
                page.mouse.wheel(delta_x, delta_y)
                page.wait_for_timeout(100)
                _assert_public_page(page)
                viewport = page.viewport_size or page.evaluate(
                    "() => ({width: window.innerWidth, height: window.innerHeight})"
                )
                result["viewport"] = {
                    "width": int(viewport["width"]), "height": int(viewport["height"])
                }
                result["focused"] = _focused_element_state(page)
                result["events"].append({
                    "type": "scroll",
                    "delta_x": round(delta_x, 2),
                    "delta_y": round(delta_y, 2)
                })
            elif kind == "type_text":
                text_value = str(action.get("text", ""))
                if len(text_value) > 10_000:
                    raise ValueError("type_text text must be <= 10000 characters")
                page.keyboard.insert_text(text_value)
                _assert_public_page(page)
                viewport = page.viewport_size or page.evaluate(
                    "() => ({width: window.innerWidth, height: window.innerHeight})"
                )
                result["viewport"] = {
                    "width": int(viewport["width"]), "height": int(viewport["height"])
                }
                result["focused"] = _focused_element_state(page)
                result["events"].append({"type": "type_text", "length": len(text_value)})
            elif kind == "press_key":
                key_value = str(action.get("key", "")).strip()
                if not key_value or len(key_value) > 100:
                    raise ValueError("press_key requires a key name up to 100 characters")
                page.keyboard.press(key_value)
                _assert_public_page(page)
                viewport = page.viewport_size or page.evaluate(
                    "() => ({width: window.innerWidth, height: window.innerHeight})"
                )
                result["viewport"] = {
                    "width": int(viewport["width"]), "height": int(viewport["height"])
                }
                result["focused"] = _focused_element_state(page)
                result["events"].append({"type": "press_key", "key": key_value})
            elif kind == "click":
                selector = str(action.get("selector", "")).strip()
                if not selector or len(selector) > 500:
                    raise ValueError("click selector is required and must be <= 500 chars")
                locator, resolved_selector = _resolve_form_selector(page, selector)
                locator.click()
                _assert_public_page(page)
                result["events"].append({"type": "click", "selector": resolved_selector})
            elif kind == "wait":
                ms = max(0, min(int(action.get("ms", 250)), 10_000))
                page.wait_for_timeout(ms)
            elif kind == "press":
                selector = str(action.get("selector", "")).strip()
                key = str(action.get("key", "")).strip()
                if not selector or not key or len(key) > 100:
                    raise ValueError("press requires selector and key")
                locator, resolved_selector = _resolve_form_selector(page, selector)
                locator.press(key)
                _assert_public_page(page)
                result["events"].append({
                    "type": "press",
                    "selector": resolved_selector,
                    "key": key,
                })
            elif kind == "fill":
                selector = str(action.get("selector", "")).strip()
                value = str(action.get("value", ""))
                if not selector or len(selector) > 500 or len(value) > 10_000:
                    raise ValueError("fill requires a valid selector and value <= 10000 chars")
                locator, resolved_selector = _resolve_form_selector(page, selector)
                locator.fill(value)
                _assert_public_page(page)
                result["events"].append({"type": "fill", "selector": resolved_selector})
            elif kind == "inspect":
                result["elements"] = page.locator("input,button,textarea,select,[role='button'],a").evaluate_all(
                    """els => els.slice(0, 200).map((e, i) => {
                        const out = {index:i, tag:e.tagName.toLowerCase(), text:(e.innerText||e.value||'').trim().slice(0,200)};
                        for (const a of ['id','name','type','aria-label','placeholder','role']) if (e.getAttribute(a)) out[a]=e.getAttribute(a);
                        if (e.id && /^[A-Za-z_][A-Za-z0-9_-]*$/.test(e.id)) out.selector='#'+e.id;
                        else if (e.name && /^[A-Za-z_][A-Za-z0-9_-]*$/.test(e.name)) out.selector=e.tagName.toLowerCase()+'[name="'+e.name+'"]';
                        return out;
                    })"""
                )
                result["title"] = page.title()[:500]
                result["final_url"] = page.url
            elif kind == "extract":
                text_value = page.locator("body").inner_text(timeout=timeout)
                result["text"] = text_value[:MAX_TEXT]
                result["title"] = page.title()[:500]
                hrefs = page.locator("a[href]").evaluate_all(
                    """els => els.slice(0, 2000).map(e => ({
                        text:(e.innerText||'').trim(),
                        href:e.href
                    }))"""
                )
                result["links"] = hrefs
            elif kind == "amazon_product_details":
                fields = action.get("fields") or ["title", "price", "rating", "availability"]
                if not isinstance(fields, list) or len(fields) > 10:
                    raise ValueError("amazon_product_details fields must be a list of at most 10 items")
                selectors = {
                    "title": ["#productTitle"],
                    "price": ["#corePrice_feature_div .a-offscreen", "#priceblock_ourprice", "#priceblock_dealprice", ".apexPriceToPay .a-offscreen"],
                    "rating": ["#acrPopover .a-icon-alt", "[data-hook='rating-out-of-text']"],
                    "availability": ["#availability span", "#availability"],
                }
                product = {}
                evidence = {}
                for field in fields:
                    if field not in selectors:
                        raise ValueError(f"unsupported product field: {field}")
                    value = None
                    matched = None
                    for selector in selectors[field]:
                        try:
                            locator = page.locator(selector).first
                            if locator.count() and locator.is_visible():
                                value = locator.inner_text(timeout=min(timeout, 2500)).strip()
                                if value:
                                    matched = selector
                                    break
                        except Exception:
                            continue
                    product[field] = value or None
                    evidence[field] = {"selector": matched, "present": bool(value)}
                result["product"] = product
                result["evidence"] = evidence
                result["verified_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                result["warnings"] = [
                    f"{field} unavailable on page" for field, value in product.items() if value is None
                ]
                result["events"].append({"type": "amazon_product_details_extracted"})
            elif kind == "affiliate_link":
                # The remote browser has no access to the user's phone clipboard.
                # Capture clipboard writes made by Amazon's link generator, then
                # return only a validated Amazon Associates URL to the local console.
                candidate_script = _AFFILIATE_CLIPBOARD_CANDIDATE_SCRIPT
                candidates = []
                frames = getattr(page, "frames", None)
                candidate_frames = frames if isinstance(frames, (list, tuple)) and frames else [page]
                for frame in candidate_frames:
                    try:
                        found = frame.evaluate(candidate_script)
                        if isinstance(found, list):
                            candidates.extend(found[:1200])
                    except Exception:
                        # A frame may navigate or be cross-origin/unavailable; other
                        # frames and the top page are still eligible candidates.
                        continue
                affiliate_link = next(
                    (
                        candidate.strip()
                        for candidate in candidates
                        if isinstance(candidate, str) and _is_amazon_affiliate_link(candidate)
                    ),
                    None,
                )
                if not affiliate_link:
                    raise ValueError(
                        "No Amazon affiliate link detected. Open Amazon Associates SiteStripe, "
                        "generate/copy the link there, then tap Capture affiliate link again."
                    )
                result["affiliate_link"] = affiliate_link
                result["events"].append({"type": "affiliate_link_captured"})
            elif kind == "extract_selector":
                selector = str(action.get("selector", "")).strip()
                if not selector or len(selector) > 500:
                    raise ValueError("extract_selector selector is required and must be <= 500 chars")
                result["text"] = page.locator(selector).first.inner_text(timeout=timeout)[:MAX_TEXT]
            elif kind == "screenshot":
                result["screenshot"] = page.screenshot(type="png", full_page=False).hex()
                viewport = page.viewport_size or page.evaluate(
                    "() => ({width: window.innerWidth, height: window.innerHeight})"
                )
                result["viewport"] = {
                    "width": int(viewport["width"]), "height": int(viewport["height"])
                }
            else:
                raise ValueError(f"unsupported browser action: {kind}")

        runtime["last_used"] = time.monotonic()
        if runtime["state_store_enabled"]:
            try:
                profile_persistence.save_profile_state(
                    profile_ref, runtime["context"].storage_state()
                )
            except Exception as exc:
                if runtime["disk_persistent"]:
                    LOG.warning(
                        "encrypted browser profile snapshot failed; continuing with durable disk (%s)",
                        type(exc).__name__,
                    )
                else:
                    raise RuntimeError(
                        "browser session state could not be persisted; profile durability is unconfirmed"
                    ) from exc
        result["profile_ref"] = profile_ref
        result["persistent_profile"] = runtime["persistent_profile"]
        result["profile_persistence_backend"] = runtime["profile_persistence_backend"]
        result["session_reused"] = not created
        result["final_url"] = page.url
        result["url"] = page.url
        result["duration_ms"] = int((time.monotonic() - started) * 1000)
        return result
    finally:
        _BROWSER_SLOTS.release()



# Playwright's synchronous API is thread-affine. HTTP requests may arrive on
# different ThreadingHTTPServer handler threads, but all browser operations
# must run on this one dedicated worker thread for the lifetime of the session.
from concurrent.futures import ThreadPoolExecutor

_BROWSER_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ucos-playwright")


def execute_task(task: dict) -> dict:
    future = _BROWSER_EXECUTOR.submit(_execute_task_on_browser_thread, task)
    return future.result()


def _shutdown_browser_worker() -> None:
    try:
        _BROWSER_EXECUTOR.submit(_close_browser_runtime).result(timeout=10)
    except Exception:
        LOG.exception("browser runtime shutdown failed")
    finally:
        _BROWSER_EXECUTOR.shutdown(wait=False, cancel_futures=True)


# ThreadPoolExecutor registers its own interpreter-shutdown hook before
# ordinary atexit handlers run. Register ours with threading so the Playwright
# context is closed on its owning worker thread before that executor is stopped.
threading._register_atexit(_shutdown_browser_worker)

def _record_task_run(task_id: str, task: dict, state: str, result=None, error=None, duration_ms=None) -> None:
    """Persist minimal browser task audit metadata; never store page text, screenshots, cookies, or credentials."""
    dsn = (
        os.getenv("UCOS_BROWSER_STATE_DATABASE_URL", "").strip()
        or os.getenv("DATABASE_URL", "").strip()
    )
    if not dsn:
        return
    try:
        import psycopg
        requested_host = urlsplit(str(task.get("url", "") or "")).hostname
        final_host = urlsplit(str((result or {}).get("final_url", "") or "")).hostname
        profile_ref = _profile_ref(task.get("profile_ref", "default"))
        persistent_profile = (result or {}).get("persistent_profile")
        with psycopg.connect(dsn, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS browser_task_runs (
                        task_id TEXT PRIMARY KEY,
                        profile_ref TEXT NOT NULL,
                        requested_host TEXT,
                        final_host TEXT,
                        state TEXT NOT NULL CHECK (state IN ('completed', 'rejected', 'failed')),
                        duration_ms INTEGER,
                        persistent_profile BOOLEAN,
                        error_type TEXT,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)
                cur.execute("""
                    INSERT INTO browser_task_runs
                        (task_id, profile_ref, requested_host, final_host, state,
                         duration_ms, persistent_profile, error_type)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (task_id) DO NOTHING
                """, (
                    task_id, profile_ref, requested_host, final_host, state,
                    duration_ms, persistent_profile, type(error).__name__ if error else None,
                ))
    except Exception as exc:
        # Audit persistence must not expose DSNs or interrupt browser execution.
        LOG.warning("browser task audit write failed (%s)", type(exc).__name__)




def _amazon_product_tool_task(payload: dict) -> dict:
    """Translate one agent tool request into a bounded Amazon browser workflow."""
    marketplace = str(payload.get("marketplace", "amazon.com")).strip().lower()
    allowed = {domain for domain in _AMAZON_MARKETPLACE_DOMAINS}
    if marketplace not in allowed:
        raise ValueError("marketplace must be a supported Amazon marketplace domain")
    product_url = str(payload.get("product_url", "")).strip()
    if not product_url:
        raise ValueError("product_url is required")
    parsed = urlsplit(product_url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port:
        raise ValueError("product_url must be a credential-free HTTPS URL on the selected Amazon marketplace")
    if host not in {marketplace, "www." + marketplace}:
        if host in {domain for domain in allowed} or host in {"www." + domain for domain in allowed}:
            raise ValueError("product_url marketplace does not match marketplace")
        raise ValueError("product_url must be an HTTPS URL on the selected Amazon marketplace")
    profile_ref = payload.get("profile_ref", "amazon-primary")
    if profile_ref != "amazon-primary":
        raise ValueError("this agent tool is restricted to the existing amazon-primary profile")

    requested_fields = payload.get("fields")
    if requested_fields is None:
        requested_fields = ["title", "price", "rating", "availability"]
    if not isinstance(requested_fields, list) or not requested_fields:
        raise ValueError("fields must be a non-empty list")
    if any(not isinstance(item, str) or not item.strip() for item in requested_fields):
        raise ValueError("each requested field must be a non-empty string")
    requested_fields = requested_fields[:]
    if len(requested_fields) > 5:
        raise ValueError("fields may contain at most 5 supported product fields")
    requested_generate_link = payload.get("generate_affiliate_link", True)
    if not isinstance(requested_generate_link, bool):
        raise ValueError("generate_affiliate_link must be a boolean")

    requested_fields = requested_fields or [
        "title", "price", "rating", "availability"
    ]
    supported_fields = {"title", "price", "rating", "availability"}
    fields = list(dict.fromkeys(item.strip() for item in requested_fields))
    unknown = sorted(set(fields) - supported_fields)
    if unknown:
        raise ValueError("unsupported product fields: " + ", ".join(unknown))

    actions = [
        {"type": "navigate", "url": product_url},
        {"type": "amazon_product_details", "fields": fields},
    ]
    if requested_generate_link:
        actions.append({"type": "affiliate_link"})
    raw = execute_task({
        "profile_ref": profile_ref,
        "timeout_ms": payload.get("timeout_ms", DEFAULT_TIMEOUT_MS),
        "actions": actions,
    })
    details = raw.get("product") or {}
    missing_fields = [field for field, value in details.items() if value is None]
    affiliate_link = raw.get("affiliate_link")
    affiliate_format_valid = bool(affiliate_link and _is_amazon_affiliate_link(affiliate_link))
    if requested_generate_link and not affiliate_format_valid:
        missing_fields.append("affiliate_link")
    complete = not missing_fields
    return {
        "status": "completed" if complete else "partial",
        "product": details,
        "affiliate_link": affiliate_link if affiliate_format_valid else None,
        "affiliate_link_format_valid": affiliate_format_valid,
        "affiliate_link_verification_scope": "format_only; redirect_destination_and_associates_account_not_verified",
        "missing_fields": missing_fields,
        "source_url": raw.get("final_url"),
        "verified_at": raw.get("verified_at"),
        "profile_ref": raw.get("profile_ref"),
        "session_reused": raw.get("session_reused"),
        "duration_ms": raw.get("duration_ms"),
        "evidence": raw.get("evidence", {}),
        "warnings": raw.get("warnings", []),
    }

def _authorized(headers, token_env: str = "UCOS_BROWSER_TOKEN") -> bool:
    """Authorize one explicitly scoped bearer token using constant-time comparison."""
    token = os.getenv(token_env, "").strip()
    supplied = str(headers.get("Authorization", ""))
    expected = f"Bearer {token}" if token else ""
    return bool(token) and hmac.compare_digest(supplied, expected)


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: dict) -> None:
        raw = json.dumps(body, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_HEAD(self):
        if self.path.rstrip("/") in {"", "/health", "/readyz"}:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_console(self):
        try:
            raw = Path(__file__).with_name("console.html").read_bytes()
        except OSError:
            self._send(500, {"error": "console unavailable"})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.rstrip("/") == "/readyz":
            # Public and dependency-light: Render can verify the HTTP server event
            # loop is accepting requests without triggering browser/DB work.
            self._send(200, {"status": "ok", "service": "ucos-personal-browser"})
            return
        if self.path.startswith("/session/health"):
            if not _authorized(self.headers):
                self._send(401, {"error": "authentication required"})
                return
            from urllib.parse import parse_qs
            query = parse_qs(urlsplit(self.path).query)
            try:
                profile_ref = _profile_ref(query.get("profile_ref", ["default"])[0])
                path, disk_persistent = _profile_dir(profile_ref)
                # Chromium scratch files are not evidence of durable profile initialization.
                has_disk_state = disk_persistent and any(Path(path).iterdir())
                state_store_enabled = profile_persistence.is_configured()
                has_saved_state = (
                    profile_persistence.has_profile_state(profile_ref) if state_store_enabled else False
                )
                persistent_profile = bool(disk_persistent or state_store_enabled)
            except (OSError, ValueError, RuntimeError):
                self._send(400, {"error": "invalid or unavailable browser profile"})
                return
            backend = (
                "neon_postgres" if state_store_enabled and not disk_persistent
                else "disk+neon_postgres" if state_store_enabled
                else "disk" if disk_persistent
                else "ephemeral"
            )
            self._send(200, {
                "status": "ok",
                "profile_ref": profile_ref,
                "persistent": persistent_profile,
                "persistence_backend": backend,
                "profile_initialized": bool(has_disk_state or has_saved_state),
                "authentication": "UNKNOWN",
            })
            return
        if self.path.rstrip("/") == "":
            self._serve_console()
            return
        if self.path.rstrip("/") == "/console":
            self._serve_console()
            return
        if self.path.rstrip("/") != "/health":
            self._send(404, {"error": "not found"})
            return
        if not _authorized(self.headers):
            self._send(401, {"error": "authentication required"})
            return
        self._send(200, {"status": "ok", "service": "ucos-personal-browser", "engine": "playwright-chromium"})

    def do_POST(self):
        route = self.path.rstrip("/")
        if route not in {"/execute", "/tool/amazon/product", "/tool/product/research"}:
            self._send(404, {"error": "not found"})
            return
        # The operator token is console-only. Agent tool routes use a
        # distinct credential so an agent cannot reuse its tool token against
        # the unrestricted operator browser endpoint (or vice versa).
        auth_env = "UCOS_BROWSER_AGENT_TOKEN" if route in {
            "/tool/amazon/product", "/tool/product/research"
        } else "UCOS_BROWSER_TOKEN"
        if not _authorized(self.headers, auth_env):
            self._send(401, {"error": "authentication required"})
            return
        if route == "/tool/amazon/product":
            approved = os.getenv("UCOS_AMAZON_AGENT_ACCESS_APPROVED", "false").strip().lower() in {"1", "true", "yes"}
            agent_ua = _amazon_agent_user_agent()
            if not approved or not agent_ua:
                self._send(403, {
                    "state": "blocked",
                    "error": "live Amazon agent access requires documented policy approval and an explicit Agent/UCOSPersonalBrowser User-Agent",
                })
                return
        task_id = uuid.uuid4().hex
        started = time.monotonic()
        payload = {}
        try:
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                raise ValueError("Content-Type must be application/json")
            if self.headers.get("Content-Encoding", "identity").strip().lower() not in {"", "identity"}:
                raise ValueError("compressed request bodies are not supported")
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > 1_000_000:
                raise ValueError("request body must be 1..1000000 bytes")
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                raise ValueError("request body must be an object")
            if route == "/tool/product/research":
                result = product_research.research(payload)
                duration_ms = int((time.monotonic() - started) * 1000)
                audit_task = {"profile_ref": "product-research", "url": payload.get("product_url", "")}
                _record_task_run(task_id, audit_task, "completed", result=result, duration_ms=duration_ms)
                self._send(200, {"state": "completed", "task_id": task_id, "result": result})
                return
            if route == "/tool/amazon/product":
                result = _amazon_product_tool_task(payload)
                audit_task = {
                    "profile_ref": result.get("profile_ref", "amazon-primary"),
                    "url": result.get("source_url", payload.get("product_url", "")),
                }
                duration_ms = int((time.monotonic() - started) * 1000)
                _record_task_run(task_id, audit_task, "completed", result=result, duration_ms=duration_ms)
                self._send(200, {"state": "completed", "task_id": task_id, "result": result})
                return
            result = execute_task(payload)
            duration_ms = int((time.monotonic() - started) * 1000)
            _record_task_run(task_id, payload, "completed", result=result, duration_ms=duration_ms)
            self._send(200, {"state": "completed", "task_id": task_id, "result": result})
        except product_research.ProviderAccessDenied as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            _record_task_run(task_id, {"profile_ref": "product-research"}, "rejected", error=exc, duration_ms=duration_ms)
            self._send(403, {"state": "blocked", "task_id": task_id, "error": "provider access denied"})
        except product_research.ProviderRateLimited as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            _record_task_run(task_id, {"profile_ref": "product-research"}, "failed", error=exc, duration_ms=duration_ms)
            self._send(429, {"state": "rate_limited", "task_id": task_id, "error": "provider rate limit reached"})
        except (product_research.ProviderNotConfigured, product_research.ProviderTemporaryFailure) as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            _record_task_run(task_id, {"profile_ref": "product-research"}, "rejected", error=exc, duration_ms=duration_ms)
            self._send(503, {"state": "unavailable", "task_id": task_id, "error": str(exc)})
        except (ValueError, TypeError) as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            if isinstance(payload, dict):
                _record_task_run(task_id, payload, "rejected", error=exc, duration_ms=duration_ms)
            self._send(400, {"state": "rejected", "task_id": task_id, "error": str(exc)})
        except Exception as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            if isinstance(payload, dict):
                _record_task_run(task_id, payload, "failed", error=exc, duration_ms=duration_ms)
            LOG.exception("browser task failed")
            self._send(502, {"state": "failed", "task_id": task_id, "error": str(exc)[:1000]})

    def log_message(self, fmt, *args):
        LOG.info("%s - %s", self.address_string(), fmt % args)


def _env_enabled(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in {"1", "true", "yes", "on"}


def _run_profile_persistence_startup_self_test() -> None:
    durable_required = profile_persistence.durable_required()
    run_self_test = _env_enabled("UCOS_BROWSER_SESSION_SELF_TEST")

    if run_self_test:
        try:
            profile_persistence.self_test()
            LOG.info("UCOS_BROWSER_SESSION_PERSISTENCE_SELF_TEST=PASS backend=encrypted_postgres")
        except Exception as exc:
            LOG.error(
                "UCOS_BROWSER_SESSION_PERSISTENCE_SELF_TEST=FAIL error_type=%s",
                type(exc).__name__,
            )
            if durable_required:
                raise RuntimeError(
                    "durable browser profile storage is required but its startup self-test failed"
                ) from exc

    if not durable_required:
        return

    # The generic self-test proves the DB/key pair can round-trip a fresh snapshot.
    # Validate the real named profile too, without logging cookies, localStorage values,
    # or any other session content. This catches encryption-key drift after redeploys.
    profile_ref = _profile_ref(
        os.getenv("UCOS_BROWSER_PERSISTENCE_CHECK_PROFILE", "amazon-primary")
    )
    try:
        saved_state = profile_persistence.load_profile_state(profile_ref)
    except Exception as exc:
        LOG.error(
            "UCOS_BROWSER_PERSISTENCE_STARTUP_VALIDATION=FAIL profile_ref=%s error_type=%s",
            profile_ref,
            type(exc).__name__,
        )
        raise RuntimeError(
            "durable browser profile storage is required but the saved profile could not be validated"
        ) from exc

    if saved_state is None:
        LOG.info(
            "UCOS_BROWSER_EXISTING_PROFILE_SNAPSHOT=NOT_FOUND profile_ref=%s",
            profile_ref,
        )
        return

    cookies = saved_state.get("cookies", [])
    origins = saved_state.get("origins", [])
    LOG.info(
        "UCOS_BROWSER_EXISTING_PROFILE_SNAPSHOT=DECRYPTABLE profile_ref=%s "
        "cookie_count=%d origin_count=%d",
        profile_ref,
        len(cookies) if isinstance(cookies, list) else 0,
        len(origins) if isinstance(origins, list) else 0,
    )


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    port = int(os.getenv("PORT", "10000"))
    if not os.getenv("UCOS_BROWSER_TOKEN", "").strip():
        raise RuntimeError("UCOS_BROWSER_TOKEN is required")
    _run_profile_persistence_startup_self_test()
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    LOG.info("UCOS Personal Browser listening on 0.0.0.0:%s", port)
    server.serve_forever()


if __name__ == "__main__":
    main()
