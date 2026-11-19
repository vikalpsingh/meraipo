# Public-page Google Analytics

The shared root layout mounts one AnalyticsConsent component with GA4 measurement
ID `G-ZYEKCCV3J5` (override via `GA4_MEASUREMENT_ID`; empty disables it).
Use `https://www.googletagmanager.com/gtag/js?id=G-ZYEKCCV3J5`.
`gtm.js` is not the loader for this GA4 measurement ID; do not install a duplicate
snippet on individual pages.

After the visitor grants analytics consent, the component initializes dataLayer,
gtag and the tag once, then sends sanitized page_view events on public route changes.
Home, tracker, IPO/company detail, IPO status, email registration and information
pages inherit the root layout. MeraAdmin and private email-action pages are excluded.
Denied/withdrawn consent prevents pageviews. Contact details, arbitrary queries and
fragments are omitted. Only predefined email campaign attribution is retained.

## Google property configuration and verification

1. Deploy/restart the updated web application; retain the existing consent flow.
2. GA4 → Admin → Data streams → select the web stream for this ID.
3. Enhanced measurement → Page views → Show advanced settings: disable **Page changes
   based on browser history events** because this app explicitly sends route pageviews.
   The app also sets `send_page_view: false` to avoid the config command's automatic view.
4. Open MeraIPO, allow analytics, navigate through public pages and use GA4 Realtime or
   Tag Assistant/DebugView to verify one page_view per navigation. Browser blocking,
   denied consent and network failures can prevent delivery.
5. Confirm no second GTM container, plugin or inline snippet sends the same pageviews.

Local tests mock Google and cover consent, correct loader, single initialization,
multiple public pages, rerender deduplication, private-route exclusion and URL sanitizing.
They do not prove live receipt in the Google property. No Google account settings were
changed during implementation.

References:
- https://developers.google.com/tag-platform/gtagjs/configure
- https://developers.google.com/analytics/devguides/collection/ga4/views
