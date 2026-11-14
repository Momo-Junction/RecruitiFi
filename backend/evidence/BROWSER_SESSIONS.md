# Synthetic Talent browser sessions

These protected session endpoints remain available. The current hackathon
`BrowserEvidence`/`EmployerEvidence` UI uses a separate opt-in, constant-fixture
public path instead; see `deploy/rahti/ai/PUBLIC_DEMO.md`. Its UI has no AI login.

Analysis remains disabled unless the existing synthetic flag, candidate allowlist
and server-only operator token are configured. Browser access additionally requires:

```text
TALENTMATCH_AI_SESSION_SECRET=<independent random secret of at least 32 characters>
TALENTMATCH_AI_DEMO_ACCOUNTS=<JSON object mapping talent-001 etc. to distinct synthetic account passwords>
```

Passwords must be 12–128 characters; only existing Talent identities in the
synthetic allowlist are accepted. Configure these on the server, never in Vite
variables or Git. Do not reuse real passwords. The public role/account selector
does not authenticate: the user must separately enter that account's password.

POST `/api/evidence-session` accepts `{account,password}` in at most 512 bytes.
It verifies credentials and same-origin Origin before issuing a one-hour HMAC-signed
HttpOnly, SameSite=Strict cookie scoped to `/api`, Secure over HTTPS. Plain HTTP
is allowed only for loopback development. GET returns only the authenticated
candidate ID and CSRF token; DELETE requires Origin plus CSRF and clears the cookie.
All analysis endpoints retain operator-token support and alternatively verify
the cookie's signature/expiry/allowlisted identity. Cookie-authenticated writes
require matching Origin and `X-Recruitifi-CSRF`. Candidate IDs and mock account
headers cannot change the cookie's authenticated owner.

Login attempts are bounded to ten per peer address/minute, with at most 256
tracked addresses per process. This is not a distributed rate limiter.

The original protected browser workflow used this session mechanism. The current
Talent material UI triggers only the public fictional fixture, polls every 1.5
seconds and renders EvidenceAnalysis results; it does not request a session.
It stops polling on terminal state, error, identity change or unmount.
Operator tokens are never sent to React; session/CSRF credentials are not written
to browser storage. Dashboard sign-out requests cookie deletion. Unsupported or
disabled browser sessions hide controls. Vite's development API proxy preserves
Host for same-origin cookies/CSRF; production uses same-origin FastAPI serving.

This is **synthetic hackathon authentication only**, not production identity.
Account passwords are server configuration, not a production password database.
Signed sessions are stateless: a copied cookie remains usable until expiry unless
the signing key is rotated or its account is removed. Logout clears the browser
cookie, not every copied session. Password rotation alone does not revoke cookies.
Existing non-analysis mock-role APIs have not become production-authorized APIs.
Only use an isolated synthetic database; configuration cannot detect personal data.

Validate HTTPS/proxy-header trust and Origin behavior before any remote use;
there is no automatic trust of arbitrary forwarded headers. Real-user ownership,
durable revocation, distributed throttling, model-service authentication and a
full browser security review remain prerequisites for real candidate data.
No deployment, database reset, matching-score change or operator-token exposure is
part of this change.
