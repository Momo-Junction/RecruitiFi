# Proposed private-AI policy change — not applied

This proposal uses the two current policy descriptions supplied by the operator.
Their live YAML, namespace labels and CNI/router configuration have not been read.
Only the checked-in AI policy and application Service/Route were inspected locally.

## Exact changes

For **both** `allow-from-router` and `deny-other-namespaces-access`, change only:

```yaml
spec:
  podSelector:
    matchExpressions:
      - key: app
        operator: NotIn
        values: [recruitifi-ai]
```

This replaces their current `spec.podSelector: {}`. Preserve every existing
`ingress.from`, router namespace selector, port rule and `policyTypes` value.
Do not replace the router namespace selector with `{}`. Do not change the
same-namespace `from.podSelector: {}` into a namespace selector or empty `from`.

`NotIn` retains Pods with other `app` values **and Pods without that label**, so
existing non-AI traffic permissions remain unchanged. Narrowing both destination
selectors removes the two broad grants to AI. Selecting only `app: recruitifi`
instead would unnecessarily change permissions for other namespace workloads.

**No functional change to `networkpolicy.yaml` is needed.** It already selects
`app: recruitifi-ai`, permits only same-namespace source Pods having both
`app: recruitifi` AND `recruitifi.ai-client: 'true'`, and only on TCP/8080.
It denies AI egress; connection replies remain permitted. There is no router
namespace grant and no arbitrary IP/node allow rule. Keep its ingress and egress
rules as checked in. The AI Pod/Service labels must retain `app: recruitifi-ai`.

Policies are additive: leaving either broad policy selecting AI defeats the
restriction. Inspect **all** other policies selecting AI as well. Source egress
must also permit the app connection; do not loosen namespace-wide egress here.
Neither Service, public Route, application Deployment nor database needs changing
for this policy patch. App pods need the existing explicit caller label before
they can connect; a missing label must result in denied access.

## Operator preflight and backups (commands only; not executed)

Use an explicitly selected project and an approved maintenance window. Store
backups outside Git. Verify context/project before any mutation:

```sh
oc whoami --show-server
oc project -q
umask 077
policy_backup_dir=$(mktemp -d)
oc get networkpolicy -o yaml > "$policy_backup_dir/all-policies.yaml"
oc get networkpolicy allow-from-router -o json > "$policy_backup_dir/router.json"
oc get networkpolicy deny-other-namespaces-access -o json > "$policy_backup_dir/namespace.json"
oc get networkpolicy recruitifi-ai-isolation -o yaml > "$policy_backup_dir/ai.yaml"
oc get pods --show-labels
oc get service recruitifi recruitifi-ai
oc get route recruitifi
```

Keep `policy_backup_dir` for rollback/audit. Confirm the two broad policies have
`policyTypes: [Ingress]` and `podSelector: {}`. The provided JSON patches test both
conditions and refuse to overwrite unexpected selectors/types. If they differ,
stop and review the actual YAML; do not remove the guards to force the patch.
Inspect live AI rules against `networkpolicy.yaml`, and check for any other
policy with an empty selector, overlapping selector, broad namespace or IP grant.

Confirm public Service endpoints have `app: recruitifi` and AI endpoints have
`app: recruitifi-ai`. Inspect EndpointSlices as well as Service labels:

```sh
oc get endpointslice -l kubernetes.io/service-name=recruitifi -o wide
oc get endpointslice -l kubernetes.io/service-name=recruitifi-ai -o wide
```

The existing application caller label is necessary but is not proof of identity
against a namespace administrator. Retain bearer authentication and restrict RBAC
for label mutation, deployment creation and Secret reads. Never give test Pods
the inference Secret just to prove TCP reachability.

## Before/after access matrix

Use NEW connections for every test, both via Service DNS and directly to each AI
Pod IP; existing connections can survive policy updates. Use `/healthz` or
`/readyz` (no secret/body required). An HTTP 401 on `/embed` still means network
access was allowed; it does **not** prove a NetworkPolicy denial.

| Source → destination | Before (described defaults) | After |
|---|---|---|
| Public HTTPS Route → application | Existing response | Same response |
| Dual-labelled same-namespace app → AI TCP/8080 | HTTP 200 health | HTTP 200 health |
| `app: recruitifi` without caller label → AI | HTTP 200 health | TCP/HTTP connection blocked |
| Unrelated same-namespace Pod → AI | HTTP 200 health | Blocked |
| Ordinary router-namespace Pod → AI | HTTP 200 health | Blocked |
| Actual ingress router process → AI | Reachable under broad grant | Must be blocked; see host-network caveat |
| Other namespace → AI | Blocked | Blocked |
| Kubelet → AI probes | Ready/healthy | Ready/healthy |
| Existing non-AI namespace traffic | Baseline | Same as baseline |

Do not invent an AI public Route to test this. The AI stays ClusterIP only.
Record baseline public Route status/body and a representative application API
response. HTTP 401 is a valid unchanged baseline if shared demo auth is enabled.
For example (use the actual route hostname):

```sh
app_host=$(oc get route recruitifi -o jsonpath='{.spec.host}')
curl --connect-timeout 3 --max-time 10 -sS -o /dev/null -w '%{http_code}\n' "https://$app_host/"
curl --connect-timeout 3 --max-time 10 -sS -o /dev/null -w '%{http_code}\n' "https://$app_host/healthz"
```

For Pods with Python installed, reuse this read-only TCP/HTTP probe, substituting
an existing authorized, unlabelled, or unrelated Pod name for `SOURCE_POD`. Set
`AI_HOST` to `recruitifi-ai` first, then to each AI Pod IP. It disables proxies,
prints only status or failure type, sends no inference text/credential, and
returns nonzero on connection failure:

```sh
oc exec -i SOURCE_POD -- python - AI_HOST <<'PY'
import sys, urllib.request
host = sys.argv[1]
if ':' in host:
    host = '[' + host + ']'
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
try:
    with opener.open('http://' + host + ':8080/healthz', timeout=3) as response:
        print('HTTP', response.status)
except Exception as error:
    print('CONNECT_FAILED', type(error).__name__)
    raise SystemExit(1)
PY
```

Denied tests require a healthy AI destination and a successful authorized control
test at the same time. Diagnose DNS, client egress and service endpoints separately;
a timeout caused by a broken service is not evidence of isolation. Repeat after
CNI convergence using fresh processes. For unrelated/new diagnostic Pods, use an
approved image/identity and no Secret, privilege, host networking or caller label.
Creating those Pods is a separately authorized cluster operation, not performed
here. An operator with router-namespace permission must run an equivalent
bounded HTTP/TCP probe from an ordinary pod there **and the actual router process**
to both the AI Service IP and each Pod IP. Do not create a public AI route or
grant application users elevated router-namespace privileges to run the test.

## Future change sequence (not executed)

1. Capture the matrix baseline and backups. Verify the AI policy already exists
   and is correct **before** narrowing the two broad destination selectors. If
   absent, prepare/apply only `networkpolicy.yaml` first and inspect its live rules.
2. Preview each guarded patch through server-side dry-run and review the output.
3. Patch both selectors; the public app remains selected throughout. While only
   one patch has landed, AI is still reachable through the other broad policy;
   do not claim isolation until both succeed. If interrupted, finish the pair
   promptly or stop the AI workload rather than leave a false security claim.
4. Repeat the matrix, check AI readiness/events and public Route/API responses.

```sh
oc patch networkpolicy allow-from-router --type=json \
  --patch-file=deploy/rahti/ai/exclude-ai-selector.jsonpatch --dry-run=server -o yaml
oc patch networkpolicy deny-other-namespaces-access --type=json \
  --patch-file=deploy/rahti/ai/exclude-ai-selector.jsonpatch --dry-run=server -o yaml
# Only after review and separate execution authorization:
oc patch networkpolicy allow-from-router --type=json \
  --patch-file=deploy/rahti/ai/exclude-ai-selector.jsonpatch
oc patch networkpolicy deny-other-namespaces-access --type=json \
  --patch-file=deploy/rahti/ai/exclude-ai-selector.jsonpatch
oc get pods -l app=recruitifi-ai
oc describe pod AI_POD
oc get events --sort-by=.lastTimestamp
```

Do not use `oc apply -f deploy/rahti/ai/` indiscriminately: JSON patch documents
are not Kubernetes resources. Select `networkpolicy.yaml` explicitly.

## Safe rollback

Restoring the broad selectors while AI is running reopens router and unrelated
Pod access. If rollback is required, first stop AI (no persistent data is involved)
and wait until **all** its Pods terminate and EndpointSlices have no ready AI
endpoints. Then restore only the two original empty selectors, preserving all
current ingress/source rules. The guarded rollback refuses unexpected drift:

```sh
oc scale deployment/recruitifi-ai --replicas=0
oc wait --for=delete pod -l app=recruitifi-ai --timeout=120s
oc get endpointslice -l kubernetes.io/service-name=recruitifi-ai -o yaml
oc patch networkpolicy allow-from-router --type=json \
  --patch-file=deploy/rahti/ai/restore-all-pods-selector.jsonpatch
oc patch networkpolicy deny-other-namespaces-access --type=json \
  --patch-file=deploy/rahti/ai/restore-all-pods-selector.jsonpatch
```

Apply the rollback patch only to policies changed by this procedure. If only one
forward patch succeeded, revert only that one. If the guard fails, inspect the
backups/current policy and preserve concurrent changes; do not force-replace it.
Keep the dedicated AI policy, Service and Secret. Recheck the application Route.
**Do not restart AI with broad grants restored.** Restore reviewed isolation and
prove the matrix before scaling AI back to its original single replica.

## Health probes and limits of this proposal

Kubelet probes originate at the node; ordinary NetworkPolicy does not block a
Pod's resident node. Do not add a router/namespace-wide health-check grant.
Probes on `/healthz` and `/readyz` remain unauthenticated and unchanged. Confirm
their real status after the change; operator monitoring from other Pods may need
its own narrowly reviewed policy, not a blanket exception.

`hostNetwork` router traffic may be treated as node traffic by the CNI. Therefore
standard NetworkPolicy alone cannot guarantee blocking such routers while also
preserving node-origin probes. Inspect the real ingress controller endpoint mode
and test from actual router Pods/nodes. If it bypasses policy, this goal remains
blocked pending CSC/CNI-supported controls; do not add broad node IP exceptions
or claim an ordinary router-namespace test proves router isolation.

Other matching policies, platform-level policies, RBAC, policy propagation and
probe/router behavior require cluster validation. Nothing has been applied, no
diagnostic Pods created, and no database/deployment modified by this preparation.

References: [CSC network policies](https://docs.csc.fi/cloud/rahti/configurations/netpol/),
[Kubernetes policy semantics, probes/node traffic and hostNetwork](https://kubernetes.io/docs/concepts/services-networking/network-policies/).
