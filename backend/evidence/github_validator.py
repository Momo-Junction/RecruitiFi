"""Validate repository URL syntax only; no DNS, HTTP, Git or filesystem access."""
import re
from typing import TypedDict
from urllib.parse import urlsplit


class GitHubURLValidationError(ValueError):
    """The input is outside the supported GitHub repository URL format."""


class GitHubRepository(TypedDict):
    owner: str
    repository: str
    canonical_url: str


# Deliberately conservative ASCII identifiers, not arbitrary GitHub page URLs.
_OWNER = re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?')
_REPOSITORY = re.compile(r'[A-Za-z0-9._-]{1,100}')
_AUTHORITY = re.compile(r'github\.com(?::443)?', re.IGNORECASE)


def validate_github_repository_url(url: str) -> GitHubRepository:
    """Return owner/repository/canonical_url, or GitHubURLValidationError.

    Accept HTTPS github.com with an absent port or explicit 443, exactly two
    nonempty path segments, an optional single trailing slash and `.git` suffix.
    Preserve owner/repository case; normalize the scheme/host and omit port/suffix.
    No percent decoding or Unicode/whitespace cleanup is performed. Validation
    cannot establish whether a repository exists or is public without fetching.
    """
    if not isinstance(url, str) or not url or len(url) > 2048:
        raise GitHubURLValidationError('Provide a GitHub repository URL of at most 2048 characters.')
    # urlsplit silently strips some controls; reject them before parsing instead.
    if not url.isascii() or any(ord(char) <= 32 or ord(char) == 127 for char in url):
        raise GitHubURLValidationError('URL must contain only ASCII characters without whitespace or controls.')
    if '\\' in url or '%' in url:
        raise GitHubURLValidationError('Backslashes and percent-encoded URL components are unsupported.')
    if '?' in url or '#' in url:
        raise GitHubURLValidationError('Repository URLs must not contain query strings or fragments.')
    try:
        parsed = urlsplit(url)
        host, port = parsed.hostname, parsed.port
    except ValueError:
        raise GitHubURLValidationError('Malformed GitHub repository URL or port.') from None
    if parsed.scheme != 'https':
        raise GitHubURLValidationError('Only HTTPS repository URLs are supported.')
    if parsed.username is not None or parsed.password is not None:
        raise GitHubURLValidationError('Embedded URL credentials are not permitted.')
    if host != 'github.com':
        raise GitHubURLValidationError('The hostname must be exactly github.com.')
    if port not in (None, 443) or not _AUTHORITY.fullmatch(parsed.netloc):
        raise GitHubURLValidationError('Only an omitted port or the explicit default HTTPS port 443 is supported.')
    path = parsed.path[:-1] if parsed.path.endswith('/') else parsed.path
    segments = path.split('/')
    if len(segments) != 3 or segments[0] != '':
        raise GitHubURLValidationError('Use exactly /owner/repository, without additional path segments.')
    owner, repository = segments[1:]
    if repository.lower().endswith('.git'):
        repository = repository[:-4]
        if repository.lower().endswith('.git'):
            raise GitHubURLValidationError('Repeated .git suffixes are unsupported.')
    if not _OWNER.fullmatch(owner) or '--' in owner:
        raise GitHubURLValidationError('Invalid repository owner: use 1–39 alphanumeric characters with single internal hyphens.')
    if not _REPOSITORY.fullmatch(repository) or repository in ('.', '..'):
        raise GitHubURLValidationError('Invalid repository name: use 1–100 ASCII letters, digits, dots, underscores or hyphens; no dot segments.')
    return {'owner': owner, 'repository': repository,
            'canonical_url': f'https://github.com/{owner}/{repository}'}


def validate_github_repository_or_profile_url(url: str) -> GitHubRepository | None:
    """A repository identifier, or None for a validated metadata-only profile.

    Profile acceptance does not permit profile fetching, repository discovery or
    relaxed repository-fetcher validation. Reuse exactly the repository owner's
    HTTPS/host/credentials/port/path checks with a fixed placeholder segment.
    """
    try:
        return validate_github_repository_url(url)
    except GitHubURLValidationError:
        if not isinstance(url,str) or url.endswith('//'):
            raise GitHubURLValidationError('Use an HTTPS GitHub profile or repository URL.') from None
        validate_github_repository_url(url.rstrip('/')+'/__profile_metadata__')
        return None
