from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

EvidenceTier = Literal["self_declared", "portfolio", "certificate"]
LanguageLevel = Literal["A1", "A2", "B1", "B2", "C1", "C2"]
PositiveId = Annotated[int, Field(gt=0)]


class Skill(BaseModel):
    id: int
    esco_uri: str
    name: str
    category: str


class WeightedSkill(BaseModel):
    skill_id: PositiveId
    weight: Annotated[int, Field(gt=0)]


class CompanyRequirements(BaseModel):
    relocation_support: bool
    working_language: str
    must_have_skills: list[WeightedSkill]
    nice_to_have_skills: list[WeightedSkill]


class Company(CompanyRequirements):
    id: int
    name: str
    industry: str
    booth_number: str
    min_match_threshold: int


class CompanyRoleUpdate(CompanyRequirements):
    working_language: Literal["English", "Finnish", "Swedish"]
    min_match_threshold: Annotated[int, Field(ge=50, le=90)]

    @model_validator(mode="after")
    def validate_skill_weights(self):
        for skills, total in ((self.must_have_skills, 70), (self.nice_to_have_skills, 20)):
            if sum(skill.weight for skill in skills) != total:
                raise ValueError(f"Skill weights must total {total}.")
        ids = [skill.skill_id for skill in self.must_have_skills + self.nice_to_have_skills]
        if len(ids) != len(set(ids)):
            raise ValueError("Each skill can appear only once across both groups.")
        return self


class CandidateSkill(BaseModel):
    skill_id: PositiveId
    evidence_tier: EvidenceTier


class CandidateProfile(BaseModel):
    has_cv: bool
    has_portfolio: bool
    languages: dict[str, LanguageLevel]
    needs_visa_sponsorship: bool
    skills: list[CandidateSkill]


class Candidate(CandidateProfile):
    id: int
    anonymous_code: str
    full_name: str
    email: str


class MatchSimulation(BaseModel):
    company_id: PositiveId
    candidate: CandidateProfile


class SkillScore(BaseModel):
    skill_id: int
    skill_name: str
    weight: int
    evidence_tier: EvidenceTier | Literal["missing"]
    multiplier: float
    points: float


class ImprovementHint(BaseModel):
    action: str
    point_gain: float
    kind: Literal["certificate", "cv", "portfolio"]
    skill_id: int | None = None


class MatchBreakdown(BaseModel):
    dealbreakers_passed: bool
    dealbreaker_reasons: list[str]
    must_have_points: float
    nice_to_have_points: float
    profile_proof_points: int
    total_score: float
    must_have_skills: list[SkillScore]
    nice_to_have_skills: list[SkillScore]
    improvement_hints: list[ImprovementHint]


class CompanyMatch(MatchBreakdown):
    company_id: int
    min_match_threshold: int
    meets_threshold: bool


class RankedMatch(CompanyMatch):
    rank: int
    candidate_id: int
    anonymous_code: str


class MeetingContact(BaseModel):
    full_name: str
    email: str
    conversation_starter: str
