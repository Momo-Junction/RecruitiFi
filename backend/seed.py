import json
import re

if __package__:
    from .database import DB_PATH, SCHEMA_PATH, connect
    from .seed_data import CANDIDATES, COMPANIES, SKILLS
else:
    from database import DB_PATH, SCHEMA_PATH, connect
    from seed_data import CANDIDATES, COMPANIES, SKILLS


def upsert(connection, table, columns, rows):
    placeholders = ", ".join("?" for _ in columns)
    assignments = ", ".join(f"{column} = excluded.{column}" for column in columns[1:])
    connection.executemany(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT(id) DO UPDATE SET {assignments}",
        rows,
    )


def seed():
    skill_ids = {name: index for index, (name, _) in enumerate(SKILLS, start=1)}

    def weighted_skills(weights, total):
        if sum(weights.values()) != total or any(weight <= 0 for weight in weights.values()):
            raise ValueError(f"Skill weights must be positive and sum to {total}")
        return json.dumps(
            [{"skill_id": skill_ids[name], "weight": weight} for name, weight in weights.items()]
        )

    with connect() as connection:
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        upsert(
            connection,
            "skills",
            ("id", "esco_uri", "name", "category"),
            [
                (
                    skill_ids[name],
                    "urn:talentmatch:esco-style:skill:" + slug(name),
                    name,
                    category,
                )
                for name, category in SKILLS
            ],
        )
        upsert(
            connection,
            "companies",
            (
                "id", "name", "industry", "booth_number", "relocation_support",
                "working_language", "min_match_threshold", "must_have_skills", "nice_to_have_skills",
            ),
            [
                (index, *details, weighted_skills(required, 70), weighted_skills(preferred, 20))
                for index, (*details, required, preferred) in enumerate(COMPANIES, start=1)
            ],
        )
        seed_candidates(connection, skill_ids)

    print(f"Seeded {len(SKILLS)} skills, {len(COMPANIES)} companies and {len(CANDIDATES)} candidates.")
    print(f"SQLite database: {DB_PATH.resolve()}")


# Seeded materials are recognizable by these prefixes so reseeding never touches uploads.
DEMO_URL_PREFIX = "https://example.com/talentmatch-demo/"
DEMO_CV_PREFIX = "talentmatch-demo-cv-"
DEMO_NOTE = "Synthetic demo material. Not a real document."


def demo_pdf(text):
    """Build a minimal one-page PDF so seeded CVs download like real uploads."""
    safe = text.replace("\\", "").replace("(", "").replace(")", "")
    stream = f"BT /F1 14 Tf 72 720 Td ({safe}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(output)
    output += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    output += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    output += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(output)


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower().replace("+", " plus")).strip("-")


def seed_candidates(connection, skill_ids):
    upsert(
        connection,
        "candidates",
        (
            "id", "anonymous_code", "full_name", "email", "has_cv", "has_portfolio",
            "languages", "needs_visa_sponsorship", "skills",
        ),
        [
            (
                code, f"Talent #{code}", name, f"talent{code}@example.com", cv, portfolio,
                json.dumps(languages), sponsorship,
                json.dumps([
                    {"skill_id": skill_ids[skill], "evidence_tier": tier}
                    for tier, skills in evidence.items()
                    for skill in skills
                ]),
            )
            for code, name, cv, portfolio, languages, sponsorship, evidence in CANDIDATES
        ],
    )

    # Scores come from saved materials, so give each persona the proof its seed record describes.
    connection.execute(
        "DELETE FROM profile_materials WHERE url LIKE ? OR filename LIKE ?",
        (DEMO_URL_PREFIX + "%", DEMO_CV_PREFIX + "%"),
    )
    documents, links = [], []
    for code, name, cv, portfolio, _, _, evidence in CANDIDATES:
        if cv:
            documents.append((
                code, "cv", "CV (synthetic)", DEMO_NOTE, None, f"{DEMO_CV_PREFIX}{code}.pdf",
                "application/pdf", demo_pdf(f"Synthetic CV for {name} - demo data only"),
            ))
        for category, tier in (("project", "portfolio"), ("certificate", "certificate")):
            for skill in evidence.get(tier, []):
                label = "Project" if category == "project" else "Certificate"
                links.append((
                    code, category, f"{label}: {skill} (synthetic)", DEMO_NOTE, skill_ids[skill],
                    f"{DEMO_URL_PREFIX}{code}/{category}/{slug(skill)}",
                ))
        if portfolio and not evidence.get("portfolio"):
            links.append((
                code, "project", "Portfolio (synthetic)", DEMO_NOTE, None,
                f"{DEMO_URL_PREFIX}{code}/project/portfolio",
            ))
    connection.executemany(
        """INSERT INTO profile_materials
           (candidate_id, category, title, description, skill_id, filename, content_type, content)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        documents,
    )
    connection.executemany(
        """INSERT INTO profile_materials (candidate_id, category, title, description, skill_id, url)
           VALUES (?, ?, ?, ?, ?, ?)""",
        links,
    )


if __name__ == "__main__":
    seed()
