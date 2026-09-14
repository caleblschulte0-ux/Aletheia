"""Add the job boards his own records and The Muse point at. Run it ONCE.

    python scripts/seed_learned_boards.py --state C:/Users/caleb/Aletheia/state/private --dry-run
    python scripts/seed_learned_boards.py --state C:/Users/caleb/Aletheia/state/private

His words, 2026-09-13: *"it keeps applying to jobs everywhere across the
Internet, not just on Greenhouse."* Batches now learn a board every time they
meet one; this catches up on the boards she met before they did.

READS (never writes): every application record, the sent ledger, his
profile's `work_wanted`, and a few pages of The Muse's free public listings for
the kind of work his records name - each listing followed to the employer's
own page, the same way `company_sites` does it. The Muse's page cursor is
kept in a throwaway file, so the next real batch still starts where it was.

KEEPS: a board on a system she can list (`jobs.PROVIDERS`: Greenhouse, Lever,
Ashby, Workable, SmartRecruiters, Recruitee) that she does not already search
AND that answers its provider's public listing right now with at least one
opening.

WRITES: `jobs/learned_boards.json` under --state, through `jobs._learn_boards`
- the same function every batch learns with - and nothing else. It applies to
nothing and sends nothing. --dry-run writes nothing at all.

--state is the private-state directory. Without it the script uses
ALETHEIA_PRIVATE_STATE, then the `state/private` of the checkout it runs from
- which, from a worktree, is NOT his real state. The path is printed first.
"""
from __future__ import annotations

import argparse
import collections
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LEAD_READERS = 4


def _counts(rows: list[dict]) -> dict:
    return dict(sorted(collections.Counter(r.get("provider", "?") for r in rows).items()))


def record_urls(apply_run) -> list[dict]:
    """Every job address on his records and in his sent ledger."""
    seen = []
    for record in apply_run.all_runs():
        for key in ("url", "posting"):
            if record.get(key):
                seen.append({"url": record[key], "company": record.get("company", ""),
                             "from": "application record"})
    for url, entry in apply_run.already_sent().items():
        seen.append({"url": url, "company": (entry or {}).get("company", ""),
                     "from": "sent ledger"})
    return seen


def muse_urls(company_sites, roles: list[str], wanted: str, *, pages: int,
              most: int, fetch=None) -> tuple[list[dict], int]:
    """Employer pages behind a few pages of Muse listings, and how many listings were read."""
    fetch = fetch or company_sites._fetch
    cursor = Path(tempfile.mkdtemp(prefix="seed-muse-")) / "cursor.json"
    usual = company_sites.PAGES_PER_CATEGORY
    company_sites.PAGES_PER_CATEGORY = max(1, int(pages))
    try:
        leads = company_sites.muse_leads(roles, wanted=wanted, early=False,
                                         cursor_path=cursor, limit=most)
    finally:
        company_sites.PAGES_PER_CATEGORY = usual

    def one(lead):
        try:
            status, final, body = fetch(lead["lead"])
        except Exception:
            return None
        if status != 200:
            return None
        host = company_sites.host_of(final or lead["lead"])
        target = (company_sites.employer_link(body, lead_host=host)
                  or company_sites.follow_hops(body, lead_host=host, fetch=fetch))
        return ({"url": target, "company": lead.get("company", ""), "from": "company site"}
                if target else None)

    with ThreadPoolExecutor(LEAD_READERS) as pool:
        return [row for row in pool.map(one, leads) if row], len(leads)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state", default="", help="private-state directory to read and add to")
    ap.add_argument("--muse-pages", type=int, default=3,
                    help="Muse listing pages per category (0 skips The Muse)")
    ap.add_argument("--leads", type=int, default=180, help="Muse listings followed at most")
    ap.add_argument("--dry-run", action="store_true", help="say what would be added; write nothing")
    args = ap.parse_args(argv)
    if args.state:
        # Before `aletheia` is imported: its stores bind their paths at import.
        os.environ["ALETHEIA_PRIVATE_STATE"] = str(Path(args.state).expanduser().resolve())
    sys.path.insert(0, str(REPO))
    from aletheia import apply_run, company_sites, jobs, profile, stateio

    print(f"private state: {stateio.private_root()}")
    before = _counts(jobs.boards())
    seen = record_urls(apply_run)
    roles = sorted({str(r.get("job_title")) for r in apply_run.all_runs() if r.get("job_title")})
    try:
        wanted = str(profile.known().get("work_wanted") or "")
    except Exception:
        wanted = ""
    from_muse, read = [], 0
    if args.muse_pages > 0 and (roles or wanted):
        from_muse, read = muse_urls(company_sites, roles[:25], wanted,
                                    pages=args.muse_pages, most=args.leads)
    candidates = jobs.boards_seen(seen + from_muse)
    proved = jobs.prove_boards(candidates)
    live = [row for row in proved if row["live"]]
    for row in sorted(proved, key=lambda r: (not r["live"], r["provider"], r["board"])):
        mark = f"{row['count']:>5} open" if row["live"] else "  skipped "
        print(f"{mark}  {row['provider']:15} {row['board']:28} {row['company'][:30]:30} "
              f"from {row['found_by'] or '?'}{'  - ' + row['why'] if row['why'] else ''}")
    added = 0 if args.dry_run else jobs._learn_boards(live, source="seed")
    after = _counts(jobs.boards())
    print(f"\njob addresses read: {len(seen)} on his records, {len(from_muse)} employer pages "
          f"from {read} Muse listings")
    print(f"new boards seen: {len(candidates)}; answering with openings: {len(live)}; "
          f"{'would add' if args.dry_run else 'added'}: {len(live) if args.dry_run else added}")
    print(f"boards per provider before: {before}")
    print(f"boards per provider after:  {after if not args.dry_run else '(dry run - unchanged)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
