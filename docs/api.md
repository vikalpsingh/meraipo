# API reference

Development OpenAPI: `http://localhost:8000/docs`; disabled in production. Public requests read database/cache only.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/health/live`, `/health/ready` | Process and DB/Redis readiness |
| GET | `/api/v1/ipos/open`, `/upcoming`, `/recent` | Issue collections |
| GET | `/api/v1/ipos/{slug}` | Company journey alias |
| GET | `/api/v1/tracker` | Paginated filters/screens |
| GET | `/api/v1/companies/{slug}`, `/companies/{slug}/journey` | Baseline, periods and provenance |
| GET | `/api/v1/companies/{slug}/quarters`, `/prices`, `/valuation` | Detail sections |
| GET | `/api/v1/site/message` | Active scheduled message/quote |
| GET | `/api/v1/site/advertisements?placement=home` | Enabled home/tracker placements |
| POST | `/api/v1/admin/login`, `/logout` | Create/revoke session |
| GET | `/api/v1/admin/session`, `/dashboard`, `/audit` | Session, operational summary, history |
| POST | `/api/v1/admin/ipos` | Create company/IPO/baseline |
| PUT | `/api/v1/admin/ipos/{slug}` | Update issue while preserving baseline |
| PUT | `/api/v1/admin/ipos/{slug}/applicant-guide` | Review category limits, deadlines, registrar and business brief |
| POST | `/api/v1/admin/ipos/{slug}/gmp` | Append GMP |
| POST | `/api/v1/admin/companies/{slug}/quarters` | Append result revision |
| POST | `/api/v1/admin/companies/{slug}/quarters/import` | Atomic array of 1–100 results |
| GET/POST | `/api/v1/admin/messages`, `/advertisements` | List/create content |
| PUT | `/api/v1/admin/messages/{id}`, `/advertisements/{id}` | Edit/schedule/disable |

Tracker filters include FY ending, quarter, board, sector, view, quality, trend, numeric return/drawdown/growth/ROCE/debt bounds, page and page_size (maximum 100). Omit empty API filters. The UI defaults to the current Indian financial quarter and offers all periods.

Admin writes require a session cookie, exact Origin and X-CSRF-Token returned by login/session. Login is rate-limited with Redis. Bodies are limited to 1 MB. Quarter/GMP records require stable import_key values: identical repeats are harmless; changed payloads with the same key return 409. Monetary metrics use ₹ crore unless labelled per-share; null means unavailable. Source URLs require HTTPS and verification is explicit.
