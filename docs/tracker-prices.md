# IPO Tracker listing-day prices and returns

The company record stores `listing_price`, `listing_price_date`, and
`listing_price_exchange`. These represent the official **closing price on the
exact listing date**, not the opening trade or the first available later close.
The selected exchange matches the company's daily CMP series. Daily closing-price
sync reconciles these fields from retained `DailyClose` rows, including historical
backfills and exchange corrections. Corrected listing dates invalidate the old
baseline. Source file/revision provenance remains in the daily-close tables.

The API calculates percentages from current stored values on each catalogue read:

- Listing gain = (listing-day close / IPO upper band - 1) × 100.
- Gain since IPO = (latest CMP / IPO upper band - 1) × 100.
- Return since listing = (latest CMP / listing-day close - 1) × 100.

Missing or non-positive upper bands produce unavailable gains. A later CMP never
overwrites the listing-day baseline. Public-display permission applies to both
CMP and the listing close. Returns are unadjusted for dividends/corporate actions.
Existing third-party `ipos.listing_price` data is retained separately; it is not
silently relabelled as an official listing-day close.

Tracker keeps company, issue size and price/return columns first. Research columns
with a populated value on the current results page precede pending columns, with
quarterly revenue, PAT and EPS included. Mobile labels use each column's own label,
so rearranging columns cannot mismatch labels and values.

Validation: real NSE/BSE sample-file imports through API output, price corrections,
backfills after newer CMP, negative returns, missing/zero bands, display permissions,
listing-date corrections, and desktop/mobile column rendering.


Tracker sorting accepts `sort=return_ipo|drawdown` and `order=asc|desc`.
Sorting happens after filtering and before pagination; null values remain last,
with company name and ID breaking ties. Rows above (not equal to) 100% IPO gain
have a light green background. Header links reset the page and retain filters;
mobile users can use the Sort by and Order controls.

Screener links use the existing company.screener_url when valid. IPOAlerts
screenerUrl/screener_url fields are normalized and persisted through the existing
company ingestion flow; absent values preserve existing links. When absent,
the API builds a consolidated link from persisted BSE security code, then NSE
symbol. BSE issue IDs and company-name guesses are never used. No Screener
scraping or per-request external lookup is performed, and missing identifiers
produce no link. Exchange-derived URLs are candidates; coverage on Screener is
outside this app's control. Existing records need no migration or duplicate URL
backfill because the company-linked identifiers are already stored.
