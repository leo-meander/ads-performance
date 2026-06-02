"""Simplify branch_keypoints to single-focus titles.

Per user request: each keypoint must point at exactly ONE thing — straightforward.
The seeded titles combine a landmark with an em-dash tail that nests several
items, e.g.

    "~5-min walk to Nguyen Hue Walking Street — rooftop bars (Chill Skybar, Social Club, EON51)"

The tail is what makes them "too much". Strategy:

  1. Cut everything from the first em/en-dash separator onward.
  2. Drop a TRAILING transit parenthetical (e.g. "(MRT Blue + Green lines)") —
     that is metadata, not the single fact. Keep inline distances ("(~300m)")
     and place names ("(阿宗麵線)") — those ARE the one thing.

UPDATE is in-place (same UUID), so any combo already linked to a keypoint keeps
its metrics. No soft-delete, no new rows.

Dry-run by default — prints every before -> after. Pass --apply to commit.

  cd backend && python scripts/simplify_keypoints_single_focus.py           # preview
  cd backend && python scripts/simplify_keypoints_single_focus.py --apply    # write
"""
import sys, io, os, re

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timezone
from sqlalchemy import text

from app.database import engine

APPLY = "--apply" in sys.argv
now = datetime.now(timezone.utc).isoformat()

# Em dash (—, U+2014) or en dash (–, U+2013) used as a " — descriptor" separator.
_DASH_TAIL = re.compile(r"\s+[—–]\s+.*$")
# A trailing parenthetical that is transit-line metadata, e.g. "(MRT Blue + Green
# lines)", "(MRT Green line)". Distances "(~300m)" and CJK names "(阿宗麵線)" do
# NOT match (no MRT / line keyword) and are preserved.
_TRANSIT_TAIL = re.compile(r"\s*\([^()]*\b(?:MRT|[Ll]ines?)\b[^()]*\)\s*$")


def simplify(title: str) -> str:
    t = _DASH_TAIL.sub("", title)
    t = _TRANSIT_TAIL.sub("", t)
    return t.strip()


changed = []
seen_per_branch: dict = {}

with engine.connect() as c:
    rows = c.execute(
        text(
            "SELECT id, branch_id, category, title FROM branch_keypoints "
            "WHERE is_active = TRUE ORDER BY branch_id, category, title"
        )
    ).fetchall()

    for kp_id, branch_id, category, title in rows:
        new_title = simplify(title)
        if new_title and new_title != title:
            changed.append((kp_id, branch_id, category, title, new_title))
        # collision tracking (purely informational — no unique constraint exists)
        seen_per_branch.setdefault(branch_id, {}).setdefault(new_title.lower(), []).append(title)

    print(f"Active keypoints scanned: {len(rows)}")
    print(f"Titles to simplify:       {len(changed)}\n")

    for _id, _bid, cat, old, new in changed:
        print(f"  [{cat:10}] {old}")
        print(f"  {'':12}-> {new}\n")

    # Report any titles that collapse to the same text within one branch.
    collisions = []
    for bid, titles in seen_per_branch.items():
        for low, originals in titles.items():
            if len(originals) > 1:
                collisions.append((bid, low, originals))
    if collisions:
        print("\n  ⚠ Collisions (multiple rows now share a title — left as-is, separate UUIDs):")
        for bid, low, originals in collisions:
            print(f"    branch {bid}: {len(originals)} rows -> '{low}'")
            for o in originals:
                print(f"        from: {o}")

    if APPLY:
        for kp_id, _bid, _cat, _old, new in changed:
            c.execute(
                text(
                    "UPDATE branch_keypoints SET title = :t, updated_at = :now WHERE id = :id"
                ),
                {"t": new, "now": now, "id": kp_id},
            )
        c.commit()
        print(f"\n--- APPLIED: {len(changed)} titles updated in place.")
    else:
        print(f"\n--- DRY RUN: nothing written. Re-run with --apply to commit {len(changed)} updates.")
