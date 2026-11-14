import json
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field, HttpUrl, model_validator

from .database import connect
from .models import Candidate, CandidateSkill, PositiveId

router = APIRouter(prefix="/api/candidates")
Category = Literal["cv", "project", "certificate", "research", "linkedin", "github", "website"]
MAX_BYTES = 10 * 1024 * 1024
PUBLIC_COLUMNS = "id, candidate_id, category, title, description, skill_id, url, filename, content_type, created_at"


def candidate_profile(connection, candidate_id):
    row = connection.execute("SELECT * FROM candidates WHERE id = ?", (candidate_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Candidate not found.")
    candidate = dict(row)
    candidate["languages"] = json.loads(candidate["languages"])
    skills = {item["skill_id"]: "self_declared" for item in json.loads(candidate["skills"])}
    materials = connection.execute(
        f"SELECT {PUBLIC_COLUMNS} FROM profile_materials WHERE candidate_id = ? ORDER BY id DESC",
        (candidate_id,),
    ).fetchall()
    candidate["has_cv"] = any(item["category"] == "cv" for item in materials)
    candidate["has_portfolio"] = any(item["category"] == "project" for item in materials)
    for item in materials:
        if item["skill_id"] is None:
            continue
        tier = "certificate" if item["category"] == "certificate" else "portfolio"
        if item["category"] not in ("certificate", "project", "research"):
            continue
        if skills.get(item["skill_id"]) != "certificate":
            skills[item["skill_id"]] = tier
    candidate["skills"] = [{"skill_id": skill_id, "evidence_tier": tier} for skill_id, tier in skills.items()]
    return {"candidate": Candidate.model_validate(candidate).model_dump(), "materials": [dict(item) for item in materials]}


class MaterialMetadata(BaseModel):
    category: Category
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1500)
    skill_id: PositiveId | None = None

    @model_validator(mode="after")
    def check_title(self):
        self.title = self.title.strip()
        if not self.title:
            raise ValueError("Enter a title.")
        return self


class ProfileLink(MaterialMetadata):
    url: HttpUrl

    @model_validator(mode="after")
    def check_link(self):
        if self.category == "cv":
            raise ValueError("Upload your CV as a document.")
        parts = urlsplit(str(self.url))
        if parts.username or parts.password:
            raise ValueError("Use a public link without embedded credentials.")
        return self


def validate_owner_and_skill(connection, candidate_id, skill_id):
    if not connection.execute("SELECT 1 FROM candidates WHERE id = ?", (candidate_id,)).fetchone():
        raise HTTPException(404, "Candidate not found.")
    if skill_id is not None and not connection.execute("SELECT 1 FROM skills WHERE id = ?", (skill_id,)).fetchone():
        raise HTTPException(422, "Unknown skill.")


@router.get("/{candidate_id}/profile")
def get_profile(candidate_id: PositiveId):
    with connect() as connection:
        return candidate_profile(connection, candidate_id)


@router.post("/{candidate_id}/links")
def add_link(candidate_id: PositiveId, link: ProfileLink):
    with connect() as connection:
        validate_owner_and_skill(connection, candidate_id, link.skill_id)
        connection.execute(
            """INSERT INTO profile_materials (candidate_id, category, title, description, skill_id, url)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (candidate_id, link.category, link.title, link.description, link.skill_id, str(link.url)),
        )
        return candidate_profile(connection, candidate_id)


@router.post("/{candidate_id}/documents")
async def upload_document(
    candidate_id: PositiveId, request: Request, category: Literal["cv", "project", "certificate", "research"],
    title: str, filename: str, description: str = "", skill_id: PositiveId | None = None,
):
    if not title.strip() or len(title) > 120 or len(description) > 1500 or len(filename) > 200:
        raise HTTPException(422, "Check the document title, description and filename.")
    with connect() as connection:
        validate_owner_and_skill(connection, candidate_id, skill_id)
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > MAX_BYTES:
            raise HTTPException(413, "Choose a file smaller than 10 MB.")
    signatures = {
        ".pdf": (b"%PDF-", "application/pdf"),
        ".png": (b"\x89PNG\r\n\x1a\n", "image/png"),
        ".jpg": (b"\xff\xd8\xff", "image/jpeg"),
        ".jpeg": (b"\xff\xd8\xff", "image/jpeg"),
    }
    extension = "." + filename.rsplit(".", 1)[-1].lower()
    signature, mime = signatures.get(extension, (b"", ""))
    if not signature or not content.startswith(signature):
        raise HTTPException(415, "Upload a PDF, PNG or JPEG file.")
    safe_name = filename.replace("\\", "/").split("/")[-1]
    with connect() as connection:
        connection.execute(
            """INSERT INTO profile_materials
               (candidate_id, category, title, description, skill_id, filename, content_type, content)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (candidate_id, category, title.strip(), description, skill_id, safe_name, mime, bytes(content)),
        )
        return candidate_profile(connection, candidate_id)


@router.get("/{candidate_id}/documents/{material_id}")
def download_document(candidate_id: PositiveId, material_id: PositiveId):
    with connect() as connection:
        row = connection.execute(
            "SELECT content, content_type FROM profile_materials WHERE id = ? AND candidate_id = ? AND content IS NOT NULL",
            (material_id, candidate_id),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Document not found.")
    return Response(bytes(row["content"]), media_type=row["content_type"], headers={
        "Content-Disposition": "attachment", "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
    })


@router.delete("/{candidate_id}/materials/{material_id}")
def delete_material(candidate_id: PositiveId, material_id: PositiveId):
    with connect() as connection:
        validate_owner_and_skill(connection, candidate_id, None)
        deleted = connection.execute(
            "DELETE FROM profile_materials WHERE id = ? AND candidate_id = ?", (material_id, candidate_id),
        )
        if deleted.rowcount != 1:
            raise HTTPException(404, "Material not found.")
        return candidate_profile(connection, candidate_id)


@router.put("/{candidate_id}/skills")
def save_skills(candidate_id: PositiveId, skills: list[PositiveId]):
    with connect() as connection:
        for skill_id in skills:
            validate_owner_and_skill(connection, candidate_id, skill_id)
        validate_owner_and_skill(connection, candidate_id, None)
        connection.execute("UPDATE candidates SET skills = ? WHERE id = ?", (
            json.dumps([CandidateSkill(skill_id=skill_id, evidence_tier="self_declared").model_dump()
                        for skill_id in dict.fromkeys(skills)]), candidate_id,
        ))
        return candidate_profile(connection, candidate_id)
