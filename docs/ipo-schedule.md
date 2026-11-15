# IPO sync schedule baseline

Agreed schedule: active, every 12 hours, anchored at 00:30 IST; Saturday OFF,
Sunday OFF. Runs Monday–Friday at 00:30 and 12:30 IST.

The database scheduler_controls record remains authoritative. Code defaults apply
only when no control record exists; startup does not rewrite saved settings.
Do not copy development databases into production or rerun historical migrations.

For an existing local development database, apply explicitly:

    python -m scripts.set_dev_ipo_schedule

This helper refuses production environments and non-local database hosts. It is
not part of deployment. Existing production settings are preserved on upgrades.
