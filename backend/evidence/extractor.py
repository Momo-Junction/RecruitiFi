"""Extract project metadata and bounded PDF text as untrusted, JSON-ready data.

No URL fetching, OCR, file execution, analysis, logging of content, or DB writes.
These input/output limits are not a CPU/memory sandbox for hostile PDF parsers.
"""
from collections.abc import Mapping
from io import BytesIO
from sqlite3 import Row
from typing import Any, Literal, TypedDict

from pypdf import PdfReader
from pypdf.errors import LimitReachedError, PdfReadError

from ..database import connect

MAX_PDF_PAGES = 10
MAX_TEXT_CHARACTERS = 20_000
MAX_INPUT_BYTES = 10 * 1024 * 1024

ExtractionStatus = Literal[
    'extracted', 'external_not_analyzed', 'unsupported_file_type',
    'file_too_large', 'page_limit_exceeded', 'text_limit_reached', 'encrypted_pdf',
    'no_extractable_text', 'malformed_pdf', 'resource_limit_exceeded',
    'extraction_failed',
]


class ProjectEvidence(TypedDict):
    material_id: int
    candidate_id: int
    project_title: str
    project_description: str
    linked_skill_id: int | None
    pdf_text: str
    source_type: Literal['project_link', 'uploaded_pdf', 'uploaded_image', 'unsupported_file']
    extraction_status: ExtractionStatus
    external_content_status: Literal['not_analyzed', 'not_applicable']
    pages_total: int | None
    pages_processed: int
    extracted_characters: int
    text_truncated: bool
    untrusted: Literal[True]


class _TextLimitReached(Exception):
    pass


class _EncryptedPdf(Exception):
    pass


class _TextOnlyPdfReader(PdfReader):
    def _handle_encryption(self, password):
        # Pinned pypdf normally tries the empty password here. Stop before any
        # decryption or optional crypto provider, including for AES documents.
        raise _EncryptedPdf


def _positive_id(value):
    if type(value) is not int or value <= 0:
        raise ValueError('Candidate and material IDs must be positive integers.')


def extract_project_material(material: Mapping[str, Any] | Row) -> ProjectEvidence:
    """Accept a stored row/dict, including its content BLOB, without mutating it.

    Only category='project' is accepted. Titles, descriptions and PDF text are
    copied as data, never interpreted as instructions or verified skill claims.
    """
    row = dict(material)  # Also supports sqlite3.Row, which lacks .get().
    if row.get('category') != 'project':
        raise ValueError('Only project materials are supported.')
    _positive_id(row.get('id'))
    _positive_id(row.get('candidate_id'))
    if not isinstance(row.get('title'), str) or not isinstance(row.get('description'), str):
        raise ValueError('Stored project title and description must be strings.')
    linked_skill = row.get('skill_id')
    if linked_skill is not None:
        _positive_id(linked_skill)

    link = row.get('url') is not None
    content = row.get('content')
    if link and (content is not None or row.get('content_size') is not None):
        raise ValueError('A project must contain either a URL or a file, not both.')
    filename = str(row.get('filename') or '').lower()
    mime = row.get('content_type')
    pdf = filename.endswith('.pdf') and mime == 'application/pdf'
    image = mime in ('image/png', 'image/jpeg')
    result: ProjectEvidence = {
        'material_id': row['id'], 'candidate_id': row['candidate_id'],
        'project_title': row['title'], 'project_description': row['description'],
        'linked_skill_id': linked_skill, 'pdf_text': '',
        'source_type': 'project_link' if link else 'uploaded_pdf' if pdf else 'uploaded_image' if image else 'unsupported_file',
        'extraction_status': 'external_not_analyzed' if link else 'unsupported_file_type',
        'external_content_status': 'not_analyzed' if link else 'not_applicable',
        'pages_total': None, 'pages_processed': 0, 'extracted_characters': 0,
        'text_truncated': False, 'untrusted': True,
    }
    if link:
        return result
    size = row.get('content_size')
    if (isinstance(size, int) and size > MAX_INPUT_BYTES) or (
        isinstance(content, (bytes, bytearray)) and len(content) > MAX_INPUT_BYTES
    ):
        result['extraction_status'] = 'file_too_large'
        return result
    if not pdf:
        return result
    if not isinstance(content, (bytes, bytearray)) or not content.startswith(b'%PDF-'):
        result['extraction_status'] = 'malformed_pdf'
        return result

    parts: list[str] = []
    characters = 0

    def collect(text, *_):
        nonlocal characters
        if not text:
            return
        remaining = MAX_TEXT_CHARACTERS - characters
        parts.append(text[:remaining])
        characters += min(len(text), remaining)
        if len(text) > remaining:
            raise _TextLimitReached

    try:
        reader = _TextOnlyPdfReader(BytesIO(content), strict=True)
        if reader.is_encrypted:
            result['extraction_status'] = 'encrypted_pdf'
            return result  # No passwords/decryption or optional crypto dependencies.
        result['pages_total'] = len(reader.pages)
        if result['pages_total'] > MAX_PDF_PAGES:
            result['extraction_status'] = 'page_limit_exceeded'
            return result  # Do not extract any pages from an oversized document.
        for index, page in enumerate(reader.pages):
            if index and parts:
                collect('\n')
            result['pages_processed'] += 1
            page.extract_text(visitor_text=collect)
    except _TextLimitReached:
        result['extraction_status'] = 'text_limit_reached'
        result['text_truncated'] = True
    except _EncryptedPdf:
        result['extraction_status'] = 'encrypted_pdf'
        return result
    except (MemoryError, RecursionError, LimitReachedError):
        result['extraction_status'] = 'resource_limit_exceeded'
        return result
    except PdfReadError:
        result['extraction_status'] = 'malformed_pdf'
        return result  # Discard partial text rather than imply successful extraction.
    except Exception:
        result['extraction_status'] = 'extraction_failed'
        return result  # Do not expose raw parser errors or document contents.
    else:
        result['extraction_status'] = 'extracted'
    text = ''.join(parts)
    if not text.strip() and not result['text_truncated']:
        result['extraction_status'] = 'no_extractable_text'
        result['text_truncated'] = False
        text = ''  # Image-only/scanned and blank PDFs receive no fabricated text.
    result['pdf_text'] = text
    result['extracted_characters'] = len(text)
    return result


def extract_project_evidence(candidate_id: int, material_id: int) -> ProjectEvidence:
    """Load exactly one candidate's project via the existing SQLite connection.

    This is a scoped lookup, not authentication; a future caller must authorize
    access. The SQL size gate avoids loading oversized BLOBs into Python.
    """
    _positive_id(candidate_id)
    _positive_id(material_id)
    with connect() as connection:
        row = connection.execute(
            """SELECT id, candidate_id, category, title, description, skill_id,
                      url, filename, content_type, length(content) AS content_size,
                      CASE WHEN length(content)<=? AND content_type='application/pdf'
                           THEN content ELSE NULL END AS content
               FROM profile_materials
               WHERE id=? AND candidate_id=? AND category='project'""",
            (MAX_INPUT_BYTES, material_id, candidate_id),
        ).fetchone()
    if row is None:
        raise LookupError('Project material not found for this candidate.')
    return extract_project_material(row)
