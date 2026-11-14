# Internal MiniLM service (prepared only; not deployed)

These files add one CPU-only Deployment, a ClusterIP Service and a NetworkPolicy.
There is no Route, Ingress, NodePort, PVC, service-account token or runtime model
download. The application template now includes transport wiring; see
[application configuration and safe rollout](CONNECT_APPLICATION.md). No live
Deployment has been changed.

For a newly fabricated subject instead of existing candidates, see
[the additive synthetic demo setup](SYNTHETIC_DEMO.md).

For the current password-free, constant-fixture hackathon UI, use
[PUBLIC_DEMO.md](PUBLIC_DEMO.md). The older browser-session instructions remain
applicable only to protected workflows; they are not required by this demo path.

## Image preparation and local verification

Use Docker with Linux/amd64 support and the existing isolated model experiment
environment. If artifacts are absent, run `experiments/local_model/prepare_amd64.py`
as an explicit online preparation step before building. It uses the pinned model
revision, not a moving branch. Never commit model binaries or the virtualenv.

The image reuses `experiments/local_model/service/Dockerfile` and packages:

- `sentence-transformers/all-MiniLM-L6-v2`, Apache-2.0,
  revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`.
- Upstream dynamic UINT8 x86 AVX2 ONNX artifact: 23,046,789 bytes;
  tokenizer plus model: 23,513,036 bytes.
- Exact artifact hashes in `experiments/local_model/amd64_model_manifest.json`;
  verified at build and startup. Dependencies/base image retain existing pins.

```sh
docker buildx build --platform linux/amd64 --load \
  -f experiments/local_model/service/Dockerfile \
  -t recruitifi:minilm-service experiments/local_model
python3 experiments/local_model/service/run_container_checks.py
backend/.venv/bin/python -m unittest discover -s backend -t . -p 'test_*.py'
(cd experiments/local_model && .venv/bin/python -m unittest service.test_service -v)
docker run --rm -v "$PWD/deploy/rahti/ai:/manifests:ro" \
  ghcr.io/yannh/kubeconform:v0.8.0 -strict -summary \
  -kubernetes-version 1.35.0 /manifests
```

The container runner generates a transient test secret without printing it. It
tests authentication, offline inference, missing-model failure, arbitrary UID,
read-only rootfs and the 512MiB/0.5 CPU limits. It uses only synthetic text,
`--network=none`, no published ports, and removes its disposable containers.
Measurements are under `experiments/local_model/service/results/`. On Apple
Silicon these are emulated amd64 results, not native CSC performance guarantees.

## Runtime/security contract

The Deployment binds port 8080 on the Pod interface with one Uvicorn worker,
one ONNX intra/inter-op thread, one active inference and one queued waiter.
Queue wait is bounded to two seconds; excess calls return 429. Batches are 1–3
strings, at most 256 tokens including special tokens, never silently truncated.
The backend retains its request deadlines, response bounds and global job cap.

`/healthz` and `/readyz` need no credential for kubelet probes; `/embed` requires
one exact `Authorization: Bearer ...` header. `TALENTMATCH_EMBED_TOKEN` is mandatory
at startup (32–256 printable non-whitespace ASCII characters); missing/invalid
secrets fail before model loading. Request text, vectors and secrets are not logged.
The shared bearer secret is machine authentication, separate from Talent/Employer
browser sessions and the analysis operator token. Never expose it through Vite,
React, browser storage, ConfigMaps or image layers. Rotate both callers and AI
service together; existing pods need restart after Secret changes.

The read-only image requires only the bounded `/tmp` emptyDir. UID, groups,
SELinux and seccomp are assigned by Rahti's restricted SCC, with no fixed IDs.
All capabilities are dropped, privilege escalation and SA-token mounting disabled.
The model's image requires amd64 nodes with AVX2 support; validate actual nodes.

## Secret and future operator steps (not executed)

Prerequisites: an authorized Rahti project, `oc` login, registry build/push access,
available quota and verified NetworkPolicy enforcement. Replace `REPLACE_NAMESPACE`
and `REPLACE_TAG` in a temporary rendered manifest with your project and immutable
image tag/digest. Build/push the existing Dockerfile using your approved registry
workflow. No credentials are needed for local preparation.

Create a random Secret from a protected temporary file without exposing its value
in shell history or command arguments. Turn off shell tracing first:

```sh
set +x
umask 077
ai_secret_dir=$(mktemp -d)
trap 'rm -rf "$ai_secret_dir"' EXIT HUP INT TERM
python3 -c 'import secrets; print(secrets.token_urlsafe(48), end="")' \
  > "$ai_secret_dir/TALENTMATCH_EMBED_TOKEN"
oc create secret generic recruitifi-ai-auth \
  --from-file="TALENTMATCH_EMBED_TOKEN=$ai_secret_dir/TALENTMATCH_EMBED_TOKEN"
rm -rf "$ai_secret_dir"
trap - EXIT HUP INT TERM
unset ai_secret_dir
```

Apply the reviewed NetworkPolicy first, then Service and rendered Deployment.
Inspect `oc get pods,svc,networkpolicy`, `oc describe pod ...`, logs and rollout
state. Do not expose inference through a Route or publish this Secret in output.

Before connecting the application, deploy a newly built image containing the
updated embedding client through a separately authorized rollout. The prepared
application Pod template now has label `recruitifi.ai-client: 'true'` (retaining
`app: recruitifi`) and these server-only settings:

```yaml
- name: TALENTMATCH_EMBED_URL
  value: http://recruitifi-ai:8080/embed
- name: TALENTMATCH_EMBED_INTERNAL_HOST
  value: recruitifi-ai
- name: TALENTMATCH_EMBED_TOKEN
  valueFrom:
    secretKeyRef:
      name: recruitifi-ai-auth
      key: TALENTMATCH_EMBED_TOKEN
```

The client accepts only that exact internal hostname, port and path with explicit
opt-in and a secret, in addition to loopback. It rejects credentials in URLs,
arbitrary hosts/IP URLs, query strings, alternate ports, redirects and proxies.
DNS wait is bounded, answers must all be RFC1918/ULA private addresses, and the
chosen numeric address is pinned for connection (no second DNS lookup).
Use the same namespace. Nonstandard public Service CIDRs are intentionally rejected.
Keep synthetic-mode allowlists, browser account secrets and Employer grants configured
separately; enabling model transport does not grant browser analysis access.

## Quota, network and remaining cluster checks

For the two existing broad namespace policies, see
[the guarded selector-change proposal and rollback](NETWORK_POLICY_CHANGE.md).
The `.jsonpatch` files are operator patches, not Kubernetes resources.

AI Pod requests **250m CPU / 384Mi RAM**; limits **500m / 512Mi**, plus a bounded
64Mi temporary volume. Reserve ephemeral-storage/image quota and one additional
Pod. With the existing application the totals are 350m/640Mi requests and
1000m/1024Mi limits. CPU ratio is 2 and memory ratio is 1.34, within Rahti's maximum ratio of 5.
Recreate avoids update surge; inference is temporarily unavailable during upgrades.
Do not extrapolate model-only measurements to the application's memory budget.

The NetworkPolicy allows TCP/8080 only from same-namespace Pods with **both**
application labels and denies all AI egress. Kubelet probes are node traffic;
test actual SCC/CNI/probe behavior. Label assignment is not identity against
namespace administrators: restrict RBAC/Secret access and deployment permissions.

**NetworkPolicies are additive.** Rahti commonly has namespace-wide default
same-namespace/ingress allow policies. Another matching allow policy can widen
access despite this file. An operator must inspect and narrow those policies
without breaking the existing app, then prove an unlabelled Pod cannot connect.
No existing policy is changed here. If isolation cannot be verified, do not
enable AI access. Even when routing is allowed accidentally, `/embed` rejects
unauthenticated callers.

Internal HTTP does not encrypt bearer tokens or synthetic evidence. NetworkPolicy
is not TLS; verify platform transport protection or arrange authenticated TLS
before real personal data. DNS compromise can still direct traffic to private
addresses; trusted cluster DNS and caller egress controls are required. There is
no arbitrary internet inference fallback. This remains a synthetic hackathon
service, not production authentication or a hiring recommendation system.

Real-cluster admission, quota, AVX2, private DNS, network-policy union, unauthorized
Pod denial, Secret injection, app connectivity, native latency/memory and sustained
load remain unverified. The live RecruitiFi Deployment has not been enabled.

References: [CSC workload security](https://docs.csc.fi/cloud/rahti/configurations/workload-security/),
[quotas](https://docs.csc.fi/cloud/rahti/configurations/resource-quota/),
[NetworkPolicies](https://docs.csc.fi/cloud/rahti/configurations/netpol/).

### Opt-in analysis for every existing Talent demo account

The private profile-analysis API can also accept consented evidence from existing
Talent accounts. This remains password-verified hackathon account access, not
production identity verification. Do not distribute one person's password to
another participant or treat the account selector as authentication.

Set `TALENTMATCH_AI_CONSENTED_MODE=1` and configure
`TALENTMATCH_AI_CANDIDATES` with the approved candidate IDs (the fifteen existing
Talent mappings plus 900001). In this mode set
`TALENTMATCH_AI_SYNTHETIC_DEMO=0`; existing profiles are not declared synthetic.
Keep `TALENTMATCH_AI_PUBLIC_DEMO=0`, verified account login, the session signing
Secret, operator token, and private embedding-service authentication enabled.
The Secret-backed `TALENTMATCH_AI_DEMO_ACCOUNTS` must contain a distinct password
for each enabled Talent alias. Keep credentials out of manifests, Git, logs and
frontend build variables. No passwords are generated by application startup.

Each Talent selects at most three of their own CV/PDF, project or GitHub
materials, confirms permission, and clicks **Analyze My Profile**. Only these
materials may be analyzed (10 MiB combined file limit). Changing a selected
material invalidates its consent and cached result; it must be approved again.
No existing document is automatically submitted. The known fictional 900001
fixture retains its existing narrowly scoped server approval.

`POST /api/ai-matches/profiles/{candidate_id}/consent` accepts
`material_ids`, `confirm: true` and optional
`share_with_employer_001: true`. It requires the owner's signed session,
same-origin request and CSRF token. Ownership and supported categories are
validated in SQLite. An additive `ai_material_consents` table stores hashes and
sharing choices, without modifying documents or candidate skills.

Sharing defaults to private. Selecting the Employer 001 sharing checkbox allows
that verified Employer to see scores and short evidence excerpts for its own
jobs. Resubmitting consent without sharing revokes that access, including when
an older server sharing grant exists. Existing synthetic fixture grants remain
available. Keep the private model service internal; no model credentials or
service URL are returned to the browser. This feature does not provide consent
withdrawal/data-retention administration suitable for production personal data.

After rebuilding and publishing the updated application image, the corresponding
application environment settings are (prepare/review before applying):

```text
TALENTMATCH_AI_CONSENTED_MODE=1
TALENTMATCH_AI_CANDIDATES=402,406,411,417,423,429,432,438,445,451,458,463,470,476,483,900001
TALENTMATCH_AI_SYNTHETIC_DEMO=0
TALENTMATCH_AI_PUBLIC_DEMO=0
TALENTMATCH_VERIFIED_DEMO_LOGIN=1
TALENTMATCH_AI_JOB_MATCHING=1
```

Extend the existing Secret-backed account map with `talent-001` through
`talent-015`, preserving the existing `talent-ai-001` and `employer-001` passwords.
Each alias must retain its existing server-side candidate mapping. The account
map now has seventeen entries, below its twenty-account limit. This preparation
does not itself change the running Rahti Deployment or grant consent to any
existing materials. Never bulk-consent or analyze existing CVs to test rollout;
verify account sign-in and use newly fabricated evidence instead.
