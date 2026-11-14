# Reuse existing login/session code

No external provider or new authentication backend was added. The existing
`/api/evidence-session` password verifier and HttpOnly signed cookie can now be
used once at the application's existing account-entry screen. This is enabled
only with `TALENTMATCH_VERIFIED_DEMO_LOGIN=1`; the existing default password-free
demo navigation remains unchanged. The flag does not enable AI matching scores.

The server exposes only a capability boolean through `/api/evidence-session/config`.
If enabled settings are invalid, it returns 503 and the client does not silently
fall back to mock identity. Stored navigation is rechecked against the server
cookie before entering a verified dashboard. Passwords are transient React state,
cleared after submission, and never written to browser storage.

Reuse existing server-side account passwords, signing secret, synthetic allowlist
and Employer grants. No credentials were generated, changed, displayed or deployed
by this change. No second password entry was added inside AI panels. Private AI
APIs retain their own server-side account/candidate/company authorization; the
selector and this frontend gate alone do not authorize backend requests.

This remains the existing **synthetic demo authentication**, not production
identity. Organizer is not admitted by the session verifier. Other legacy APIs
still use mock role guards and have not become securely authenticated APIs merely
because application entry verifies a cookie. Do not enable real-data analysis or
claim general private profile protection on that basis.

Origin/HTTPS verification is unchanged. Rahti must present the correct trusted
proxy scheme/Host to FastAPI; no Origin/CSRF bypass or wildcard proxy trust was
added. A proxy configuration causing the original sign-in 403 will still require
an explicitly reviewed trusted-proxy configuration before this mode can be used.

The job relevance calculation is independently tested, but cache/invalidation,
consent tracking, private score APIs and matching-card integration are unfinished.
Do not deploy these changes as a completed model-based matching feature.
