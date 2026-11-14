"""Bounded, anonymous GitHub REST evidence retrieval. No code execution or storage.

Only identifiers produced by github_validator are accepted (and revalidated).
Network requests use a fixed host and vetted, pinned public DNS addresses. See
GITHUB_RETRIEVAL.md for limits of application-level isolation and secret detection.
"""
import base64
import binascii
import http.client
import hashlib
import ipaddress
import json
import math
from contextlib import suppress
import re
import socket
import ssl
import threading
import time
from dataclasses import dataclass
from typing import TypedDict
from urllib.parse import quote

from .github_validator import GitHubRepository, GitHubURLValidationError, validate_github_repository_url

API_HOST = 'api.github.com'
CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 5.0
ANALYSIS_SECONDS = 30.0
MAX_REPOSITORIES = 3
MAX_FILES = 20
MAX_FILE_BYTES = 20_000
MAX_TEXT_BYTES = 100_000
MAX_TREE_ENTRIES = 2_000
MAX_API_BYTES = 2_000_000
METADATA_RESPONSE_BYTES = 64_000
TREE_RESPONSE_BYTES = 512_000
BLOB_RESPONSE_BYTES = 32_000
MAX_REQUESTS = MAX_REPOSITORIES * 2 + MAX_FILES
_SHA = re.compile(r'[0-9a-f]{40}')
_SEGMENT = re.compile(r'[A-Za-z0-9._-]+')
_DOCUMENTS = {'readme.md': 0, 'package.json': 1, 'requirements.txt': 2, 'pyproject.toml': 3, 'dockerfile': 4}
_SOURCE_EXTENSIONS = ('.py', '.js', '.ts', '.tsx')
_EXCLUDED = {'node_modules', 'vendor', 'venv', 'dist', 'build', 'coverage', '__pycache__', 'site-packages'}
_SENSITIVE = {'env', 'credential', 'credentials', 'secret', 'secrets', 'key', 'keys', 'password', 'passwords',
              'token', 'tokens', 'apikey', 'private', 'config', 'settings', 'id_rsa', 'id_ed25519'}
_SECRET_TEXT = re.compile(
    r'\b[a-zA-Z][a-zA-Z0-9+.-]{0,15}://[^/\s:@]+:[^/\s@]+@|-----BEGIN [A-Z ]*PRIVATE KEY-----'
    r'|\b(?:gh[pousr]_[A-Za-z0-9_]{16,}|github_pat_[A-Za-z0-9_]{16,}|AKIA[0-9A-Z]{16})\b'
)
_SECRET_ASSIGNMENT = re.compile(
    r"""(?i)(?<![\w-])["']?([\w-]{1,128})["']?[ \t]*[:=][ \t]*["'][^"'\r\n]+["']"""
)
_DNS_SLOT = threading.BoundedSemaphore(1)


class GitHubFileEvidence(TypedDict):
    path: str
    text: str
    source_reference: str
    blob_sha: str
    decoded_bytes: int
    untrusted: bool


class GitHubRepositoryEvidence(TypedDict):
    repository: GitHubRepository
    retrieval_status: str
    tree_sha: str | None
    files: list[GitHubFileEvidence]
    skipped: list[dict]
    http_status: int | None
    untrusted: bool


class _FetchError(Exception):
    def __init__(self, status, http_status=None):
        self.status, self.http_status = status, http_status


@dataclass
class _Budget:
    deadline: float
    files: int = 0
    decoded: int = 0
    api_bytes: int = 0
    requests: int = 0

    def remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise _FetchError('timeout')
        return remaining


def _resolve(timeout):
    # OS DNS cannot be cancelled safely. Bound caller waiting and allow only one
    # outstanding resolver; a timed-out worker only resolves this fixed hostname.
    if not _DNS_SLOT.acquire(blocking=False):
        raise _FetchError('dns_busy')
    done, result = threading.Event(), {}

    def work():
        try:
            result['addresses'] = socket.getaddrinfo(API_HOST, 443, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
        except Exception as error:
            result['error'] = error
        finally:
            _DNS_SLOT.release()
            done.set()

    try:
        threading.Thread(target=work, daemon=True, name='github-fixed-host-dns').start()
    except Exception:
        _DNS_SLOT.release()
        raise
    if not done.wait(timeout):
        raise _FetchError('timeout')
    if 'error' in result:
        raise result['error']
    return result['addresses']


def _public_addresses(timeout=CONNECT_TIMEOUT):
    addresses = _resolve(timeout)
    if not addresses or len(addresses) > 16:
        raise _FetchError('unsafe_destination')
    for family, kind, protocol, _, address in addresses:
        try:
            if '%' in address[0]:
                raise ValueError('Scoped addresses are unsupported')
            ip = ipaddress.ip_address(address[0])
            effective = ip.ipv4_mapped if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped else ip
            safe = effective.is_global and not any((effective.is_multicast, effective.is_reserved,
                   effective.is_loopback, effective.is_link_local, effective.is_unspecified, effective.is_private))
        except ValueError:
            safe = False
        if (not safe or family not in (socket.AF_INET, socket.AF_INET6) or kind != socket.SOCK_STREAM
                or protocol != socket.IPPROTO_TCP or address[1] != 443 or (len(address) > 3 and address[3] != 0)):
            raise _FetchError('unsafe_destination')
    return addresses[:4]


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, timeout):
        self.tls_context = ssl.create_default_context()
        super().__init__(API_HOST, 443, timeout=timeout, context=self.tls_context)

    def connect(self):
        # Bypass the parent's second DNS lookup and any proxy/tunnel support.
        started = time.monotonic()
        addresses = _public_addresses(self.timeout)
        last_error = None
        for family, kind, protocol, _, address in addresses:
            remaining = self.timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError('Connection deadline exceeded')
            raw = socket.socket(family, kind, protocol)
            try:
                raw.settimeout(remaining)
                raw.connect(address)  # Numeric address already vetted; no DNS rebinding window.
                self.sock = self.tls_context.wrap_socket(raw, server_hostname=API_HOST)
                return
            except (OSError, ssl.SSLError) as error:
                last_error = error
                raw.close()
        if last_error:
            raise last_error
        raise _FetchError('network_error')


def _open_connection(timeout):
    return _PinnedHTTPSConnection(timeout)


def _header(response, name):
    values = [value for key, value in response.getheaders() if key.lower() == name.lower()]
    if len(values) > 1:
        raise _FetchError('invalid_response')
    return values[0] if values else None


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def _json_request(path, limit, budget, *, list_response=False):
    budget.remaining()
    if budget.requests >= MAX_REQUESTS or budget.api_bytes >= MAX_API_BYTES:
        raise _FetchError('analysis_limit_reached')
    budget.requests += 1
    connection = None
    transport_socket = None
    response = None
    expired = threading.Event()
    timer = None

    def abort():
        expired.set()
        sock = transport_socket if transport_socket is not None else connection.sock if connection is not None else None
        if sock is not None:
            with suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)

    try:
        connection = _open_connection(min(CONNECT_TIMEOUT, budget.remaining()))
        timer = threading.Timer(budget.remaining(), abort)
        timer.daemon = True
        timer.start()
        # Host is fixed by the connection; no URLs returned by GitHub are used.
        connection.request('GET', path, headers={'Accept': 'application/vnd.github+json',
                           'Accept-Encoding': 'identity', 'User-Agent': 'RecruitiFi-evidence/0.1', 'Connection': 'close'})
        transport_socket = connection.sock
        if connection.sock is not None:
            connection.sock.settimeout(min(READ_TIMEOUT, budget.remaining()))
        response = connection.getresponse()
        status = response.status
        if 300 <= status < 400:
            raise _FetchError('redirect_rejected', status)
        if status == 429 or (status == 403 and (_header(response, 'X-RateLimit-Remaining') == '0' or _header(response, 'Retry-After'))):
            raise _FetchError('rate_limited', status)
        if status == 404:
            raise _FetchError('unavailable_or_private', status)
        if status == 403:
            raise _FetchError('forbidden', status)
        if status == 409:
            raise _FetchError('empty_repository', status)
        if status != 200:
            raise _FetchError('github_unavailable' if status >= 500 else 'api_error', status)
        content_type = (_header(response, 'Content-Type') or '').split(';', 1)[0].strip().lower()
        if content_type not in ('application/json', 'application/vnd.github+json'):
            raise _FetchError('unsupported_content_type', status)
        if (_header(response, 'Content-Encoding') or 'identity').lower() != 'identity':
            raise _FetchError('unsupported_content_encoding', status)
        declared = _header(response, 'Content-Length')
        if declared is not None:
            if len(declared) > 10 or not re.fullmatch(r'[0-9]+', declared):
                raise _FetchError('invalid_response', status)
            if int(declared) > limit or int(declared) + budget.api_bytes > MAX_API_BYTES:
                raise _FetchError('response_too_large', status)
        body = bytearray()
        while True:
            if transport_socket is not None:
                transport_socket.settimeout(min(READ_TIMEOUT, budget.remaining()))
            budget.remaining()
            chunk = response.read1(min(8192, limit - len(body) + 1, MAX_API_BYTES - budget.api_bytes + 1))
            if not chunk:
                break
            budget.api_bytes += len(chunk)
            if len(body) + len(chunk) > limit or budget.api_bytes > MAX_API_BYTES:
                raise _FetchError('response_too_large', status)
            body.extend(chunk)
        budget.remaining()
        if expired.is_set():
            raise _FetchError('timeout')
        if declared is not None and len(body) != int(declared):
            raise _FetchError('invalid_response', status)
        budget.remaining()
        try:
            value = json.loads(body.decode('utf-8'), object_pairs_hook=_unique_object,
                               parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
        except (UnicodeError, ValueError, RecursionError):
            raise _FetchError('invalid_response', status) from None
        if not isinstance(value, list if list_response else dict):
            raise _FetchError('invalid_response', status)
        return value
    except _FetchError:
        raise
    except (TimeoutError, socket.timeout):
        raise _FetchError('timeout') from None
    except ssl.SSLError:
        raise _FetchError('tls_error') from None
    except (OSError, http.client.HTTPException):
        raise _FetchError('timeout' if expired.is_set() else 'network_error') from None
    finally:
        if timer is not None:
            timer.cancel()
            timer.join()
        if response is not None and hasattr(response, 'close'):
            with suppress(OSError):
                response.close()
        if connection is not None:
            connection.close()


def _safe_path(path):
    if not isinstance(path, str) or not 0 < len(path) <= 1024:
        return False
    return all(segment not in ('', '.', '..') and _SEGMENT.fullmatch(segment) for segment in path.split('/'))


def _selection_priority(path):
    parts = path.lower().split('/')
    if any(part.startswith('.') or part in _EXCLUDED for part in parts):
        return None
    if any(_SENSITIVE.intersection(re.split(r'[^a-z0-9]+', part)) for part in parts):
        return None
    name = parts[-1]
    if name in _DOCUMENTS:
        return (_DOCUMENTS[name], len(parts), path.casefold(), path)
    if name.endswith(_SOURCE_EXTENSIONS):
        return (5, len(parts), path.casefold(), path)
    return None


def _select_tree(tree):
    if tree.get('truncated') is not False:
        raise _FetchError('truncated_tree' if tree.get('truncated') is True else 'invalid_response')
    entries, tree_sha = tree.get('tree'), tree.get('sha')
    if not isinstance(entries, list):
        raise _FetchError('invalid_response')
    if len(entries) > MAX_TREE_ENTRIES:
        raise _FetchError('tree_limit_exceeded')
    if not isinstance(tree_sha, str) or not _SHA.fullmatch(tree_sha):
        raise _FetchError('invalid_response')
    selected, skipped, seen = [], [], set()
    for entry in entries:
        if not isinstance(entry, dict) or not _safe_path(entry.get('path')):
            raise _FetchError('invalid_response')
        path = entry['path']
        if path in seen or not isinstance(entry.get('sha'), str) or not _SHA.fullmatch(entry['sha']):
            raise _FetchError('invalid_response')
        seen.add(path)
        kind, mode = entry.get('type'), entry.get('mode')
        if kind == 'tree' and mode == '040000':
            continue
        if kind != 'blob' or mode not in ('100644', '100755'):
            skipped.append({'path': path, 'reason': 'symlink_submodule_or_unsupported_entry'})
            continue
        size = entry.get('size')
        if type(size) is not int or size < 0:
            raise _FetchError('invalid_response')
        priority = _selection_priority(path)
        if priority is None:
            skipped.append({'path': path, 'reason': 'excluded_path_or_type'})
        elif size > MAX_FILE_BYTES:
            skipped.append({'path': path, 'reason': 'file_too_large'})
        else:
            selected.append((priority, entry))
    selected.sort(key=lambda pair: pair[0])
    return tree_sha, [entry for _, entry in selected], skipped


def _decode_blob(blob, entry, budget):
    size, content = blob.get('size'), blob.get('content')
    if (blob.get('sha') != entry['sha'] or blob.get('encoding') != 'base64'
            or type(size) is not int or size < 0 or size != entry['size'] or size > MAX_FILE_BYTES
            or not isinstance(content, str) or not content.isascii() or len(content) > 28_000):
        raise _FetchError('invalid_response')
    compact = content.replace('\n', '').replace('\r', '')
    padding = (3 - size % 3) % 3
    if (len(compact) != 4 * ((size + 2) // 3) or len(compact) - len(compact.rstrip('=')) != padding):
        raise _FetchError('invalid_response')
    if budget.decoded + size > MAX_TEXT_BYTES:
        raise _FetchError('analysis_limit_reached')
    try:
        # GitHub wraps base64 with newlines, but no other whitespace is accepted.
        payload = base64.b64decode(compact, validate=True)
    except (binascii.Error, ValueError):
        raise _FetchError('invalid_response') from None
    expected_sha = hashlib.sha1(b'blob ' + str(size).encode('ascii') + b'\0' + payload, usedforsecurity=False).hexdigest()
    if len(payload) != size or expected_sha != entry['sha']:
        raise _FetchError('invalid_response')
    budget.decoded += len(payload)
    if budget.decoded > MAX_TEXT_BYTES:
        raise _FetchError('analysis_limit_reached')
    try:
        text = payload.decode('utf-8')
    except UnicodeError:
        return None, 'binary_or_non_utf8'
    if any(ord(char) < 32 and char not in '\t\r\n' for char in text) or payload.startswith((b'%PDF-', b'PK\x03\x04', b'\x89PNG', b'\x7fELF', b'MZ')):
        return None, 'binary_or_non_utf8'
    secret_assignment = any(any(word in match[1].lower() for word in ('password', 'secret', 'token', 'api_key', 'apikey', 'api-key', 'credential'))
                            for match in _SECRET_ASSIGNMENT.finditer(text))
    if _SECRET_TEXT.search(text) or secret_assignment:
        return None, 'possible_secret'
    return text, None


def _validated_identifier(repository):
    if not isinstance(repository, dict) or set(repository) != {'owner', 'repository', 'canonical_url'}:
        raise GitHubURLValidationError('Pass the repository identifier returned by validate_github_repository_url().')
    result = validate_github_repository_url(repository['canonical_url'])
    if result != repository:
        raise GitHubURLValidationError('Repository identifier does not match its validated canonical URL.')
    return result


def _fetch_repository(repository, budget):
    result: GitHubRepositoryEvidence = {'repository': repository, 'retrieval_status': 'retrieved', 'tree_sha': None,
                                        'files': [], 'skipped': [], 'http_status': None, 'untrusted': True}
    base = f"/repos/{repository['owner']}/{repository['repository']}"
    try:
        if budget.files >= MAX_FILES or budget.decoded >= MAX_TEXT_BYTES:
            raise _FetchError('analysis_limit_reached')
        metadata = _json_request(base, METADATA_RESPONSE_BYTES, budget)
        if type(metadata.get('private')) is not bool or not isinstance(metadata.get('visibility'), str):
            raise _FetchError('invalid_response')
        if metadata['private'] or metadata['visibility'] != 'public':
            raise _FetchError('private_repository')
        owner = metadata.get('owner')
        if (not isinstance(owner, dict) or not isinstance(owner.get('login'), str)
                or owner['login'].casefold() != repository['owner'].casefold()
                or not isinstance(metadata.get('name'), str)
                or metadata['name'].casefold() != repository['repository'].casefold()
                or not isinstance(metadata.get('full_name'), str)
                or metadata['full_name'].casefold() != f"{repository['owner']}/{repository['repository']}".casefold()):
            raise _FetchError('invalid_response')
        branch = metadata.get('default_branch')
        if branch is None:
            raise _FetchError('empty_repository')
        if not _safe_path(branch) or len(branch) > 200:
            raise _FetchError('invalid_response')
        tree = _json_request(base + '/git/trees/' + quote(branch, safe='') + '?recursive=1', TREE_RESPONSE_BYTES, budget)
        tree_sha, entries, skipped = _select_tree(tree)
        result['tree_sha'], result['skipped'] = tree_sha, skipped
        for entry in entries:
            if budget.files >= MAX_FILES or budget.decoded + entry['size'] > MAX_TEXT_BYTES:
                result['retrieval_status'] = 'partial_limit_reached'
                break
            budget.files += 1  # Count attempts, including rejected binary/secret-like files.
            blob_path = base + '/git/blobs/' + entry['sha']
            blob = _json_request(blob_path, BLOB_RESPONSE_BYTES, budget)
            text, reason = _decode_blob(blob, entry, budget)
            if reason:
                result['skipped'].append({'path': entry['path'], 'reason': reason})
                continue
            result['files'].append({'path': entry['path'], 'text': text,
                                    'source_reference': 'https://' + API_HOST + blob_path,
                                    'blob_sha': entry['sha'], 'decoded_bytes': entry['size'], 'untrusted': True})
        if result['retrieval_status'] == 'retrieved' and not result['files']:
            result['retrieval_status'] = 'no_supported_files'
    except _FetchError as error:
        result['retrieval_status'], result['http_status'] = error.status, error.http_status
        result['files'] = []  # Protocol/network failures never masquerade as successful evidence.
    return result


def fetch_github_repositories(repositories: list[GitHubRepository], *, deadline=None, _budget=None) -> list[GitHubRepositoryEvidence]:
    """Retrieve at most 3 public repos; 20 files/100 KB decoded bytes TOTAL.

    Invalid inputs raise GitHubURLValidationError before any request. Retrieval
    failures are structured statuses. Only explicit calls initiate network access.
    """
    if not isinstance(repositories, (list, tuple)) or len(repositories) > MAX_REPOSITORIES:
        raise GitHubURLValidationError('An analysis request accepts at most three validated repositories.')
    validated = [_validated_identifier(repository) for repository in repositories]
    if len({r['canonical_url'].casefold() for r in validated}) != len(validated):
        raise GitHubURLValidationError('Duplicate repositories are not supported in one analysis request.')
    end = time.monotonic() + ANALYSIS_SECONDS
    if deadline is not None:
        if type(deadline) not in (int, float) or not math.isfinite(deadline):
            raise ValueError('Invalid retrieval deadline.')
        end = min(end, deadline)  # A caller can shorten, never extend, the 30-second cap.
    budget = _budget if _budget is not None else _Budget(deadline=end)
    budget.deadline=min(budget.deadline,end)
    return [_fetch_repository(repository, budget) for repository in validated]


def fetch_github_repository(repository: GitHubRepository) -> GitHubRepositoryEvidence:
    """Single-repository convenience wrapper using the same bounded batch path."""
    return fetch_github_repositories([repository])[0]
