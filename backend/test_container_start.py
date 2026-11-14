"""Deployment preflight checks; application authentication remains unchanged."""
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

    def test_password_does_not_enable_missing_authentication(self):
        with patch('os.geteuid', return_value=1000620000), patch.dict(os.environ, {'TALENTMATCH_HOSTED_DEMO': '1', 'TALENTMATCH_DEMO_PASSWORD': secrets.token_urlsafe(24)}):
            with self.assertRaisesRegex(RuntimeError, 'authentication is not implemented'):
                validate_runtime()

    def test_database_cannot_fall_back_to_source_directory(self):
        with patch('os.geteuid', return_value=1000620000), patch.dict(os.environ, {'TALENTMATCH_HOSTED_DEMO': '0', 'TALENTMATCH_DB': '/app/backend/talentmatch.sqlite3'}):
            with self.assertRaisesRegex(RuntimeError, '/var/data'):
                validate_runtime()
