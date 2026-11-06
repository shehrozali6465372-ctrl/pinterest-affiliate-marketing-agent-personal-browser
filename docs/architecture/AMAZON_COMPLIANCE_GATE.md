# Amazon Automation and Product-Data Compliance Gate

**Status: BLOCKED — do not enable live Amazon automation until the account owner confirms the required permissions/approvals.**

Review date: 2026-11-06. This is an engineering risk assessment, not legal advice or a determination from Amazon.

## Official Amazon policy findings

1. The Associates Program Policies (updated April 14, 2026) include a dedicated Agent Terms section. An Agent is software or a service that takes autonomous or semi-autonomous action for or at a person's instruction. Agents must identify the request as agent-originated and include `Agent/[agent name]` in every HTTP/HTTPS request User-Agent. They must not disguise agent activity by mimicking human interaction speed/patterns, must answer human-vs-computer checks truthfully, and must not circumvent CAPTCHA or other access-control measures. Amazon may limit agent access at its discretion or instruct an agent to refrain from access.
2. The IP License says its limited license does not include use of data-mining, robots, or similar data-gathering/extraction tools. Product Advertising Content is licensed for the stated Associates purposes and must not be copied or used for third-party benefit. Product prices/availability may only be displayed under the stated served-link or Creators API / PA API conditions.
3. Even for Creators API / PA API, the license expressly requires prior written approval for use involving aggregation, analysis, extraction, or repurposing of Product Advertising Content. This is directly relevant to the proposed agent product-research, comparison, and ranking workflow. The fact that an API credential can be created does not grant this separate permission.
4. Amazon's current official product-data API is Creators API. Its `SearchItems` operation supports keyword-based discovery (up to 10 results per request), and `GetItems` retrieves item details. Vended detail-page URLs can contain the partner tag. Onboarding requires final Associates acceptance, qualified referred sales, and registration for Creators API credentials. The official SDK handles authentication and request signing; Amazon documents OAuth 2.0 token acquisition and `https://creatorsapi.amazon` as the API base URL.
5. SiteStripe's official help describes the user-facing `Get Link: Text` workflow. That help page is not authorization for an autonomous browser worker to automate the UI.

Official sources:

- Associates Program Policies: https://affiliate-program.amazon.com/help/operating/policies
- Associates Program Operating Agreement: https://affiliate-program.amazon.com/help/operating/agreement
- Creators API introduction: https://affiliate-program.amazon.com/creatorsapi/docs/en-us/introduction
- Creators API onboarding: https://affiliate-program.amazon.com/creatorsapi/docs/en-us/onboarding
- Creators API SearchItems: https://affiliate-program.amazon.com/creatorsapi/docs/en-us/api-reference/operations/search-items
- SiteStripe Help: https://affiliate-program.amazon.com/help/node/topic/GJMMT7G4C8K4Y3AY

## Engineering decision

- Do not implement autonomous SiteStripe clicking as the assumed production path.
- Do not run live product-page scraping/extraction from Amazon with the current Playwright worker until the account owner has confirmed that this specific agent use is permitted and obtained any required express written approval from Amazon.
- Do not assume Creators API is automatically permitted for this agent's product comparison/analysis use. Confirm eligibility and obtain any required written approval before using its data for analysis or repurposing.
- If Amazon authorizes the intended workflow, the agent must identify itself in request User-Agent as required by the current Agent Terms, must not disguise automation, and must stop on CAPTCHA, MFA, bot checks, or access-denial responses.
- Never fabricate an affiliate link, partner tag, price, rating, review count, or availability. Keep unverified fields null and report their provenance.

## Current browser branch status

The `/tool/amazon/product` endpoint and its tests are an isolated local prototype. Mocked tests prove request validation and response shaping only; they do not prove Amazon policy permission, live extraction, autonomous SiteStripe operation, or Associates attribution. The endpoint must not be treated as production-authorized. Its HTTP route fails closed unless both `UCOS_AMAZON_AGENT_ACCESS_APPROVED=true` and `UCOS_AMAZON_AGENT_USER_AGENT` containing `Agent/UCOSPersonalBrowser` are explicitly configured. The configured User-Agent is applied to the Playwright browser context. These settings are technical safeguards, not proof of Amazon approval; the route must remain disabled until the required written permission is actually obtained.

Before release, require:

- Written permission/approval evidence covering this exact agent-driven product-data and affiliate-link workflow, or an approved official API use case.
- Confirmation of Creators API eligibility and allowed intended data use if that route is selected.
- A reviewed implementation that meets the applicable agent-identification and non-obfuscation requirements.
- A read-only live test using the approved access method, with no purchases, cart actions, reviews, account changes, or Pinterest publishing.
- Compliance review of how product prices, ratings, review counts, images, and affiliate disclosures are displayed downstream.
