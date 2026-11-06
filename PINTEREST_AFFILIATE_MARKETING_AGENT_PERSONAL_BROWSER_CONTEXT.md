# Pinterest Affiliate Marketing Agent Personal Browser — Master Context

Last updated: 2026-11-06
Repository: `/root/Pinterest-affiliate-marketing-agent-personal-browser`
Purpose: authoritative working context for this standalone browser service. Update this file after meaningful project changes. Verify before repeating work.

---

## 1. Project identity and purpose

**Project:** Pinterest Affiliate Marketing Agent Personal Browser
**Service identity:** UCOS Personal Browser / `ucos-personal-browser`
**Role:** a callable browser and product-research tool for the Pinterest Affiliate Marketing Agent. It is not a second autonomous agent.

The upstream Pinterest Affiliate Marketing Agent owns:
- Product strategy and selection decisions
- Content generation (Pin title, description, alt text and creative brief)
- Pinterest image generation/design
- Scheduling and Pinterest publishing through its controlled publishing gateway
- Affiliate campaign learning loop

This browser service owns:
- Controlled browser execution and authenticated browser-profile reuse
- Product research API contract and provider adapters
- Returning observed/authorized product data with evidence and missing-field reporting
- Passing through provider-issued affiliate links without inventing tracking tags

**Strict boundaries**
- Do not create, schedule, or publish Pinterest Pins from this service.
- Never publish a real Pin during testing.
- Do not upload or host images. Return permitted remote image URLs only.
- Do not fabricate product fields, product availability, affiliate links, tracking IDs, account approval, or test results. Unknown data stays null/partial.
- Do not expose passwords, cookies, browser storage state, API tokens, encryption keys, database URLs, or other secret values.
- Do not bypass CAPTCHA, MFA, anti-bot checks, or provider access controls.
- Do not integrate with Model 1 / the main agent until the standalone browser is ready and integration is explicitly approved.
- No commit, push, deployment, production environment change, or real Pin publication unless explicitly approved.

## 2. Repository and runtime details

| Item | Verified/current value |
|---|---|
| Local repository | `/root/Pinterest-affiliate-marketing-agent-personal-browser` |
| Git remote | `https://github.com/shehrozali6465372-ctrl/pinterest-affiliate-marketing-agent-personal-browser` |
| Working branch | `local/personal-browser-hardening` |
| Current HEAD observed | `246ba63d Reduce repository to standalone UCOS Personal Browser` |
| Render service name | `pinterest-affiliate-marketing-agent-personal-browser` |
| Render service URL | `https://ucos-personal-browser.onrender.com` |
| Runtime | Python service + Playwright Chromium persistent browser |
| Local environment file | `.env` at repository root; ignored/untracked; permissions previously checked as 600 |
| Browser profile reference | `amazon-primary` |

**Deployment caution:** an earlier inspection observed deployed commit `0fb134a1add5eb7c635765238e010d2166da90b9` and a Render source configuration pointing to `universal-content-operating-system` / `main`. These are historical observations only, not a current deployment verification. Do not assume the live Render service runs this local branch or current HEAD.

## 3. Account, provider and infrastructure references

These are non-secret identifiers and operational references. They do not prove ownership, access approval, or current live status.

### GitHub
- Repository: `shehrozali6465372-ctrl/pinterest-affiliate-marketing-agent-personal-browser`
- Remote URL is listed above.
- No push has been performed for the current local hardening work.

### Render
- Service name: `pinterest-affiliate-marketing-agent-personal-browser`
- Service URL: `https://ucos-personal-browser.onrender.com`
- Do not alter production environment variables or trigger a deploy without explicit approval.

### Neon — browser session persistence database
- Neon project ID: `billowing-grass-66503241`
- Database name: `ucos_browser_db`
- Browser persistence profile reference: `amazon-primary`
- Encrypted profile persistence was previously tested: the existing `amazon-primary` ciphertext decrypted using the configured encryption key. The check did not modify a database row.
- This browser database is separate from the main Pinterest Affiliate Marketing Agent / Model 1 Neon database. Never mix connection strings, credentials, schemas, or profile data across the two projects.
- Database connection URL and encryption key are secrets; keep them only in the secure environment, never in this context file.

### Browser / Amazon account state
- Stable browser profile reference: `amazon-primary`.
- Existing encrypted Amazon browser session/profile is stored through the browser persistence mechanism.
- Do not put a username, email, password, cookie, token or personal identifier in the profile reference.
- Amazon account email, Associates Store ID / Partner Tag, publisher account identity, and policy approval evidence have not been verified in this context. Do not invent them.
- Amazon live agent access remains disabled pending the policy gate described below.

### Environment variable names (values intentionally omitted)
Latest local `.env` audit checked key presence only; all 11 browser runtime keys are present and non-empty where required:
- `LOG_LEVEL`
- `PORT`
- `UCOS_BROWSER_PERSISTENCE_CHECK_PROFILE`
- `UCOS_BROWSER_PROFILE_DIR`
- `UCOS_BROWSER_REQUIRE_DURABLE_PROFILE`
- `UCOS_BROWSER_STATE_DATABASE_URL`
- `UCOS_BROWSER_STATE_ENCRYPTION_KEY`
- `UCOS_BROWSER_TOKEN` — operator/console token only
- `UCOS_BROWSER_AGENT_TOKEN` — present but intentionally empty until a separate agent credential is provisioned for Model 1 integration
- `UCOS_AMAZON_AGENT_ACCESS_APPROVED` — explicitly `false` (fail-closed)
- `UCOS_AMAZON_AGENT_USER_AGENT` — intentionally empty until policy approval and approved identity string exist

`DATABASE_URL` is supported only as a fallback; the dedicated `UCOS_BROWSER_STATE_DATABASE_URL` is configured. No Amazon Creators API credentials or Partner Tag are configured in this browser `.env`; do not invent or copy them from Model 1. File permissions verified as `0600`. Secret values were not printed or copied into this context file.

## 4. Architecture and implemented endpoints

### Browser execution
- Authenticated `POST /execute`
- Public `GET /readyz`
- Protected `GET /health` and `GET /session/health`
- Browser console at `/console` and root route
- Playwright Chromium persistent profile, bounded to one browser worker
- Browser profile snapshots use encrypted PostgreSQL persistence.
- Shutdown closes the Playwright context on its worker thread before executor shutdown.
- Browser request interceptor validates HTTP(S) requests and blocks private/local network targets. DNS rebinding / resolution-to-connect TOCTOU risk remains; host/container network egress controls are still required.

### Amazon product tool
- Authenticated `POST /tool/amazon/product`
- Restricted to the existing `amazon-primary` profile and configured marketplace hosts.
- Supported fields: title, price, rating, availability.
- Review count/content are not in scope.
- Affiliate link capture depends on a recent clipboard write originating from an Amazon page/frame (maximum age 5 minutes), then URL/tag format validation.
- Response field `affiliate_link_format_valid` means format validation only. It does NOT verify redirect destination, Associates account ownership, or final attribution.
- Autonomous SiteStripe/Get Link trigger and redirect-destination verification are not implemented.
- Route fails closed unless `UCOS_AMAZON_AGENT_ACCESS_APPROVED=true` and an explicit User-Agent containing `Agent/UCOSPersonalBrowser` are configured. These flags must remain unset until the policy gate is satisfied.

### Provider-neutral Product Research Engine
- Module: `services/ucos_browser/product_research.py`
- Endpoint: authenticated `POST /tool/product/research`
- Tests: `tests/test_product_research.py`
- Documentation: `docs/architecture/AGENT_TOOL_CONTRACT.md`
- Adapter registry is empty by default. A provider must be explicitly registered; there is no generic website scraping fallback.
- Request accepts exactly one of `search_query` or `product_url`, a source identifier, marketplace region code, requested fields, limit 1–20 and `require_affiliate_link`.
- Supported fields: title, price, currency, product_url, image_url, category, brand, specifications, availability.
- Review content and review counts are unsupported.
- Product input URLs must be HTTPS public-domain URLs without IP literals, localhost, credentials, or explicit ports.
- Provider output URLs must be HTTPS and credential-free. Provider text/specifications/evidence are size-bounded.
- Provider-issued affiliate link is returned only when adapter status is `provider_confirmed`; unverified links are withheld.
- Missing values remain null and product records become partial where requested fields or required affiliate links are absent.
- Provider authorization failures map to HTTP 403; rate limits to HTTP 429; unavailable/unconfigured provider to HTTP 503.
- No production provider adapter is currently registered. A call with an unconfigured source correctly returns 503.

## 5. Amazon compliance gate — hard blocker

Official Amazon Associates and Creators API policy documentation was reviewed on 2026-11-06. Key conclusions recorded in `docs/architecture/AMAZON_COMPLIANCE_GATE.md`:
- Amazon's Agent Terms address autonomous/semi-autonomous software acting for or under a person's instruction.
- Agent HTTP(S) requests must identify the agent and include an `Agent/[agent name]` User-Agent.
- Agents must not disguise access as human browsing or mimic human interaction speed/patterns. Human-vs-computer checks must be answered truthfully; no CAPTCHA or anti-bot circumvention.
- Amazon may limit or prohibit agent access.
- Program Content / IP License restrictions include limits on data mining, robots, similar data-gathering/extraction, and repurposing.
- Creators API credentials do not automatically grant permission for every intended product aggregation, analysis, ranking, repurposing or Pinterest marketing workflow.
- SiteStripe's user-facing Get Link feature is not, by itself, authorization for autonomous SiteStripe automation.
- Therefore no Amazon scraping, autonomous SiteStripe automation, or production agent access until the exact workflow is confirmed permitted and any required express written approval is obtained.
- Keep Amazon route fail-closed. Do not set approval flags based on assumptions.

## 6. Product source provider evaluation

Report: `docs/architecture/PRODUCT_SOURCE_OPTIONS.md`

Candidates researched:
1. **Awin** — product feeds can provide product information and advertiser deep links; publisher account and eligible advertiser feed access required. Recommended first candidate if relevant US/UK Home & Kitchen feeds are available.
2. **CJ Affiliate** — Product Feed API; requires publisher credentials/company ID and advertiser/feed permissions.
3. **eBay Partner Network** — Browse API can return affiliate item URLs when valid ePN campaign context is supplied; requires eBay developer app and ePN campaign membership.
4. **impact.com** — partner catalogs and promotional links depend on joined brands and enabled catalog/API access.

No provider account has been accessed, no credentials supplied, and no live catalog queried. No provider has been silently selected or integrated. These networks are alternatives, not Amazon approvals or automatic replacements. Confirm each provider's terms permit the intended Pinterest workflow before adapter registration.

## 7. Security and engineering notes

- Request body requires `Content-Type: application/json`; compressed bodies are rejected; request body limit is 1 MB.
- Bearer authentication required for tool routes.
- One browser worker / bounded execution.
- Browser network URL guard blocks local/private targets; DNS rebinding protection still requires network-level egress controls.
- Product provider adapter must use fixed official API/feed hosts, strict TLS validation, bounded timeouts, bounded response size and pagination, and exact provider authorization.
- Do not accept arbitrary provider-supplied code or URLs as executable instructions.
- Do not log tokens, cookies, credentials, encryption keys, full browser storage, or secret query parameters.
- Do not host images; preserve allowed remote image URLs only.
- Avoid duplicate work: inspect existing implementation and tests before changing files.

## 8. Current verification status (2026-11-07)

Latest checks performed in the connected local browser repository:
- Full targeted regression suite after token-scope hardening: **80 passed in 99.63 seconds**, process exit code 0.
- Python compile checks for `server.py`, `product_research.py`, and `profile_persistence.py`: passed.
- `git diff --check`: passed.
- Operator/agent credential separation implemented locally: `/execute`, `/health`, and `/session/health` use `UCOS_BROWSER_TOKEN`; `/tool/amazon/product` and `/tool/product/research` require the separate `UCOS_BROWSER_AGENT_TOKEN`. Bearer comparison uses `hmac.compare_digest`. Two new HTTP tests verify that neither token can access the other scope.
- `.env` key inventory: all 11 browser runtime keys present; required values non-empty; `UCOS_BROWSER_AGENT_TOKEN` intentionally empty until Model 1 integration is provisioned; Amazon access gate explicitly disabled; Amazon User-Agent intentionally empty; file mode `0600`.
- `.env` is ignored by Git; `git ls-files .env` returned no tracked file. Tracked-code secret scan found no obvious API-key/private-key/database-URL patterns.
- Added tracked `.env.example` template with all 11 expected key names and safe empty/false defaults; no actual secrets or production values are included.
- Remote Desktop Commander device `localhost` is online; Desktop Commander config endpoint returned HTTP 200 and valid Supabase config during this session.
- Render service metadata freshly inspected: service `srv-datuu697lnhs73eqtjpg`, URL `https://ucos-personal-browser.onrender.com`, branch `main`, auto-deploy enabled, configured repository `shehrozali6465372-ctrl/universal-content-operating-system`, and latest live deploy commit `246ba63de0e596f186b8096a649235334b85d7b8`. The standalone browser repo `main` and configured Render repo `main` both resolved to the same base SHA during this check; however, the hardening/product-tool changes in the local standalone checkout are uncommitted and are not in the live deployment.
- Latest Render application logs (2026-11-06 22:53 UTC): `UCOS_BROWSER_SESSION_PERSISTENCE_SELF_TEST=PASS backend=encrypted_postgres`; existing `amazon-primary` snapshot was `DECRYPTABLE` with 78 cookies and 1 origin. This proves encrypted snapshot readability, not Amazon account authentication.
- Latest Render logs also say `/var/data/ucos-browser/profiles` is not writable; runtime falls back to `/tmp/ucos-browser/profiles/amazon-primary` and encrypted PostgreSQL snapshots. Restart recovery still needs an explicit controlled test.
- Live read-only HTTP checks from the authorized device: `GET /readyz` returned 200 (`{"status":"ok","service":"ucos-personal-browser"}`; first request took 23.2s, consistent with a cold start); `GET /console` returned 200; `GET /health` and `GET /session/health` returned 401 without a token; unauthenticated `POST /execute` returned 401. Authenticated `GET /health` returned 200 and `GET /session/health?profile_ref=amazon-primary` returned 200 with `persistent=true`, `persistence_backend=neon_postgres`, `profile_initialized=true`, and `authentication=UNKNOWN`. These are positive service/auth/persistence-state checks, not proof of Amazon login.
- Live `POST /tool/amazon/product` and `POST /tool/product/research` returned 404, confirming these newly added tool routes are not present in the current live deployment. No authenticated request was made to them.
- Current local branch `local/personal-browser-hardening` is based on `246ba63d`; changes remain uncommitted and unpushed. Render currently deploys the base commit, not the local working-tree changes.
- Docker Engine build not verified; the local Docker command was previously identified as an `udocker` shim.
- Amazon live extraction / SiteStripe is not tested and remains blocked by the policy gate. Do not enable it.
- No live non-Amazon product provider adapter is registered/configured; mocked tests prove contract behavior only.
- Model 1 end-to-end integration is not implemented or tested.
- Amazon account login and durable restart restoration are not independently verified in this run.
- No real Pinterest Pin was published; do not publish during verification.

## 9. Current local Git state

Working branch: `local/personal-browser-hardening`
HEAD observed: `246ba63d`

Files modified/untracked at the latest status check:
- Modified: `.github/workflows/ucos-browser-ci.yml`
- Modified: `docs/architecture/UCOS_BROWSER_AFFILIATE_ACCOUNT_SETUP.md`
- Modified: `services/ucos_browser/server.py`
- Modified: `tests/test_browser_profile_persistence.py`
- Modified: `tests/test_ucos_personal_browser.py`
- Untracked: `PINTEREST_AFFILIATE_MARKETING_AGENT_PERSONAL_BROWSER_CONTEXT.md`
- Untracked: `docs/architecture/AGENT_TOOL_CONTRACT.md`
- Untracked: `docs/architecture/AMAZON_COMPLIANCE_GATE.md`
- Untracked: `docs/architecture/LOCAL_MODEL1_INTEGRATION.md`
- Untracked: `docs/architecture/PRODUCT_SOURCE_OPTIONS.md`
- Untracked: `services/ucos_browser/product_research.py`
- Untracked: `tests/test_amazon_product_tool.py`
- Untracked: `tests/test_amazon_product_tool_http.py`
- Untracked: `tests/test_product_research.py`

No commit or push has been made for these local changes. Do not assume files are committed just because tests pass. The main Pinterest Affiliate Marketing Agent checkout at `/root/Pinterest-affiliate-marketing-agent` has unrelated local modifications and is 397 commits ahead of its remote tracking branch; do not modify, reset, or push it as part of this browser task.

## 10. Production blockers and next work sequence

| Priority | Blocker | Evidence / release condition |
|---|---|---|
| P0 | Deployment source alignment | Render deploys the base `246ba63d` commit from `universal-content-operating-system`; local hardening changes in this dedicated checkout are uncommitted. Agree the canonical source and ensure the deploy consumes the reviewed commit. |
| P0 | Model 1 integration | Main agent checkout has no `UCOS_BROWSER` client references; implement and test a dedicated authenticated adapter without bypassing the unified publishing gateway. Do not alter the main checkout until its existing 397-commit-ahead and dirty working tree are reconciled. |
| P0 | Amazon policy gate | Keep `UCOS_AMAZON_AGENT_ACCESS_APPROVED=false` and User-Agent empty until documented permission for the exact workflow or an approved official API use case is verified. |
| P1 | Product provider | Adapter registry is empty. Select a provider only after publisher account/feed permissions and applicable data/image/Pinterest terms are verified; then configure official credentials and live contract checks. |
| P1 | Durable restart proof | Neon snapshot self-test and decryptability pass; controlled restart-and-restore test is still outstanding. It must confirm profile recovery without treating cookie count as login proof. |
| P1 | Network egress hardening | Application blocks private/local destinations, but DNS rebinding / resolution-to-connect TOCTOU remains; enforce network-level egress controls before production tool exposure. |
| P1 | Render runtime reliability | Service is on Free plan, first live readiness request took 23.2s, and Render service metadata has no health-check path configured. Decide whether production requires an always-on plan and `/readyz` health check. |

Execution order:
1. Reconcile canonical repository/deployment source and review the local diff; do not reset unrelated work.
2. Complete browser security review, provider adapter implementation, and test coverage.
3. Build the Model 1 browser client in an isolated change with mock-based tests; keep all Pinterest publishing behind the existing unified gateway.
4. Verify production environment variable *names and presence* in Render without retrieving or exposing secret values; preserve database/token/key separation.
5. Run CI and the controlled restart/restore acceptance test.
6. Obtain the required Amazon policy evidence or keep Amazon route disabled; activate only an authorized provider.
7. Only after the user approves the exact release commit, push/deploy and perform live authenticated smoke checks.
8. Keep verification read-only with respect to Pinterest publishing; never publish a real Pin during tests.

## 11. Official reference links

- Amazon Associates policies: https://affiliate-program.amazon.com/help/operating/policies
- Amazon Associates agreement: https://affiliate-program.amazon.com/help/operating/agreement
- Amazon Creators API onboarding: https://affiliate-program.amazon.com/creatorsapi/docs/en-us/onboarding
- Awin Product Feed Publisher Guide: https://help.awin.com/developers/docs/product-feed-publisher-guide-intro
- Awin Product Feed access: https://success.awin.com/s/article/How-can-I-access-a-Product-Feed?language=en_US
- CJ Product Feed API Search: https://docs.cj.com/docs/productfeed-api-search
- eBay Browse API: https://developer.ebay.com/api-docs/buy/api-browse.html
- impact.com partner catalogs: https://help.impact.com/partner/what-would-you-like-to-learn-about/platform-features/marketing-content/product-marketplace-and-catalogs/download-product-catalogs-as-a-partner

---

## Maintenance rule

This file is the master context for the **Personal Browser project only**. Update it with verified facts after each substantial change. Keep secrets out. Mark uncertain or stale account/deployment details explicitly. Do not copy Model 1 credentials or mix the browser Neon database with the main agent database.
