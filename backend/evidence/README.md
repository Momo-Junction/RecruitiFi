# Project evidence extraction (local, no AI)

Only `profile_materials.category == 'project'` is supported. Existing uploads,
downloads, schema, frontend, scoring and deployment configuration are unchanged.
The extractor is not called by any existing API endpoint.

```python
from backend.evidence.extractor import extract_project_evidence, extract_project_material

# Reads only this candidate/material pair using backend.database.connect().
evidence = extract_project_evidence(candidate_id=402, material_id=7)

# Alternatively pass an existing sqlite3.Row or dict including the stored BLOB:
evidence = extract_project_material(material_record)
```

The ID-based loader reads the database configured by the existing `TALENTMATCH_DB`.
The examples are usage only; do not run test extraction against a real/live event.
The lookup is candidate-scoped, not authentication. A future API caller must
authorize access before calling it.

Input record fields: `id`, `candidate_id`, `category`, `title`, `description`,
optional `skill_id`, `url`, `filename`, `content_type`, and `content` (SQLite BLOB).
Only PDF file metadata matching `.pdf` and `application/pdf` is parsed; the PDF
header is checked too. Project URLs are never fetched. Uploaded images and other
file types retain metadata but are not analyzed.

Output is a JSON-ready Python dict (`ProjectEvidence` TypedDict):

```json
{
  "material_id": 7,
  "candidate_id": 402,
  "project_title": "Synthetic project",
  "project_description": "Saved description, treated as data only.",
  "linked_skill_id": 1,
  "pdf_text": "Text from the uploaded PDF, if extractable.",
  "source_type": "uploaded_pdf",
  "extraction_status": "extracted",
  "external_content_status": "not_applicable",
  "pages_total": 1,
  "pages_processed": 1,
  "extracted_characters": 43,
  "text_truncated": false,
  "untrusted": true
}
```

`extracted_characters` always equals the actual length of `pdf_text`. `pages_processed` counts pages on which extraction
was attempted, including a page interrupted by the character limit. Metadata is
preserved separately from PDF text; it is not fabricated into the extracted text.

| Status | Meaning |
| --- | --- |
| `extracted` | Nonblank PDF text extracted within limits |
| `external_not_analyzed` | Project link: saved title/description only; external content not analyzed |
| `unsupported_file_type` | Image/other file; no OCR or conversion |
| `file_too_large` | Input exceeds 10 MiB; parser not invoked |
| `page_limit_exceeded` | PDF has more than 10 pages; no pages extracted |
| `text_limit_reached` | Prefix capped at 20,000 characters across all pages, including separators |
| `encrypted_pdf` | Encryption detected; extraction/decryption skipped, even for an empty password |
| `no_extractable_text` | Blank, scanned/image-only, or otherwise no nonblank extractable text; no OCR |
| `malformed_pdf` | Invalid header or PDF parsing error; partial text discarded |
| `resource_limit_exceeded` | Parser limit, recursion or caught memory exhaustion; partial text discarded |
| `extraction_failed` | Other parser failure; partial text discarded and internal error not returned |

`source_type` is `project_link`, `uploaded_pdf`, `uploaded_image`, or
`unsupported_file`. Links have `external_content_status: not_analyzed` and empty
`pdf_text`; other sources use `not_applicable`. Missing/wrong-candidate/non-project
lookups raise `LookupError`. Invalid IDs, non-project input records, malformed
metadata types, or a record combining a URL and file raise `ValueError`.
Database failures propagate rather than being disguised as document results.

Dependency: **pypdf==7.1.0**, pinned in `backend/requirements.txt`; no optional crypto,
OCR, AI models, executables or external services are installed. No PDF parser was
previously present in the backend environment. A small reader subclass overrides
the pinned version's encryption-initialization hook to reject encrypted documents
before even attempting the empty password or loading a crypto provider. The
encrypted-fixture test must pass whenever this dependency is upgraded.

There are no network requests, JavaScript execution, uploaded-file execution, or
analysis writes. All title/description/PDF text remains untrusted, including
prompt-like instructions. A linked skill ID remains a user-supplied association,
not a verified skill. No extraction result changes existing evidence/scoring tiers.

The input/page/returned-text bounds are **not a CPU/memory sandbox**: PDF parsing
may decompress content before a text visitor runs, and complex PDFs can be costly.
Before exposing extraction automatically to uploads, review process isolation and
timeouts. Text order/formatting may be imperfect; a no-text result cannot reliably
distinguish a scan from a blank PDF. No output is stored or logged by this module.

Before future GitHub analysis, explicitly address URL/host validation, SSRF and
redirect handling, fetch-size/time limits, privacy/authorization, and prompt
injection from repository content. None of that fetching is implemented here.

Synthetic tests run entirely on in-memory PDFs and temporary SQLite databases:

```sh
backend/.venv/bin/python -m unittest backend.test_evidence -v
backend/.venv/bin/python -m unittest discover -s backend -t . -p 'test_*.py' -v
```
