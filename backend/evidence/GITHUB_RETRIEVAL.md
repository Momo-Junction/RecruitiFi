# Bounded public GitHub evidence retrieval

`github_fetcher.py` is an explicit-call backend utility, not an HTTP endpoint or
upload hook. It uses Python's standard-library HTTPS client; no dependencies,
authentication tokens, models, database writes or deployment changes are added.

```python
from backend.evidence.github_validator import validate_github_repository_url
from backend.evidence.github_fetcher import fetch_github_repository, fetch_github_repositories

repository = validate_github_repository_url('https://github.com/owner/repository')
# The following explicit calls perform network retrieval; examples only:
evidence = fetch_github_repository(repository)
batch = fetch_github_repositories([repository])
```

Raw URL strings are not accepted by the fetcher. Every identifier is revalidated
against its canonical URL, with exactly matching owner/repository fields and no
extra keys. Invalid input, duplicate repositories, or more than three identifiers
raise `GitHubURLValidationError` before any connection. The TypedDict is not an
authentication capability; equivalent values can be constructed, so revalidation
is mandatory. Callers must authorize any future user-facing analysis operation.
Use the batch entry point once per analysis request. Repeated independent calls
create fresh budgets; a future endpoint must not loop over the single-repository
wrapper to bypass request-level limits.

Only three REST endpoint shapes are constructed, all on **api.github.com:443**:

- `GET /repos/{owner}/{repository}` checks matching identity and public visibility.
- `GET /repos/{owner}/{repository}/git/trees/{encoded_default_branch}?recursive=1`
  retrieves one bounded tree, rejecting `truncated: true` and malformed entries.
- `GET /repos/{owner}/{repository}/git/blobs/{validated_sha}` retrieves selected
  immutable blobs. SHA, base64 encoding, declared/actual sizes and Git blob hash
  are checked. API-provided `url`, `download_url`, HTML links and redirect locations
  are never followed. No commit history, archive, clone, raw-content or search API.

## Selection and output

Deterministic order: README.md, package.json, requirements.txt, pyproject.toml,
Dockerfile, then `.py`, `.js`, `.ts`, `.tsx` source files. Within each class, prefer
shallower paths, then case-insensitive path order with an exact-case tie-break.
The listed document names are case-insensitive; other file types are excluded.

Paths must be bounded ASCII relative paths with ordinary filename characters.
Absolute paths, dot traversal, repeated separators, percent escapes, backslashes,
URL punctuation and control characters cause tree rejection. Hidden paths, Git
metadata, dependency/build folders and sensitive path components (including env,
credentials, keys, secrets, tokens, config and settings) are not selected. Symlinks,
submodules and unsupported entry modes are skipped; their targets are never read.
Ordinary executable-mode source files can be read as text but are never executed.

Only bounded UTF-8 text is returned. Invalid UTF-8, binary controls/signatures,
obvious private-key blocks, common token forms, credential URLs and quoted
secret-like assignments are omitted, with a reason. This is deliberately
conservative and can exclude harmless examples/configuration. **It is not a full
secret detector**: arbitrary allowed source/README files can contain obfuscated or
unrecognized credentials. Inspect only public repositories approved for analysis;
never treat public availability as permission to disclose all of their contents.

Each result contains `repository`, `retrieval_status`, `tree_sha`, `files`,
`skipped`, `http_status` and `untrusted: true`. Files contain `path`, `text`,
`source_reference` (the fixed-host immutable blob API URL), `blob_sha`,
`decoded_bytes` and `untrusted: true`. Content remains inert data, including
instructions in README files or comments. Nothing is installed, executed,
persisted to SQLite, logged as repository content, or sent to an AI provider.

## Limits

All KB values are decimal bytes, not character counts. The text/file budgets are
shared across the entire batch, not multiplied by the number of repositories.

| Resource | Limit |
| --- | --- |
| Repositories | 3, validated before retrieval |
| Selected file attempts | 20 total, including rejected binary/secret-like payloads |
| Individual decoded file | 20,000 bytes |
| Total decoded file bytes | 100,000, including omitted files |
| Parsed tree entries | 2,000; truncated trees are rejected |
| Metadata / tree / blob API body | 64,000 / 512,000 / 32,000 bytes |
| Total API body bytes | 2,000,000 per batch |
| HTTP requests | At most 26; no automatic retries or pagination |
| TCP/TLS connection / socket reads | 5 seconds each, reduced by remaining batch budget |
| Batch deadline | 30 seconds maximum; an optional caller deadline can only shorten it |

Content-Type must be JSON or GitHub's JSON media type. Compressed HTTP responses
are rejected (`Accept-Encoding: identity`); the client performs no decompression.
Content-Length is validated, and actual body size is checked as it streams before
UTF-8 decoding or JSON parsing. Duplicate JSON keys, nonfinite numbers, deep/invalid
JSON, mismatched hashes and malformed metadata/tree/blob schemas fail closed.

Successful files have status `retrieved`; intentional budget stops use
`partial_limit_reached` or `analysis_limit_reached`. No eligible output uses
`no_supported_files`. Failures such as `rate_limited`, `unavailable_or_private`,
`private_repository`, `forbidden`, `empty_repository`, `redirect_rejected`,
`response_too_large`, `truncated_tree`, `tree_limit_exceeded`, `invalid_response`,
`unsupported_content_type`, `unsupported_content_encoding`, `timeout`,
`network_error`, `tls_error`, `unsafe_destination`, `github_unavailable` and
`api_error` are returned explicitly, without raw response/error contents. HTTP
or protocol failure discards partial evidence for that repository. A 404 cannot
distinguish a nonexistent repository from a private/inaccessible one anonymously.
403 is marked rate-limited when rate/Retry-After headers establish that; other 403s
remain forbidden. No sleeping/retries bypass the budgets or rate restrictions.

## Connection-level SSRF and remaining deployment limits

The client has no arbitrary-host input, proxy support, netrc or environment-token
integration. DNS is queried only for api.github.com. Every returned address must
be globally routable and non-private/non-loopback/non-link-local/non-multicast;
mapped IPv4 and scoped IPv6 are checked. Mixed public/private answers are rejected.
At most four approved addresses are attempted under the connection budget.

TCP connects directly to a vetted numeric address, preventing a second DNS lookup
between validation and connection. TLS uses the default trusted CA context with
certificate and hostname verification, and fixed `api.github.com` SNI/Host.
Redirects are rejected for every request, including same-host redirects.

Application checks do **not** replace trusted DNS/CA configuration and a workload
egress firewall/network policy. They cannot fully control compromised routing,
NAT, infrastructure proxies or the surrounding process environment. DNS lookup is
OS-resolver controlled. Caller waiting is now bounded by the remaining connection
budget, using at most one daemon resolver worker for the fixed API hostname.
An expired OS resolver can continue in that single worker, but cannot start an
HTTP fetch; new resolution attempts fail with `dns_busy` until it finishes.
Socket watchdogs interrupt trickling headers/bodies at the shared batch deadline,
including when HTTPConnection detaches a `Connection: close` socket. These are
not real-time CPU scheduling or hard process-kill guarantees. Before exposing
this utility to untrusted callers, impose request-level/process isolation, global
concurrency/rate limits and restricted egress. No such Rahti/Docker changes are
made in this step. Live GitHub interoperability and deployment egress remain
unverified; tests mock all API/DNS/socket operations and need no internet.

Private repositories and authenticated access are intentionally unsupported.
Large, unusual-path or truncated repositories are rejected rather than partially
traversed. Only a representative subset of files is evidence, never a complete
audit or verification of skill claims. Repository visibility can change; each
retrieval relies on anonymous GitHub access at that time.

```sh
backend/.venv/bin/python -m unittest backend.test_github_fetcher -v
backend/.venv/bin/python -m unittest discover -s backend -t . -p 'test_*.py' -v
```
