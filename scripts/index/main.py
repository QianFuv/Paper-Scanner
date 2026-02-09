"""Main entrypoint for index command."""

from __future__ import annotations

import argparse
import asyncio
import csv
import multiprocessing as mp
from pathlib import Path

import aiosqlite

from scripts.browzine import BrowZineAPIClient, resolve_working_library
from scripts.index.changes import (
    collect_article_snapshot,
    compute_changed_group_keys,
    run_notify_for_manifest,
    write_change_manifest,
)
from scripts.index.db.client import LocalDatabaseClient
from scripts.index.db.operations import mark_listing_ready
from scripts.index.db.schema import init_db, optimize_db
from scripts.index.fetcher import process_journal
from scripts.index.workers import run_worker_batch, writer_process
from scripts.shared.constants import (
    DB_TIMEOUT_SECONDS,
    DEFAULT_LIBRARY_ID,
    PROJECT_ROOT,
)
from scripts.shared.converters import is_weipu_library, to_int
from scripts.weipu import WeipuAPISelectolax


def load_csv_rows(csv_path: Path) -> list[dict[str, str]]:
    """
    Load CSV rows and ensure the library column exists.

    Args:
        csv_path: Path to the CSV file.

    Returns:
        List of CSV row dictionaries.
    """
    with open(csv_path, encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    if not rows:
        return []
    if "library" not in rows[0]:
        for row in rows:
            row["library"] = DEFAULT_LIBRARY_ID
    for row in rows:
        if not row.get("library"):
            row["library"] = DEFAULT_LIBRARY_ID
    return rows


def write_csv_rows(csv_path: Path, rows: list[dict[str, str]]) -> None:
    """
    Write CSV rows back to the file.

    Args:
        csv_path: Path to the CSV file.
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


async def ensure_available_libraries(
    client: BrowZineAPIClient, csv_path: Path, rows: list[dict[str, str]]
) -> list[dict[str, str]]:
    """
    Validate libraries for CSV rows and apply fallback libraries when needed.

    Args:
        client: BrowZine API client instance.
        csv_path: Path to the CSV file.
        rows: CSV rows to validate.

    Returns:
        Updated CSV rows.
    """
    if not rows:
        return rows

    updated = False
    for row in rows:
        library_id = row.get("library") or DEFAULT_LIBRARY_ID
        row["library"] = library_id
        if is_weipu_library(library_id):
            continue
        journal_id = to_int(row.get("id"))
        if not journal_id:
            continue
        issn = row.get("issn") or ""
        resolved_id, resolved_library, reason = await resolve_working_library(
            client, journal_id, issn, library_id
        )
        if resolved_library != library_id or resolved_id != journal_id:
            row["library"] = resolved_library
            row["id"] = str(resolved_id)
            updated = True
            title = row.get("title", "Unknown")
            print(
                f"  - Switched library for {title} "
                f"(ID: {journal_id} -> {resolved_id}, "
                f"Lib: {library_id} -> {resolved_library}, "
                f"Reason: {reason})"
            )

    if updated:
        write_csv_rows(csv_path, rows)

    return rows


async def export_csv(
    csv_path: Path,
    db_path: Path,
    issue_batch_size: int,
    thread_workers: int,
    processes: int,
    timeout: int,
    resume: bool,
    update: bool,
) -> None:
    """
    Export a CSV file to a SQLite database.

    Args:
        csv_path: Path to the CSV file.
        db_path: Output SQLite database path.
        issue_batch_size: Number of issues per fetch batch.
        thread_workers: Maximum concurrent HTTP requests.
        processes: Process workers for journal-level parallelism.
        timeout: HTTP request timeout in seconds.
        resume: Whether to resume from completed years and journals.
        update: Whether to perform incremental updates for existing years.

    Returns:
        None.
    """
    rows = load_csv_rows(csv_path)
    if not rows:
        print(f"Skipping empty CSV: {csv_path.name}")
        return

    print(f"\nProcessing {csv_path.name} -> {db_path.name}")
    availability_client = BrowZineAPIClient(
        library_id=DEFAULT_LIBRARY_ID, timeout=timeout
    )
    try:
        rows = await ensure_available_libraries(availability_client, csv_path, rows)
    finally:
        await availability_client.aclose()

    if processes <= 1:
        client = BrowZineAPIClient(library_id=DEFAULT_LIBRARY_ID, timeout=timeout)
        weipu_client = WeipuAPISelectolax(timeout=timeout)
        async with aiosqlite.connect(db_path, timeout=DB_TIMEOUT_SECONDS) as db:
            await init_db(db)
            local_db = LocalDatabaseClient(db)
            await local_db.start()
            try:
                for index, row in enumerate(rows, start=1):
                    title = row.get("title", "Unknown")
                    print(f"  [{index}/{len(rows)}] Exporting {title}")
                    await process_journal(
                        local_db,
                        client,
                        weipu_client,
                        csv_path,
                        row,
                        issue_batch_size,
                        thread_workers,
                        True,
                        resume,
                        update,
                    )
            finally:
                await local_db.close()
                await optimize_db(db)
                if not update:
                    await mark_listing_ready(db)
                await client.aclose()
                await weipu_client.aclose()
        return

    ctx = mp.get_context()
    request_queue = ctx.Queue()
    response_queues = [ctx.Queue() for _ in range(processes)]
    status_queue = ctx.Queue()
    writer = ctx.Process(
        target=writer_process, args=(str(db_path), request_queue, response_queues)
    )
    writer.start()

    workers: list[mp.Process] = []
    for worker_id in range(processes):
        worker_rows = rows[worker_id::processes]
        if not worker_rows:
            continue
        worker = ctx.Process(
            target=run_worker_batch,
            args=(
                worker_id,
                request_queue,
                response_queues[worker_id],
                status_queue,
                str(csv_path),
                worker_rows,
                issue_batch_size,
                thread_workers,
                timeout,
                resume,
                update,
            ),
        )
        worker.start()
        workers.append(worker)

    completed = 0
    total = len(rows)
    try:
        while completed < total:
            message = await asyncio.to_thread(status_queue.get)
            if message is None:
                continue
            completed += 1
            if message.get("ok"):
                title = message.get("title") or message.get("journal_id") or "Unknown"
                print(f"  Finished {title}")
            else:
                title = message.get("title") or message.get("journal_id") or "Unknown"
                error = message.get("error") or "Unknown error"
                print(f"  - Journal worker failed: {title} ({error})")
    finally:
        request_queue.put({"type": "stop"})
        writer.join()
        for worker in workers:
            worker.join()

    async with aiosqlite.connect(db_path, timeout=DB_TIMEOUT_SECONDS) as db:
        await optimize_db(db)
        if not update:
            await mark_listing_ready(db)


async def async_main(args: argparse.Namespace) -> None:
    """
    Run export process for all target CSV files.

    Args:
        args: Parsed CLI arguments.

    Returns:
        None.
    """
    project_root = PROJECT_ROOT
    meta_dir = project_root / "data" / "meta"
    index_dir = project_root / "data" / "index"
    index_dir.mkdir(parents=True, exist_ok=True)

    if not meta_dir.exists():
        print(f"Directory not found: {meta_dir}")
        return

    if args.file:
        csv_paths = [meta_dir / args.file]
        if not csv_paths[0].exists():
            print(f"CSV not found: {csv_paths[0]}")
            return
    else:
        csv_paths = sorted(meta_dir.glob("*.csv"))

    if not csv_paths:
        print(f"No CSV files found in {meta_dir}")
        return

    issue_batch_size = max(1, args.issue_batch or args.workers * 3)

    print("=" * 60)
    print("BrowZine Article Indexer")
    print("=" * 60)
    print(f"Found {len(csv_paths)} CSV file(s)")
    print(f"Request workers: {args.workers}")
    print(f"Process workers: {args.processes}")
    print(f"Issue batch size: {issue_batch_size}")
    if args.update:
        print("Change tracking: enabled (article-level diff)")

    manifest_records: list[tuple[Path, Path]] = []

    for csv_path in csv_paths:
        db_path = index_dir / f"{csv_path.stem}.sqlite"
        before_issue_map: dict[str, set[int]] = {}
        before_inpress_map: dict[int, set[int]] = {}
        if args.update and db_path.exists():
            before_issue_map, before_inpress_map = collect_article_snapshot(db_path)

        await export_csv(
            csv_path,
            db_path,
            issue_batch_size,
            args.workers,
            args.processes,
            args.timeout,
            args.resume,
            args.update,
        )

        if args.update and db_path.exists():
            after_issue_map, after_inpress_map = collect_article_snapshot(db_path)
            changed_issue_keys, changed_inpress_ids, summary = (
                compute_changed_group_keys(
                    before_issue_map,
                    after_issue_map,
                    before_inpress_map,
                    after_inpress_map,
                )
            )
            manifest_path = write_change_manifest(
                db_path,
                changed_issue_keys,
                changed_inpress_ids,
                summary,
            )
            manifest_records.append((db_path, manifest_path))
            print(
                "  Change manifest:",
                manifest_path,
                f"(issues={len(changed_issue_keys)}, "
                f"inpress={len(changed_inpress_ids)}, "
                f"added={summary['added_article_count']}, "
                f"removed={summary['removed_article_count']})",
            )

    if args.notify and args.update:
        for db_path, manifest_path in manifest_records:
            print(f"Running notify for {db_path.name}")
            return_code = run_notify_for_manifest(
                db_path,
                manifest_path,
                args.notify_dry_run,
            )
            if return_code != 0:
                print(
                    f"  - notify failed for {db_path.name} with exit code {return_code}"
                )

    print("\nDone.")


def main() -> None:
    """
    Parse CLI arguments and run the exporter.

    Args:
        None.

    Returns:
        None.
    """
    parser = argparse.ArgumentParser(
        description="Export BrowZine journal articles to SQLite databases"
    )
    parser.add_argument(
        "--file",
        "-f",
        type=str,
        help="Specific CSV filename under data/meta (e.g., utd24.csv)",
    )
    parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=8,
        help="Maximum concurrent HTTP requests",
    )
    parser.add_argument(
        "--issue-batch",
        type=int,
        default=0,
        help="Issues per async batch (default: workers * 3)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=20,
        help="HTTP request timeout in seconds",
    )
    parser.add_argument(
        "--processes",
        type=int,
        default=1,
        help="Process workers for journal-level parallelism",
    )
    parser.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Resume from completed years and journals",
    )
    parser.add_argument(
        "--update",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Incrementally update existing years and journals",
    )
    parser.add_argument(
        "--notify",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Run notify after update using the generated change manifest",
    )
    parser.add_argument(
        "--notify-dry-run",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Run notify with --dry-run when --notify is enabled",
    )
    args = parser.parse_args()

    if args.notify and not args.update:
        parser.error("--notify requires --update")

    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
