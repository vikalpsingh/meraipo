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
