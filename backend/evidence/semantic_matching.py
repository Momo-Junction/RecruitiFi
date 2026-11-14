"""Review-only semantic relevance for explicitly synthetic project experiments.

No writes, matching-engine imports, candidate skill changes, or hiring decisions.
The caller supplies an isolated SQLite connection; no application DB is opened.
"""
import math
import threading
import time

from .embedding_client import EmbeddingClient, EmbeddingServiceError, MODEL_ID, MODEL_REVISION
from .extractor import extract_project_material

MAX_SKILLS = 100
MAX_FRAGMENTS = 6
FRAGMENT_CHARACTERS = 200
SKILL_TEXT_CHARACTERS = 400
EXCERPT_CHARACTERS = 160
ANALYSIS_SECONDS = 120.0
_ANALYSIS_SLOT = threading.BoundedSemaphore(1)


def _catalog(connection):
    columns = {row[1] for row in connection.execute('PRAGMA table_info(skills)')}
    description = 'description' if 'description' in columns else "''"
    rows = connection.execute(f'SELECT id, name, {description} FROM skills ORDER BY id LIMIT ?',
                              (MAX_SKILLS + 1,)).fetchall()
    if len(rows) > MAX_SKILLS:
        raise ValueError('Skill catalog exceeds the experimental 100-skill limit.')
    skills = []
    for identifier, name, detail in rows:
        if type(identifier) is not int or identifier <= 0 or not isinstance(name, str) or not name.strip():
            raise ValueError('Invalid stored skill identity.')
        if detail is None:
            detail = ''
        if not isinstance(detail, str):
            raise ValueError('Invalid stored skill description.')
        text = f'{name}: {detail}' if detail.strip() else name
        if len(text) > SKILL_TEXT_CHARACTERS:
            raise ValueError('Stored skill comparison text exceeds the experimental limit.')
        skills.append({'id': identifier, 'name': name, 'text': text})
    return skills


def _fragments(evidence):
    fields = ['project_title', 'project_description']
    if evidence['extraction_status'] in ('extracted', 'text_limit_reached'):
        fields.append('pdf_text')
    fragments = []
    limited = bool(evidence['text_truncated'])
    for field in fields:
        text = evidence[field]
        if not isinstance(text, str) or len(text) > 20_000:
            raise ValueError('Evidence field is invalid or exceeds extraction limits.')
        for start in range(0, len(text), FRAGMENT_CHARACTERS):
            part = text[start:start + FRAGMENT_CHARACTERS]
            if not part.strip():
                continue
            if len(fragments) == MAX_FRAGMENTS:
                limited = True
                return fragments, limited
            fragments.append({'field': field, 'start': start, 'end': start + len(part), 'text': part})
    return fragments, limited


def _embed_batches(client, texts, deadline):
    vectors = []
    for index in range(0, len(texts), 3):
        if time.monotonic() >= deadline:
            raise EmbeddingServiceError('timeout')
        vectors.extend(client.embed(texts[index:index + 3], deadline=deadline))
    return vectors


def match_evidence_fragments(fragments, *, connection, synthetic_data=False, consent_verified=False, top_k=3, deadline=None):
    """Shared bounded comparison for project or GitHub fragments; no URL fetching.

    Fragments contain material_id, source_type, field, start, end, text, and an
    optional source provenance dictionary. Provenance is returned, never embedded.
    """
    if synthetic_data is not True and consent_verified is not True:
        raise ValueError('Only explicitly declared isolated synthetic experiments are enabled.')
    if type(top_k) is not int or not 1 <= top_k <= 5:
        raise ValueError('top_k must be between 1 and 5.')
    if not isinstance(fragments, list) or len(fragments) > MAX_FRAGMENTS:
        raise ValueError('At most six attributed fragments are supported.')
    for part in fragments:
        if (type(part['material_id']) is not int or part['material_id'] <= 0
                or not isinstance(part['text'], str) or not part['text'].strip()
                or len(part['text']) > FRAGMENT_CHARACTERS
                or type(part['start']) is not int or part['start'] < 0
                or part['end'] != part['start'] + len(part['text'])
                or not isinstance(part['field'], str) or not isinstance(part['source_type'], str)):
            raise ValueError('Invalid attributed evidence fragment.')
    end = time.monotonic() + ANALYSIS_SECONDS
    if deadline is not None:
        if type(deadline) not in (int, float) or not math.isfinite(deadline):
            raise ValueError('Invalid analysis deadline.')
        end = min(end, deadline)
    if not _ANALYSIS_SLOT.acquire(blocking=False):
        raise EmbeddingServiceError('busy')
    try:
        deadline = end
        if time.monotonic() >= deadline:
            raise EmbeddingServiceError('timeout')
        skills = _catalog(connection)
        report = {'model': MODEL_ID, 'revision': MODEL_REVISION, 'untrusted': True,
                  'fragments': [], 'status': 'no_evidence' if not fragments else 'no_skills' if not skills else 'complete'}
        if not fragments or not skills:
            return report
        client = EmbeddingClient()
        client.check_ready(deadline=deadline)
        skill_vectors = _embed_batches(client, [skill['text'] for skill in skills], deadline)
        evidence_vectors = _embed_batches(client, [part['text'] for part in fragments], deadline)
        for index, (part, vector) in enumerate(zip(fragments, evidence_vectors)):
            if time.monotonic() >= deadline:
                raise EmbeddingServiceError('timeout')
            scored = []
            for skill, other in zip(skills, skill_vectors):
                similarity = math.fsum(a * b for a, b in zip(vector, other)) / (math.hypot(*vector) * math.hypot(*other))
                scored.append((max(-1.0, min(1.0, similarity)), skill))
            scored.sort(key=lambda item: (-item[0], item[1]['id']))
            matches = [{'skill_id': skill['id'], 'skill_name': skill['name'], 'similarity_score': score,
                        'material_id': part['material_id'], 'evidence_source_type': part['source_type'],
                        'evidence_field': part['field'], 'excerpt_start': part['start'],
                        'excerpt_end': part['start'] + min(EXCERPT_CHARACTERS, len(part['text'])),
                        'supporting_excerpt': part['text'][:EXCERPT_CHARACTERS],
                        'review_status': 'unreviewed', 'interpretation': 'semantic_relevance_only'}
                       for score, skill in scored[:top_k]]
            if 'source' in part:
                for match in matches:
                    match['source'] = dict(part['source'])
            report['fragments'].append({'fragment_index': index, 'evidence_field': part['field'],
                                        'start': part['start'], 'end': part['end'], 'matches': matches})
        if time.monotonic() >= deadline:
            raise EmbeddingServiceError('timeout')
        return report
    finally:
        _ANALYSIS_SLOT.release()


def match_project_evidence(evidence, *, connection, synthetic_data=False, consent_verified=False, top_k=3):
    """Compare existing extractor output; synthetic declaration is mandatory."""
    if synthetic_data is not True and consent_verified is not True:
        raise ValueError('Only explicitly declared isolated synthetic experiments are enabled.')
    if type(evidence['material_id']) is not int or evidence['material_id'] <= 0:
        raise ValueError('Invalid material ID.')
    if evidence['source_type'] not in ('project_link', 'uploaded_pdf', 'uploaded_image', 'unsupported_file'):
        raise ValueError('Invalid evidence source type.')
    fragments, limited = _fragments(evidence)
    for part in fragments:
        part.update(material_id=evidence['material_id'], source_type=evidence['source_type'])
    report = match_evidence_fragments(fragments, connection=connection, synthetic_data=synthetic_data, consent_verified=consent_verified, top_k=top_k)
    report.update(material_id=evidence['material_id'], extraction_status=evidence['extraction_status'],
                  external_content_status=evidence['external_content_status'], coverage_limited=limited)
    if limited and report['status'] == 'complete':
        report['status'] = 'limited'
    return report


def match_project_material(material, *, connection, synthetic_data=False, consent_verified=False, top_k=3):
    """Reuse the existing extractor on a supplied synthetic stored material row."""
    if synthetic_data is not True and consent_verified is not True:
        raise ValueError('Only explicitly declared isolated synthetic experiments are enabled.')
    return match_project_evidence(extract_project_material(material), connection=connection,
                                  synthetic_data=synthetic_data, consent_verified=consent_verified, top_k=top_k)
