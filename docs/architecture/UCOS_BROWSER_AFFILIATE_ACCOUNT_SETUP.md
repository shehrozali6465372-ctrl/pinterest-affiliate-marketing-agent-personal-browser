# Browser-assisted affiliate account setup

UCOS Layer 10 can acquire a real affiliate product and tagged link through the
authenticated Personal Browser without receiving the affiliate password or
session cookies.

## Account registration

Use the existing account registry. Put the browser profile reference in the
account's affiliate_rules:

    {
      "browser_provider": "amazon",
      "browser_account_ref": "amazon-primary",
      "marketplace": "www.amazon.com",
      "browser_required": true
    }

`browser_account_ref` is a safe profile identifier, not an Amazon username or
password. The corresponding Playwright persistent profile lives inside the
browser worker.

## Runtime flow

Layer 14 control plane -> Layer 10 AffiliateBrowserClient -> Layer 14 PersonalBrowserAffiliateGateway -> UCOS Personal Browser -> authenticated Amazon profile -> product search -> product page / SiteStripe -> tagged HTTPS affiliate URL -> Layer 10 evidence -> content/publish package.

Credentials stay inside the browser profile. UCOS never accepts or stores the affiliate password in Layer 10.

## API

The current standalone agent tool is:

- `POST /tool/amazon/product`
- Header: `Authorization: Bearer <UCOS_BROWSER_AGENT_TOKEN>` (separate from the operator console token)
- JSON body: `{"profile_ref":"amazon-primary","marketplace":"amazon.com","product_url":"https://www.amazon.com/dp/B012345678","fields":["title","price","rating","availability"],"generate_affiliate_link":true}`

The endpoint returns page-observed product fields, evidence, missing fields, and an affiliate URL only when a recent Amazon-origin clipboard write is captured and its format passes validation. `affiliate_link_format_valid` is a format check only; it is not redirect-destination or Associates-account verification. The agent endpoint is restricted to the existing `amazon-primary` profile.

The historical `/affiliate/amazon/status` and `/affiliate/amazon/search` paths are not implemented by the current standalone HTTP handler. Product search-query input is also not implemented yet; the current tool requires a product URL.

## One-time account login

The browser profile must first be signed in to the Amazon account that owns the Associates account. Amazon documents that SiteStripe appears when the Amazon session corresponds to the Associates account, and SiteStripe can generate tagged links from the product page.

UCOS deliberately does not automate password entry or CAPTCHA/anti-bot bypass.

## Persistence requirement

The browser profile is persistent for the lifetime of the worker filesystem. For production account sessions to survive Render deploys/restarts, the browser service needs durable storage for `UCOS_BROWSER_PROFILE_DIR`. Without durable storage, the account must be authenticated again after the profile is lost.

## Compliance

Affiliate links must remain the real links returned by the approved affiliate workflow. UCOS must not fabricate tags, alter Amazon-served content, or create artificial clicks. Affiliate disclosures should be included in the publishing package.