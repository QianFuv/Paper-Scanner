"""
Fill and validate journal metadata using the BrowZine API.

This script merges the previous fill and validation workflows:
- Fill missing ISSN values by journal ID
- Fill missing journal IDs by ISSN with fallback libraries
- Validate journals for accessible issues and articles
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

DEFAULT_LIBRARY_ID = "3050"
FALLBACK_LIBRARIES = ["215", "866", "72", "853", "554", "371", "230"]
TOKEN_EXPIRY_BUFFER = 300


class BrowZineAPIClient:
    """
    BrowZine API client for retrieving journal information.

    Args:
        library_id: Default library ID for requests.
        timeout: HTTP request timeout in seconds.
    """

    def __init__(self, library_id: str = DEFAULT_LIBRARY_ID, timeout: int = 10) -> None:
        """
        Initialize the API client.

        Args:
            library_id: Default library ID for requests.
            timeout: HTTP request timeout in seconds.
        """
        self.base_url = "https://api.thirdiron.com/v2"
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

        url = f"{self.base_url}/api-tokens"
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

    async def search_by_issn(
        self, issn: str, try_fallback: bool = True
    ) -> tuple[dict[str, Any] | None, str | None]:
        """
        Search for a journal by ISSN across multiple libraries.

        Args:
            issn: Journal ISSN (with or without hyphen).
            try_fallback: Whether to try fallback libraries if not found.

        Returns:
            Tuple of (journal info dict, library_id) or (None, None).
        """
        libraries_to_try = [self.default_library_id]
        if try_fallback:
            libraries_to_try.extend(FALLBACK_LIBRARIES)

        for library_id in libraries_to_try:
            url = f"{self.base_url}/libraries/{library_id}/search"
            params = {"client": "bzweb", "query": issn}
            data = await self._get_json(
                url,
                library_id,
                params,
                accept="application/json, text/javascript, */*; q=0.01",
            )
            if data and data.get("data"):
                return data["data"][0], library_id

        return None, None

    async def get_journal_info(
        self, journal_id: str, library_id: str | None = None
    ) -> dict[str, Any] | None:
        """
        Get journal information by journal ID.

        Args:
            journal_id: BrowZine journal ID.
            library_id: Library ID to query. If None, uses default.

        Returns:
            Journal information dictionary or None if not found.
        """
        lib_id = library_id or self.default_library_id
        url = f"{self.base_url}/libraries/{lib_id}/journals/{journal_id}"
        params = {"client": "bzweb"}
        data = await self._get_json(url, lib_id, params)
        if data and "data" in data:
            return data["data"]
        return None

    async def get_current_issue(
        self, journal_id: str, library_id: str | None = None
    ) -> dict[str, Any] | None:
        """
        Get current issue for a journal.

        Args:
            journal_id: BrowZine journal ID.
            library_id: Library ID to query. If None, uses default.

        Returns:
            Issue information or None if not available.
        """
        lib_id = library_id or self.default_library_id
        url = f"{self.base_url}/libraries/{lib_id}/journals/{journal_id}/issues/current"
        params = {"client": "bzweb"}
        data = await self._get_json(url, lib_id, params)
        if not data:
            return None
        issues = data.get("issues", [])
        if issues:
            return issues[0]
        return None

    async def get_articles_from_issue(
        self, issue_id: int, library_id: str | None = None
    ) -> list[dict[str, Any]] | None:
        """
        Get articles from a specific issue.

        Args:
            issue_id: BrowZine issue ID.
            library_id: Library ID to query. If None, uses default.

        Returns:
            List of articles or None if not available.
        """
        lib_id = library_id or self.default_library_id
        url = f"{self.base_url}/libraries/{lib_id}/issues/{issue_id}/articles"
        params = {"client": "bzweb"}
        data = await self._get_json(url, lib_id, params)
        if not data:
            return None
        articles = data.get("data", [])
        return articles if articles else None

    async def aclose(self) -> None:
        """
        Close the underlying HTTP client.

        Returns:
            None.
        """
        await self._client.aclose()


def ensure_library_column(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """
    Ensure all rows have a library column with default value 3050.

    Args:
        rows: List of CSV row dictionaries.

    Returns:
        List of rows with library column added if missing.
    """
    if not rows:
        return rows

    if "library" not in rows[0]:
        for row in rows:
            row["library"] = DEFAULT_LIBRARY_ID

    for row in rows:
        if not row.get("library"):
            row["library"] = DEFAULT_LIBRARY_ID

    return rows


def load_csv_rows(csv_path: Path) -> list[dict[str, str]]:
    """
    Load CSV rows.

    Args:
        csv_path: Path to CSV file.

    Returns:
        List of CSV row dictionaries.
    """
    with open(csv_path, encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader)


def write_csv_rows(csv_path: Path, rows: list[dict[str, str]]) -> None:
    """
    Write CSV rows back to the file.

    Args:
        csv_path: Path to CSV file.
        rows: CSV rows to write.

    Returns:
        None.
    """
    if not rows:
        return
    with open(csv_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


async def fill_issn_by_id(client: BrowZineAPIClient, csv_path: Path) -> None:
    """
    Fill ISSN field using existing journal IDs.

    Args:
        client: BrowZine API client instance.
        csv_path: Path to CSV file.

    Returns:
        None.
    """
    print(f"\nProcessing {csv_path.name}...")

    rows = ensure_library_column(load_csv_rows(csv_path))
    if not rows:
        print(f"  ✗ Empty file: {csv_path.name}")
        return

    updated_count = 0
    for i, row in enumerate(rows, start=1):
        if row.get("id") and not row.get("issn"):
            journal_id = row["id"]
            title = row.get("title", "Unknown")
            lib_id = row.get("library", DEFAULT_LIBRARY_ID)

            print(
                f"  [{i}/{len(rows)}] Fetching ISSN for {title} "
                f"(ID: {journal_id}, Lib: {lib_id})..."
            )

            journal_info = await client.get_journal_info(journal_id, lib_id)
            if journal_info:
                attributes = journal_info.get("attributes", {})
                issn = attributes.get("issn")
                if issn:
                    row["issn"] = issn
                    updated_count += 1
                    print(f"    ✓ Found ISSN: {issn}")
                else:
                    print("    ✗ ISSN not found")
            else:
                print("    ✗ Journal not found")

            await asyncio.sleep(0.5)

    write_csv_rows(csv_path, rows)
    print(f"  Updated {updated_count} ISSNs")


async def fill_id_by_issn(client: BrowZineAPIClient, csv_path: Path) -> None:
    """
    Fill journal ID field using existing ISSNs.

    Args:
        client: BrowZine API client instance.
        csv_path: Path to CSV file.

    Returns:
        None.
    """
    print(f"\nProcessing {csv_path.name}...")

    rows = ensure_library_column(load_csv_rows(csv_path))
    if not rows:
        print(f"  ✗ Empty file: {csv_path.name}")
        return

    updated_count = 0
    for i, row in enumerate(rows, start=1):
        if row.get("issn") and not row.get("id"):
            issn = row["issn"]
            title = row.get("title", "Unknown")
            print(f"  [{i}/{len(rows)}] Searching for {title} (ISSN: {issn})...")

            journal, lib_id = await client.search_by_issn(issn, try_fallback=True)
            if journal and lib_id:
                journal_id = journal.get("id")
                if journal_id:
                    row["id"] = str(int(journal_id))
                    row["library"] = lib_id
                    updated_count += 1
                    print(f"    ✓ Found ID: {journal_id} (Lib: {lib_id})")
                else:
                    print("    ✗ ID not found in response")
            else:
                print("    ✗ Journal not found in any library")

            await asyncio.sleep(0.5)

    write_csv_rows(csv_path, rows)
    print(f"  Updated {updated_count} journal IDs")


async def process_fill_csv(client: BrowZineAPIClient, csv_path: Path) -> None:
    """
    Process a single CSV file to fill missing metadata.

    Args:
        client: BrowZine API client instance.
        csv_path: Path to CSV file.

    Returns:
        None.
    """
    if not csv_path.exists():
        print(f"  ✗ File not found: {csv_path}")
        return

    rows = load_csv_rows(csv_path)
    if not rows:
        print(f"  ✗ Empty file: {csv_path.name}")
        return

    rows = ensure_library_column(rows)

    has_id = "id" in rows[0]
    has_issn = "issn" in rows[0]

    has_missing_issn = any(
        row.get("id") and (not has_issn or not row.get("issn")) for row in rows
    )
    has_missing_id = any(
        row.get("issn") and (not has_id or not row.get("id")) for row in rows
    )

    if has_missing_issn:
        await fill_issn_by_id(client, csv_path)

    if has_missing_id:
        await fill_id_by_issn(client, csv_path)

    if not has_missing_issn and not has_missing_id:
        print(f"  ✓ {csv_path.name}: All metadata already complete")


async def validate_single_journal(
    client: BrowZineAPIClient, journal_id: str, library_id: str
) -> tuple[bool, str]:
    """
    Validate a single journal in a specific library.

    Args:
        client: BrowZine API client instance.
        journal_id: BrowZine journal ID.
        library_id: Library ID to validate in.

    Returns:
        Tuple of (is_valid, reason).
    """
    journal_info = await client.get_journal_info(journal_id, library_id)
    if not journal_info:
        return False, "Journal not found"

    attributes = journal_info.get("attributes", {})
    available = attributes.get("available", False)
    if not available:
        return False, "Journal not available"

    current_issue = await client.get_current_issue(journal_id, library_id)
    if not current_issue:
        return False, "No current issue found"

    issue_id = current_issue.get("id")
    if not issue_id:
        return False, "Issue has no ID"

    articles = await client.get_articles_from_issue(int(issue_id), library_id)
    if not articles:
        return False, "No articles found in current issue"

    has_actual_content = any(
        article.get("attributes", {}).get("abstract")
        or article.get("attributes", {}).get("fullTextFile")
        for article in articles
    )
    if not has_actual_content:
        return False, "Articles have no actual content"

    return True, "Valid"


async def validate_journal(
    client: BrowZineAPIClient, journal_id: str, issn: str, library_id: str | None = None
) -> tuple[bool, str, str | None, str | None]:
    """
    Validate that a journal has accessible issues and articles.

    Args:
        client: BrowZine API client instance.
        journal_id: BrowZine journal ID.
        issn: Journal ISSN for fallback search.
        library_id: Library ID to try first.

    Returns:
        Tuple of (is_valid, reason, working_library_id, working_journal_id).
    """
    lib_id = library_id or client.default_library_id

    is_valid, reason = await validate_single_journal(client, journal_id, lib_id)
    if is_valid:
        return True, reason, lib_id, journal_id

    if not issn:
        return False, "No ISSN for fallback search", None, None

    for fallback_lib in FALLBACK_LIBRARIES:
        journal, _ = await client.search_by_issn(issn, try_fallback=True)
        if not journal:
            continue

        fallback_id = journal.get("id")
        if not fallback_id:
            continue

        is_valid, reason = await validate_single_journal(
            client, str(int(fallback_id)), fallback_lib
        )
        if is_valid:
            return True, reason, fallback_lib, str(int(fallback_id))

    return False, "No accessible content in any library", None, None


async def validate_and_filter_csv(client: BrowZineAPIClient, csv_path: Path) -> None:
    """
    Validate journals in CSV and remove inaccessible ones.

    Args:
        client: BrowZine API client instance.
        csv_path: Path to CSV file.

    Returns:
        None.
    """
    print(f"\n{'=' * 60}")
    print(f"Processing {csv_path.name}")
    print(f"{'=' * 60}")

    rows = ensure_library_column(load_csv_rows(csv_path))
    if not rows:
        print(f"  ✗ Empty file: {csv_path.name}")
        return

    initial_count = len(rows)
    valid_rows: list[dict[str, str]] = []
    removed_count = 0

    for i, row in enumerate(rows, start=1):
        journal_id = row.get("id")
        if not journal_id:
            title = row.get("title", "Unknown")
            print(f"  [{i}/{len(rows)}] ✗ {title}: No journal ID - REMOVED")
            removed_count += 1
            continue

        title = row.get("title", "Unknown")
        issn = row.get("issn", "")
        lib_id = row.get("library", DEFAULT_LIBRARY_ID)

        print(
            f"  [{i}/{len(rows)}] Validating {title} "
            f"(ID: {journal_id}, Lib: {lib_id})..."
        )

        is_valid, reason, working_lib, working_id = await validate_journal(
            client, journal_id, issn, lib_id
        )

        if is_valid:
            if working_lib and working_id:
                if working_lib != lib_id or working_id != journal_id:
                    row["library"] = working_lib
                    row["id"] = working_id
                    print(
                        f"    ✓ Valid - {reason} "
                        f"(switched to Lib: {working_lib}, ID: {working_id})"
                    )
                else:
                    print(f"    ✓ Valid - {reason}")
            valid_rows.append(row)
        else:
            removed_count += 1
            print(f"    ✗ REMOVED - {reason}")

        await asyncio.sleep(0.5)

    if valid_rows:
        write_csv_rows(csv_path, valid_rows)

    print(f"\n{'=' * 60}")
    print(f"Summary for {csv_path.name}:")
    print(f"  Initial count: {initial_count}")
    print(f"  Valid journals: {len(valid_rows)}")
    print(f"  Removed: {removed_count}")
    print(f"  Retention rate: {len(valid_rows) / initial_count * 100:.1f}%")
    print(f"{'=' * 60}")


def select_csv_files(data_meta_dir: Path, filename: str | None) -> list[Path]:
    """
    Select CSV files to process.

    Args:
        data_meta_dir: Directory containing CSV files.
        filename: Optional specific filename.

    Returns:
        List of CSV file paths.
    """
    if filename:
        csv_file = data_meta_dir / filename
        if not csv_file.exists():
            print(f"✗ File not found: {csv_file}")
            return []
        return [csv_file]
    return sorted(data_meta_dir.glob("*.csv"))


async def async_main(args: argparse.Namespace) -> None:
    """
    Async entrypoint for metadata workflow.

    Args:
        args: Parsed CLI arguments.

    Returns:
        None.
    """
    project_root = Path(__file__).parent.parent.parent
    data_meta_dir = project_root / "data" / "meta"

    if not data_meta_dir.exists():
        print(f"✗ Directory not found: {data_meta_dir}")
        return

    csv_files = select_csv_files(data_meta_dir, args.file)
    if not csv_files:
        print(f"✗ No CSV files found in {data_meta_dir}")
        return

    client = BrowZineAPIClient(library_id=DEFAULT_LIBRARY_ID, timeout=args.timeout)

    print("=" * 60)
    print("BrowZine Journal Metadata Tool")
    print("=" * 60)
    print(f"\nFound {len(csv_files)} CSV file(s) to process")

    try:
        if args.mode in {"fill", "both"}:
            print("\nRunning fill workflow...\n")
            for csv_file in csv_files:
                await process_fill_csv(client, csv_file)

        if args.mode in {"validate", "both"}:
            print("\nRunning validation workflow...\n")
            for csv_file in csv_files:
                await validate_and_filter_csv(client, csv_file)
    finally:
        await client.aclose()

    print("\n" + "=" * 60)
    print("✓ All files processed successfully!")
    print("=" * 60)


def main() -> None:
    """
    Main function to fill and validate journal metadata in data/meta.
    """
    parser = argparse.ArgumentParser(
        description="Fill and validate journal metadata using BrowZine API"
    )
    parser.add_argument(
        "--file",
        "-f",
        type=str,
        help="Specific CSV file to process (filename only, e.g., 'utd24.csv')",
    )
    parser.add_argument(
        "--mode",
        "-m",
        type=str,
        choices=["fill", "validate", "both"],
        default="both",
        help="Workflow mode: fill, validate, or both",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="HTTP request timeout in seconds",
    )
    args = parser.parse_args()
    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
