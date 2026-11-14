"""Explicit, insert-only synthetic openings initializer. Never run backend.seed on an existing event."""
import json

from .database import SCHEMA_PATH, connect
from .jobs import Industry
from .models import CompanyRoleUpdate

# Names resolve to actual catalog IDs; no candidate's skill claims are changed.
EXTRA_SKILLS = [
    ('Logistics Coordination', 'Logistics'), ('Inventory Control', 'Logistics'),
    ('Food Hygiene', 'Restaurant'), ('Food Service', 'Restaurant'),
    ('Commercial Cleaning', 'Cleaning'), ('Cleaning Safety', 'Cleaning'),
]
# Stable opening IDs. All positions are fictional hackathon examples, not real vacancies.
JOBS = [
    (1001, 1, 'Quantum Software Developer', 'it', 'Build a synthetic quantum-tooling prototype.',
     {'Python': 40, 'Quantum circuit programming with Qiskit': 30}, {'Git': 10, 'Automated Testing': 10}),
    (1002, 1, 'Quantum Hardware Engineer', 'engineering', 'Prototype synthetic lab electronics and signal processing.',
     {'Digital Signal Processing': 40, 'Electronics Prototyping': 30}, {'C++': 10, 'Embedded Systems': 10}),
    (1003, 1, 'Research Data Analyst', 'it', 'Explore a synthetic research dataset.',
     {'Data Analysis': 35, 'Statistical Analysis': 35}, {'SQL': 10, 'Python': 10}),
    (2001, 2, 'Energy Systems Engineer', 'engineering', 'Model a fictional clean-energy system.',
     {'Power Systems Engineering': 40, 'Energy Modeling': 30}, {'Data Analysis': 10, 'Life Cycle Assessment': 10}),
    (2002, 2, 'Demo Equipment Logistics Coordinator', 'logistics', 'Coordinate fictional event equipment and inventory.',
     {'Logistics Coordination': 40, 'Inventory Control': 30}, {'Project Management': 10, 'Technical Documentation': 10}),
    (3001, 3, 'Clinical Data Coordinator', 'health_sector', 'Document a synthetic clinical data workflow.',
     {'Clinical Data Management': 40, 'Data Privacy': 30}, {'Medical Device Quality Management': 10, 'SQL': 10}),
    (3002, 3, 'Demo Facilities Cleaning Assistant', 'cleaning', 'Practice fictional facility cleaning and safe procedures.',
     {'Commercial Cleaning': 40, 'Cleaning Safety': 30}, {'Technical Documentation': 10, 'Finnish Language': 10}),
    (4001, 4, 'Cloud Platform Engineer', 'it', 'Build a synthetic deployment platform.',
     {'Docker': 35, 'Cloud Infrastructure': 35}, {'Kubernetes': 10, 'CI/CD': 10}),
    (4002, 4, 'Service Delivery Coordinator', 'business_services', 'Coordinate delivery of a fictional client service.',
     {'Project Management': 40, 'Stakeholder Management': 30}, {'Agile Delivery': 10, 'Technical Documentation': 10}),
    (5001, 5, 'Accessible Product Designer', 'it', 'Design a fictional accessible digital service.',
     {'UI/UX Design': 35, 'Web Accessibility': 35}, {'User Research': 10, 'Figma Prototyping': 10}),
    (5002, 5, 'Demo Event Catering Assistant', 'restaurant', 'Support a fictional pop-up catering event; not a real vacancy.',
     {'Food Hygiene': 40, 'Food Service': 30}, {'English Language': 10, 'Finnish Language': 10}),
    (5003, 5, 'Client Services Coordinator', 'business_services', 'Plan a fictional client discovery workshop.',
     {'Stakeholder Management': 40, 'User Research': 30}, {'Project Management': 10, 'Technical Documentation': 10}),
]


def initialize_jobs():
    with connect() as connection:
        # Only CREATE IF NOT EXISTS, deliberately no existing startup data update.
        connection.executescript(SCHEMA_PATH.read_text(encoding='utf-8'))
        connection.execute('BEGIN IMMEDIATE')
        required_companies = {job[1] for job in JOBS}
        available = {row['id'] for row in connection.execute('SELECT id FROM companies')}
        if not required_companies <= available:
            raise RuntimeError(f'Missing required demo company IDs: {sorted(required_companies - available)}. No event reseed was attempted.')
        # Resolve existing names before adding only the six missing domain skills.
        for name, category in EXTRA_SKILLS:
            if not connection.execute('SELECT id FROM skills WHERE name=?', (name,)).fetchone():
                uri = 'urn:talentmatch:demo-job-skill:' + name.lower().replace(' ', '-')
                connection.execute('INSERT INTO skills(esco_uri, name, category) VALUES (?, ?, ?)', (uri, name, category))
        names = {row['name']: row['id'] for row in connection.execute('SELECT id, name FROM skills')}
        inserted = 0
        for identity, company, title, industry, description, required, preferred in JOBS:
            existing = connection.execute('SELECT company_id FROM job_openings WHERE id=?', (identity,)).fetchone()
            if existing:
                if existing['company_id'] != company:
                    raise RuntimeError(f'Reserved demo job ID {identity} belongs to a different company; refusing to overwrite it.')
                continue  # Preserve title, category, weights, active state and any manual edits.
            if industry not in Industry.__args__:
                raise RuntimeError(f'Invalid industry: {industry}')
            missing = (required.keys() | preferred.keys()) - names.keys()
            if missing:
                raise RuntimeError(f'Missing required catalog skills: {sorted(missing)}. No candidate skills were added.')
            groups = [[{'skill_id': names[name], 'weight': weight} for name, weight in group.items()] for group in (required, preferred)]
            # Reuse the existing 70/20, uniqueness and positive-weight validation.
            CompanyRoleUpdate(working_language='English', relocation_support=False, min_match_threshold=75,
                              must_have_skills=groups[0], nice_to_have_skills=groups[1])
            cursor = connection.execute(
                'INSERT INTO job_openings(id, company_id, title, industry, description, must_have_skills, nice_to_have_skills) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (identity, company, title, industry, description, json.dumps(groups[0]), json.dumps(groups[1])),
            )
            inserted += cursor.rowcount
    return inserted


if __name__ == '__main__':
    print(f'Inserted {initialize_jobs()} synthetic openings; existing jobs and event data retained.')
