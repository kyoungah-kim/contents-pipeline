"""Find usable units (whole clips or tagged moments) matching facet queries."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

BAD_QUALITY = {"unusable", "blurry"}


@dataclass
class Unit:
    clip_id: str
    path: str
    kind: str
    start: float
    end: float | None
    label: str
    tags: dict[str, set[str]] = field(default_factory=dict)
    score: float = 0.0

    @property
    def key(self) -> tuple:
        return (self.clip_id, round(self.start, 1))


def _tags(con: sqlite3.Connection) -> dict[str, dict[str, set[str]]]:
    out: dict[str, dict[str, set[str]]] = {}
    for r in con.execute("SELECT clip_id, facet, value FROM tags"):
        out.setdefault(r["clip_id"], {}).setdefault(r["facet"], set()).add(r["value"])
    return out


def match_score(tags: dict[str, set[str]], want: dict, prefer: dict | None = None) -> float | None:
    """None if any wanted facet is unmet; otherwise a score that rewards extra matches."""
    s = 0.0
    for facet, vals in (want or {}).items():
        hit = tags.get(facet, set()) & {str(v).lower() for v in vals}
        if not hit:
            return None
        s += 1 + 0.25 * (len(hit) - 1)
    for facet, vals in (prefer or {}).items():
        s += 0.5 * len(tags.get(facet, set()) & {str(v).lower() for v in vals})
    return s


def candidates(con: sqlite3.Connection, want: dict, prefer: dict | None = None, avoid: dict | None = None,
               allow_privacy: bool = False) -> list[Unit]:
    all_tags = _tags(con)
    moments: dict[str, list[sqlite3.Row]] = {}
    for m in con.execute("SELECT * FROM moments"):
        moments.setdefault(m["clip_id"], []).append(m)
    out: list[Unit] = []
    for c in con.execute("SELECT * FROM clips"):
        t = all_tags.get(c["id"])
        if not t:
            continue
        if t.get("quality", set()) & BAD_QUALITY:
            continue
        if not allow_privacy and t.get("privacy"):
            continue
        if avoid and any(t.get(f, set()) & {str(v).lower() for v in vs} for f, vs in avoid.items()):
            continue
        s = match_score(t, want, prefer)
        if s is None:
            continue
        ms = moments.get(c["id"])
        if ms:
            for m in ms:
                out.append(Unit(c["id"], c["path"], c["kind"], m["start"], m["end"], m["label"], t, s + 0.3))
        else:
            out.append(Unit(c["id"], c["path"], c["kind"], 0.0, c["duration"], "", t, s))
    return sorted(out, key=lambda u: -u.score)
