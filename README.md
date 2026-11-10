# The Daily Buff: public price feed

This repository contains only a bounded price updater, its tests and already-public price facts for the Daily Buff application. It has no client records, nutrition database, private application source, Cloudflare credentials or Supabase credentials.

The scheduled workflow runs every Monday at 05:17 Cyprus time. GitHub can delay scheduled jobs. Standard runners in this **public** repository are free; do not change it to private or select a larger paid runner. No artifacts, paid services or external service secrets are needed. The repository-scoped built-in token can write only this repository.

## Data safeguards

- Only the 750 reviewed source-product identities in `seed.json` can be refreshed. No new foods, matches, packs or shops are admitted automatically.
- e-Kalathi source IDs and product names must match; branch IDs, names, retailers and addresses must be unchanged. This preserves the separate supermarket-location review.
- Alphamega requires the same product ID, canonical barcode, exact name/pack, source URL and EUR currency. Its public shopper-search configuration is retrieved at runtime and never committed or logged.
- METRO promotions require the same source ID, exact title, non-unit-priced pack and a usable expiry. Missing or changed offers are held rather than rematched by name.
- Duplicate records, truncated pages, invalid prices, changes below half/above double a prior price, or >20% branch-coverage loss are held for review.
- Requests run serially with 2-second spacing (10 seconds for Alphamega search), a 45-second per-request timeout, a 420-request cap and a 35-minute job limit. No retries around access denials, logins, blocks or challenges.
- A failed source retains all its old values **and dates**. Successful sources can still publish. Individual held products never receive fresh timestamps. `status.json` explains coverage and holds; the job reports source failures visibly.
- The app excludes observations older than seven days and expired offers from current comparisons. The file's generation time is not a price observation time.

`prices.json` is one atomic latest snapshot. Git history preserves prior snapshots. Weekly data/status commits provide genuine repository activity; if updates stop, GitHub may disable inactive public schedules after 60 days. Inspect Actions and re-enable only after resolving the cause. Disable **Weekly price refresh** in Actions to stop the schedule.

## Sources and limitations

- [e-Kalathi](https://www.e-kalathi.gov.cy/): public product and branch-price facts, linked per product. Not the selling retailer. Stock is unknown.
- [Alphamega](https://www.alphamega.com.cy/): public online-shop product prices and availability, distinct from branch observations.
- [METRO](https://www.metro.com.cy/en/current_offers): advertised promotions with expiry dates, distinct from branch prices.

These are dated observations, not guaranteed checkout prices. Images, retailer descriptions, private data and search client configuration are not republished. Source identities and attribution remain attached to each record. No licence to third-party content is implied.

To test locally: `python -m unittest -v test_refresh.py`. To collect an explicit refresh: `python refresh.py`. Python standard library only. Exit code 2 indicates a failed source or no e-Kalathi refresh; inspect `status.json`. Do not publish code or secrets through the data-only commit step.

