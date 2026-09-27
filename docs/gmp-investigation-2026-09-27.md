# GMP investigation — 27 September 2026

The IPOAlerts collection, staging, publication and public API path is working. The latest retained provider response and master history were checked for the five reported companies.

| Company | Latest provider GMP | Stored master result | Finding |
| --- | ---: | ---: | --- |
| Green Asia Impex | No source quote | None | IPOAlerts returned `sources: []` |
| Peshwa Wheat | No source quote | None | IPOAlerts returned `sources: []` |
| Himalayan Solar | No source quote | None | IPOAlerts returned `sources: []` |
| Bench Mark Infotech Services | ₹16 | ₹16 | Stored correctly with provider timestamp |
| Roopa Screen | ₹32 | ₹32 | Stored correctly with provider timestamp |

Missing quotes are upstream data gaps, not scheduler or storage loss. A missing quote must remain unavailable; zero is a real quote and must not be substituted. The adapter now also accepts traceable constituent `gmpPrice` values when the provider supplies sources and a timestamp but has not produced its aggregate. MeraAdmin reports a separate `missing GMP` count for open/upcoming issues.

GMP is unofficial and can legitimately be absent. The scheduler continues to request `includeGmp=true` and retains raw provider responses for diagnosis.

After deployment, manual production-path run `cbaa80fd-7101-4db6-be95-d16977e92e2b` completed successfully: 68 records fetched, 5 written, 63 unchanged, 0 failed across 30 provider pages. The public API still reports no quote for Green Asia, Peshwa Wheat and Himalayan Solar, confirming the current gap remains at the provider.
