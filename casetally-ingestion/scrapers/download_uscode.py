#!/usr/bin/env python3
"""
Download U.S. Code title HTML from govinfo.gov into the local data archive.

The ingestion plugin reads *.html files from the archive directory and derives
the title number from the filename, so files are saved using the same
"U.S.C. Title N - NAME.html" convention as the titles already present.

Note: govinfo serves these as .htm; they must be saved as .html or
USCodeIngestor.run() will not pick them up (it globs "*.html").

Usage:
    python scrapers/download_uscode.py --titles 4
    python scrapers/download_uscode.py --missing
    python scrapers/download_uscode.py --missing --dry-run
"""

import argparse
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

YEAR = "2024"
BASE = "https://www.govinfo.gov/content/pkg/USCODE-{year}-title{n}/html/USCODE-{year}-title{n}.htm"

# Title 53 is reserved and has no content.
RESERVED = {53}

TITLE_NAMES = {
    1: "GENERAL PROVISIONS", 2: "THE CONGRESS", 3: "THE PRESIDENT",
    4: "FLAG AND SEAL, SEAT OF GOVERNMENT, AND THE STATES",
    5: "GOVERNMENT ORGANIZATION AND EMPLOYEES", 6: "DOMESTIC SECURITY",
    7: "AGRICULTURE", 8: "ALIENS AND NATIONALITY", 9: "ARBITRATION",
    10: "ARMED FORCES", 11: "BANKRUPTCY", 12: "BANKS AND BANKING",
    13: "CENSUS", 14: "COAST GUARD", 15: "COMMERCE AND TRADE",
    16: "CONSERVATION", 17: "COPYRIGHTS", 18: "CRIMES AND CRIMINAL PROCEDURE",
    19: "CUSTOMS DUTIES", 20: "EDUCATION", 21: "FOOD AND DRUGS",
    22: "FOREIGN RELATIONS AND INTERCOURSE", 23: "HIGHWAYS",
    24: "HOSPITALS AND ASYLUMS", 25: "INDIANS", 26: "INTERNAL REVENUE CODE",
    27: "INTOXICATING LIQUORS", 28: "JUDICIARY AND JUDICIAL PROCEDURE",
    29: "LABOR", 30: "MINERAL LANDS AND MINING", 31: "MONEY AND FINANCE",
    32: "NATIONAL GUARD", 33: "NAVIGATION AND NAVIGABLE WATERS",
    34: "CRIME CONTROL AND LAW ENFORCEMENT", 35: "PATENTS",
    36: "PATRIOTIC AND NATIONAL OBSERVANCES, CEREMONIES, AND ORGANIZATIONS",
    37: "PAY AND ALLOWANCES OF THE UNIFORMED SERVICES",
    38: "VETERANS' BENEFITS", 39: "POSTAL SERVICE",
    40: "PUBLIC BUILDINGS, PROPERTY, AND WORKS", 41: "PUBLIC CONTRACTS",
    42: "THE PUBLIC HEALTH AND WELFARE", 43: "PUBLIC LANDS",
    44: "PUBLIC PRINTING AND DOCUMENTS", 45: "RAILROADS", 46: "SHIPPING",
    47: "TELECOMMUNICATIONS", 48: "TERRITORIES AND INSULAR POSSESSIONS",
    49: "TRANSPORTATION", 50: "WAR AND NATIONAL DEFENSE",
    51: "NATIONAL AND COMMERCIAL SPACE PROGRAMS", 52: "VOTING AND ELECTIONS",
    54: "NATIONAL PARK SERVICE AND RELATED PROGRAMS",
}


def resolve_archive_dir(explicit: str | None) -> Path:
    """Locate the uscode archive directory the ingestor reads from."""
    if explicit:
        return Path(explicit).expanduser().resolve()
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "casetally-data-archive" / "openrights-data-archive" / "uscode"
        if candidate.is_dir():
            return candidate
    raise SystemExit("Could not locate the uscode archive dir; pass --data-dir")


def present_titles(archive: Path) -> set[int]:
    found = set()
    for path in archive.glob("*.html"):
        m = re.search(r"[Tt]itle[_\s]*(\d+)", path.name)
        if m:
            found.add(int(m.group(1)))
    return found


def target_path(archive: Path, n: int) -> Path:
    return archive / f"U.S.C. Title {n} - {TITLE_NAMES[n]}.html"


def download(n: int, dest: Path, retries: int = 3) -> tuple[bool, str]:
    url = BASE.format(year=YEAR, n=n)
    tmp = dest.with_suffix(".part")
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "casetally-ingestion/1.0"})
            with urllib.request.urlopen(req, timeout=180) as resp, open(tmp, "wb") as fh:
                total = 0
                while chunk := resp.read(1 << 20):
                    fh.write(chunk)
                    total += len(chunk)
            if total < 10_000:
                tmp.unlink(missing_ok=True)
                return False, f"suspiciously small ({total} bytes)"
            tmp.replace(dest)
            return True, f"{total / 1048576:.1f} MB"
        except urllib.error.HTTPError as exc:
            tmp.unlink(missing_ok=True)
            if exc.code == 404:
                return False, "404 not found"
            if attempt == retries:
                return False, f"HTTP {exc.code}"
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            if attempt == retries:
                return False, str(exc)[:80]
        time.sleep(2 * attempt)
    return False, "exhausted retries"


def main() -> int:
    ap = argparse.ArgumentParser(description="Download U.S. Code HTML from govinfo.gov")
    ap.add_argument("--titles", help="comma-separated title numbers, e.g. 4,26,42")
    ap.add_argument("--missing", action="store_true", help="download every title not already present")
    ap.add_argument("--data-dir", help="override archive directory")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    archive = resolve_archive_dir(args.data_dir)
    have = present_titles(archive)

    if args.titles:
        wanted = [int(x) for x in args.titles.split(",") if x.strip()]
    elif args.missing:
        wanted = [n for n in range(1, 55) if n not in have and n not in RESERVED]
    else:
        ap.error("pass --titles or --missing")

    print(f"archive : {archive}")
    print(f"present : {len(have)} titles")
    print(f"to fetch: {len(wanted)} -> {wanted}\n")

    if args.dry_run:
        return 0

    ok = failed = 0
    for i, n in enumerate(wanted, 1):
        if n in RESERVED:
            print(f"[{i}/{len(wanted)}] title {n:<2} skipped (reserved)")
            continue
        dest = target_path(archive, n)
        if dest.exists():
            print(f"[{i}/{len(wanted)}] title {n:<2} already present")
            continue
        print(f"[{i}/{len(wanted)}] title {n:<2} downloading...", end=" ", flush=True)
        success, detail = download(n, dest)
        print(detail)
        ok, failed = (ok + 1, failed) if success else (ok, failed + 1)

    print(f"\ndownloaded={ok} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
