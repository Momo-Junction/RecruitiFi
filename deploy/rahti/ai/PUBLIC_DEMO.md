# Password-free fictional AI demo (prepared, not deployed)

Talent selects `talent-ai-001`, opens Projects & portfolio and clicks **Analyze
Evidence**. Employer selects `employer-001`, opens candidate 900001 and clicks
**View AI evidence findings**. There is no second AI password, session login or
CSRF requirement on this path. If the candidate is below job thresholds, use the
existing Employer **Eligible queue → Explore all talent** control; do not change
skills, thresholds or fit percentages to make it eligible.

## Scope and security boundary

Public access is explicitly opt-in and defaults off. The following **server-only**
configuration must match exactly:

```text
TALENTMATCH_AI_PUBLIC_DEMO=1
TALENTMATCH_AI_SYNTHETIC_DEMO=1
TALENTMATCH_AI_SYNTHETIC_CANDIDATES=900001
```

The demo uses only the provisioned fixture in `backend/evidence/synthetic_demo.py`.
Candidate identity markers and the project category/title/description/URL must
match those constants. Exactly one material must belong to the candidate, with
no uploaded BLOB, filename, content type or linked skill. A changed project,
additional upload/link or duplicate disables this public path. No candidate
profile/material is automatically repaired, reset, seeded or overwritten.

The worker rechecks the fixture and constructs extraction input from constants,
not mutable evidence text; it never calls GitHub or a PDF parser on this path.
The supervisor rechecks before saving. Reads recheck the current material and
validate every stored excerpt against the constant text. Only this route's
dedicated jobs and their semantic findings are returned. Other candidate IDs,
material IDs, jobs, employers, uploaded documents and arbitrary URLs/paths/grants
are rejected. Browser request bodies and query options are not supported.

Existing operator/session-protected analysis routes retain their protections.
This new flow needs **none** of the AI account passwords, signing secret,
operator token or Employer grant configuration. Existing Secrets can remain for
protected internal workflows; do not delete or publish them. The public boundary
is hardcoded, not inferred from mock roles or configurable Employer grants.

The mock selector controls presentation only. Anyone who can reach the application
may use these new routes for the same fixed fictional fixture; it is intentionally
not authenticated Talent/Employer authorization. Existing hosted application
HTTP Basic authentication still wraps the routes when enabled. Do not disable,
remove or change `TALENTMATCH_DEMO_AUTH_ENABLED` / `TALENTMATCH_DEMO_PASSWORD` for
this rollout. Unrelated profile/upload/authentication behavior is unchanged.

Private MiniLM URL/hostname and `TALENTMATCH_EMBED_TOKEN` stay exclusively on the
backend. The token still comes from `recruitifi-ai-auth`. No model URL, token,
password or privileged key is sent to React. The AI remains ClusterIP-only with
its bearer authentication and existing NetworkPolicies.

One global background job is allowed, existing deadlines/limits are retained,
active requests coalesce, and completed constant-fixture results are reused.
Failed jobs have a 30-second retry cooldown. There is no public deletion/reset
endpoint. Old unrelated jobs are never recovered or edited by these routes; an
unrelated stuck job produces a busy response for operator investigation.

## Public API (still behind hosted app auth if configured)

Prefix: `/api/ai-demo/candidates/900001`.

| Method | Path | Behavior |
|---|---|---|
| GET | `/materials/{material_id}` | Check exact fictional fixture; return latest public job metadata. |
| POST | `/materials/{material_id}/analysis` | Empty body only; return 202 and scoped job URLs. |
| GET | `/analysis-jobs/{job_id}` | Public-demo job status only. |
| GET | `/analysis-jobs/{job_id}/result` | 202 while active; safe findings on completion or sanitized failure. |
| GET | `/employers/1/findings` | Same fictional result, read-only; no configurable grants. |

Disabled/non-exact allowlist → 404; other subjects/materials/employers or modified
evidence → 403; unknown/non-demo job → 404; options/body → 422; busy/cooldown → 429;
missing supervisor → 503. Model outages produce a failed background job, never
fabricated findings. Responses are `no-store`. Similarity remains relevance,
not proficiency, authorship, hiring suitability or existing job-fit percentages.

## Local validation

```sh
backend/.venv/bin/python -m unittest discover -s backend -t . -p 'test_*.py'
(cd frontend && npm test && npm run build)
```

Tests use disposable SQLite/mocked embeddings, never Rahti or real documents.
They verify direct no-cookie triggering/results, Employer reads, other-candidate
denial, fixture edits/uploads, worker/save-time races, stored-excerpt tampering,
unchanged existing records, retry limits and hosted-password enforcement.
Frontend tests check relative routes, absence of credentials/CSRF, 202 polling,
scope checks, cancellation, and denial/service errors.

## Safe future rollout (commands only; NOT executed)

1. Build/publish the updated application image via the existing root Dockerfile
   and approved registry workflow. It packages the new backend modules and built
   frontend; it does not package MiniLM. Record a verified immutable image digest.
2. Verify candidate 900001 and its exact fictional project already exist. If
   absent, provisioning requires separate explicit approval using the insert-only
   helper; never run the general seed/reset commands. Do not modify 402 or 406.
3. Verify private AI readiness, bearer Secret, caller label, namespace policies,
   quota and the existing application's hosted-password configuration. No AI
   Service/Route/PVC/network-policy changes are required for this UI change.
4. In a dedicated Bash shell, prepare a resourceVersion-guarded image/config patch
   from the live snapshot. Keep the temporary files outside Git and private.

```bash
set -euo pipefail
set +x
umask 077
oc whoami --show-server
oc project -q
oc rollout status deployment/recruitifi-ai --timeout=180s
rollout_dir=$(mktemp -d)
export rollout_dir
oc get deployment recruitifi -o json > "$rollout_dir/before.json"
export APP_IMAGE='image-registry.openshift-image-registry.svc:5000/YOUR_PROJECT/recruitifi@sha256:YOUR_VERIFIED_DIGEST'
python3 - <<'PY'
import json,os,re
from pathlib import Path
root=Path(os.environ['rollout_dir'])
d=json.loads((root/'before.json').read_text()); image=os.environ['APP_IMAGE']
assert re.fullmatch(r'image-registry\.openshift-image-registry\.svc:5000/[a-z0-9-]+/recruitifi@sha256:[0-9a-f]{64}',image), 'Supply the real verified digest.'
assert d['spec']['replicas']==1 and d['spec']['strategy']['type']=='Recreate'
assert d['spec']['template']['metadata']['labels']['app']=='recruitifi'
containers=d['spec']['template']['spec']['containers']
indices=[i for i,c in enumerate(containers) if c['name']=='recruitifi']; assert len(indices)==1
i=indices[0]; c=containers[i]; base=f'/spec/template/spec/containers/{i}'
env={e['name']:e for e in c.get('env',[])}
assert env.get('TALENTMATCH_EMBED_URL',{}).get('value')=='http://recruitifi-ai:8080/embed'
assert env.get('TALENTMATCH_EMBED_INTERNAL_HOST',{}).get('value')=='recruitifi-ai'
ref=env.get('TALENTMATCH_EMBED_TOKEN',{}).get('valueFrom',{}).get('secretKeyRef',{})
assert ref.get('name')=='recruitifi-ai-auth' and ref.get('key')=='TALENTMATCH_EMBED_TOKEN' and not ref.get('optional',False)
ops=[{'op':'test','path':'/metadata/resourceVersion','value':d['metadata']['resourceVersion']},
 {'op':'replace','path':base+'/image','value':image},
 {'op':'add','path':'/spec/template/metadata/labels/recruitifi.ai-client','value':'true'}]
for name,value in [('TALENTMATCH_AI_PUBLIC_DEMO','1'),('TALENTMATCH_AI_SYNTHETIC_DEMO','1'),('TALENTMATCH_AI_SYNTHETIC_CANDIDATES','900001')]:
    found=[j for j,e in enumerate(c['env']) if e['name']==name]; assert len(found)<=1
    ops.append({'op':'replace' if found else 'add','path':base+'/env/'+(str(found[0]) if found else '-'),'value':{'name':name,'value':value}})
(root/'public-demo.patch.json').write_text(json.dumps(ops,indent=2))
print('Prepared patch; hosted auth, PVC, resources and probes retained.')
PY
oc patch deployment recruitifi --type=json \
  --patch-file="$rollout_dir/public-demo.patch.json" --dry-run=server -o name
```

Stop for review. If prerequisites fail, use `CONNECT_APPLICATION.md` to prepare the
transport first; do not bypass assertions or expose the model endpoint publicly.
Only after execution authorization, apply the reviewed patch once:

```sh
oc patch deployment recruitifi --type=json \
  --patch-file="$rollout_dir/public-demo.patch.json" -o name
oc rollout status deployment/recruitifi --timeout=180s
```

This preserves the existing PVC, SQLite data, replicas/Recreate strategy,
resources, probes, hosted authentication and unrelated environment values. The
resourceVersion guard prevents overwriting intervening changes. Never scale to
multiple SQLite writers or delete a PVC/database to resolve a failed rollout.

After rollout verify hosted password enforcement (if enabled), the public Route,
Talent 900001 analysis/results, Employer 001 view, and 403 rejection for other
candidate IDs. Do not submit or download their documents to test denial. Verify
no internal URL/token appears in browser requests or logs. To disable this public
path without deleting data, prepare a reviewed update setting only
`TALENTMATCH_AI_PUBLIC_DEMO=0`; do not turn off the application's hosted password.
