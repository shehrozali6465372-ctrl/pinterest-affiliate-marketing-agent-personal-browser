# UCOS Personal Browser — Agent Tool Contract

## Purpose

This service is one callable tool used by the Pinterest Affiliate Marketing Agent. The agent sends one product URL and requested fields; the browser reuses the protected Amazon account profile, reads visible product information, and returns structured evidence plus a real Associates link only when it has been captured from Amazon's own supported workflow.

The service is not a second agent. It does not choose products, generate content, create pins, schedule, or publish to Pinterest. The provider-neutral `POST /tool/product/research` contract supports either a search query or a product URL and routes only to explicitly registered provider adapters. It is the preferred integration boundary for non-Amazon providers; it does not scrape arbitrary websites or assume that public visibility grants reuse rights.

## Agent endpoint

`POST /tool/amazon/product` and `POST /tool/product/research` require `Authorization: Bearer <UCOS_BROWSER_AGENT_TOKEN>`. This token is separate from `UCOS_BROWSER_TOKEN`, which is reserved for the human operator console and generic `/execute` endpoint. Never give the agent the operator token. The Amazon route also returns HTTP 403 unless `UCOS_AMAZON_AGENT_ACCESS_APPROVED=true` and `UCOS_AMAZON_AGENT_USER_AGENT` contains `Agent/UCOSPersonalBrowser`; keep both disabled until the compliance gate is satisfied. The User-Agent is applied to the Playwright context.

Example request:

```json
{
  "profile_ref": "amazon-primary",
  "marketplace": "amazon.com",
  "product_url": "https://www.amazon.com/dp/B012345678",
  "fields": ["title", "price", "rating", "availability"],
  "generate_affiliate_link": true,
  "timeout_ms": 30000
}
```

Supported marketplaces are the explicit domains configured in the service's marketplace allow-list. Product URLs must be HTTPS and belong to the selected marketplace. Unknown fields and unsupported hosts are rejected before browser execution.

## Response

```json
{
  "status": "completed",
  "product": {
    "title": "Page-observed title",
    "price": "$19.99",
    "rating": "4.5 out of 5 stars",
    "availability": "In Stock"
  },
  "affiliate_link": "https://www.amazon.com/dp/B012345678?tag=approved-20",
  "affiliate_link_format_valid": true,
  "affiliate_link_verification_scope": "format_only; redirect_destination_and_associates_account_not_verified",
  "missing_fields": [],
  "source_url": "https://www.amazon.com/dp/B012345678",
  "verified_at": "2026-11-06T12:00:00Z",
  "profile_ref": "amazon-primary",
  "session_reused": true,
  "duration_ms": 1234,
  "evidence": {
    "title": {"selector": "#productTitle", "present": true}
  },
  "warnings": []
}
```

This is the response shape, not a claim that live Amazon currently returns these example values. `status` is `partial` whenever requested data or the requested Associates link is absent. Missing product fields are `null`; the service must never infer price, rating, or stock state. Customer reviews and review counts are outside this tool's extraction scope.

## Provider-neutral product research endpoint

`POST /tool/product/research` requires the same bearer authentication and JSON content type as the other tool endpoints. It accepts exactly one of `search_query` or `product_url`, a `source` adapter identifier, a marketplace, requested fields, a result limit (1–20), and a `require_affiliate_link` boolean. Supported fields are title, price, currency, product URL, image URL, category, brand, specifications, and availability. Customer review content and review counts are deliberately not supported.

The adapter registry is empty by default. A source must be explicitly registered in code and must enforce its own provider authorization, data license, rate limits, and affiliate-link rules. An unconfigured source returns HTTP 503; it never falls back to generic scraping. A provider response is normalized into product records with evidence, missing fields, and affiliate-link status. Input product URLs must be HTTPS public-domain URLs (no IP literals, localhost, credentials, or explicit ports); each future adapter must additionally enforce its own exact provider-domain allow-list and outbound network policy before fetching. Output URLs must be HTTPS and credential-free. Text, specifications, and evidence payloads are size-bounded. Provider authorization failures map to HTTP 403, throttling to HTTP 429, and unavailable providers to HTTP 503. The browser does not invent or append tracking tags.

Example request:

```json
{
  "source": "approved-catalog",
  "marketplace": "US",
  "search_query": "three tier spice rack",
  "fields": ["title", "price", "currency", "product_url", "image_url", "category", "brand", "specifications", "availability"],
  "limit": 10,
  "require_affiliate_link": true
}
```

No real provider adapter is configured by this implementation yet. The contract and adapter tests use a mocked provider; this proves request validation and normalization, not live product discovery or link generation.

## Amazon policy release gate

Read `AMAZON_COMPLIANCE_GATE.md` before enabling live Amazon traffic. The current endpoint is a local prototype only. Do not use Playwright scraping or autonomous SiteStripe interaction in production until the specific agent workflow is confirmed permitted and any required express written approval is obtained. Creators API is not an automatic workaround for product analysis/repurposing restrictions.

## Amazon link generation boundary

The browser accepts an affiliate URL only when it observes a recent clipboard write originating from the Amazon page in the authenticated session and the URL passes the configured Amazon/Associates-tag format check. The response field is `affiliate_link_format_valid`, not verified: it is a syntax/format check only. It does not prove redirect destination, tag ownership, or account attribution. `amzn.to` is accepted syntactically at this stage; redirect resolution and destination-tag verification are not implemented. The tool is restricted to the existing `amazon-primary` profile, and accepts only the exact marketplace host or its `www` host (not arbitrary subdomains).

The current clipboard hook captures Amazon-generated copy events. It does not yet prove that the service can autonomously open SiteStripe and trigger Get Link without manual interaction. This is an explicit production gate. Account challenges (CAPTCHA/MFA) must not be bypassed.

## Session and security

- The default account profile is `amazon-primary`; preserve its existing encrypted browser state.
- Only the browser service may read browser state. Never return cookies, storage state, credentials, or tokens.
- Keep the API bearer token private to the single trusted agent caller.
- Private/local network request targets are blocked by the browser request guard; host/container egress controls are still required for full DNS-rebinding protection.
- Use bounded request sizes, one browser worker, and the per-request timeout limit.
- The endpoint is read-only with respect to Amazon product data; it does not place orders, add items to cart, post reviews, or change account settings.

## Test and release status

- Unit/contract tests use mocked page output; they do not represent a live Amazon result.
- No live SiteStripe autonomous link-generation test has been completed.
- Live Amazon product extraction is blocked pending the compliance gate in `AMAZON_COMPLIANCE_GATE.md`.
- No real Pinterest Pin is created during tests.
- No Git push, Model 1 integration, or Render deploy is authorized by this contract.