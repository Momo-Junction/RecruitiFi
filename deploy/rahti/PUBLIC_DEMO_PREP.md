# Public shared-demo preparation — not deployed

These changes are opt-in. They do not reset or add data at application startup.
Use `Feature`'s rebuilt main application image; the private MiniLM image/service,
PVC, Route, resource limits and network policies remain unchanged.

## Behavior and boundaries

- `TALENTMATCH_PASSWORD_FREE_DEMO=true` allows configured Talent, Employer and
  Organizer accounts to enter without a password. Default `false` retains passwords.
- Keep `TALENTMATCH_VERIFIED_DEMO_LOGIN=1`: the existing account screen establishes
  an HttpOnly, Secure-on-HTTPS, SameSite cookie and server-generated CSRF token.
  Mode changes invalidate prior-mode cookies. Existing origin, CSRF, ownership,
  consent, inference concurrency and source-size restrictions remain enforced.
- This is **public demo selection, not authentication**. Anyone can choose any
  configured account. Candidate scoping prevents accidentally using another
  selected profile, but switching accounts is public. Sharing is not private from
  other visitors selecting an authorized Employer. Review the retained dataset
  before public use; do not use personal applicant information.
- Preserve all existing account/password/signing/operator/model Secrets. Passwords
  are ignored only in explicit public mode and remain available for rollback.
  Operator and embedding bearer tokens stay server-side. No inference URL/token
  is supplied to the browser. Only existing configured demo identities can enter;
  missing or unconfigured profiles fail instead of selecting another candidate.
- `TALENTMATCH_DEMO_AUTH_ENABLED=false` removes the hosted Basic-auth challenge.
  The optional patch sets both switches explicitly. It must be applied only after
  the new image is running; the old image does not support public account sessions.

## One-time data preparation

`backend.demo_release` requires an explicit existing database. Its default is a
read-only preview; **nothing here has been applied to Rahti**.

It clears all Talent skill claims, unlinks material-to-skill associations (so
linked materials do not repopulate the skill section), and removes Talent likes
and passes for fresh discovery. It reconciles withdrawn-match notifications using
existing code. Employer likes, task/submission data, candidates, companies,
accounts, skill catalog, uploads, links and analysis history remain intact.
Old AI caches become stale and require explicit selection/consent/reanalysis.

It adds exactly **50 fictional active jobs**, ten per existing company 1–5,
covering all seven industries. IDs 910001–910050 are reserved. Requirements reuse
existing skill IDs and existing 70/20 weight validation; matching/scoring is unchanged.
Existing jobs are never overwritten. Missing companies/skills, occupied IDs,
active analyses, or exceeding the 128-active-job budget stop the operation.
The existing additive `backend.seed_jobs` initializer is a prerequisite if its
catalog/job setup has never been run; never reseed existing candidate profiles.

A full SQLite backup is created with exclusive file creation and mode 0600 before
any data changes. All changes and the completion marker are one transaction.
`demo_release_runs` records this preparation version; subsequent runs do **not**
erase new skills/likes or duplicate jobs. Keep the backup outside Git and export
it off the PVC: a second file on the PVC is not a disaster-recovery backup.

## Future operator commands — do not run until deployment is authorized

First build/publish the new linux/amd64 image using the existing release workflow
and record its immutable digest. Deploy it with the existing guarded image-only
update and verify `/healthz`, retaining current password mode and one replica with
`Recreate`. Do not apply a stale full Deployment template over live settings.
Record the previous image and flag values for rollback.

Then, from the intended existing project, after confirming no analysis is running:

```sh
# Read-only: no data is changed by this command.
oc -n recruitifi-demo exec deployment/recruitifi -- \
  python -m backend.demo_release --database /var/data/talentmatch.sqlite3

# Explicit one-time write operation. Stop if preview or backup creation fails.
# Use a new backup filename for this release; an existing file is never overwritten.
oc -n recruitifi-demo exec deployment/recruitifi -- \
  python -m backend.demo_release --database /var/data/talentmatch.sqlite3 \
  --apply --backup /var/data/before-public-demo-v1.sqlite3

# Export the private backup immediately to a private directory outside Git.
umask 077
backup_dir=$(mktemp -d)
oc -n recruitifi-demo exec deployment/recruitifi -- \
  cat /var/data/before-public-demo-v1.sqlite3 > "$backup_dir/before-public-demo-v1.sqlite3"
# Confirm the export succeeded and PRAGMA integrity_check returns ok before cleanup.

# Preserve existing Deployment settings; enable the explicitly public session mode.
oc -n recruitifi-demo patch deployment recruitifi --type=strategic \
  --patch-file=deploy/rahti/password-free-demo.patch.yaml --dry-run=server -o name
oc -n recruitifi-demo patch deployment recruitifi --type=strategic \
  --patch-file=deploy/rahti/password-free-demo.patch.yaml
oc -n recruitifi-demo rollout status deployment/recruitifi --timeout=240s
```

Use a shell with error checking (`set -e`) when executing this sequence. Do not
continue to public mode after a failed preparation/export. SQLite reserves room
for the backup on the PVC; insufficient space aborts before data changes. Retain
an off-cluster copy under the team's backup policy.

Verify all three roles enter without passwords; AI consent/trigger/poll/results
work; rejected CSRF and wrong-profile requests remain rejected; all Talent skill
lists and Your likes are empty; job count is the previous count +50. Employer
interest notifications may remain because Employer likes are intentionally retained.
Check the existing HTTPS origin configuration behind the router; do not bypass CSRF.

To restore password mode, set `TALENTMATCH_PASSWORD_FREE_DEMO=false` and keep
`TALENTMATCH_VERIFIED_DEMO_LOGIN=1`. Restore hosted Basic-auth to its recorded prior
value if desired. Cookies from public mode are rejected after the switch. App
rollback does not restore SQLite. For a data rollback, first stop application
writes and follow the existing SQLite backup/restore procedure, using the verified
off-cluster backup; never overwrite an active database or delete the PVC.
