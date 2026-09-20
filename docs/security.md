# Security

Passwords use Argon2id. Sessions are opaque random tokens, hashed in PostgreSQL, with expiry and revocation. Cookies are HttpOnly, SameSite=Lax and Secure in production. Admin mutations require a session-bound CSRF token and allowed Origin. Login attempts use shared Redis limits in production and generic errors. Admin changes create audit entries in the same transaction.

Secrets belong to environment variables/secret managers. Production fails startup for insecure configuration. No public registration, broker connectivity, PAN, demat, UPI or bank credentials. React escapes content; plain-text messages do not accept HTML. Only HTTPS links are accepted for public research and advertisements. Upload size/type checks apply to document storage. Restrict database users, disable public API docs, terminate TLS at the ingress, and run dependency scanning in CI.
