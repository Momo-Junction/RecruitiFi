"""Offline tests for the strict repository URL boundary; no repository fetching."""
import json
import unittest
from unittest.mock import patch

from .evidence.github_validator import GitHubURLValidationError, validate_github_repository_url


class GitHubValidatorTests(unittest.TestCase):
    def assert_invalid(self, urls):
        for url in urls:
            with self.subTest(url=url), self.assertRaises(GitHubURLValidationError):
                validate_github_repository_url(url)

    def test_valid_url_returns_structured_repository_identifier(self):
        result = validate_github_repository_url('https://github.com/Momo-Junction/RecruitiFi')
        self.assertEqual(result, {'owner': 'Momo-Junction', 'repository': 'RecruitiFi',
                                  'canonical_url': 'https://github.com/Momo-Junction/RecruitiFi'})
        self.assertEqual(json.loads(json.dumps(result)), result)

    def test_supported_variants_normalize_without_changing_identifier_case(self):
        expected = {'owner': 'Owner', 'repository': 'project_name.v2-1',
                    'canonical_url': 'https://github.com/Owner/project_name.v2-1'}
        for url in ['https://github.com/Owner/project_name.v2-1',
                    'https://github.com/Owner/project_name.v2-1/',
                    'HTTPS://GITHUB.COM/Owner/project_name.v2-1.git',
                    'https://github.com:443/Owner/project_name.v2-1.git/',
                    'https://github.com/Owner/project_name.v2-1.GIT']:
            with self.subTest(url=url):
                self.assertEqual(validate_github_repository_url(url), expected)
        self.assertEqual(validate_github_repository_url('https://github.com/a/.github')['repository'], '.github')

    def test_only_https_absolute_urls_are_supported(self):
        self.assert_invalid(['http://github.com/a/b', 'git://github.com/a/b', 'ssh://github.com/a/b',
                             'ftp://github.com/a/b', '//github.com/a/b', 'github.com/a/b',
                             'git@github.com:a/b.git', 'https:github.com/a/b',
                             'file:///github.com/a/b', 'javascript:alert(1)'])

    def test_hostname_allowlist_rejects_internal_ips_and_lookalikes(self):
        hosts = ['localhost', 'localhost.localdomain', '127.0.0.1', '127.1', '2130706433',
                 '0x7f000001', '10.0.0.1', '172.16.0.1', '192.168.1.1', '169.254.169.254',
                 '0.0.0.0', '[::1]', '[fc00::1]', '[::ffff:127.0.0.1]', '8.8.8.8',
                 'github.com.evil.com', 'evilgithub.com', 'www.github.com', 'api.github.com',
                 'github.com.', 'github.com..', 'github-com', 'github', 'raw.githubusercontent.com',
                 'githubusercontent.com', 'github.com.localhost', 'xn--gthub-n4a.com']
        self.assert_invalid([f'https://{host}/owner/repo' for host in hosts])

    def test_credentials_and_authority_confusion_are_rejected(self):
        self.assert_invalid(['https://user:secret@github.com/a/b', 'https://user@github.com/a/b',
                             'https://@github.com/a/b', 'https://:secret@github.com/a/b',
                             'https://github.com@evil.com/a/b', 'https://evil.com@github.com/a/b',
                             'https://github.com\\@evil.com/a/b', 'https://github.com:443@evil.com/a/b',
                             'https://github.com%40evil.com/a/b'])

    def test_unsupported_and_noncanonical_ports_are_rejected(self):
        self.assert_invalid([f'https://github.com:{port}/a/b' for port in
                             ['80', '8080', '8443', '0', '-1', '65536', 'abc', '', '0443', '+443', '443:443']])

    def test_extra_or_missing_path_segments_are_rejected(self):
        self.assert_invalid(['https://github.com', 'https://github.com/', 'https://github.com/owner',
                             'https://github.com/owner/', 'https://github.com//repo',
                             'https://github.com//owner/repo', 'https://github.com/owner//repo',
                             'https://github.com/owner/repo//', 'https://github.com/owner/repo/tree/main',
                             'https://github.com/owner/repo/blob/main/README.md', 'https://github.com/owner/repo/issues',
                             'https://github.com/owner/repo/../other', 'https://github.com/owner/repo;parameter'])

    def test_dot_segments_and_invalid_identifiers_are_rejected(self):
        self.assert_invalid([f'https://github.com/{owner}/repo' for owner in ['.', '..', '-owner', 'owner-', 'own--er', 'own_er', 'a' * 40]])
        self.assert_invalid([f'https://github.com/owner/{repo}' for repo in ['.', '..', '.git', '..git', 'repo.git.git', 'repo.GIT.git', 'repo:443', 'repo@host', 'a' * 101]])
        boundary = validate_github_repository_url(f'https://github.com/{"a" * 39}/{"b" * 100}')
        self.assertEqual(len(boundary['owner']), 39)
        self.assertEqual(len(boundary['repository']), 100)

    def test_encoding_unicode_and_parser_control_normalization_are_rejected(self):
        self.assert_invalid(['https://githu\u0432.com/a/b', 'https://github\uff0ecom/a/b',
                             'https://github.com\uff0fevil.com/a/b', 'https://github.com/a/r\u00e9po',
                             'https://github.com/a/%2e%2e', 'https://github.com/a/repo%2fissues',
                             'https://github.com/%6fwner/repo', 'https://github.com/a/%252e%252e',
                             'https://github.com/a/repo%00', 'https://github.com/a/repo\\other',
                             ' https://github.com/a/b', 'https://github.com/a/b ',
                             '\x00https://github.com/a/b', 'https://git\nhub.com/a/b',
                             'https://github.com/a/b\r\nHost: localhost', 'https://github.com/a/b\t',
                             'https://github.com/a/b\x7f', 'https://github.com/a/b\u200b'])

    def test_queries_and_fragments_even_empty_are_rejected(self):
        self.assert_invalid(['https://github.com/a/b?x=1', 'https://github.com/a/b#readme',
                             'https://github.com/a/b?', 'https://github.com/a/b#',
                             'https://github.com/a/b?url=http://127.0.0.1', 'https://github.com/a/b.git/#readme'])

    def test_invalid_types_malformed_authorities_and_long_inputs_have_clear_errors(self):
        self.assert_invalid([None, 123, b'https://github.com/a/b', [], {}, '',
                             'https://[github.com/a/b', 'https:///a/b', 'https://github.com:443:80/a/b',
                             'https://github.com/a/' + 'b' * 2048])
        with self.assertRaises(GitHubURLValidationError) as error:
            validate_github_repository_url('https://user:DO_NOT_ECHO_SECRET@github.com/a/b')
        self.assertIn('credentials', str(error.exception))
        self.assertNotIn('DO_NOT_ECHO_SECRET', str(error.exception))
        self.assertIsInstance(error.exception, ValueError)

    def test_canonical_url_is_idempotent(self):
        result = validate_github_repository_url('HTTPS://GITHUB.COM:443/Owner/Repository.git/')
        self.assertEqual(validate_github_repository_url(result['canonical_url']), result)

    def test_validation_never_resolves_hosts_fetches_redirects_or_runs_git(self):
        with patch('socket.getaddrinfo') as dns, patch('socket.create_connection') as network, \
                patch('urllib.request.urlopen') as http, patch('http.client.HTTPSConnection') as https, \
                patch('subprocess.Popen') as process, patch('os.system') as system:
            validate_github_repository_url('https://github.com/owner/repo')
            self.assert_invalid(['https://127.0.0.1/a/b', 'https://github.com.evil.com/a/b'])
        for operation in [dns, network, http, https, process, system]:
            operation.assert_not_called()


class GitHubProfileMetadataTests(unittest.TestCase):
    def test_profiles_are_metadata_only_and_repositories_remain_validated(self):
        from .evidence.github_validator import validate_github_repository_or_profile_url as classify
        self.assertIsNone(classify('https://github.com/SyntheticOwner'))
        self.assertIsNone(classify('https://github.com/SyntheticOwner/'))
        self.assertEqual(classify('https://github.com/SyntheticOwner/Test')['repository'],'Test')
        for url in ('http://github.com/Owner','https://github.com.evil.invalid/Owner','https://user:password@github.com/Owner','https://github.com:8080/Owner','https://github.com/Owner?tab=repositories','https://github.com/Owner#bio','https://github.com/Owner//','https://127.0.0.1/Owner','https://github.com/Owner/Test/tree/main'):
            with self.subTest(url=url),self.assertRaises(ValueError):classify(url)
