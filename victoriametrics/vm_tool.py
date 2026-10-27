#!/usr/bin/env python3
"""Import / export data to and from VictoriaMetrics.

Examples:
    # Import (JSON array, single object or NDJSON are all accepted)
    python vm_tool.py import -f import.json --host http://localhost:8428

    # Export all series matching a selector to an NDJSON file
    python vm_tool.py export -f export.json --host http://localhost:8428 --match sensor.gas_meter_consumption_value --start 2026-10-01T00:00:00Z

    # Basic auth
    python vm_tool.py export -f export.json --host http://localhost:8428 --match sensor.gas_meter_consumption_value --user admin --password secret
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Iterable, Iterator

import requests

DEFAULT_HOST = "http://localhost:8428"
DEFAULT_FILE = "data.json"
DEFAULT_BATCH_SIZE = 1000  # Max number of data points (samples) per HTTP request
DEFAULT_TIMEOUT = 120  # seconds


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def normalize_host(host: str) -> str:
    """Accept 'localhost:8428', 'http://localhost:8428/' etc. and return a clean base URL."""
    host = host.strip().rstrip("/")
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"
    return host


def build_session(user: str | None, password: str | None, token: str | None) -> requests.Session:
    session = requests.Session()
    if token:
        session.headers["Authorization"] = f"Bearer {token}"
    elif user:
        session.auth = (user, password or "")
    return session


def iter_records(path: pathlib.Path) -> Iterator[dict]:
    """Yield one series (dict) per record.

    Supports:
      * a JSON array of objects (may be on a single line)
      * a single JSON object (single-line or pretty-printed)
      * NDJSON / JSON lines (the native VictoriaMetrics format), streamed
        line by line.

    Note: a single huge line has to be parsed as a whole, so it must fit
    into memory. Batching is done afterwards by data points, not by lines.
    """
    with open(path, "r", encoding="utf-8") as f:
        # Peek at the first non-whitespace character
        first = ""
        while True:
            ch = f.read(1)
            if not ch:
                return  # empty file
            if not ch.isspace():
                first = ch
                break
        f.seek(0)

        if first == "[":
            for item in json.load(f):
                if not isinstance(item, dict):
                    raise ValueError("JSON array must contain only objects.")
                yield item
            return

        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                if lineno == 1:
                    # Possibly a pretty-printed (multi-line) single object
                    f.seek(0)
                    try:
                        obj = json.load(f)
                    except json.JSONDecodeError:
                        raise ValueError(
                            f"Invalid JSON on line 1: {exc}. Expected a JSON array, "
                            "a JSON object, or one JSON object per line."
                        ) from exc
                    if not isinstance(obj, dict):
                        raise ValueError("JSON content must be an object or a list of objects.")
                    yield obj
                    return
                raise ValueError(f"Invalid JSON on line {lineno}: {exc}") from exc
            if not isinstance(obj, dict):
                raise ValueError(f"Line {lineno} is not a JSON object.")
            yield obj


def split_series(record: dict, max_points: int) -> Iterator[tuple[str, int]]:
    """Split one series into chunks of at most `max_points` samples.

    Yields (json_line, number_of_points). The metric labels are repeated in
    every chunk, which VictoriaMetrics merges back into the same series.
    """
    values = record.get("values")
    timestamps = record.get("timestamps")

    if not isinstance(values, list):
        # Unknown structure: pass through unchanged, count as one point
        yield json.dumps(record, separators=(",", ":")), 1
        return

    if isinstance(timestamps, list) and len(timestamps) != len(values):
        raise ValueError(
            f"'values' ({len(values)}) and 'timestamps' ({len(timestamps)}) "
            "have different lengths."
        )

    for i in range(0, max(len(values), 1), max_points):
        chunk = {**record, "values": values[i : i + max_points]}
        if isinstance(timestamps, list):
            chunk["timestamps"] = timestamps[i : i + max_points]
        yield json.dumps(chunk, separators=(",", ":")), len(chunk["values"])


def batch_by_points(
    records: Iterable[dict], max_points: int
) -> Iterator[tuple[list[str], int]]:
    """Group series (or series chunks) into batches of at most `max_points` samples.

    Yields (list_of_json_lines, points_in_batch).
    """
    batch: list[str] = []
    points = 0
    for record in records:
        for line, n in split_series(record, max_points):
            if batch and points + n > max_points:
                yield batch, points
                batch, points = [], 0
            batch.append(line)
            points += n
    if batch:
        yield batch, points


# --------------------------------------------------------------------------- #
# Import
# --------------------------------------------------------------------------- #
def import_to_victoriametrics(
    file_path: str,
    host: str = DEFAULT_HOST,
    batch_size: int = DEFAULT_BATCH_SIZE,
    session: requests.Session | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    dry_run: bool = False,
) -> bool:
    """Import a JSON / NDJSON file into VictoriaMetrics. Returns True on success."""
    path = pathlib.Path(file_path)
    if not path.is_file():
        print(f"Error: File '{file_path}' not found.", file=sys.stderr)
        return False

    url = f"{normalize_host(host)}/api/v1/import"
    session = session or requests.Session()

    print(f"Importing '{path}' -> {url} (batch size {batch_size})"
          f"{' [DRY RUN]' if dry_run else ''}")

    total = 0
    try:
        for batch_no, (batch, points) in enumerate(
            batch_by_points(iter_records(path), batch_size), start=1
        ):
            payload = ("\n".join(batch) + "\n").encode("utf-8")

            if not dry_run:
                resp = session.post(
                    url,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=timeout,
                )
                if resp.status_code not in (200, 204):
                    print(f"Failed batch {batch_no}: HTTP {resp.status_code}", file=sys.stderr)
                    print(f"Response: {resp.text}", file=sys.stderr)
                    return False

            print(f"Batch {batch_no}: points {total + 1}-{total + points} OK")
            total += points
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return False
    except requests.RequestException as exc:
        print(f"Connection error: {exc}", file=sys.stderr)
        return False

    print(f"Done. {total} data points {'validated' if dry_run else 'imported'}.")
    return True


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #
def export_from_victoriametrics(
    file_path: str,
    host: str = DEFAULT_HOST,
    match: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    session: requests.Session | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    overwrite: bool = False,
) -> bool:
    """Export series as NDJSON (re-importable via import). Returns True on success."""
    path = pathlib.Path(file_path)
    if path.exists() and not overwrite:
        print(f"Error: '{file_path}' already exists. Use --overwrite to replace it.",
              file=sys.stderr)
        return False

    url = f"{normalize_host(host)}/api/v1/export"
    # Default selector: everything
    params: list[tuple[str, str]] = [("match[]", m) for m in (match or ['{__name__!=""}'])]
    if start:
        params.append(("start", start))
    if end:
        params.append(("end", end))

    session = session or requests.Session()

    count = 0
    try:
        with session.get(url, params=params, stream=True, timeout=timeout) as resp:
            print(f"Exporting from {resp.url} -> '{path}'")
            if resp.status_code != 200:
                print(f"Export failed: HTTP {resp.status_code}", file=sys.stderr)
                print(f"Response: {resp.text}", file=sys.stderr)
                return False

            with open(path, "wb") as out:
                for line in resp.iter_lines():
                    if not line:
                        continue
                    out.write(line + b"\n")
                    count += 1
    except requests.RequestException as exc:
        print(f"Connection error: {exc}", file=sys.stderr)
        return False

    if count == 0:
        print("Warning: no series matched; the output file is empty.")
    else:
        print(f"Done. {count} series exported.")
    return True


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import / export data to and from VictoriaMetrics.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Options shared by all sub-commands
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-H", "--host", default=DEFAULT_HOST,
                        help=f"VictoriaMetrics address (default: {DEFAULT_HOST})")
    common.add_argument("-f", "--file", default=DEFAULT_FILE,
                        help=f"Input/output file (default: {DEFAULT_FILE})")
    common.add_argument("--user", help="Basic auth user")
    common.add_argument("--password", help="Basic auth password")
    common.add_argument("--token", help="Bearer token (takes precedence over basic auth)")
    common.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help=f"HTTP timeout in seconds (default: {DEFAULT_TIMEOUT})")

    sub = parser.add_subparsers(dest="command", required=True)

    p_imp = sub.add_parser("import", parents=[common], help="Import a file into VictoriaMetrics")
    p_imp.add_argument("-b", "--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                       help=f"Max data points per request (default: {DEFAULT_BATCH_SIZE})")
    p_imp.add_argument("--dry-run", action="store_true",
                       help="Parse and validate the file without sending anything")

    p_exp = sub.add_parser("export", parents=[common], help="Export data from VictoriaMetrics")
    p_exp.add_argument("-m", "--match", action="append",
                       help="Series selector, can be given multiple times "
                            "(default: all series)")
    p_exp.add_argument("--start", help="Start time (RFC3339 or unix timestamp)")
    p_exp.add_argument("--end", help="End time (RFC3339 or unix timestamp)")
    p_exp.add_argument("--overwrite", action="store_true",
                       help="Overwrite the output file if it exists")

    return parser


def main() -> int:
    args = build_parser().parse_args()
    session = build_session(args.user, args.password, args.token)

    if args.command == "import":
        ok = import_to_victoriametrics(
            args.file, args.host, args.batch_size, session, args.timeout, args.dry_run
        )
    else:
        ok = export_from_victoriametrics(
            args.file, args.host, args.match, args.start, args.end,
            session, args.timeout, args.overwrite,
        )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
