"""
Script to validate journal access and filter out inaccessible journals.

This script validates that journals can:
- Be accessed via BrowZine API
- Return actual issues
- Return actual articles (not just external redirects)

Journals that fail validation are removed from the CSV files.
Supports multiple library IDs with automatic fallback.
When switching libraries, both library and id columns are updated.
"""

import argparse
import csv
import time
from pathlib import Path
from typing import Any

import requests


class BrowZineValidator:
    """
    Validator for checking journal accessibility via BrowZine API.
    Supports multiple libraries with automatic fallback.
    """

    FALLBACK_LIBRARIES = ["215", "866", "72", "853", "554", "371", "230"]

    def __init__(self, library_id: str = "3050") -> None:
        self.base_url = "https://api.thirdiron.com/v2"
        self.library_id = library_id
        self.token: str | None = None
        self.tokens: dict[str, str] = {}

    def get_api_token(self, library_id: str | None = None) -> bool:
        """
        Obtain API token for authenticated requests.

        Args:
            library_id: Library ID to get token for. If None, uses self.library_id.

        Returns:
            True if token was successfully retrieved, False otherwise.
        """
        lib_id = library_id or self.library_id

        if lib_id in self.tokens:
            self.token = self.tokens[lib_id]
            self.library_id = lib_id
            return True

        url = f"{self.base_url}/api-tokens"
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/json; charset=UTF-8",
            "Referer": "https://browzine.com/",
        }
        payload = {
            "libraryId": lib_id,
            "returnPreproxy": True,
            "client": "bzweb",
            "forceAuth": False,
        }

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            if response.status_code == 200:
                data = response.json()
                token = data["api-tokens"][0]["id"]
                self.tokens[lib_id] = token
                self.token = token
                self.library_id = lib_id
                return True
            return False
        except Exception:
            return False

    def get_headers(self) -> dict[str, str]:
        """
        Get common headers for authenticated API requests.

        Returns:
            Dictionary of HTTP headers.
        """
        return {
            "Accept": "application/vnd.api+json",
            "Authorization": f"Bearer {self.token}",
            "Referer": "https://browzine.com/",
        }

    def search_by_issn(self, issn: str, library_id: str) -> dict[str, Any] | None:
        """
        Search for a journal by ISSN in a specific library.

        Args:
            issn: Journal ISSN (with or without hyphen).
            library_id: Library ID to search in.

        Returns:
            Journal information dictionary or None if not found.
        """
        if not self.get_api_token(library_id):
            return None

        url = f"{self.base_url}/libraries/{library_id}/search"
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Authorization": f"Bearer {self.token}",
            "Referer": "https://browzine.com/",
        }
        params = {"client": "bzweb", "query": issn}

        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get("data"):
                    return data["data"][0]
            return None
        except Exception:
            return None

    def get_journal_info(
        self, journal_id: str, library_id: str | None = None
    ) -> dict[str, Any] | None:
        """
        Get journal information by journal ID.

        Args:
            journal_id: BrowZine journal ID.
            library_id: Library ID to query. If None, uses self.library_id.

        Returns:
            Journal information dictionary or None if not found.
        """
        lib_id = library_id or self.library_id

        if not self.get_api_token(lib_id):
            return None

        url = f"{self.base_url}/libraries/{lib_id}/journals/{journal_id}"
        params = {"client": "bzweb"}

        try:
            response = requests.get(
                url, headers=self.get_headers(), params=params, timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                if "data" in data:
                    return data["data"]
            return None
        except Exception:
            return None

    def get_current_issue(
        self, journal_id: str, library_id: str | None = None
    ) -> dict[str, Any] | None:
        """
        Get current issue for a journal.

        Args:
            journal_id: BrowZine journal ID.
            library_id: Library ID to query. If None, uses self.library_id.

        Returns:
            Issue information or None if not available.
        """
        lib_id = library_id or self.library_id

        if not self.get_api_token(lib_id):
            return None

        url = f"{self.base_url}/libraries/{lib_id}/journals/{journal_id}/issues/current"
        params = {"client": "bzweb"}

        try:
            response = requests.get(
                url, headers=self.get_headers(), params=params, timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                issues = data.get("issues", [])
                if issues and len(issues) > 0:
                    return issues[0]
            return None
        except Exception:
            return None

    def get_articles_from_issue(
        self, issue_id: int, library_id: str | None = None
    ) -> list[dict[str, Any]] | None:
        """
        Get articles from a specific issue.

        Args:
            issue_id: BrowZine issue ID.
            library_id: Library ID to query. If None, uses self.library_id.

        Returns:
            List of articles or None if not available.
        """
        lib_id = library_id or self.library_id

        if not self.get_api_token(lib_id):
            return None

        url = f"{self.base_url}/libraries/{lib_id}/issues/{issue_id}/articles"
        params = {"client": "bzweb"}

        try:
            response = requests.get(
                url, headers=self.get_headers(), params=params, timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                articles = data.get("data", [])
                return articles if articles else None
            return None
        except Exception:
            return None

    def validate_single_journal(
        self, journal_id: str, library_id: str
    ) -> tuple[bool, str]:
        """
        Validate a single journal in a specific library.

        Args:
            journal_id: BrowZine journal ID.
            library_id: Library ID to validate in.

        Returns:
            Tuple of (is_valid, reason).
        """
        journal_info = self.get_journal_info(journal_id, library_id)
        if not journal_info:
            return False, "Journal not found"

        attributes = journal_info.get("attributes", {})
        available = attributes.get("available", False)
        if not available:
            return False, "Journal not available"

        current_issue = self.get_current_issue(journal_id, library_id)
        if not current_issue:
            return False, "No current issue found"

        issue_id = current_issue.get("id")
        if not issue_id:
            return False, "Issue has no ID"

        articles = self.get_articles_from_issue(issue_id, library_id)
        if not articles:
            return False, "No articles found in current issue"

        has_actual_content = False
        for article in articles:
            attrs = article.get("attributes", {})
            if attrs.get("abstract") or attrs.get("fullTextFile"):
                has_actual_content = True
                break

        if not has_actual_content:
            return False, "Articles have no actual content"

        return True, "Valid"

    def validate_journal(
        self, journal_id: str, issn: str, library_id: str | None = None
    ) -> tuple[bool, str, str | None, str | None]:
        """
        Validate that a journal has accessible issues and articles.
        Try fallback libraries if initial validation fails.

        Args:
            journal_id: BrowZine journal ID.
            issn: Journal ISSN for fallback search.
            library_id: Library ID to try first.

        Returns:
            Tuple of (is_valid, reason, working_library_id, working_journal_id).
        """
        lib_id = library_id or self.library_id

        is_valid, reason = self.validate_single_journal(journal_id, lib_id)
        if is_valid:
            return True, reason, lib_id, journal_id

        if not issn:
            return False, "No ISSN for fallback search", None, None

        for fallback_lib in self.FALLBACK_LIBRARIES:
            journal = self.search_by_issn(issn, fallback_lib)
            if not journal:
                continue

            fallback_id = journal.get("id")
            if not fallback_id:
                continue

            is_valid, reason = self.validate_single_journal(
                str(int(fallback_id)), fallback_lib
            )
            if is_valid:
                return True, reason, fallback_lib, str(int(fallback_id))

        return False, "No accessible content in any library", None, None


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
            row["library"] = "3050"

    for row in rows:
        if not row.get("library"):
            row["library"] = "3050"

    return rows


def validate_and_filter_csv(validator: BrowZineValidator, csv_path: Path) -> None:
    """
    Validate journals in CSV and remove inaccessible ones.

    Args:
        validator: BrowZine validator instance.
        csv_path: Path to CSV file.
    """
    print(f"\n{'=' * 60}")
    print(f"Processing {csv_path.name}")
    print(f"{'=' * 60}")

    rows = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    rows = ensure_library_column(rows)

    initial_count = len(rows)
    valid_rows = []
    removed_count = 0

    for i, row in enumerate(rows, start=1):
        if not row["id"]:
            print(f"  [{i}/{len(rows)}] ✗ {row['title']}: No journal ID - REMOVED")
            removed_count += 1
            continue

        journal_id = row["id"]
        title = row["title"]
        issn = row.get("issn", "")
        lib_id = row.get("library", "3050")

        print(
            f"  [{i}/{len(rows)}] Validating {title} "
            f"(ID: {journal_id}, Lib: {lib_id})..."
        )

        is_valid, reason, working_lib, working_id = validator.validate_journal(
            journal_id, issn, lib_id
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

        time.sleep(0.5)

    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        if valid_rows:
            fieldnames = valid_rows[0].keys()
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(valid_rows)

    print(f"\n{'=' * 60}")
    print(f"Summary for {csv_path.name}:")
    print(f"  Initial count: {initial_count}")
    print(f"  Valid journals: {len(valid_rows)}")
    print(f"  Removed: {removed_count}")
    print(f"  Retention rate: {len(valid_rows) / initial_count * 100:.1f}%")
    print(f"{'=' * 60}")


def main() -> None:
    """
    Main function to validate and filter all journal CSV files in data/meta.
    """
    parser = argparse.ArgumentParser(
        description="Validate journal access and filter out inaccessible journals"
    )
    parser.add_argument(
        "--file",
        "-f",
        type=str,
        help="Specific CSV file to process (filename only, e.g., 'utd24.csv')",
    )
    args = parser.parse_args()

    project_root = Path(__file__).parent.parent.parent
    data_meta_dir = project_root / "data" / "meta"

    if not data_meta_dir.exists():
        print(f"✗ Directory not found: {data_meta_dir}")
        return

    if args.file:
        csv_file = data_meta_dir / args.file
        if not csv_file.exists():
            print(f"✗ File not found: {csv_file}")
            return
        csv_files = [csv_file]
    else:
        csv_files = sorted(data_meta_dir.glob("*.csv"))

    if not csv_files:
        print(f"✗ No CSV files found in {data_meta_dir}")
        return

    validator = BrowZineValidator(library_id="3050")

    print("=" * 60)
    print("BrowZine Journal Validation Script")
    print("=" * 60)
    print(f"\nFound {len(csv_files)} CSV file(s) to process")
    print("\nObtaining API token for default library (3050)...")

    if not validator.get_api_token():
        print("✗ Failed to obtain API token. Exiting.")
        return

    print("✓ API token obtained successfully\n")

    for csv_file in csv_files:
        validate_and_filter_csv(validator, csv_file)

    print("\n" + "=" * 60)
    print("✓ All files validated and filtered successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()
