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
