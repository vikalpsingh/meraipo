# Public IPO navigation update — 25 October 2026

## Delivered

- `apps/web/app/page.tsx`: broker shortcuts appear at the top of Home.
- `apps/web/app/tracker/page.tsx`: removes the broker shortcuts from Tracker.
- `apps/web/components/tracker-table.tsx`: sortable headings are buttons using
  client-side router replacement with scroll disabled. Existing query parameters,
  including pagination, are preserved. Window and table scroll offsets are restored
  after the update; the table component is not keyed/remounted by sort order.
- `apps/web/app/ipo-status/page.tsx`, `components/ipo-status-frame.tsx` and
  `lib/nse-ipo-status.ts`: public status page with the official NSE iframe and an
  always-visible external link. No MeraIPO PAN field, proxy, storage or result capture.
- `components/site-navigation.tsx` and `app/sitemap.ts`: public IPO Status route.
- `app/globals.css`: sort-button and responsive status-page styles.
- `next.config.ts`: allows only the official NSE hostname for child frames;
  existing protections against embedding MeraIPO itself remain unchanged.
- `compose.yaml`: runtime `NSE_IPO_EMBED_ENABLED` switch; set to `false` to deliver
  the external-link-only state. The iframe can also be hidden by the visitor.

## Verification and limits

No test cases or test suite were run. TypeScript checking and the production
Next.js build passed. An isolated Next.js browser preview used synthetic market
data, never personal information. Desktop and 390px mobile layouts were inspected.
Broker links appear on Home; IPO Status navigation marks the route as active.
The embedded form was simulated; hiding it retained the working official fallback.

Sorting preserved window scrollY=635, table scrollLeft=200 and scrollTop=5 in both
directions, page=2, page_size=20, view, board and search query. An expanded filter
section and an unsaved filter input remained unchanged. No main-document navigation
was observed. These are browser interaction checks, not the full test suite.

NSE URL: https://www.nseindia.com/invest/check-trades-bids-verify-ipo-bids
The official page content was verified through web retrieval. Direct HTTP access
timed out and a browser request failed in this environment. Therefore live iframe
support and real bid/allotment submission are **not verified**. Browser `load`
events cannot prove a cross-origin form works, so the UI never claims it loaded
successfully. If framing is denied, slow or blank, “Open on NSE” remains available
in a separate tab with `noopener noreferrer`, preserving MeraIPO. No real PAN was
entered or submitted and no framing restrictions were bypassed.

Local startup was attempted using Compose, Docker Desktop start and a normal
restart. The daemon still reports “Docker Desktop is unable to start”. No volumes
were reset or deleted. Full local deployment/startup remains blocked on Docker.

## Update — 26 October 2026

The NSE iframe has been replaced with the user-supplied screenshot, stored at
`apps/web/public/ipo-status/nse-status-preview.png`. The responsive preview is an
accessible new-tab link to the official NSE page and is explicitly labelled as
an image. The separate Open on NSE button remains. No personal details are
collected by MeraIPO. Removed the obsolete embed switch and NSE frame permission;
child frames are now disallowed. Earlier embedding notes above describe the
superseded implementation.
