# RecruitiFi on CSC Rahti 2 — locally validated shared demo

Hosted startup now uses a minimal shared-demo HTTP Basic gate. With
`TALENTMATCH_HOSTED_DEMO=1`, the username is `demo` and the password comes only
from `TALENTMATCH_DEMO_PASSWORD` (the Deployment references a Kubernetes Secret).
Missing/blank passwords or invalid hosted-mode configuration fail startup.
Invalid or missing request credentials return 401 with a browser login challenge.
The frontend, compiled assets, API, documentation and downloads are protected;
only exact GET/HEAD `/healthz` is exempt for probes. Authorized hosted responses
use Cache-Control: no-store. Local development with hosted mode unset/0 remains
unchanged. Use HTTPS for every hosted credential exchange.

Root cause of the previous blocker: `backend/container_start.py` unconditionally
raised after validating the password because authentication did not exist. That
fail-closed guard was appropriate for the earlier infrastructure-only scope. The
now-authorized isolated middleware replaces the unconditional rejection; security
checks were not bypassed. No account system or business rules were introduced.

No CSC login, cluster connection, cluster build, deployment or resource creation
was performed. **Real Rahti admission, PVC permissions and HTTPS must still be
tested by an authorized operator before public use.** Commands below are for
that later test. This shared demo must use **synthetic candidates/documents only**.
Everyone with the shared password has the existing demo access; this does not
implement candidate ownership, per-user authorization, audit identity or account
management. Never use the shared demo for personal or confidential information.

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
  hosted configuration validation, single Uvicorn worker, 8080/0.0.0.0 binding.
- Minimal application deployment changes: health endpoint, conditional static
  mount after API routes gated by the container-only `TALENTMATCH_SERVE_FRONTEND=1`
  image environment variable, production-relative API base URL. No schema, scoring,
  UI or business API request/response changes were made. Hosted-only access
  protection is isolated in `backend/demo_auth.py` with focused tests.

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
missing/blank passwords and root all fail startup. It also starts a hosted
container against the same synthetic event and verifies valid credentials succeed
while absent, malformed and wrong credentials are rejected for HTML, JS, API, docs
and persisted downloads. Health remains available without authentication.
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

The image enables static serving with `TALENTMATCH_SERVE_FRONTEND=1`. Without
that flag, local Uvicorn retains the original root 404 even if frontend/dist exists.
Production build sets `VITE_API_URL` to an empty string; API calls use relative
`/api/...` URLs on the HTTPS origin. Runtime VITE variables cannot change a built
bundle. Local Vite development retains the localhost API fallback. No CORS
change is needed for a single same-origin service.

## Later: project and Secret (do not run until authorized)

The manifest sets hosted mode to 1. Create its required Secret before starting
the Deployment; a missing/blank password must fail closed. Keep the public Route
absent until storage and authenticated access have passed the operator checks.

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
The middleware consumes this environment value at process startup. Restart after
rotation. Browsers may retain old HTTP Basic credentials and prompt again; there
is no application login/logout page or password in the React build.

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

After choosing the project, creating its Secret and building a release image,
render the namespace/tag into a local ignored output directory.
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

- **401/browser password prompt:** use username `demo` and the password in the
  Secret. Confirm the Pod restarted after rotation; clear stale browser credentials
  if necessary. Never turn hosted mode off to work around authentication.
- **Missing Secret/password:** create the named Secret/key with a nonempty value;
  do not put it in image build args or logs.
- **Permission denied / SQLite readonly:** inspect assigned identity, Pod SCC,
  directory ownership and group modes; verify CSI fsGroup support. Ask CSC support
  about a platform storage issue; never fix with root/chmod 777/fixed IDs.
- **CrashLoop after pull:** inspect previous logs, data path, Secret and the hosted
  configuration. Do not reseed as a repair step.
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
authorized cluster test. Hosted access is locally tested; actual HTTPS/Route access remains unverified.

## Local verification results (14 November 2026)

| Check | Result | Evidence / limit |
| --- | --- | --- |
| Docker build | PASS | linux/amd64, pinned Node/Python bases and frozen pnpm lockfile |
| Frontend production build | PASS | Node 22 build inside Docker; no development API host in bundle |
| Backend checks | PASS | 21 tests on host and inside Python 3.13 image |
| Arbitrary non-root identity | PASS locally | UID 1000620000 then 1000620001, group 0, read-only rootfs |
| Persistence | PASS locally | Same disposable volume, WAL mode, synthetic BLOB after recreation, changed-UID write |
| Backup | PASS locally | SQLite backup API, integrity check and restore into an in-memory DB |
| Missing password/root guard | PASS | Missing/blank passwords and root fail; valid hosted configuration starts |
| Image content audit | PASS | No DB/env/Git/test files; readable assets and no development API base |
| Core Kubernetes schema validation | PASS | kubeconform strict: PVC, Deployment, Service (3/3) |
| Route YAML/policy checks | PASS | Parses; Service target, named port, edge TLS and Redirect verified |
| Route schema / Rahti admission | NOT VERIFIED | Available legacy schema incorrectly requires server-owned status; no cluster contacted |
| Actual SCC/CSI PVC, fsGroup, SELinux, HTTPS | NOT TESTED | Requires later authorized Rahti test |
| Hosted authentication/startup | PASS locally | Valid requests succeed; missing, malformed and wrong credentials return 401 for HTML/JS/API/docs/downloads |

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

## Historical infrastructure review (before shared authentication)

Comparison baseline: `be8131b` (the parent of the deployment work). Before review
fixes, the deployment range contained 16 one-file commits. Review found and fixed
only two operational regressions:

1. An explicitly empty VITE_API_URL in development had lost the original localhost
   fallback. The original `||` behavior is restored; production still uses same origin.
2. A local backend would serve frontend/dist whenever it existed. Static serving
   now requires TALENTMATCH_SERVE_FRONTEND=1, set only by the container image.

No existing API handler body was changed: an AST comparison against baseline
passes after excluding new operational imports, /healthz and the static mount.
Matching/scoring, schema, database connection, profile/document implementation,
seed implementation, package.json and both lockfiles are byte-identical to baseline.
The only frontend source change is the API base URL expression; no UI file changed.
Adding /healthz and container-only static serving are intentional deployment HTTP
additions, not a claim that literally no HTTP surface was added.

Rebuilt reviewed image: `linux/amd64`. Host and image each pass 10 backend tests.
The container test now additionally fetches the compiled JS asset and rejects a
development API host in it; SQLite WAL mode is enabled on the disposable test DB
before persistence is verified. Static serving, uploads, WAL persistence, replacement
UID writes, backup/integrity checks and expected startup failures all pass.
Local Uvicorn and Vite were also started on loopback ports 18081 and 5199 with a
temporary DB, no password and no static-serving flag. Both started; the API and
Vite module loaded; local backend / remained 404. Only those test processes were
stopped. Browser interaction/visual QA was not performed in this infrastructure review.

Commands and results (from repository root; Docker commands access only local Docker):

```sh
# PASS: deployment scope and whitespace review
git diff --stat be8131b
git diff --check
# PASS: no tracked DB, private key or local environment files (no output)
git ls-files '*.sqlite*' '*.db' '*.pem' '*.key' '.env' '**/.env'
# PASS: Docker static checks and amd64 build
docker buildx build --check .
docker buildx build --platform linux/amd64 --load -t recruitifi:rahti-local .
# PASS: synthetic test, including WAL persistence and UID replacement
python3 deploy/rahti/test_container.py recruitifi:rahti-local
# PASS: 10 host backend/preflight tests
backend/.venv/bin/python -m unittest discover -s backend -t . -p 'test_*.py' -v
# PASS: same 10 tests inside final runtime (test files mounted only for this check)
docker run --rm --platform linux/amd64 --user 1000620000:0 --read-only \
  --tmpfs /tmp:rw,size=64m,mode=1770,uid=1000620000,gid=0 --entrypoint python \
  --mount type=bind,src="$PWD/backend/test_swipes.py",dst=/app/backend/test_swipes.py,readonly \
  --mount type=bind,src="$PWD/backend/test_container_start.py",dst=/app/backend/test_container_start.py,readonly \
  recruitifi:rahti-local -m unittest discover -s backend -t . -p 'test_*.py' -v
# PASS: strict core schemas (3 valid, 0 invalid/errors/skipped)
docker run --rm --platform linux/arm64 \
  --mount type=bind,src="$PWD/deploy/rahti",dst=/manifests,readonly \
  ghcr.io/yannh/kubeconform:v0.6.7 -strict -summary \
  /manifests/pvc.yaml /manifests/deployment.yaml /manifests/service.yaml
# PASS: redacted deployment commit secret scan; initially 16 commits, no leaks
docker run --rm --platform linux/arm64 \
  --mount type=bind,src="$PWD",dst=/repo,readonly \
  zricethezav/gitleaks:v8.24.3 git /repo --log-opts=be8131b..HEAD --redact --no-banner
```

Use native validator architecture on other machines; linux/arm64 above is for this
Apple Silicon host, not the application image architecture. All four manifests
also parsed as YAML and passed selector/port/Secret/PVC/security/resource policy
assertions. Existing Route schema/admission limitations remain as reported above.
The historical review stopped at the absent-authentication blocker. The later
shared-authentication fix described above supersedes that blocker. Actual SCC/CSI/TLS,
Route admission and cluster deployment remain **NOT TESTED**.

## Hosted authentication validation (14 November 2026)

The old unconditional startup rejection has been replaced by isolated shared HTTP
Basic authentication in `backend/demo_auth.py`. It uses constant-time byte
comparisons and a UTF-8 Basic challenge. Both launcher and direct
`backend.main:app` startup validate configuration before writes or service startup.
Never use this shared credential for real candidate data. No password is hardcoded
or passed in an image build argument; no new Python dependency is required.

Local results:

- **PASS:** linux/amd64 Docker build using the existing Dockerfile and lockfiles.
- **PASS:** 21 backend/preflight/authentication tests, both on host and in the image.
- **PASS:** existing frontend type check and production build (`npm run build`).
- **PASS:** arbitrary UIDs, read-only rootfs, 8080, health, static serving, API,
  fresh schema initialization without reseeding, SQLite WAL/upload persistence,
  backup integrity, and changed-UID writes from the existing container checks.
- **PASS:** hosted mode starts with a generated synthetic password; username
  `demo` succeeds on HTML, JS, API, docs and stored downloads; absent/malformed/
  wrong usernames or passwords get 401 and a Basic challenge. Health is public.
  An unauthenticated upload is rejected; an authenticated synthetic upload is
  retrieved after another hosted container recreation under a different UID.
- **PASS:** missing/blank configured passwords stop the container. Invalid hosted
  mode fails unit validation; direct app import also refuses a missing password.
- **PASS:** image audit found auth module and assets but no embedded password,
  local .env, databases, Git or test files.
- **PASS:** four manifest YAMLs and consistency/security assertions; kubeconform
  strict core schema check reports 3 valid, 0 invalid/errors/skipped.
- **NOT TESTED:** actual Rahti SCC admission, project fsGroup/SELinux, CSI PVC,
  in-cluster image build, Route admission and end-to-end HTTPS.

The current CSC documentation still specifies rahti-restricted-v2, project-assigned
UID/fsGroup/SELinux and its platform seccomp default. Existing manifests leave
those identities/seccomp to the platform, drop capabilities and prohibit privilege
escalation. No Kubernetes, Dockerfile, schema, matching, frontend or dependency
changes were needed for the auth fix. All existing storage/runtime tests remain;
the obsolete expected authentication-blocker failure now tests successful hosted
startup and rejected requests instead.

Reproduce local validation (no CSC connection):

```sh
docker buildx build --platform linux/amd64 --load -t recruitifi:rahti-local .
python3 deploy/rahti/test_container.py recruitifi:rahti-local
backend/.venv/bin/python -m unittest discover -s backend -t . -p 'test_*.py' -v
(cd frontend && npm run build)
# All backend checks inside the production runtime with temporary test-only mounts:
docker run --rm --platform linux/amd64 --user 1000620000:0 --read-only \
  --tmpfs /tmp:rw,size=64m,mode=1770,uid=1000620000,gid=0 --entrypoint python \
  --mount type=bind,src="$PWD/backend/test_swipes.py",dst=/app/backend/test_swipes.py,readonly \
  --mount type=bind,src="$PWD/backend/test_container_start.py",dst=/app/backend/test_container_start.py,readonly \
  --mount type=bind,src="$PWD/backend/test_demo_auth.py",dst=/app/backend/test_demo_auth.py,readonly \
  recruitifi:rahti-local -m unittest discover -s backend -t . -p 'test_*.py' -v
```

For manual hosted requests use the browser's Basic prompt (`demo`) or `curl --user
demo https://<actual-route-host>/api/companies` (curl prompts for the password; do
not put it in a command argument). Missing credentials must give 401 for `/`, API,
assets and documents, while `/healthz` gives 200. Obtain the real Route hostname
using the earlier runbook command; never invent one. Perform this later only on
an authorized deployment with HTTPS, after validating the assigned storage identity.

Secret creation, rotation, one-time empty-event seeding, backups, restoring and
safe resource removal remain as documented above. No data was overwritten, and
no commit, push or cluster deployment was performed for this fix.

### Exact integration diff for this hosted-auth fix

New authentication implementation and focused tests are in `backend/demo_auth.py`
and `backend/test_demo_auth.py`. Existing startup integration changes:

```diff
diff --git a/backend/container_start.py b/backend/container_start.py
index 4e57412..bd5232f 100644
--- a/backend/container_start.py
+++ b/backend/container_start.py
@@ -2,17 +2,13 @@
 import os
 from pathlib import Path

+from .demo_auth import hosted_password
+

 def validate_runtime():
     if os.geteuid() == 0:
         raise RuntimeError("Run with a platform-assigned non-root UID; root runtime is not supported.")
-    if os.environ.get("TALENTMATCH_HOSTED_DEMO") == "1":
-        if not os.environ.get("TALENTMATCH_DEMO_PASSWORD", "").strip():
-            raise RuntimeError("TALENTMATCH_DEMO_PASSWORD is required for hosted demo mode.")
-        raise RuntimeError(
-            "Hosted demo authentication is not implemented in this checkout. "
-            "Deployment is blocked; do not expose this unauthenticated application."
-        )
+    hosted_password()  # Fail closed before any data writes if hosted config is invalid.
     database = Path(os.environ.get("TALENTMATCH_DB", ""))
     if not database.is_absolute() or database.parent != Path("/var/data"):
         raise RuntimeError("Container TALENTMATCH_DB must be an absolute file path directly in /var/data.")
diff --git a/backend/main.py b/backend/main.py
index 4db786e..8ff81a4 100644
--- a/backend/main.py
+++ b/backend/main.py
@@ -8,6 +8,7 @@ from fastapi import FastAPI, HTTPException, Query
 from fastapi.middleware.cors import CORSMiddleware
 from fastapi.staticfiles import StaticFiles

+from .demo_auth import DemoAuthMiddleware, hosted_password
 from .database import SCHEMA_PATH, connect
 from .matching_engine import LANGUAGE_LEVELS, SCORING_VERSION, calculate_match
 from .models import (
@@ -31,6 +32,7 @@ CANDIDATE_JSON_FIELDS = ("languages", "skills")

 @asynccontextmanager
 async def lifespan(app: FastAPI):
+    hosted_password()
     with connect() as connection:
         connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
         connection.execute(
@@ -40,6 +42,8 @@ async def lifespan(app: FastAPI):
     yield


+# Validate hosted configuration before Uvicorn can accept requests, including direct launches.
+hosted_password()
 app = FastAPI(title="City of Espoo TalentMatch", lifespan=lifespan)
 app.include_router(profile_router)
 app.add_middleware(
@@ -55,6 +59,9 @@ app.add_middleware(
     allow_headers=["Content-Type"],
 )

+# Outermost middleware protects static files, docs, downloads and every API method.
+app.add_middleware(DemoAuthMiddleware)
+

 def read_rows(query: str, *json_fields: str, params: tuple = ()):
     with connect() as connection:
```
