# RecruitiFi on CSC Rahti 2 — infrastructure prepared, hosted deployment blocked

**Do not deploy this checkout publicly.** Inspection of commit `be8131b` found no
`TALENTMATCH_HOSTED_DEMO` handling, demo-password authentication, `/healthz`,
production static server, Dockerfile, Kubernetes files, or `render.yaml`.
The requested shared-password protection does not exist in this branch. At the
owner's direction, authentication was **not** added. The container launcher refuses
hosted mode even when a Secret supplies a password. Do not disable that guard in
Rahti: integrate and separately review an authenticated hosted baseline first.
No CSC login, cluster connection, build, deployment or resource creation was
performed while preparing these files. Commands below are for a later authorized
operator. This is a shared event demo: **synthetic candidates and documents only**.

## Contents and scope

- Root `Dockerfile`: Node 22 / pinned pnpm 10.28.0 frontend build, Python 3.13 slim
  runtime; Linux amd64 supported. Base image manifests are digest-pinned.
- Root `.dockerignore`: allowlisted build context; excludes all environment files,
  local databases, secrets, Git, node_modules, virtualenvs and build artifacts.
- `pvc.yaml`, `deployment.yaml`, `service.yaml`, `route.yaml`: one Deployment,
  one 1Gi RWO PVC, ClusterIP Service, edge TLS Route with HTTP redirect.
- `requirements.lock`: tested Python dependency constraints for repeatable image builds.
- `test_container.py`: local-only synthetic smoke and persistence test; cleans up
  only its uniquely named containers and volume.
- `backend/container_start.py`: non-root/data-path checks, group-write umask,
  explicit hosted-mode blocker, single Uvicorn worker, 8080/0.0.0.0 binding.
- Minimal application deployment changes: health endpoint, conditional static
  mount after API routes, production-relative API base URL. No schema, scoring,
  UI, authentication or API request/response changes were made.

The repository documents pnpm, has a v9 pnpm lockfile and pnpm workspace build
policy. It also contains an npm lockfile and existing CI uses npm; these are
preserved. Docker uses **pnpm --frozen-lockfile**, not an unlocked npm install.
Python dependencies come from unchanged `backend/requirements.txt`, constrained
by `deploy/rahti/requirements.lock` to the versions tested in this image. Update
constraints deliberately with a rebuild/test; record the final image digest per
release. The versions already resolved in the tested image are preserved; base Python requirements are unchanged.

## Runtime data and identity

All durable writes (profiles, skills, employer roles, likes, audit calculations,
link metadata and uploaded document BLOBs) use SQLite through `TALENTMATCH_DB`.
Documents are not stored in a separate uploads directory. The container sets
`TALENTMATCH_DB=/var/data/talentmatch.sqlite3`; mount the **whole directory**, so
SQLite's journal and any WAL/SHM files remain beside the database. `/tmp` is an
emptyDir for disposable runtime scratch space. Source/assets stay read-only;
Python bytecode writing is disabled. The image includes no local database.

The existing startup applies `CREATE TABLE IF NOT EXISTS` schema and an existing
skill-name update. It does **not** seed. The seed command upserts demo records and
can overwrite edits: never run it routinely on restart or on an existing event.
There is no hosted-demo initializer to reuse. On first use, an operator must
explicitly initialize a new empty event once (see below).

The Deployment uses one replica, Recreate, one worker, no autoscaler, no fixed
UID/GID/fsGroup, no privilege escalation and no capabilities. Both CPU and memory
limits are <=5 times requests (100m/500m CPU, 256Mi/512Mi RAM). Allow 40 seconds
for SIGTERM; Uvicorn drains for up to 25 seconds. Recreate causes update downtime
and avoids overlapping old/new application pods. Do not force-delete pods while
SQLite is writing. RWO alone does not enforce one writer on the same node.

The image sets **no USER**; OpenShift must assign a non-root identity. The launcher
rejects root when used locally. It grants group 0 access to the image's empty
`/var/data` directory. **A mounted PVC hides that directory and its permissions.**
Rahti's SCC assigns the runtime UID, supplemental fsGroup and SELinux context;
the CSI storage implementation must make the PVC writable to that fsGroup.
Leave those fields and seccomp unset so Rahti applies its policy (currently
`rahti-restricted-v2`, with a platform-specific seccomp default). Do not force
`RuntimeDefault`, UID 1000, fsGroup 0, root init containers or chmod 777.
The launcher's umask 0007 allows database writes by a replacement UID sharing the
storage group. SQLite can default to mode 0644 regardless of umask, so the launcher
exclusively precreates a missing DB with mode 0660. It never truncates or chmods
an existing DB. Confirm this on the actual PVC before any public exposure.

## Prerequisites and local verification

Docker Desktop/Engine with buildx (amd64 emulation on Apple Silicon), Python 3.11+
for the test driver, and outbound access to public image/package registries.
Later, for Rahti only: an active CSC project with Rahti entitlement and quota,
`oc`, a selected project, and authority to create its resources. Never commit
credentials, generated Secret YAML or downloaded backups.

From the repository root:

```sh
docker buildx build --platform linux/amd64 --load -t recruitifi:rahti-local .
docker image inspect recruitifi:rahti-local --format '{{.Os}}/{{.Architecture}}'
python3 deploy/rahti/test_container.py recruitifi:rahti-local
backend/.venv/bin/python -m unittest discover -s backend -t . -p 'test_*.py' -v
```

The Docker build runs the production frontend build using Node 22 and its actual
pnpm lockfile. The test starts only on a loopback-bound ephemeral port, as UID
1000620000 and then UID 1000620001, group 0, read-only rootfs, dropped capabilities
and no new privileges. It uses a new disposable Docker volume, initializes only
that test database once, uploads synthetic PDF-signature test bytes, recreates
the container and verifies download and a new database write. It also checks
missing password, unsupported hosted authentication and root all fail startup.
No password is embedded in the image or test output. Test-created data is removed.

Docker initializes an empty named volume from the image directory metadata;
this is **not** proof that CSI mounts, SCC-generated fsGroup or SELinux work on
Rahti. It is not a root init-container workaround. A local bind mount needs
explicit owner/group permissions compatible with the chosen test UID/groups;
do not mount your working database or use world-writable permissions.

For a manual loopback-only container (unauthenticated, never expose publicly):

```sh
docker volume create recruitifi-local-data
docker run --name recruitifi-local --user 1000620000:0 --read-only \
  --cap-drop=ALL --security-opt=no-new-privileges \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m,mode=1770,uid=1000620000,gid=0 \
  --mount type=volume,src=recruitifi-local-data,dst=/var/data \
  -p 127.0.0.1:8080:8080 -e TALENTMATCH_HOSTED_DEMO=0 recruitifi:rahti-local
# Another terminal:
curl --fail http://127.0.0.1:8080/healthz
curl --fail http://127.0.0.1:8080/
curl --fail http://127.0.0.1:8080/api/companies
# A fresh DB returns an empty directory until explicitly seeded.
```

Production build sets `VITE_API_URL` to an empty string; API calls use relative
`/api/...` URLs on the HTTPS origin. Runtime VITE variables cannot change a built
bundle. Local Vite development retains the localhost API fallback. No CORS
change is needed for a single same-origin service.

## Later: project and Secret (do not run until authorized)

First resolve and review hosted authentication. The manifest intentionally sets
hosted mode to 1, so this checkout will fail closed rather than publish an open API.

Use the Login Command from the [Rahti web console](https://console.rahti.csc.fi/),
or `oc login https://api.2.rahti.csc.fi:6443 --web` if supported by your CLI.
Do not paste access tokens into Git, scripts or chat. The web flow avoids putting
a token in shell history. Select your own unique namespace and actual CSC project:

```sh
export RAHTI_NAMESPACE='replace-with-your-project-name'
export CSC_PROJECT='replace-with-your-csc-project-number'
oc new-project "$RAHTI_NAMESPACE" --description="csc_project: $CSC_PROJECT"
oc project "$RAHTI_NAMESPACE"
oc get resourcequota,limitrange
```

Create the Secret through a hidden prompt, stdin, and an isolated temporary file
outside the repository. No password appears in command arguments or shell history.
Run this block with **bash**; keep shell tracing disabled:

```bash
set +x
umask 077
secret_dir=$(mktemp -d)
trap 'rm -rf "$secret_dir"' EXIT
read -r -s -p 'Shared demo password: ' demo_password
printf '\n'
test -n "$demo_password" || exit 1
printf '%s' "$demo_password" > "$secret_dir/password"
unset demo_password
oc create secret generic recruitifi-demo \
  --from-file=TALENTMATCH_DEMO_PASSWORD="$secret_dir/password"
rm -f "$secret_dir/password"
rmdir "$secret_dir"
trap - EXIT
```

For rotation use a protected operator procedure to replace the Secret, then
restart the Deployment; an environment variable does not update in existing Pods.
A Secret reference is configuration, not authentication: it does not remove the
current blocker.

## Later: build inside Rahti (the sole cluster image workflow)

Use CSC's Docker binary BuildConfig flow; no S2I, auto-deployment or second image
pipeline is required. Run the initial `oc new-build` from an empty temporary
folder so it cannot infer a Git source. Use unique release tags, not `latest`.

```sh
export RELEASE='replace-with-unique-release-tag'
mkdir -p .rahti-build
# Stage only allowlisted build inputs, never send your workspace wholesale.
python3 - <<'PY'
from pathlib import Path
import shutil
root = Path('.rahti-build')
for name in ['Dockerfile', '.dockerignore', 'backend/requirements.txt', 'backend/schema.sql',
             'frontend/package.json', 'frontend/pnpm-lock.yaml', 'frontend/pnpm-workspace.yaml',
             'frontend/index.html', 'frontend/tsconfig.json', 'frontend/vite.config.ts',
             'deploy/rahti/requirements.lock']:
    dest = root / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(name, dest)
for path in Path('backend').glob('*.py'):
    if not path.name.startswith('test_'):
        shutil.copyfile(path, root / path)
shutil.copytree('frontend/src', root / 'frontend/src', dirs_exist_ok=True)
PY
# Initial BuildConfig/ImageStream creation only:
build_dir=$(mktemp -d)
(cd "$build_dir" && oc new-build --name=recruitifi --to="recruitifi:$RELEASE" \
  --binary --strategy=docker)
rmdir "$build_dir"
# Confirm the output tag before each build, including updates:
oc patch bc/recruitifi --type=merge \
  -p "{\"spec\":{\"output\":{\"to\":{\"kind\":\"ImageStreamTag\",\"name\":\"recruitifi:$RELEASE\"}}}}"
oc start-build recruitifi --from-dir=.rahti-build --follow --wait
oc get builds
oc get istag "recruitifi:$RELEASE"
export IMAGE="image-registry.openshift-image-registry.svc:5000/$RAHTI_NAMESPACE/recruitifi:$RELEASE"
```

Review the staged directory before submitting; rebuild it from a fresh empty
`.rahti-build` for each release so removed sources cannot linger. Dockerignore
filters Docker builds; do not rely on it to sanitize an `oc` binary archive.
The local build uses `--platform linux/amd64`; a Rahti build runs on its amd64
nodes. Record the resulting immutable image digest for rollbacks and releases.
Public base image pulls, builder permissions, registry access and build resource
quotas still need testing on Rahti. Dependencies are installed during build only.

## Later: render and apply

**Blocked for this checkout.** After hosted authentication has been implemented
and verified, render the namespace/tag into a local ignored output directory.
Kubernetes does not expand shell variables in `image:` automatically.

```sh
mkdir -p .rahti-rendered
export IMAGE
python3 - <<'PY'
import os
from pathlib import Path
image = os.environ['IMAGE']
assert 'REPLACE_' not in image and image.count('/') >= 2
source = Path('deploy/rahti/deployment.yaml').read_text()
placeholder = 'image-registry.openshift-image-registry.svc:5000/REPLACE_NAMESPACE/recruitifi:REPLACE_TAG'
assert source.count(placeholder) == 1
Path('.rahti-rendered/deployment.yaml').write_text(source.replace(placeholder, image))
PY
oc apply -f deploy/rahti/pvc.yaml
oc apply -f .rahti-rendered/deployment.yaml
oc apply -f deploy/rahti/service.yaml
# Keep public Route absent while checking identity, storage and authentication.
oc get pvc recruitifi-data
oc rollout status deployment/recruitifi --timeout=180s
oc exec deployment/recruitifi -- id
oc exec deployment/recruitifi -- python -c 'import os; from backend.database import DB_PATH; print(DB_PATH); assert str(DB_PATH)=="/var/data/talentmatch.sqlite3"; assert os.access(DB_PATH.parent, os.W_OK)'
```

A fresh schema starts empty. Only when confirmed to be a **new, empty event**,
initialize synthetic data once; never use this on a restored/existing event:

```sh
oc exec deployment/recruitifi -- python -c 'from backend.database import connect; from backend.seed import seed; c=connect(); db=c.__enter__(); assert all(db.execute("SELECT count(*) FROM " + t).fetchone()[0] == 0 for t in ("skills","companies","candidates","profile_materials","swipe_decisions","match_audit")), "Refusing to seed an existing event"; c.__exit__(None,None,None); seed()'
```

Validate hosted access rejects unauthenticated requests and accepts the intended
shared password (including documents/API, not only HTML) before adding the Route:

```sh
oc apply -f deploy/rahti/route.yaml
hostname=$(oc get route recruitifi -o jsonpath='{.spec.host}')
printf 'HTTPS URL: https://%s\n' "$hostname"
curl --fail "https://$hostname/healthz"
curl -I "http://$hostname/"
```

`/healthz` is process health after lifespan startup, independent of seed records
or external services; it is not a disk-space, authentication or backup test.
The assigned Route hostname is obtained from the cluster, not invented here.
Readiness/liveness use the same endpoint; startupProbe allows up to 150 seconds.

## Operations, updates and restart

```sh
oc get pods,svc,route,pvc -l app=recruitifi
oc logs deployment/recruitifi --tail=100
oc logs deployment/recruitifi --previous --tail=100
oc describe deployment recruitifi
oc describe pod -l app=recruitifi
oc describe pvc recruitifi-data
oc get events --sort-by=.metadata.creationTimestamp
oc rollout status deployment/recruitifi --timeout=180s
```

For updates build a new unique tag via the **same** BuildConfig flow, back up the
DB, set IMAGE to the new reference and re-render/apply the Deployment. Alternatively:

```sh
oc set image deployment/recruitifi recruitifi="$IMAGE"
oc rollout status deployment/recruitifi --timeout=180s
# Safe restart, retains PVC and does not seed:
oc rollout restart deployment/recruitifi
oc rollout status deployment/recruitifi --timeout=180s
```

Always remain at one replica and Recreate, including during rollback. Retain the
previous image digest and a verified backup. Do not delete the PVC on restart.
Increase requested PVC capacity only after checking the active storage class's
expansion support and project quota; changing storage request needs no app change.
Never assume the volume can be expanded online or reduced in size.

## Backup and restore

A PVC is **not a backup**. Store versioned, access-controlled SQLite backup files
outside the Pod/PVC and test restoration regularly. They include uploaded BLOBs,
profiles, audit and likes. Do not simply copy a live .sqlite3 file: committed data
may be in WAL, and raw copies can be inconsistent. Use SQLite's online backup API.

The following makes a consistent snapshot in ephemeral /tmp and streams it to
the operator's machine; check command exit code before retaining the artifact.
Ensure /tmp can hold the snapshot (manifest default is 64Mi). For larger DBs use a
planned offline backup/maintenance procedure with adequate scratch capacity.

```sh
umask 077
mkdir -p backups
backup_file="backups/talentmatch-$(date -u +%Y%m%dT%H%M%SZ).sqlite3"
oc exec deployment/recruitifi -- python -c 'import os,sqlite3,tempfile,sys,shutil; src=sqlite3.connect("file:"+os.environ["TALENTMATCH_DB"]+"?mode=ro",uri=True); f=tempfile.NamedTemporaryFile(suffix=".sqlite3"); dst=sqlite3.connect(f.name); src.backup(dst); assert dst.execute("PRAGMA integrity_check").fetchone()[0]=="ok"; dst.close(); src.close(); f.seek(0); shutil.copyfileobj(f,sys.stdout.buffer)' > "$backup_file.pending" \
  && mv "$backup_file.pending" "$backup_file"
python3 - "$backup_file" <<'PY'
import sqlite3, sys
with sqlite3.connect('file:' + sys.argv[1] + '?mode=ro', uri=True) as db:
    assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
PY
# Transfer a protected copy to independent durable backup storage.
```

Restore is a deliberate data replacement operation. First take and verify a
separate backup of the existing event and confirm the intended recovery point.
Remove the public Route, scale the app to zero, wait until its Pod is fully gone,
then use a temporary maintenance Pod with the **same** PVC and image; never run
it while an app Pod is still writing. Create it with the following specification
(render IMAGE in memory first; do not leave a placeholder in an applied resource):

```sh
oc delete route recruitifi --ignore-not-found
oc scale deployment/recruitifi --replicas=0
oc wait --for=delete pod -l app=recruitifi --timeout=180s
python3 - <<'PY' | oc apply -f -
import json, os
print(json.dumps({
  'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'recruitifi-maintenance'},
  'spec': {'restartPolicy': 'Never', 'automountServiceAccountToken': False,
    'securityContext': {'runAsNonRoot': True},
    'containers': [{'name': 'maintenance', 'image': os.environ['IMAGE'],
      'command': ['python', '-c', 'import time; time.sleep(3600)'],
      'resources': {'requests': {'cpu': '100m', 'memory': '256Mi'}, 'limits': {'cpu': '500m', 'memory': '512Mi'}},
      'securityContext': {'allowPrivilegeEscalation': False, 'readOnlyRootFilesystem': True, 'capabilities': {'drop': ['ALL']}},
      'volumeMounts': [{'name': 'data', 'mountPath': '/var/data'}]}],
    'volumes': [{'name': 'data', 'persistentVolumeClaim': {'claimName': 'recruitifi-data'}}]}}))
PY
oc wait --for=condition=Ready pod/recruitifi-maintenance --timeout=180s
# Upload into a NEW temporary filename, refusing to overwrite any existing one:
oc exec -i recruitifi-maintenance -- python -c 'import os,sys,shutil; os.umask(0o007); f=open("/var/data/restore-pending.sqlite3","xb"); shutil.copyfileobj(sys.stdin.buffer,f); f.close()' < "$backup_file"
# Verify, then restore through SQLite, which handles journal state transactionally.
oc exec recruitifi-maintenance -- python -c 'import os,sqlite3; os.umask(0o007); src=sqlite3.connect("file:/var/data/restore-pending.sqlite3?mode=ro",uri=True); assert src.execute("PRAGMA integrity_check").fetchone()[0]=="ok"; dst=sqlite3.connect("/var/data/talentmatch.sqlite3"); src.backup(dst); assert dst.execute("PRAGMA integrity_check").fetchone()[0]=="ok"; dst.close(); src.close(); os.unlink("/var/data/restore-pending.sqlite3")'
oc delete pod recruitifi-maintenance --wait=true
oc scale deployment/recruitifi --replicas=1
oc rollout status deployment/recruitifi --timeout=180s
# Verify restored synthetic documents, records and access protection first:
oc apply -f deploy/rahti/route.yaml
```

Allow PVC space for the restored copy, destination and temporary journals. On
failure keep the app scaled to zero and Route absent; inspect logs and verify the
external backup before recovery. Never blindly delete journal/WAL/SHM files.
No restore command was executed during repository preparation.

## Troubleshooting and safe removal

- **Hosted authentication is not implemented:** expected hard blocker for this
  checkout. A password Secret does not implement authentication. Do not turn
  hosted mode off to work around this on a public cluster.
- **Missing Secret/password:** create the named Secret/key with a nonempty value;
  do not put it in image build args or logs.
- **Permission denied / SQLite readonly:** inspect assigned identity, Pod SCC,
  directory ownership and group modes; verify CSI fsGroup support. Ask CSC support
  about a platform storage issue; never fix with root/chmod 777/fixed IDs.
- **CrashLoop after pull:** inspect previous logs, data path, Secret and the hosted
  blocker. Do not reseed as a repair step.
- **PVC Pending/Multi-Attach:** inspect events, quota and storage class; wait for
  the old pod/volume attachment to terminate. Do not switch to RollingUpdate.
- **OOMKilled / upload failures:** inspect memory limits and 10MB upload limit;
  review SQLite/audit/BLOB growth. Adjust operational resources within quotas and
  <=5x ratios; do not change business logic.
- **ImagePullBackOff:** replace both placeholders, verify completed build tag and
  namespace registry pull permission. Builds never need the demo password.
- **Exec format error:** rebuild as linux/amd64.
- **Frontend calls localhost / blank page:** use image-built assets, no local
  .env in build context; verify same-origin /api calls and asset responses.
- **Probe failure:** check 8080/0.0.0.0, startup logs and mounted DB access. Health
  needs no seed/external service, but startup must complete.
- **Full disk:** back up externally, inspect DB growth and quota; do not delete DB.

To remove the application while **retaining data**:

```sh
oc delete route recruitifi --ignore-not-found
oc delete deployment recruitifi --ignore-not-found
oc delete service recruitifi --ignore-not-found
# Optional, separately: delete the BuildConfig/ImageStream/Secret by exact name.
# KEEP pvc/recruitifi-data. Never use `oc delete -f deploy/rahti` or delete the project.
oc get pvc recruitifi-data
```

Deleting the PVC or namespace can permanently destroy the database and documents.
Take and verify an external backup before any intentionally destructive cleanup.

## Platform references and remaining verification

- [CSC image builds and amd64 requirement](https://docs.csc.fi/cloud/rahti/usage/images/creating/)
- [CSC CLI login/projects](https://docs.csc.fi/cloud/rahti/get-started/cli/)
- [CSC workload security and platform seccomp](https://docs.csc.fi/cloud/rahti/configurations/workload-security/)
- [CSC persistent storage](https://docs.csc.fi/cloud/rahti/usage/storage/)

Local test results are recorded in the final report. Neither local Docker volume
permissions nor public-schema YAML validation prove Rahti admission, project
quotas, storage-class availability, CSI fsGroup/SELinux, HTTPS routing, graceful
node eviction or restoration on actual Rahti storage. All still require a later
authorized cluster test. End-to-end hosted access is blocked by missing auth.

## Local verification results (14 November 2026)

| Check | Result | Evidence / limit |
| --- | --- | --- |
| Docker build | PASS | linux/amd64, pinned Node/Python bases and frozen pnpm lockfile |
| Frontend production build | PASS | Node 22 build inside Docker; no development API host in bundle |
| Backend checks | PASS | 10 tests on host and inside Python 3.13 image |
| Arbitrary non-root identity | PASS locally | UID 1000620000 then 1000620001, group 0, read-only rootfs |
| Persistence | PASS locally | Same disposable volume, synthetic BLOB download after recreation, changed-UID write |
| Backup | PASS locally | SQLite backup API, integrity check and restore into an in-memory DB |
| Missing password/root/hosted guard | PASS | All fail clearly without exposing an unauthenticated hosted server |
| Image content audit | PASS | No DB/env/Git/test files; readable assets and no development API base |
| Core Kubernetes schema validation | PASS | kubeconform strict: PVC, Deployment, Service (3/3) |
| Route YAML/policy checks | PASS | Parses; Service target, named port, edge TLS and Redirect verified |
| Route schema / Rahti admission | NOT VERIFIED | Available legacy schema incorrectly requires server-owned status; no cluster contacted |
| Actual SCC/CSI PVC, fsGroup, SELinux, HTTPS | NOT TESTED | Requires later authorized Rahti test |
| Hosted authenticated deployment | BLOCKED | Authentication absent; owner requested infrastructure-only preparation |

The initial changed-UID test failed on SQLite mode 0644; exclusive 0660 precreation
in the launcher fixed it, and the full local test then passed. The amd64 build
itself runs through Apple Silicon emulation; kubeconform's old amd64 binary crashed
under that emulation, so core schema validation used its native arm64 image.
`oc` client validation could not run without a kubeconfig; no credentials or
cluster discovery were attempted. Public JSON schemas are not Rahti admission tests.

Reproduce the strict core schema check without a cluster:

```sh
docker run --rm \
  --mount type=bind,src="$PWD/deploy/rahti",dst=/manifests,readonly \
  ghcr.io/yannh/kubeconform:v0.6.7 -strict -summary \
  /manifests/pvc.yaml /manifests/deployment.yaml /manifests/service.yaml
```

### Exact existing application source diff

These are the only changes to existing application source. They are needed
because this checkout has neither static serving nor a health endpoint, and its
production frontend otherwise targets the visitor's localhost. The container-only
launcher is new operational code in `backend/container_start.py`, not a replacement
for matching, authorization or profile logic.

```diff
diff --git a/backend/main.py b/backend/main.py
index 3543504..f584611 100644
--- a/backend/main.py
+++ b/backend/main.py
@@ -1,10 +1,12 @@
 import json
 import os
+from pathlib import Path
 from typing import Literal
 from contextlib import asynccontextmanager
 
 from fastapi import FastAPI, HTTPException, Query
 from fastapi.middleware.cors import CORSMiddleware
+from fastapi.staticfiles import StaticFiles
 
 from .database import SCHEMA_PATH, connect
 from .matching_engine import LANGUAGE_LEVELS, SCORING_VERSION, calculate_match
@@ -313,3 +315,14 @@ def undo_swipe(actor: Literal['talent', 'employer'], candidate_id: PositiveId, c
             (actor, candidate_id, company_id),
         )
     return {'deleted': True}
+
+
+@app.get("/healthz", include_in_schema=False)
+def healthz():
+    return {"status": "ok"}
+
+
+# Container builds supply these assets; local Vite development is unchanged.
+_frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
+if (_frontend_dist / "index.html").is_file():
+    app.mount("/", StaticFiles(directory=_frontend_dist, html=True), name="frontend")
diff --git a/frontend/src/api.ts b/frontend/src/api.ts
index fdce1a4..9655361 100644
--- a/frontend/src/api.ts
+++ b/frontend/src/api.ts
@@ -85,7 +85,7 @@ export interface Match {
   improvement_hints: ImprovementHint[]
 }
 
-const apiUrl = (import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')
+const apiUrl = (import.meta.env.VITE_API_URL ?? (import.meta.env.PROD ? '' : 'http://127.0.0.1:8000')).replace(/\/$/, '')
 
 export type MaterialCategory = 'cv' | 'project' | 'certificate' | 'research' | 'linkedin' | 'github' | 'website'
 export interface ProfileMaterial {
```
