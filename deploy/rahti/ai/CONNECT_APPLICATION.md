# Application connection: prepared only, not deployed

For the current password-free fictional project UI, follow [PUBLIC_DEMO.md](PUBLIC_DEMO.md).
The account-password/signing/grant settings below apply to the retained protected
workflow, not the new constant-fixture public routes.

The application Deployment now has the caller label and the three transport
settings. Its existing settings, image placeholder, one replica, Recreate, PVC,
resources, security context and probes remain unchanged. Route/Service are unchanged.
Transport settings do not enable analysis or establish that data is synthetic.

## Missing configuration / operator decisions

No live configuration, Secret or database was inspected. The following browser
analysis settings are absent from the checked-in Deployment; supply them only in
a separately reviewed server-side configuration after verifying synthetic data:

| Setting | Requirement |
|---|---|
| `TALENTMATCH_AI_SYNTHETIC_DEMO` | Explicit `1` only for an isolated synthetic dataset/materials; leave disabled for mixed/real data. Configuration is not a PII detector. |
| `TALENTMATCH_AI_SYNTHETIC_CANDIDATES` | Operator-approved 1–15 positive IDs, comma-separated without spaces. |
| `TALENTMATCH_AI_DEMO_TOKEN` | Independent operator secret: 32–256 printable non-whitespace ASCII characters; required even for cookie access. |
| `TALENTMATCH_AI_SESSION_SECRET` | Independent random signing secret, at least 32 characters. |
| `TALENTMATCH_AI_DEMO_ACCOUNTS` | Server-only JSON map of existing Talent/Employer account names to distinct 12–128-character synthetic passwords. No Organizer; max 20 accounts. |
| `TALENTMATCH_AI_EMPLOYER_ACCESS` | Company-ID strings mapped to approved candidate-ID lists; max five companies. No grants means no Employer access. |

The new `TALENTMATCH_EMBED_TOKEN` reference requires the **existing**
`recruitifi-ai-auth` Secret and its identically named key (32–256 printable
non-whitespace ASCII characters). AI and app must use that same service secret.
Its live existence/value has not been verified. Keep service, operator, signing
secrets and all account passwords independent; never put them in Git, images,
Vite variables, browser storage or command arguments. Reference browser/operator
settings through intended server-side Secret keys in a separate enablement change;
no default passwords, optional fallback or bypass is introduced here.

From `backend/demo_accounts.py`, Talent accounts 001–015 map in order to
`402,406,411,417,423,429,432,438,445,451,458,463,470,476,483`;
Employer accounts 001–005 map to companies 1–5. Actual records must exist and be
synthetic. Every configured Talent must be allowlisted; every Employer account
must have an explicit grant entry. For example, after verification, `402,406`
with grants `{"1":[402,406]}` can support Talent 001/002 and Employer 001.
This example supplies no passwords or authorization to use live data. Do not
seed/reset the PVC to fit it, or enable analysis on a public database receiving
real uploads. Mock role selection is not authentication.

See `backend/evidence/API.md`, `BROWSER_SESSIONS.md`, and `EMPLOYER_VIEW.md` for
cookie scopes, CSRF, account/password validation and synthetic restrictions.
Verify HTTPS scheme, Host and Origin through the actual trusted Rahti proxy;
do not bypass CSRF/Origin or configure unrestricted proxy trust to fix login.
The existing hosted Basic-auth choice is preserved, not changed by this work.

## Fresh image required

The root Dockerfile includes `backend/evidence/*.py`, the existing PDF dependency
and built frontend, without model artifacts. Preparation built and checked
`recruitifi:internal-ai-prepared` (linux/amd64), including source-hash comparisons
for the current embedding client, sessions and API modules and browser UI strings.
It did not inspect or replace the running Rahti image.

```sh
docker buildx build --platform linux/amd64 --load -t recruitifi:internal-ai-prepared .
docker run --rm --platform linux/amd64 --user 1000620000:0 \
  --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
  recruitifi:internal-ai-prepared python -c \
  'import backend.main; from backend.evidence import embedding_client,sessions,api,employer_api; assert embedding_client.INTERNAL_HOST == "recruitifi-ai"; print("Imports and internal client present")'
```

Publish verified current source with the existing approved registry/build
workflow in `../README.md`. Record the resulting **immutable internal image
digest**; do not reuse an old mutable tag. Nothing was pushed by preparation.

## Future safe rollout commands — not executed

Prerequisites: correct project; synthetic-only data verified; ready AI service;
existing matching Secret; verified network isolation from `NETWORK_POLICY_CHANGE.md`;
quota; reviewed image digest; approval for a single-replica Recreate outage.
No browser feature flag is enabled by the commands below. If it is already enabled
in the live configuration, verify its accounts, allowlist, grants and data first.

Use a dedicated Bash shell with error/pipe checking. A failed preflight, render,
dry-run or rollout is a stop condition. Keep the protected backup outside Git.

```bash
set -euo pipefail
set +x
umask 077
oc whoami --show-server
oc project -q
oc rollout status deployment/recruitifi-ai --timeout=180s
oc get endpointslice -l kubernetes.io/service-name=recruitifi-ai -o wide
oc get secret recruitifi-ai-auth -o json | python3 -c \
  'import sys,json,base64; v=base64.b64decode(json.load(sys.stdin)["data"]["TALENTMATCH_EMBED_TOKEN"],validate=True); assert 32<=len(v)<=256 and all(33<=c<=126 for c in v); print("AI Secret key present and valid")'
export rollout_dir=$(mktemp -d)
oc get deployment recruitifi -o json > "$rollout_dir/before.json"
# Replace the entire example with the verified published pull reference:
export APP_IMAGE='image-registry.openshift-image-registry.svc:5000/YOUR_PROJECT/recruitifi@sha256:YOUR_VERIFIED_DIGEST'
python3 - <<'PY'
import json,os,re
from pathlib import Path
root=Path(os.environ['rollout_dir'])
d=json.loads((root/'before.json').read_text())
image=os.environ['APP_IMAGE']
assert re.fullmatch(r'image-registry\.openshift-image-registry\.svc:5000/[a-z0-9-]+/recruitifi@sha256:[0-9a-f]{64}',image), 'Supply a real verified image digest.'
assert d['spec']['replicas']==1 and d['spec']['strategy']['type']=='Recreate'
t=d['spec']['template']; assert t['metadata']['labels']['app']=='recruitifi'
matches=[i for i,c in enumerate(t['spec']['containers']) if c['name']=='recruitifi']
assert len(matches)==1
i=matches[0]; c=t['spec']['containers'][i]; base=f'/spec/template/spec/containers/{i}'
ops=[{'op':'test','path':'/metadata/resourceVersion','value':d['metadata']['resourceVersion']},
     {'op':'add','path':'/spec/template/metadata/labels/recruitifi.ai-client','value':'true'},
     {'op':'replace','path':base+'/image','value':image}]
if 'env' not in c: ops.append({'op':'add','path':base+'/env','value':[]})
settings=[{'name':'TALENTMATCH_EMBED_URL','value':'http://recruitifi-ai:8080/embed'},
 {'name':'TALENTMATCH_EMBED_INTERNAL_HOST','value':'recruitifi-ai'},
 {'name':'TALENTMATCH_EMBED_TOKEN','valueFrom':{'secretKeyRef':{'name':'recruitifi-ai-auth','key':'TALENTMATCH_EMBED_TOKEN'}}}]
for entry in settings:
    found=[j for j,e in enumerate(c.get('env',[])) if e['name']==entry['name']]
    assert len(found)<=1, 'Duplicate environment key; review manually.'
    ops.append({'op':'replace' if found else 'add','path':base+'/env/'+(str(found[0]) if found else '-'),'value':entry})
revision=d['metadata'].get('annotations',{}).get('deployment.kubernetes.io/revision','')
assert revision.isdigit(), 'Record/review the previous rollout revision.'
(root/'previous-revision').write_text(revision)
(root/'connect.patch.json').write_text(json.dumps(ops,indent=2))
print('Prepared guarded patch retaining existing live settings.')
PY
oc patch deployment recruitifi --type=json \
  --patch-file="$rollout_dir/connect.patch.json" --dry-run=server -o name
```

Stop here and review the protected patch and dry-run result. Only with execution
authorization, run this separate mutation block in the same dedicated shell:

```bash
oc patch deployment recruitifi --type=json \
  --patch-file="$rollout_dir/connect.patch.json" -o name
oc rollout status deployment/recruitifi --timeout=180s
oc get pods -l 'app=recruitifi,recruitifi.ai-client=true'
```

Review the prepared patch privately before executing its mutation command. It
changes exactly the label, three environment entries and one image in one update.
The resourceVersion test rejects concurrent changes; take a fresh snapshot and
review/regenerate on conflict rather than removing the guard. The snapshot-based
patch preserves unknown live environment settings, PVC, probes and resources.
Do not apply the repository template over an unreviewed live Deployment, scale
above one replica, switch update strategy, or issue multiple image/env rollouts.

Verify `/healthz`, HTTPS frontend/API, network access/denial matrix, service-token
rejection, and CPU/memory/OOM state. Once separately configured for synthetic
access, verify Talent password login → CSRF trigger → polling/results and Employer
sharing/candidate isolation. No secrets or evidence should appear in logs.

If needed, review the saved prior revision and confirm no unrelated rollout has
occurred before operational rollback:

```sh
previous_revision=$(cat "$rollout_dir/previous-revision")
oc rollout history deployment/recruitifi
oc rollout undo deployment/recruitifi --to-revision="$previous_revision"
oc rollout status deployment/recruitifi --timeout=180s
```

Rollback restores a Pod template, not SQLite contents. Keep one replica, Recreate,
the existing PVC and AI network isolation. Never reset data or undo another
operator's intervening work. No real-cluster rollout/admission, HTTPS proxy behavior
or live image digest was verified by this local preparation.
