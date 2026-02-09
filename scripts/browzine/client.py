"""BrowZine API client implementation."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any

import httpx

from scripts.shared.constants import (
    BROWZINE_BASE_URL,
    DEFAULT_LIBRARY_ID,
    TOKEN_EXPIRY_BUFFER,
)
from scripts.shared.converters import to_int


class BrowZineAPIClient:
    """
    Client for BrowZine API access with token caching.

    Args:
        library_id: Default library ID for requests.
        timeout: HTTP request timeout in seconds.
    """

    def __init__(self, library_id: str = DEFAULT_LIBRARY_ID, timeout: int = 20) -> None:
        """
        Initialize the API client.

        Args:
            library_id: Default library ID for requests.
            timeout: HTTP request timeout in seconds.
        """
        self.default_library_id = library_id
        self.timeout = timeout
        self._tokens: dict[str, str] = {}
        self._token_expiry: dict[str, float] = {}
        self._lock = asyncio.Lock()
        self._client = httpx.AsyncClient(timeout=self.timeout)

    def _parse_expires_at(self, value: Any) -> float | None:
        """
        Parse expires_at string into a Unix timestamp.

        Args:
            value: expires_at value from the API response.

        Returns:
            Unix timestamp in seconds or None when parsing fails.
        """
        if not value or not isinstance(value, str):
            return None
        try:
            normalized = value.replace("Z", "+00:00")
            return datetime.fromisoformat(normalized).timestamp()
        except ValueError:
            return None

    def _token_is_valid(self, library_id: str) -> bool:
        """
        Determine whether a cached token is still valid.

        Args:
            library_id: Library ID for the token.

        Returns:
            True if token is valid or expiry is unknown, otherwise False.
        """
        expires_at = self._token_expiry.get(library_id)
        if expires_at is None:
            return True
        return expires_at - time.time() > TOKEN_EXPIRY_BUFFER

    async def _get_token(self, library_id: str, refresh: bool = False) -> str | None:
        """
        Request or reuse a token for the given library.

        Args:
            library_id: Library ID to authenticate.
            refresh: Whether to force refresh the token.

        Returns:
            Token string or None when authentication fails.
        """
        async with self._lock:
            if (
                not refresh
                and library_id in self._tokens
                and self._token_is_valid(library_id)
            ):
                return self._tokens[library_id]

        url = f"{BROWZINE_BASE_URL}/api-tokens"
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/json; charset=UTF-8",
            "Referer": "https://browzine.com/",
        }
        payload = {
            "libraryId": library_id,
            "returnPreproxy": True,
            "client": "bzweb",
            "forceAuth": False,
        }

        try:
            response = await self._client.post(url, headers=headers, json=payload)
            if response.status_code == 200:
                data = response.json()
                token_payload = data["api-tokens"][0]
                token = token_payload["id"]
                expires_at = self._parse_expires_at(token_payload.get("expires_at"))
                async with self._lock:
                    self._tokens[library_id] = token
                    if expires_at is not None:
                        self._token_expiry[library_id] = expires_at
                    elif library_id in self._token_expiry:
                        self._token_expiry.pop(library_id)
                return token
        except httpx.RequestError:
            return None
        return None

    async def _get_json(
        self,
        url: str,
        library_id: str,
        params: dict[str, Any],
        accept: str = "application/vnd.api+json",
        retries: int = 2,
    ) -> dict[str, Any] | None:
        """
        Perform an authenticated GET request and parse JSON.

        Args:
            url: Request URL.
            library_id: Library ID for authentication.
            params: Query parameters.
            accept: Accept header value.
            retries: Number of retries for transient errors.

        Returns:
            Parsed JSON dictionary or None when the request fails.
        """
        token = await self._get_token(library_id)
        if not token:
            return None

        headers = {
            "Accept": accept,
            "Authorization": f"Bearer {token}",
            "Referer": "https://browzine.com/",
        }

        for attempt in range(retries + 1):
            try:
                response = await self._client.get(url, headers=headers, params=params)
            except httpx.RequestError:
                if attempt < retries:
                    await asyncio.sleep(1 + attempt)
                    continue
                return None

            if response.status_code == 401 and attempt < retries:
                token = await self._get_token(library_id, refresh=True)
                if not token:
                    return None
                headers["Authorization"] = f"Bearer {token}"
                continue

            if response.status_code == 200:
                return response.json()

            if response.status_code in {429, 500, 502, 503, 504} and attempt < retries:
                await asyncio.sleep(1 + attempt)
                continue

            return None

        return None

    async def get_journal_info(
        self, journal_id: int, library_id: str
    ) -> dict[str, Any] | None:
        """
        Fetch journal metadata for a journal ID.

        Args:
            journal_id: BrowZine journal ID.
            library_id: Library ID for the request.

        Returns:
            Journal JSON payload or None when unavailable.
        """
        url = f"{BROWZINE_BASE_URL}/libraries/{library_id}/journals/{journal_id}"
        params = {"client": "bzweb"}
        data = await self._get_json(url, library_id, params)
        if data and "data" in data:
            return data["data"]
        return None

    async def search_by_issn(self, issn: str, library_id: str) -> dict[str, Any] | None:
        """
        Search for a journal by ISSN within a specific library.

        Args:
            issn: Journal ISSN (with or without hyphen).
            library_id: Library ID for the request.

        Returns:
            Journal payload or None when unavailable.
        """
        url = f"{BROWZINE_BASE_URL}/libraries/{library_id}/search"
        params = {"client": "bzweb", "query": issn}
        data = await self._get_json(
            url,
            library_id,
            params,
            accept="application/json, text/javascript, */*; q=0.01",
        )
        if data and data.get("data"):
            return data["data"][0]
        return None

    async def get_current_issue(
        self, journal_id: int, library_id: str
    ) -> dict[str, Any] | None:
        """
        Fetch the current issue for a journal.

        Args:
            journal_id: BrowZine journal ID.
            library_id: Library ID for the request.

        Returns:
            Issue payload or None when unavailable.
        """
        url = (
            f"{BROWZINE_BASE_URL}/libraries/{library_id}/journals/{journal_id}/"
            "issues/current"
        )
        params = {"client": "bzweb"}
        data = await self._get_json(url, library_id, params)
        if not data:
            return None
        issues = data.get("issues", [])
        if issues:
            return issues[0]
        return None

    async def get_publication_years(
        self, journal_id: int, library_id: str
    ) -> list[int] | None:
        """
        Fetch available publication years for a journal.

        Args:
            journal_id: BrowZine journal ID.
            library_id: Library ID for the request.

        Returns:
            List of publication years or None when unavailable.
        """
        url = (
            f"{BROWZINE_BASE_URL}/libraries/{library_id}/journals/{journal_id}/"
            "publication-years"
        )
        params = {"client": "bzweb"}
        data = await self._get_json(url, library_id, params)
        if not data:
            return None
        years = []
        for item in data.get("publicationYears", []):
            year = to_int(item.get("id"))
            if year:
                years.append(year)
        return years

    async def get_issues_by_year(
        self, journal_id: int, library_id: str, year: int
    ) -> list[dict[str, Any]] | None:
        """
        Fetch issues for a journal year.

        Args:
            journal_id: BrowZine journal ID.
            library_id: Library ID for the request.
            year: Publication year.

        Returns:
            List of issue payloads or None when unavailable.
        """
        url = f"{BROWZINE_BASE_URL}/libraries/{library_id}/journals/{journal_id}/issues"
        params = {"client": "bzweb", "publication-year": str(year)}
        data = await self._get_json(url, library_id, params)
        if not data:
            return None
        return data.get("issues", [])

    async def get_articles_from_issue(
        self, issue_id: int, library_id: str
    ) -> list[dict[str, Any]] | None:
        """
        Fetch all articles for an issue.

        Args:
            issue_id: BrowZine issue ID.
            library_id: Library ID for the request.

        Returns:
            List of article payloads or None when unavailable.
        """
        url = f"{BROWZINE_BASE_URL}/libraries/{library_id}/issues/{issue_id}/articles"
        params = {"client": "bzweb"}
        data = await self._get_json(url, library_id, params)
        if not data:
            return None
        return data.get("data", [])

    async def get_articles_in_press(
        self, journal_id: int, library_id: str
    ) -> list[dict[str, Any]]:
        """
        Fetch all in-press articles for a journal.

        Args:
            journal_id: BrowZine journal ID.
            library_id: Library ID for the request.

        Returns:
            List of in-press article payloads.
        """
        url = (
            f"{BROWZINE_BASE_URL}/libraries/{library_id}/journals/{journal_id}/"
            "articles-in-press"
        )
        cursor = None
        results: list[dict[str, Any]] = []
        seen_cursors: set[str] = set()
        page_count = 0
        max_pages = 1000

        while True:
            params: dict[str, Any] = {"client": "bzweb"}
            if cursor:
                if cursor in seen_cursors:
                    break
                seen_cursors.add(cursor)
                params["cursor"] = cursor
            data = await self._get_json(url, library_id, params)
            if not data:
                break
            results.extend(data.get("data", []))
            cursor = data.get("meta", {}).get("cursor", {}).get("next")
            page_count += 1
            if page_count >= max_pages:
                break
            if not cursor:
                break

        return results

    async def aclose(self) -> None:
        """
        Close the underlying HTTP client.

        Returns:
            None.
        """
        await self._client.aclose()
