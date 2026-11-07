# Local Integration Architecture — UCOS Personal Browser + Model 1

## Decision

The Personal Browser is a local-first, separately runnable browser service intended to become an infrastructure dependency of the existing Pinterest Affiliate Marketing Agent (Model 1). It is not a second affiliate-marketing agent and must not duplicate Model 1's content, learning, scheduling, or Pinterest publishing logic.

**Workflow:** finish and verify the browser locally → review the local architecture contract → integrate a thin client into Model 1 → test the integration without publishing a Pinterest Pin → only then consider a remote merge/deployment.

No GitHub merge, production deployment, Amazon account login, or Pinterest publication is authorized by this local build step.

## Responsibilities

### Personal Browser service

- Owns the Playwright Chromium runtime and the Amazon Associates browser session.
- Accepts authenticated, bounded browser tasks through `POST /execute`.
- Captures the affiliate URL actually produced by the permitted Amazon Associates/SiteStripe browser flow.
- Returns the captured URL and task evidence to its caller.
- Encrypts persisted Playwright storage state (cookies and origin localStorage) before storing it in the configured PostgreSQL database.
- Does not generate or invent Associate tags, bypass CAPTCHA/anti-bot checks, or publish Pinterest Pins.

### Model 1

- Owns product selection, content generation, title, description, alt text, pin idea, learning loop, and publication orchestration.
- Calls the browser through one dedicated adapter/client. It must not embed Playwright or operate the browser database directly.
- Accepts an affiliate URL only when it is returned by the browser capture action and passes Model 1's own marketplace/tag validation.
- Keeps Pinterest publishing behind the existing unified publishing gateway. The browser adapter has no Pinterest publishing capability.

## Current browser HTTP contract

- `GET /readyz`: public liveness/readiness response; no browser or database proof.
- `GET /health`: protected service health.
- `GET /session/health?profile_ref=...`: protected persistence metadata. Its `authentication` field is explicitly `UNKNOWN`; it does not prove Amazon is logged in.
- `POST /execute`: protected human-operator browser task endpoint. Requires `Authorization: Bearer <UCOS_BROWSER_TOKEN>` and a JSON object containing a bounded task (for example `profile_ref`, `url`, `actions`, and optional timeout). Do not give this operator token to Model 1.
- `POST /tool/amazon/product` and `POST /tool/product/research`: agent-only tool endpoints. Require the separate `UCOS_BROWSER_AGENT_TOKEN`; it cannot authorize `/execute`, and the operator token cannot authorize these tool routes.
- Affiliate capture is an action in the browser worker; it accepts only a validated Amazon Associates URL observed in a recent (maximum five-minute) clipboard-write event from the Amazon page/frame. It no longer scans arbitrary DOM links, input values, or selected text, which could return stale or unrelated tagged URLs. A short URL is accepted syntactically but its redirect destination/tag is not independently resolved by the current validator.

The setup document's historical `/affiliate/amazon/status` and `/affiliate/amazon/search` paths are not part of the standalone service's current HTTP handler. Do not code Model 1 against those paths unless they are separately implemented and tested.

## Secrets and session isolation

- Browser service secrets stay in the browser service environment: `UCOS_BROWSER_TOKEN` (operator only), `UCOS_BROWSER_AGENT_TOKEN` (agent only), `UCOS_BROWSER_STATE_DATABASE_URL`, and `UCOS_BROWSER_STATE_ENCRYPTION_KEY`.
- The Fernet encryption key must never be passed to Model 1 or returned by any endpoint.
- Model 1 stores only its caller token for the browser service, not Amazon passwords, cookies, or raw browser state.
- Use a stable, non-secret profile reference such as `amazon-primary`. Do not put usernames, email addresses, passwords, or tokens in the profile reference.
- Amazon sign-in is a human-controlled setup step. MFA/CAPTCHA must be completed normally by the account owner.

## Network and security boundary

- Browser tasks are authenticated and bounded; URL validation rejects non-HTTP(S), local, and private targets.
- The browser now applies that URL policy to browser network requests as well as initial navigation, including redirects and subresources.
- This application-layer check is defense in depth, not a substitute for network egress restrictions. DNS rebinding and DNS-resolution-to-connect races still require container/host egress controls to be fully mitigated.
- The service currently uses a shared bearer token. Treat it as a private single-caller service; do not expose it to browsers, public frontend code, or untrusted tenants. If multiple independent callers/accounts are introduced, add explicit caller-to-profile authorization before doing so.

## Required integration tests (no real Pinterest publication)

1. Missing/wrong browser token is rejected.
2. Model 1 adapter sends the expected profile reference and browser task, and never logs secrets or form values.
3. Browser failure, timeout, missing SiteStripe output, ordinary product URL, or invalid marketplace URL cannot produce an affiliate link.
4. Model 1 persists only the returned URL and minimal evidence metadata.
5. Browser adapter cannot call or bypass the Pinterest publishing gateway.
6. Existing unified gateway authentication, idempotency, publication-ledger, and duplicate-publish tests remain green.
7. All tests use mocks/local fixtures; no test sends a real Pin to Pinterest.

## Local acceptance gates

- [x] Browser unit/contract tests pass (49 passed in the latest full run).
- [x] Chromium clipboard-capture hook and provenance edge-case tests pass using local mocked browser fixtures; real SiteStripe clipboard capture remains pending.
- [x] Browser network-request guard tests pass.
- [x] Full standalone browser repository test suite passes (49 passed in the latest full run).
- [ ] Docker image builds locally and the container starts with test-only secrets; Docker Engine is unavailable on the current local device (the `docker` command is an `udocker` shim).
- [x] Protected endpoint auth and unprotected `/readyz` are verified locally (`/readyz` 200, authenticated `/health` 200).
- [x] Encrypted persistence verified against the configured browser Neon database: existing `amazon-primary` ciphertext decrypted with the configured key; no row was modified by this check.
- [ ] Amazon account session restore is verified only with the account owner's authorization; no credentials are placed in test fixtures. Current read-only Amazon navigation found no sign-in prompt or challenge and detected account UI markers, but this is not conclusive account-level authentication proof.
- [ ] Model 1 adapter tests pass without any Pinterest publication call; Model 1 has not been modified or integrated.

## Current state

This file is an integration contract and implementation plan, not evidence of a completed Model 1 integration. The Personal Browser remains a local project until the above gates pass and the user separately approves integration/remote deployment.
