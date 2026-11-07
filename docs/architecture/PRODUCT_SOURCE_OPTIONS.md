# Product Source Provider Options

Review date: 2026-11-06

## Decision context

The standalone UCOS Personal Browser exposes a provider-neutral product research contract. Its adapter registry is intentionally empty until a source is authorized and configured. The primary business target remains Home Decor & Kitchen, USA/UK. Amazon live agent access remains blocked by the separate compliance gate; do not treat another network's approval as Amazon approval.

## Candidate comparison

| Provider | Product data access | Affiliate link support | Preconditions | Fit |
|---|---|---|---|---|
| Awin | Advertiser product feeds can include name, description, price, image and Awin deep link | Feed includes an Awin deep link | Publisher account, access to eligible advertiser feeds; product-feed API key differs from Publisher API key | Strong candidate for US/UK retail catalog breadth |
| CJ Affiliate | Product Feed API supports product/feed discovery and product-detail search | Advertiser feed/link data; access depends on publisher/advertiser permissions | CJ Personal Access Token, generated Company ID and relevant advertiser partner/feed access | Strong candidate where home/kitchen advertisers publish usable feeds |
| eBay Partner Network | Browse API searches listings and retrieves item details | itemAffiliateWebUrl is returned when the ePN campaign ID is supplied in X-EBAY-C-ENDUSERCTX | eBay developer app plus ePN membership/campaign ID | Technically clear API path; marketplace listings may vary in quality and availability |
| impact.com | Partner product catalogs can be downloaded or accessed through API | Promotional product links available for joined brands | Partner account, joined brand/catalog relationship, API access enabled | Viable when relevant home/kitchen brands offer catalogs |

## Recommended implementation order

1. Keep the generic adapter contract and empty-by-default registry.
2. Prefer Awin as the first catalog adapter if the publisher account has relevant US/UK home and kitchen feeds. Its feed already carries the advertiser deep link, reducing custom affiliate-link generation.
3. If Awin access or category coverage is insufficient, evaluate CJ Product Feed API next.
4. Add eBay only if ePN membership and campaign ID are available and marketplace listings fit the product-quality requirements.
5. Evaluate impact.com only for specific joined brands with accessible product catalogs.

## Adapter acceptance requirements

Before registering a production adapter, verify:
- The user's publisher account is authorized for the exact advertiser/feed/catalog.
- Terms permit the intended product discovery, analysis, content creation, and Pinterest promotion workflow.
- Feed/API data freshness, attribution, and link rules are documented.
- Returned links are provider-issued and retained unchanged; never synthesize campaign tags.
- Product image URLs are passed through as remote URLs. This service must not upload or host images.
- Adapter outbound requests use fixed provider API/feed hosts, strict TLS validation, timeouts, response-size limits, and bounded pagination.
- Only fields actually returned by the source are populated; unknown values remain null.
- Affiliate link status is provider_confirmed only when the provider itself returns a link under the authenticated publisher context.

## Explicitly not done

- No provider account was accessed.
- No API/feed credentials were supplied or configured.
- No live product source was queried.
- No affiliate link was generated or verified.
- No adapter has been registered; /tool/product/research correctly returns 503 for unconfigured sources.
- No Model 1 integration, commit, push, deployment, or Pinterest Pin publication occurred.

## Official documentation

- Awin Product Feed Publisher Guide: https://help.awin.com/developers/docs/product-feed-publisher-guide-intro
- Awin Product Feed access: https://success.awin.com/s/article/How-can-I-access-a-Product-Feed?language=en_US
- Awin Publisher FAQs: https://help.awin.com/developers/docs/faqs-for-publishers
- CJ Product Feed API Search: https://docs.cj.com/docs/productfeed-api-search
- eBay Browse API and affiliate headers: https://developer.ebay.com/api-docs/buy/api-browse.html
- impact.com partner product catalogs: https://help.impact.com/partner/what-would-you-like-to-learn-about/platform-features/marketing-content/product-marketplace-and-catalogs/download-product-catalogs-as-a-partner
