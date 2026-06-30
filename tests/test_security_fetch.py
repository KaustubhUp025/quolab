"""S1 — fetch hardening: SSRF / token-leak / local-path guards.

These exercise the pure URL/host logic in ``indexer`` without any network or clone.
"""

from __future__ import annotations

import pytest

from quolab.config import Settings
from quolab.indexer import _clone_url, _remote_host, fetch_repo


def _settings(**kw) -> Settings:
    # Pin token empty so these stay deterministic regardless of any ambient .env.
    base = dict(embedder="hash", store="sqlite", fetch="git", gitlab_token="")
    base.update(kw)
    return Settings(**base)


# --- host allowlist (SSRF guard) ------------------------------------------

def test_default_allowlist_is_gitlab_url_host():
    s = _settings(gitlab_url="https://gitlab.com")
    assert s.fetch_allow_host_list == ["gitlab.com"]


def test_group_repo_resolves_to_allowed_gitlab_host():
    s = _settings(gitlab_url="https://gitlab.com")
    assert _clone_url(s, "group/repo") == "https://gitlab.com/group/repo.git"


def test_disallowed_remote_host_is_refused():
    s = _settings(gitlab_url="https://gitlab.com")
    with pytest.raises(ValueError, match="Refusing to fetch from host"):
        _clone_url(s, "https://evil.example.com/x.git")


def test_scp_style_git_url_host_is_checked():
    s = _settings(gitlab_url="https://gitlab.com")
    assert _remote_host("git@gitlab.com:group/repo.git") == "gitlab.com"
    with pytest.raises(ValueError, match="Refusing to fetch from host"):
        _clone_url(s, "git@evil.example.com:group/repo.git")


def test_wildcard_allows_any_host():
    s = _settings(gitlab_url="https://gitlab.com", fetch_allow_hosts="*")
    assert _clone_url(s, "https://anything.example.org/x.git").startswith("https://anything")


def test_explicit_allowlist_overrides_default():
    s = _settings(gitlab_url="https://gitlab.com", fetch_allow_hosts="git.acme.io")
    assert _clone_url(s, "https://git.acme.io/a/b.git").startswith("https://git.acme.io")
    with pytest.raises(ValueError):
        _clone_url(s, "https://gitlab.com/a/b.git")


# --- token never leaks to a non-allow-listed host -------------------------

def test_token_injected_only_for_allowed_https_host():
    s = _settings(gitlab_url="https://gitlab.com", gitlab_token="secret-pat")
    url = _clone_url(s, "group/repo")
    assert "oauth2:secret-pat@gitlab.com" in url


def test_token_never_reaches_disallowed_host():
    s = _settings(gitlab_url="https://gitlab.com", gitlab_token="secret-pat")
    # The guard raises before any credential is attached.
    with pytest.raises(ValueError):
        _clone_url(s, "https://evil.example.com/x.git")


# --- local-path passthrough gate ------------------------------------------

def test_local_path_indexing_allowed_by_default(tmp_path):
    s = _settings(repo_cache=str(tmp_path / "repos"))
    assert fetch_repo(s, str(tmp_path), "HEAD") == tmp_path


def test_local_path_indexing_blocked_when_disabled(tmp_path):
    s = _settings(repo_cache=str(tmp_path / "repos"), allow_local_path=False)
    with pytest.raises(ValueError, match="Refusing to index local path"):
        fetch_repo(s, str(tmp_path), "HEAD")
