import argparse
import json
import re

if __package__:
    from .database import DB_PATH, SCHEMA_PATH, connect
    from .seed_data import CANDIDATES, COMPANIES, SKILLS, practice_candidates, practice_companies
else:
    from database import DB_PATH, SCHEMA_PATH, connect
    from seed_data import CANDIDATES, COMPANIES, SKILLS, practice_candidates, practice_companies


def seed_rows(connection, table, columns, rows, *, add_only):
    placeholders = ", ".join("?" for _ in columns)
    assignments = ", ".join(f"{column} = excluded.{column}" for column in columns[1:])
    conflict = "DO NOTHING" if add_only else f"DO UPDATE SET {assignments}"
    connection.executemany(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT(id) {conflict}",
        rows,
    )


def seed(*, add_only=False):
    companies = [(index, *company) for index, company in enumerate(COMPANIES, start=1)]
    companies.extend(practice_companies())
    candidates = [*CANDIDATES, *practice_candidates()]
    skill_ids = {name: index for index, (name, _) in enumerate(SKILLS, start=1)}

    def weighted_skills(weights, total):
        if sum(weights.values()) != total or any(weight <= 0 for weight in weights.values()):
            raise ValueError(f"Skill weights must be positive and sum to {total}")
        return json.dumps(
            [{"skill_id": skill_ids[name], "weight": weight} for name, weight in weights.items()]
        )

    with connect() as connection:
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        seed_rows(
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
            add_only=add_only,
        )
        seed_rows(
            connection,
            "companies",
            (
                "id", "name", "industry", "booth_number", "relocation_support",
                "working_language", "min_match_threshold", "must_have_skills", "nice_to_have_skills",
            ),
            [
                (company_id, *details, weighted_skills(required, 70), weighted_skills(preferred, 20))
                for company_id, *details, required, preferred in companies
            ],
            add_only=add_only,
        )
        seed_rows(
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
                for code, name, cv, portfolio, languages, sponsorship, evidence in candidates
            ],
            add_only=add_only,
        )

    print(f"Demo catalog ready with {len(SKILLS)} skills, {len(companies)} employers and {len(candidates)} candidates.")
    print(f"SQLite database: {DB_PATH.resolve()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed the fictional TalentMatch directory.")
    parser.add_argument("--add-only", action="store_true", help="Keep existing profiles and add missing demo records.")
    seed(add_only=parser.parse_args().add_only)
