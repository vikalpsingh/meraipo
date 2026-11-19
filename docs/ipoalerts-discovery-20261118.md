# IPO discovery correction — 18 November 2026

The IPOWatch GMP page returned zero HTML tr elements during investigation. Its
current widget loads data dynamically; the existing WatchTables parser cannot
read that widget. Mahanadi Coalfields was absent from the public MeraIPO Home page.
This reproduces a source compatibility gap, not a verified production log diagnosis.

Use the existing IPOAlerts adapter. New-install defaults now select ipoalerts.
It requests open, upcoming and announced separately, walks all reported pages,
uses x-api-key authentication, and rejects incomplete previews. GMP plan failures
retain schedule discovery; do not require a paid GMP add-on for the IPO list.

For the existing deployment, sign in to /meraadmin, Market configuration, select
IPOAlerts as IPO source, retain/set its API key, save, then run IPO discovery and
review import diagnostics. Saved database configuration overrides environment
and code defaults. No production setting or deployment was changed here.
Do not clear existing records or insert fabricated dates/prices/GMP.

The Mahanadi later-page test uses synthetic provider data, not an authenticated
API response. Confirm that your account's API returns the issue before asserting
that it is fixed on production. Provider docs:
https://ipoalerts.in/docs/api-reference/endpoints/get-all-ipos
