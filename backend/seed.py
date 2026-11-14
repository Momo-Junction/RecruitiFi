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
                    "urn:talentmatch:esco-style:skill:" + re.sub(r"[^a-z0-9]+", "-", name.lower().replace("+", " plus")).strip("-"),
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

    print(f"Seeded {len(SKILLS)} skills, {len(COMPANIES)} companies and {len(CANDIDATES)} candidates.")
    print(f"SQLite database: {DB_PATH.resolve()}")


if __name__ == "__main__":
    seed()
