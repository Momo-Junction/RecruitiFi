CREATE TABLE IF NOT EXISTS skills (
    id INTEGER PRIMARY KEY,
    esco_uri TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    industry TEXT NOT NULL,
    booth_number TEXT NOT NULL UNIQUE,
    relocation_support INTEGER NOT NULL CHECK (relocation_support IN (0, 1)),
    working_language TEXT NOT NULL,
    min_match_threshold INTEGER NOT NULL CHECK (min_match_threshold BETWEEN 0 AND 100),
    must_have_skills TEXT NOT NULL CHECK (json_type(must_have_skills) = 'array'),
    nice_to_have_skills TEXT NOT NULL CHECK (json_type(nice_to_have_skills) = 'array')
);

CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY,
    anonymous_code TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    has_cv INTEGER NOT NULL CHECK (has_cv IN (0, 1)),
    has_portfolio INTEGER NOT NULL CHECK (has_portfolio IN (0, 1)),
    languages TEXT NOT NULL CHECK (json_type(languages) = 'object'),
    needs_visa_sponsorship INTEGER NOT NULL CHECK (needs_visa_sponsorship IN (0, 1)),
    skills TEXT NOT NULL CHECK (json_type(skills) = 'array')
);

CREATE TABLE IF NOT EXISTS swipe_decisions (
    candidate_id INTEGER NOT NULL REFERENCES candidates(id),
    company_id INTEGER NOT NULL REFERENCES companies(id),
    actor TEXT NOT NULL CHECK (actor IN ('talent', 'employer')),
    decision TEXT NOT NULL CHECK (decision IN ('like', 'pass')),
    PRIMARY KEY (candidate_id, company_id, actor)
);

CREATE TABLE IF NOT EXISTS match_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    calculated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    source TEXT NOT NULL,
    company_name TEXT NOT NULL,
    candidate_code TEXT,
    inputs TEXT NOT NULL CHECK (json_type(inputs) = 'object'),
    result TEXT NOT NULL CHECK (json_type(result) = 'object')
);

CREATE TABLE IF NOT EXISTS profile_materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id),
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    skill_id INTEGER REFERENCES skills(id),
    url TEXT,
    filename TEXT,
    content_type TEXT,
    content BLOB,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK ((url IS NOT NULL AND content IS NULL) OR (url IS NULL AND content IS NOT NULL))
);

-- Additive migration: existing event records and uploaded BLOBs are untouched.
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id),
    company_id INTEGER NOT NULL REFERENCES companies(id),
    recipient TEXT NOT NULL CHECK (recipient IN ('talent', 'employer')),
    kind TEXT NOT NULL CHECK (kind IN ('interest', 'match')),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    read_at TEXT,
    UNIQUE (candidate_id, company_id, recipient, kind),
    CHECK (kind = 'match' OR recipient = 'talent')
);
CREATE INDEX IF NOT EXISTS notifications_talent ON notifications(candidate_id, recipient, active);
CREATE INDEX IF NOT EXISTS notifications_employer ON notifications(company_id, recipient, active);

-- Additive job requirements; company-level swipes/notifications retain their keys.
CREATE TABLE IF NOT EXISTS job_openings (
    id INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    title TEXT NOT NULL CHECK (length(trim(title)) > 0),
    industry TEXT NOT NULL CHECK (industry IN ('it', 'business_services', 'logistics', 'health_sector', 'restaurant', 'cleaning', 'engineering')),
    description TEXT NOT NULL,
    must_have_skills TEXT NOT NULL CHECK (json_type(must_have_skills) = 'array'),
    nice_to_have_skills TEXT NOT NULL CHECK (json_type(nice_to_have_skills) = 'array'),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);
CREATE INDEX IF NOT EXISTS jobs_company ON job_openings(company_id, active);
CREATE INDEX IF NOT EXISTS jobs_industry ON job_openings(industry, active);

-- AI evidence storage: additive/idempotent; never promotes candidate skills.
CREATE TABLE IF NOT EXISTS evidence_analysis_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id INTEGER NOT NULL REFERENCES profile_materials(id) ON DELETE CASCADE,
    analysis_kind TEXT NOT NULL CHECK (analysis_kind IN ('project', 'github')),
    model_id TEXT NOT NULL CHECK (length(model_id) BETWEEN 1 AND 200),
    model_revision TEXT NOT NULL CHECK (length(model_revision) BETWEEN 1 AND 128),
    status TEXT NOT NULL CHECK (status IN ('complete','limited','partial','failed','no_evidence','no_skills')),
    extraction_status TEXT CHECK (length(extraction_status) BETWEEN 1 AND 64),
    retrieval_status TEXT CHECK (length(retrieval_status) BETWEEN 1 AND 64),
    semantic_status TEXT CHECK (length(semantic_status) BETWEEN 1 AND 64),
    error_code TEXT CHECK (length(error_code) BETWEEN 1 AND 64),
    coverage_limited INTEGER NOT NULL CHECK (coverage_limited IN (0,1)),
    review_status TEXT NOT NULL DEFAULT 'unreviewed' CHECK (review_status IN ('unreviewed','accepted','rejected')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS evidence_runs_material ON evidence_analysis_runs(material_id, id);

CREATE TABLE IF NOT EXISTS evidence_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES evidence_analysis_runs(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL CHECK (length(source_type) BETWEEN 1 AND 64),
    evidence_field TEXT NOT NULL CHECK (length(evidence_field) BETWEEN 1 AND 512),
    repository_url TEXT CHECK (length(repository_url) <= 256),
    file_path TEXT CHECK (length(file_path) <= 1024),
    tree_sha TEXT CHECK (length(tree_sha) = 40),
    blob_sha TEXT CHECK (length(blob_sha) = 40),
    source_reference TEXT CHECK (length(source_reference) <= 512),
    excerpt TEXT NOT NULL DEFAULT '' CHECK (length(excerpt) <= 160),
    excerpt_start INTEGER CHECK (excerpt_start >= 0),
    excerpt_end INTEGER CHECK (excerpt_end >= excerpt_start),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (id, run_id),
    CHECK ((excerpt_start IS NULL AND excerpt_end IS NULL AND excerpt='')
        OR (excerpt_start IS NOT NULL AND excerpt_end IS NOT NULL AND excerpt_end-excerpt_start=length(excerpt)))
);
CREATE INDEX IF NOT EXISTS evidence_sources_run ON evidence_sources(run_id);

CREATE TABLE IF NOT EXISTS evidence_skill_findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES evidence_analysis_runs(id) ON DELETE CASCADE,
    source_id INTEGER NOT NULL,
    skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    skill_name TEXT NOT NULL CHECK (length(skill_name) BETWEEN 1 AND 400),
    finding_kind TEXT NOT NULL CHECK (finding_kind IN ('semantic','observation')),
    similarity_score REAL,
    observation_kind TEXT CHECK (length(observation_kind) <= 64),
    observed_value TEXT CHECK (length(observed_value) <= 214),
    review_status TEXT NOT NULL DEFAULT 'unreviewed' CHECK (review_status IN ('unreviewed','accepted','rejected')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY (source_id, run_id) REFERENCES evidence_sources(id, run_id) ON DELETE CASCADE,
    CHECK ((finding_kind='semantic' AND similarity_score IS NOT NULL AND similarity_score BETWEEN -1 AND 1
            AND observation_kind IS NULL AND observed_value IS NULL)
        OR (finding_kind='observation' AND similarity_score IS NULL AND observation_kind IS NOT NULL AND observed_value IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS evidence_findings_source ON evidence_skill_findings(source_id, run_id);
CREATE INDEX IF NOT EXISTS evidence_findings_run ON evidence_skill_findings(run_id);
CREATE INDEX IF NOT EXISTS evidence_findings_skill ON evidence_skill_findings(skill_id);

-- Operational job state only; active rows retain admission after source deletion.
CREATE TABLE IF NOT EXISTS evidence_analysis_jobs (
    id TEXT PRIMARY KEY,
    candidate_id INTEGER REFERENCES candidates(id) ON DELETE SET NULL,
    material_id INTEGER REFERENCES profile_materials(id) ON DELETE SET NULL,
    run_id INTEGER REFERENCES evidence_analysis_runs(id) ON DELETE SET NULL,
    top_k INTEGER NOT NULL CHECK (top_k BETWEEN 1 AND 5),
    status TEXT NOT NULL CHECK (status IN ('queued','running','completed','failed','timed_out','cancelled','interrupted')),
    error_code TEXT,
    lease_deadline REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS evidence_one_active_job ON evidence_analysis_jobs((1)) WHERE status IN ('queued','running');
CREATE UNIQUE INDEX IF NOT EXISTS evidence_one_candidate_job ON evidence_analysis_jobs(candidate_id) WHERE status IN ('queued','running');
CREATE INDEX IF NOT EXISTS evidence_jobs_candidate ON evidence_analysis_jobs(candidate_id,created_at);

-- Cached model-derived job coverage; source analysis deletion invalidates results.
CREATE TABLE IF NOT EXISTS ai_profile_matches (
    candidate_id INTEGER PRIMARY KEY REFERENCES candidates(id) ON DELETE CASCADE,
    run_id INTEGER NOT NULL REFERENCES evidence_analysis_runs(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL,
    result TEXT NOT NULL CHECK(json_valid(result)),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS ai_material_consents (
    material_id INTEGER PRIMARY KEY REFERENCES profile_materials(id) ON DELETE CASCADE,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    digest TEXT NOT NULL,
    share_company_id INTEGER REFERENCES companies(id),
    consented_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS hiring_task_assignments (
    id INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    candidate_id INTEGER NOT NULL REFERENCES candidates(id),
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    submission_url TEXT,
    verified INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    CHECK (verified = 0 OR submission_url IS NOT NULL)
);
