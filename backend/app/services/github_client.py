"""Read-only GitHub API client (REST + GraphQL).

* Only ever issues GET requests against public resources (plus the read-only GraphQL endpoint).
* Honours primary and secondary rate limits; never sleeps through a long reset window - it raises
  ``GitHubRateLimited`` so the job queue can defer the work instead.
* Tokens are held in memory only and never logged.
"""

import asyncio
import base64
import datetime as dt
import hashlib
import re
import time

import httpx

from app.config import get_settings
from app.logging_config import get_logger

log = get_logger("github")

API_VERSION = "2022-11-28"
USER_AGENT = "signal-atlas/0.1 (+read-only technology intelligence)"

_blocked_until: dict[str, float] = {}  # token fingerprint -> epoch seconds


class GitHubError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class GitHubNotFound(GitHubError):
    pass


class GitHubRateLimited(GitHubError):
    def __init__(self, reset_at: dt.datetime, message: str = "GitHub API rate limit reached"):
        super().__init__(message, 429)
        self.reset_at = reset_at


def parse_dt(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


_LAST_PAGE_RE = re.compile(r'[?&]page=(\d+)[^>]*>;\s*rel="last"')

REPO_METRICS_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    openIssues: issues(states: OPEN) { totalCount }
    closedIssues: issues(states: CLOSED) { totalCount }
    openPRs: pullRequests(states: OPEN) { totalCount }
    mergedPRs: pullRequests(states: MERGED) { totalCount }
    watchers { totalCount }
  }
}
"""


class GitHubClient:
    def __init__(self, token: str | None = None, *, base_url: str | None = None,
                 transport: httpx.AsyncBaseTransport | None = None, max_retries: int = 3):
        settings = get_settings()
        self._token = token if token is not None else settings.github_token
        self.base_url = (base_url or settings.github_api_url).rstrip("/")
        self._fingerprint = hashlib.sha256((self._token or "anonymous").encode()).hexdigest()[:12]
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": API_VERSION, "User-Agent": USER_AGENT}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        self._http = httpx.AsyncClient(base_url=self.base_url, headers=headers, timeout=20.0, transport=transport)
        self.max_retries = max_retries
        self.rate: dict = {}
        self.requests_made = 0
        self._sleep = asyncio.sleep

    @property
    def authenticated(self) -> bool:
        return bool(self._token)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "GitHubClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    # ------------------------------------------------------------------ core

    def _check_blocked(self) -> None:
        until = _blocked_until.get(self._fingerprint)
        if until and until > time.time():
            raise GitHubRateLimited(dt.datetime.fromtimestamp(until, dt.UTC))

    def _record_rate(self, resp: httpx.Response) -> None:
        h = resp.headers
        if "x-ratelimit-remaining" in h:
            self.rate = {
                "limit": int(h.get("x-ratelimit-limit", 0) or 0),
                "remaining": int(h.get("x-ratelimit-remaining", 0) or 0),
                "reset": int(h.get("x-ratelimit-reset", 0) or 0),
                "resource": h.get("x-ratelimit-resource"),
            }

    async def _request(self, method: str, path: str, *, params: dict | None = None, headers: dict | None = None,
                       json: dict | None = None, ok: tuple[int, ...] = (200,)) -> httpx.Response:
        self._check_blocked()
        attempt = 0
        while True:
            attempt += 1
            try:
                resp = await self._http.request(method, path, params=params, headers=headers, json=json)
            except httpx.HTTPError as exc:
                if attempt > self.max_retries:
                    raise GitHubError(f"GitHub request failed: {type(exc).__name__}") from exc
                await self._sleep(min(2 ** attempt, 15))
                continue
            self.requests_made += 1
            self._record_rate(resp)
            if resp.status_code in ok:
                return resp
            if resp.status_code == 404:
                raise GitHubNotFound(f"Not found: {path}", 404)
            if resp.status_code in (403, 429):
                remaining = resp.headers.get("x-ratelimit-remaining")
                retry_after = resp.headers.get("retry-after")
                if remaining == "0" or retry_after or "rate limit" in resp.text.lower():
                    reset = float(resp.headers.get("x-ratelimit-reset") or 0)
                    wait = float(retry_after) if retry_after else max(reset - time.time(), 60.0)
                    if wait <= 5 and attempt <= self.max_retries:
                        await self._sleep(wait)
                        continue
                    until = time.time() + wait
                    _blocked_until[self._fingerprint] = until
                    log.warning("github_rate_limited", path=path, wait_seconds=round(wait), authenticated=self.authenticated)
                    raise GitHubRateLimited(dt.datetime.fromtimestamp(until, dt.UTC))
                raise GitHubError(f"GitHub denied access to {path}", resp.status_code)
            if resp.status_code in (500, 502, 503, 504) and attempt <= self.max_retries:
                await self._sleep(min(2 ** attempt, 15))
                continue
            if resp.status_code == 401:
                raise GitHubError("GitHub rejected the configured credentials", 401)
            raise GitHubError(f"Unexpected GitHub response {resp.status_code} for {path}", resp.status_code)

    async def _get_json(self, path: str, params: dict | None = None):
        return (await self._request("GET", path, params=params)).json()

    # ------------------------------------------------------------------ repositories

    async def search_repositories(self, query: str, *, sort: str | None = "stars", order: str = "desc",
                                  per_page: int = 30, page: int = 1) -> dict:
        params: dict = {"q": query, "order": order, "per_page": min(per_page, 100), "page": page}
        if sort:
            params["sort"] = sort
        return await self._get_json("/search/repositories", params)

    async def get_repo(self, full_name: str, etag: str | None = None) -> tuple[dict | None, str | None]:
        """Return ``(data, etag)``; ``data`` is None when the repository is unchanged (HTTP 304)."""
        headers = {"If-None-Match": etag} if etag else None
        resp = await self._request("GET", f"/repos/{full_name}", headers=headers, ok=(200, 304))
        if resp.status_code == 304:
            return None, etag
        return resp.json(), resp.headers.get("etag")

    async def get_languages(self, full_name: str) -> dict[str, int]:
        return await self._get_json(f"/repos/{full_name}/languages")

    async def get_contributors(self, full_name: str, per_page: int = 30) -> list[dict]:
        resp = await self._request("GET", f"/repos/{full_name}/contributors", params={"per_page": per_page}, ok=(200, 204))
        return resp.json() if resp.status_code == 200 else []

    async def count_contributors(self, full_name: str) -> int | None:
        """Total contributors (including anonymous) read from pagination headers - one request."""
        try:
            resp = await self._request("GET", f"/repos/{full_name}/contributors", params={"per_page": 1, "anon": "true"}, ok=(200, 204))
        except GitHubError as exc:
            if isinstance(exc, GitHubRateLimited):
                raise
            return None  # GitHub refuses this listing for very large repositories
        if resp.status_code == 204:
            return 0
        match = _LAST_PAGE_RE.search(resp.headers.get("link", ""))
        return int(match.group(1)) if match else len(resp.json())

    async def get_releases(self, full_name: str, per_page: int = 30) -> list[dict]:
        return await self._get_json(f"/repos/{full_name}/releases", {"per_page": per_page})

    async def get_commit_activity(self, full_name: str) -> list[dict] | None:
        """52 weeks of commit counts. GitHub computes this lazily (HTTP 202); returns None if not ready."""
        for attempt in range(3):
            resp = await self._request("GET", f"/repos/{full_name}/stats/commit_activity", ok=(200, 202, 204))
            if resp.status_code == 200:
                data = resp.json()
                return data if isinstance(data, list) else None
            if resp.status_code == 204:
                return []
            if attempt < 2:
                await self._sleep(2.0)
        return None

    async def get_forks(self, full_name: str, per_page: int = 20) -> list[dict]:
        return await self._get_json(f"/repos/{full_name}/forks", {"per_page": per_page, "sort": "stargazers"})

    async def list_root(self, full_name: str) -> list[str]:
        try:
            data = await self._get_json(f"/repos/{full_name}/contents/")
        except GitHubNotFound:
            return []
        return [item["name"] for item in data if isinstance(item, dict) and item.get("type") == "file"]

    async def get_file(self, full_name: str, path: str, max_bytes: int = 400_000) -> str | None:
        try:
            data = await self._get_json(f"/repos/{full_name}/contents/{path}")
        except GitHubNotFound:
            return None
        if not isinstance(data, dict) or data.get("encoding") != "base64" or (data.get("size") or 0) > max_bytes:
            return None
        try:
            return base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")
        except ValueError:
            return None

    async def graphql_repo_metrics(self, full_name: str) -> dict | None:
        """Issue / PR totals in a single GraphQL call. Requires a token; returns None otherwise."""
        if not self._token:
            return None
        owner, _, name = full_name.partition("/")
        resp = await self._request("POST", "/graphql", json={"query": REPO_METRICS_QUERY, "variables": {"owner": owner, "name": name}})
        repo = (resp.json().get("data") or {}).get("repository")
        if not repo:
            return None
        return {
            "open_issues": repo["openIssues"]["totalCount"],
            "closed_issues": repo["closedIssues"]["totalCount"],
            "open_prs": repo["openPRs"]["totalCount"],
            "merged_prs": repo["mergedPRs"]["totalCount"],
            "watchers": repo["watchers"]["totalCount"],
        }

    # ------------------------------------------------------------------ users

    async def get_user(self, login: str) -> dict:
        return await self._get_json(f"/users/{login}")

    async def get_user_repos(self, login: str, per_page: int = 30) -> list[dict]:
        return await self._get_json(f"/users/{login}/repos", {"per_page": per_page, "sort": "pushed", "type": "owner"})

    async def get_authenticated_user(self) -> dict:
        return await self._get_json("/user")

    async def get_rate_limit(self) -> dict:
        return await self._get_json("/rate_limit")


def reset_rate_limit_state() -> None:
    _blocked_until.clear()
