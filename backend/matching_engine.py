from collections import Counter
from collections.abc import Mapping
from typing import Any

from .models import CandidateProfile, CompanyRequirements, WeightedSkill

# Store multipliers and weighted scores in tenths to avoid floating-point drift.
EVIDENCE_MULTIPLIERS = {"missing": 0, "self_declared": 7, "portfolio": 9, "certificate": 10}
LANGUAGE_LEVELS = {level: rank for rank, level in enumerate(("A1", "A2", "B1", "B2", "C1", "C2"))}
SCORING_VERSION = "1"


def calculate_match(
    candidate: CandidateProfile | Mapping[str, Any],
    company: CompanyRequirements | Mapping[str, Any],
    *,
    skill_names: Mapping[int, str] | None = None,
) -> dict[str, Any]:
    """Score a profile using only its inputs and an optional skill-name lookup."""
    candidate = CandidateProfile.model_validate(candidate)
    company = CompanyRequirements.model_validate(company)
    skill_names = skill_names or {}

    required_language = company.working_language.strip().casefold()
    language_rank = max(
        (
            LANGUAGE_LEVELS[level]
            for language, level in candidate.languages.items()
            if language.strip().casefold() == required_language
        ),
        default=-1,
    )
    reasons = []
    if language_rank < LANGUAGE_LEVELS["B2"]:
        reasons.append(f"{company.working_language} proficiency of B2 or higher is required.")
    if candidate.needs_visa_sponsorship and not company.relocation_support:
        reasons.append("Candidate needs visa sponsorship and the employer does not offer relocation support.")

    evidence_by_id = {}
    for skill in candidate.skills:
        existing_tier = evidence_by_id.get(skill.skill_id, "missing")
        if EVIDENCE_MULTIPLIERS[skill.evidence_tier] > EVIDENCE_MULTIPLIERS[existing_tier]:
            evidence_by_id[skill.skill_id] = skill.evidence_tier

    def score_skills(requirements: list[WeightedSkill]):
        breakdown = []
        total_tenths = 0
        for requirement in requirements:
            skill_id = requirement.skill_id
            tier = evidence_by_id.get(skill_id, "missing")
            multiplier = EVIDENCE_MULTIPLIERS[tier]
            points = requirement.weight * multiplier
            total_tenths += points
            breakdown.append({
                "skill_id": skill_id,
                "skill_name": skill_names.get(skill_id, f"Skill #{skill_id}"),
                "weight": requirement.weight,
                "evidence_tier": tier,
                "multiplier": multiplier / 10,
                "points": points / 10,
            })
        return breakdown, total_tenths

    must_have, must_have_tenths = score_skills(company.must_have_skills)
    nice_to_have, nice_to_have_tenths = score_skills(company.nice_to_have_skills)
    if sum(skill.weight for skill in company.must_have_skills) > 70:
        raise ValueError("Must-have skill weights cannot exceed 70.")
    if sum(skill.weight for skill in company.nice_to_have_skills) > 20:
        raise ValueError("Nice-to-have skill weights cannot exceed 20.")
    proof_points = 5 * (candidate.has_cv + candidate.has_portfolio)

    weight_by_id = Counter()
    for requirement in company.must_have_skills + company.nice_to_have_skills:
        weight_by_id[requirement.skill_id] += requirement.weight

    hints = []
    for skill_id, weight in weight_by_id.items():
        tier = evidence_by_id.get(skill_id, "missing")
        gain = weight * (EVIDENCE_MULTIPLIERS["certificate"] - EVIDENCE_MULTIPLIERS[tier])
        if gain:
            name = skill_names.get(skill_id, f"Skill #{skill_id}")
            action = (
                f"Add missing skill: {name} with a certificate"
                if tier == "missing"
                else f"Attach certificate for {name}"
            )
            hints.append({
                "action": action, "point_gain": gain / 10, "kind": "certificate", "skill_id": skill_id
            })
    if not candidate.has_cv:
        hints.append({"action": "Upload CV", "point_gain": 5, "kind": "cv"})
    if not candidate.has_portfolio:
        hints.append({"action": "Upload portfolio", "point_gain": 5, "kind": "portfolio"})
    hints.sort(key=lambda hint: (-hint["point_gain"], hint["action"]))

    return {
        "dealbreakers_passed": not reasons,
        "dealbreaker_reasons": reasons,
        "must_have_points": must_have_tenths / 10,
        "nice_to_have_points": nice_to_have_tenths / 10,
        "profile_proof_points": proof_points,
        "total_score": (must_have_tenths + nice_to_have_tenths + proof_points * 10) / 10,
        "must_have_skills": must_have,
        "nice_to_have_skills": nice_to_have,
        "improvement_hints": hints,
    }
