"""
Script to fill journal metadata using BrowZine API.

This script fills:
- ISSN for utd24.csv (using existing journal IDs)
- Journal IDs for fms_chinese.csv and fms_global.csv (using existing ISSNs)
- Library ID for all journals (default 3050, fallback to other libraries)
"""

import argparse
import csv
import time
from pathlib import Path
from typing import Any

import requests


class BrowZineAPIClient:
    """
    BrowZine API client for retrieving journal information across multiple libraries.
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

    def search_by_issn(
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
        libraries_to_try = [self.library_id]
        if try_fallback:
            libraries_to_try.extend(self.FALLBACK_LIBRARIES)

        for lib_id in libraries_to_try:
            if not self.get_api_token(lib_id):
                continue

            url = f"{self.base_url}/libraries/{lib_id}/search"
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
                        return data["data"][0], lib_id
            except Exception:
                continue

        return None, None

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


def fill_issn_by_id(client: BrowZineAPIClient, csv_path: Path) -> None:
    """
    Fill ISSN field using existing journal IDs.

    Args:
        client: BrowZine API client instance.
        csv_path: Path to CSV file.
    """
    print(f"\nProcessing {csv_path.name}...")

    rows = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    rows = ensure_library_column(rows)

    updated_count = 0
    for i, row in enumerate(rows, start=1):
        if row.get("id") and not row.get("issn"):
            journal_id = row["id"]
            title = row["title"]
            lib_id = row.get("library", "3050")

            print(
                f"  [{i}/{len(rows)}] Fetching ISSN for {title} "
                f"(ID: {journal_id}, Lib: {lib_id})..."
            )

            journal_info = client.get_journal_info(journal_id, lib_id)
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

            time.sleep(0.5)

    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        fieldnames = rows[0].keys() if rows else []
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"  Updated {updated_count} ISSNs")


def fill_id_by_issn(client: BrowZineAPIClient, csv_path: Path) -> None:
    """
    Fill journal ID field using existing ISSNs.

    Args:
        client: BrowZine API client instance.
        csv_path: Path to CSV file.
    """
    print(f"\nProcessing {csv_path.name}...")

    rows = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    rows = ensure_library_column(rows)

    updated_count = 0
    for i, row in enumerate(rows, start=1):
        if row.get("issn") and not row.get("id"):
            issn = row["issn"]
            title = row["title"]
            print(f"  [{i}/{len(rows)}] Searching for {title} (ISSN: {issn})...")

            journal, lib_id = client.search_by_issn(issn, try_fallback=True)
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

            time.sleep(0.5)

    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        fieldnames = rows[0].keys() if rows else []
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"  Updated {updated_count} journal IDs")


def process_csv_file(client: BrowZineAPIClient, csv_path: Path) -> None:
    """
    Process a single CSV file to fill missing metadata.

    Args:
        client: BrowZine API client instance.
        csv_path: Path to CSV file.
    """
    if not csv_path.exists():
        print(f"  ✗ File not found: {csv_path}")
        return

    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print(f"  ✗ Empty file: {csv_path.name}")
        return

    first_row = rows[0]
    has_id = "id" in first_row
    has_issn = "issn" in first_row

    has_missing_issn = False
    has_missing_id = False

    for row in rows:
        if has_id and row.get("id") and (not has_issn or not row.get("issn")):
            has_missing_issn = True
        if has_issn and row.get("issn") and (not has_id or not row.get("id")):
            has_missing_id = True

    if has_missing_issn:
        fill_issn_by_id(client, csv_path)

    if has_missing_id:
        fill_id_by_issn(client, csv_path)

    if not has_missing_issn and not has_missing_id:
        print(f"  ✓ {csv_path.name}: All metadata already complete")


def main() -> None:
    """
    Main function to fill journal metadata in all CSV files in data/meta.
    """
    parser = argparse.ArgumentParser(
        description="Fill journal metadata using BrowZine API"
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

    client = BrowZineAPIClient(library_id="3050")

    print("=" * 60)
    print("BrowZine Journal Metadata Filler")
    print("=" * 60)
    print(f"\nFound {len(csv_files)} CSV file(s) to process")
    print("\nObtaining API token for default library (3050)...")

    if not client.get_api_token():
        print("✗ Failed to obtain API token. Exiting.")
        return

    print("✓ API token obtained successfully\n")

    for csv_file in csv_files:
        process_csv_file(client, csv_file)

    print("\n" + "=" * 60)
    print("✓ All files processed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()
