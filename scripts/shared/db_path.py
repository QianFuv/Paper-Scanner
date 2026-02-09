"""Database path resolution helpers shared by API and notify modules."""

from __future__ import annotations

from pathlib import Path

from scripts.shared.constants import INDEX_DIR


def list_database_files() -> list[Path]:
    """
    List available SQLite database files.

    Returns:
        Sorted list of `.sqlite` files under index directory.
    """
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(INDEX_DIR.glob("*.sqlite"))


def resolve_db_path(db_name: str | None) -> Path:
    """
    Resolve database path from optional name.

    Args:
        db_name: Optional database file stem or filename.

    Returns:
        Resolved database path.

    Raises:
        ValueError: Database cannot be resolved unambiguously.
    """
    if db_name:
        candidate = Path(db_name).name
        if not candidate.endswith(".sqlite"):
            candidate = f"{candidate}.sqlite"
        db_path = INDEX_DIR / candidate
        if not db_path.exists():
            raise ValueError("Database not found")
        return db_path

    sqlite_files = list_database_files()
    if len(sqlite_files) == 1:
        return sqlite_files[0]
    if not sqlite_files:
        raise ValueError("No SQLite databases found")
    raise ValueError("Multiple databases found, specify ?db=<name>")
