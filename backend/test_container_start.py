"""Deployment preflight checks; hosted configuration fails closed."""
import os
import secrets
import unittest
from unittest.mock import patch

from .container_start import validate_runtime


class ContainerPreflightTests(unittest.TestCase):
    def test_root_is_rejected(self):
        with patch('os.geteuid', return_value=0):
            with self.assertRaisesRegex(RuntimeError, 'non-root UID'):
                validate_runtime()

    def test_hosted_mode_requires_password(self):
        with patch('os.geteuid', return_value=1000620000), patch.dict(os.environ, {'TALENTMATCH_HOSTED_DEMO': '1', 'TALENTMATCH_DEMO_PASSWORD': ''}):
            with self.assertRaisesRegex(RuntimeError, 'PASSWORD is required'):
                validate_runtime()

    def test_valid_hosted_password_passes_auth_preflight(self):
        with patch('os.geteuid', return_value=1000620000), patch.dict(os.environ, {'TALENTMATCH_HOSTED_DEMO': '1', 'TALENTMATCH_DEMO_PASSWORD': secrets.token_urlsafe(24)}):
            # Next check deliberately uses an invalid path: valid auth must reach it.
            os.environ['TALENTMATCH_DB'] = '/app/backend/talentmatch.sqlite3'
            with self.assertRaisesRegex(RuntimeError, '/var/data'):
                validate_runtime()

    def test_database_cannot_fall_back_to_source_directory(self):
        with patch('os.geteuid', return_value=1000620000), patch.dict(os.environ, {'TALENTMATCH_HOSTED_DEMO': '0', 'TALENTMATCH_DB': '/app/backend/talentmatch.sqlite3'}):
            with self.assertRaisesRegex(RuntimeError, '/var/data'):
                validate_runtime()
