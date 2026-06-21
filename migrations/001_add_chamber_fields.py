#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Conductor migration 001 - add chamber_size + pia_chamber_type to `chambers`.

WHY
    place_chamber.py writes "chamber_size" (SMALL/LARGE) and place_pia_chamber.py
    writes "pia_chamber_type", but neither column existed in LAYER_SCHEMA. QGIS's
    write pattern (idx = fields().indexOf(name); if idx >= 0: setAttribute(...))
    silently dropped both on every save, and bom.py - guarding its lookup with
    `"chamber_size" in fields` - therefore costed EVERY chamber as SMALL.

    Adding the columns to LAYER_SCHEMA fixes NEW projects. This migration fixes
    EXISTING GeoPackages so future saves/edits persist and the BoM reads real
    data going forward.

WHAT IT CANNOT DO
    It cannot recover historical SMALL/LARGE choices - those values were never
    written to disk. After migrating, review chamber sizes on existing projects;
    unset chambers continue to cost as SMALL in the BoM until edited.

USAGE
    python3 001_add_chamber_fields.py PROJECT.gpkg [PROJECT2.gpkg ...]

PROPERTIES
    * Idempotent - running twice is safe (skips columns that already exist).
    * Pure stdlib (sqlite3) - no QGIS required.
"""
import os
import sqlite3
import sys

TABLE = "chambers"
NEW_COLS = [
    ("chamber_size", "TEXT"),       # SMALL / LARGE
    ("pia_chamber_type", "TEXT"),   # FW1-14, CW1-3, MH
]


def migrate(path):
    if not os.path.isfile(path):
        print(f"  SKIP (file not found): {path}")
        return False
    con = sqlite3.connect(path)
    try:
        cur = con.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (TABLE,),
        )
        if not cur.fetchone():
            print(f"  SKIP (no '{TABLE}' table): {path}")
            return False

        existing = {row[1] for row in cur.execute(f"PRAGMA table_info({TABLE})")}
        added = []
        for col, typ in NEW_COLS:
            if col in existing:
                print(f"  = '{col}' already present, skipping")
                continue
            cur.execute(f'ALTER TABLE "{TABLE}" ADD COLUMN "{col}" {typ}')
            added.append(col)
            print(f"  + added '{col}' {typ}")
        con.commit()

        total = cur.execute(f'SELECT COUNT(*) FROM "{TABLE}"').fetchone()[0]
        unset = cur.execute(
            f'SELECT COUNT(*) FROM "{TABLE}" '
            f"WHERE \"chamber_size\" IS NULL OR \"chamber_size\" = ''"
        ).fetchone()[0]
        print(f"  chambers: {total} total | {unset} with no size set "
              f"(cost as SMALL in BoM until edited)")
        if added:
            print(f"  OK - added {len(added)} column(s): {', '.join(added)}")
        else:
            print("  OK - nothing to do (already migrated)")
        return True
    finally:
        con.close()


def main(argv):
    paths = argv[1:]
    if not paths:
        print(__doc__)
        return 1
    print("Conductor migration 001 - add chamber_size + pia_chamber_type\n")
    ok = 0
    for p in paths:
        print(f"Migrating: {p}")
        if migrate(p):
            ok += 1
        print()
    print(f"Done. {ok}/{len(paths)} GeoPackage(s) processed.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
