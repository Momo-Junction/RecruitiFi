"""Optional manual integration test: synthetic evidence and disposable DB only."""
import argparse
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from .. import database
from ..seed_data import SKILLS
from .semantic_matching import match_project_material


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthetic', action='store_true', help='Confirm synthetic-only local testing.')
    args = parser.parse_args()
    if not args.synthetic:
        parser.error('--synthetic is required; real materials are not supported in this experiment.')
    with tempfile.TemporaryDirectory(prefix='recruitifi-semantic-synthetic-') as directory:
        # Patch only this test process; never open the configured application/live DB.
        with patch.object(database, 'DB_PATH', Path(directory) / 'synthetic.sqlite3'):
            with database.connect() as connection:
                connection.executescript(database.SCHEMA_PATH.read_text())
                # Same catalog names/categories and ID assignment as existing seed.py.
                connection.executemany('INSERT INTO skills(id,esco_uri,name,category) VALUES(?,?,?,?)',
                    [(index, f'urn:synthetic:catalog:{index}', name, category)
                     for index, (name, category) in enumerate(SKILLS, start=1)])
                connection.commit()
                connection.execute('PRAGMA query_only = ON')
                row = {'id': 7, 'candidate_id': 402, 'category': 'project', 'skill_id': None,
                       'title': 'Synthetic Python and FastAPI project',
                       'description': 'Developed REST APIs using Python and FastAPI with automated tests.',
                       'url': 'https://example.invalid/synthetic-project', 'content': None}
                before = connection.total_changes
                result = match_project_material(row, connection=connection, synthetic_data=True)
                assert connection.total_changes == before
                assert result['fragments'] and result['status'] == 'complete'
                valid_ids = {row[0] for row in connection.execute('SELECT id FROM skills')}
                assert all(match['skill_id'] in valid_ids for fragment in result['fragments'] for match in fragment['matches'])
                print(json.dumps(result, indent=2))  # Deliberately synthetic manual output only.


if __name__ == '__main__':
    main()
