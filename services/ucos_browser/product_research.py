"""Provider-neutral product research contract and adapter registry.

This module deliberately contains no scraping implementation. Providers must
be explicitly registered and must enforce their own access, licensing, and
affiliate-link rules before returning data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import ipaddress
import re
from typing import Any, Callable
from urllib.parse import urlsplit


ALLOWED_FIELDS = frozenset({
    "title", "price", "currency", "product_url", "image_url",
    "category", "brand", "specifications", "availability",
})
MAX_QUERY_LENGTH = 500
MAX_RESULTS = 20
MAX_TEXT_FIELD = 10_000
MAX_EVIDENCE_BYTES = 16_384
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_MARKETPLACE = re.compile(r"^[a-z]{2}(?:-[a-z]{2})?$", re.IGNORECASE)


@dataclass(frozen=True)
class ResearchRequest:
    source: str
    marketplace: str
    search_query: str | None = None
    product_url: str | None = None
    fields: tuple[str, ...] = tuple(sorted(ALLOWED_FIELDS))
    limit: int = 10
    require_affiliate_link: bool = True


@dataclass
class ProductRecord:
    title: str | None = None
    price: str | None = None
    currency: str | None = None
    product_url: str | None = None
    image_url: str | None = None
    category: str | None = None
    brand: str | None = None
    specifications: dict[str, Any] = field(default_factory=dict)
    availability: str | None = None
    affiliate_link: str | None = None
    affiliate_link_status: str = "unavailable"
    evidence: dict[str, Any] = field(default_factory=dict)


class ProviderNotConfigured(RuntimeError):
    pass


class ProviderAccessDenied(RuntimeError):
    """The configured provider rejected or does not authorize this request."""


class ProviderRateLimited(RuntimeError):
    """The provider throttled the request; callers may retry later."""


class ProviderTemporaryFailure(RuntimeError):
    """The provider is temporarily unavailable."""


_ADAPTERS: dict[str, Callable[[ResearchRequest], list[ProductRecord]]] = {}


def register_adapter(source: str, adapter: Callable[[ResearchRequest], list[ProductRecord]]) -> None:
    key = str(source or "").strip().lower()
    if not key or len(key) > 64 or not key.replace("-", "").replace("_", "").isalnum():
        raise ValueError("source must be a short alphanumeric identifier")
    if not callable(adapter):
        raise ValueError("adapter must be callable")
    _ADAPTERS[key] = adapter


def unregister_adapter(source: str) -> None:
    _ADAPTERS.pop(str(source or "").strip().lower(), None)


def validate_request(payload: dict[str, Any]) -> ResearchRequest:
    if not isinstance(payload, dict):
        raise ValueError("request body must be an object")
    source = str(payload.get("source", "")).strip().lower()
    if not _IDENTIFIER.fullmatch(source):
        raise ValueError("source must be a short alphanumeric identifier")
    marketplace = str(payload.get("marketplace", "")).strip().lower()
    if not _MARKETPLACE.fullmatch(marketplace):
        raise ValueError("marketplace must be a valid region code such as US or en-gb")
    query = payload.get("search_query")
    product_url = payload.get("product_url")
    if query is not None:
        if not isinstance(query, str) or not query.strip() or len(query.strip()) > MAX_QUERY_LENGTH:
            raise ValueError("search_query must be 1..500 characters")
        query = query.strip()
    if product_url is not None:
        if not isinstance(product_url, str) or len(product_url) > 2048:
            raise ValueError("product_url must be a URL string <= 2048 characters")
        product_url = product_url.strip()
        parsed = urlsplit(product_url)
        hostname = (parsed.hostname or "").rstrip(".").lower()
        try:
            ipaddress.ip_address(hostname.strip("[]"))
            is_ip_literal = True
        except ValueError:
            is_ip_literal = False
        if (parsed.scheme != "https" or not hostname or parsed.username or parsed.password
                or parsed.port or hostname == "localhost" or hostname.endswith(".localhost")
                or is_ip_literal):
            raise ValueError("product_url must be an HTTPS public-domain URL without credentials or a port")
    if bool(query) == bool(product_url):
        raise ValueError("provide exactly one of search_query or product_url")
    fields = payload.get("fields", sorted(ALLOWED_FIELDS))
    if not isinstance(fields, list) or not fields or len(fields) > len(ALLOWED_FIELDS):
        raise ValueError("fields must be a non-empty list of supported fields")
    if any(not isinstance(item, str) or item not in ALLOWED_FIELDS for item in fields):
        raise ValueError("fields contain an unsupported field")
    if len(set(fields)) != len(fields):
        raise ValueError("fields must not contain duplicates")
    limit = payload.get("limit", 10)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_RESULTS:
        raise ValueError("limit must be an integer from 1 to 20")
    require_link = payload.get("require_affiliate_link", True)
    if not isinstance(require_link, bool):
        raise ValueError("require_affiliate_link must be a boolean")
    return ResearchRequest(
        source=source, marketplace=marketplace, search_query=query,
        product_url=product_url, fields=tuple(fields), limit=limit,
        require_affiliate_link=require_link,
    )


def _validate_provider_url(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError(f"provider returned an invalid {field_name}")
    parsed = urlsplit(value.strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port:
        raise ValueError(f"provider returned a non-HTTPS or credential-bearing {field_name}")
    return value.strip()


def _bounded_text(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > MAX_TEXT_FIELD:
        raise ValueError(f"provider returned an invalid or oversized {field_name}")
    return value


def _record_to_dict(record: ProductRecord, request: ResearchRequest) -> dict[str, Any]:
    if not isinstance(record, ProductRecord):
        raise ValueError("provider returned an invalid product record")
    if not isinstance(record.evidence, dict):
        raise ValueError("provider returned invalid evidence")
    result = {name: getattr(record, name) for name in request.fields}
    for name in ("title", "price", "currency", "category", "brand", "availability"):
        if name in result:
            result[name] = _bounded_text(result[name], name)
    if "specifications" in result:
        specs = result["specifications"]
        if not isinstance(specs, dict) or len(str(specs).encode("utf-8")) > MAX_EVIDENCE_BYTES:
            raise ValueError("provider returned invalid or oversized specifications")
    if len(str(record.evidence).encode("utf-8")) > MAX_EVIDENCE_BYTES:
        raise ValueError("provider returned oversized evidence")
    if "product_url" in result:
        result["product_url"] = _validate_provider_url(result["product_url"], "product_url")
    if "image_url" in result:
        result["image_url"] = _validate_provider_url(result["image_url"], "image_url")
    link_statuses = {"provider_confirmed", "unverified", "unavailable", "not_supported"}
    if record.affiliate_link_status not in link_statuses:
        raise ValueError("provider returned an unsupported affiliate_link_status")
    affiliate_link = _validate_provider_url(record.affiliate_link, "affiliate_link")
    if record.affiliate_link_status != "provider_confirmed":
        affiliate_link = None
    result["affiliate_link"] = affiliate_link
    result["affiliate_link_status"] = record.affiliate_link_status
    result["evidence"] = record.evidence
    missing = [name for name in request.fields if result.get(name) is None]
    if request.require_affiliate_link and not affiliate_link:
        missing.append("affiliate_link")
    return {"product": result, "missing_fields": missing,
            "status": "completed" if not missing else "partial"}


def research(payload: dict[str, Any]) -> dict[str, Any]:
    request = validate_request(payload)
    adapter = _ADAPTERS.get(request.source)
    if adapter is None:
        raise ProviderNotConfigured(f"product research source is not configured: {request.source}")
    records = adapter(request)
    if not isinstance(records, list):
        raise ValueError("provider adapter must return a list")
    if len(records) > request.limit:
        records = records[:request.limit]
    products = [_record_to_dict(record, request) for record in records]
    return {
        "status": "completed" if products and all(p["status"] == "completed" for p in products) else "partial",
        "source": request.source,
        "marketplace": request.marketplace,
        "query": request.search_query,
        "products": products,
        "result_count": len(products),
        "warnings": [] if products else ["provider returned no products"],
        "customer_reviews_collected": False,
    }
