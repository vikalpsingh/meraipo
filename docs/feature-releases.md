# Public feature releases

In `/meraadmin`, open **Feature releases**. IPO Tracker starts hidden; **Enable and make live** publishes its navigation, homepage link, page, API and sitemap entry. **Hide feature** disables them again. Existing browser pages update on refresh/navigation. Collection jobs and stored company data are unaffected.

Flags are persisted in `site_feature_flags`. Changes require an authenticated admin and CSRF token and are recorded in the admin audit log. Missing settings default to hidden. Home and admin remain accessible if flag retrieval fails.

To add a future tab, register its key, label and description in `apps/api/feature_routes.py:FEATURES`. Use `require_feature(key)` on its public API routes and `features()` to guard its Next page, navigation links and sitemap entry. The admin switch appears automatically; it remains hidden until explicitly enabled. Add route, navigation and toggle tests before releasing. Adding a flag alone does not automatically guard new routes.

The existing Upcoming IPO section is part of Home and remains visible. Feature releases control whole registered features, not IPO lifecycle categories.
