"""Tag import/export.

Tags describe what is on screen, using open facets. They never assign a theme:
themes are queries over these facts, so one clip can serve many themes.

Import format (JSON):
{
  "<clip_id>": {
    "space":   ["living", "playroom-corner"],
    "zone":    ["arched-wardrobe"],            # the subject this shot documents
    "angle":   ["arched-wardrobe-front"],      # repeatable camera position for that subject
    "state":   ["mid-sort"],                   # optional free label; stages come from time order
    "content": ["wood-tone", "fabric", "toy-bins", "color-accent"],
    "action":  ["assembling"],
    "shot":    ["wide", "fixed-angle"],       # wide | medium | closeup | overhead | timelapse
    "light":   ["daylight"],
    "quality": ["ok"],                        # ok | shaky | dark | blurry | unusable
    "privacy": [],                            # face | name | window-view | address  -> excluded by default
    "moments": [{"start": 1.0, "end": 4.5, "label": "after wide"}],
    "notes":   "free text, e.g. the transcript of a voice memo"
  }
}
Facets are open: any new key becomes a facet.
"""
from __future__ import annotations

import json
from pathlib import Path

from .config import Layout
from .db import connect

RESERVED = {"moments", "notes"}


def import_tags(L: Layout, path: Path, source: str = "agent", replace: bool = True) -> int:
    con = connect(L.db)
    data = json.loads(Path(path).read_text())
    known = {r["id"] for r in con.execute("SELECT id FROM clips")}
    n = 0
    for cid, facets in data.items():
        if cid not in known:
            continue
        if replace:
            con.execute("DELETE FROM tags WHERE clip_id=? AND source=?", (cid, source))
            con.execute("DELETE FROM moments WHERE clip_id=?", (cid,))
        for facet, vals in facets.items():
            if facet in RESERVED:
                continue
            for v in ([vals] if isinstance(vals, str) else vals):
                con.execute("INSERT OR IGNORE INTO tags VALUES(?,?,?,?)", (cid, facet, str(v).strip().lower(), source))
        for m in facets.get("moments", []):
            con.execute("INSERT INTO moments(clip_id,start,end,label) VALUES(?,?,?,?)",
                        (cid, float(m["start"]), float(m["end"]), m.get("label", "")))
        if facets.get("notes"):
            con.execute("INSERT OR REPLACE INTO notes VALUES(?,?)", (cid, facets["notes"]))
        n += 1
    con.commit()
    return n


def untagged(L: Layout) -> list[dict]:
    con = connect(L.db)
    rows = con.execute(
        "SELECT c.id, c.path, c.kind, c.duration FROM clips c "
        "WHERE NOT EXISTS (SELECT 1 FROM tags t WHERE t.clip_id=c.id) ORDER BY c.taken_at"
    ).fetchall()
    return [dict(r) for r in rows]


def facet_counts(L: Layout) -> dict[str, dict[str, int]]:
    con = connect(L.db)
    out: dict[str, dict[str, int]] = {}
    for r in con.execute("SELECT facet, value, COUNT(*) n FROM tags GROUP BY facet, value ORDER BY facet, n DESC"):
        out.setdefault(r["facet"], {})[r["value"]] = r["n"]
    return out
