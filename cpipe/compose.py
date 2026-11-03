"""Compose reel specs: theme (what story) x format (what shape) x seed (which variation).

One theme can yield many reels; one clip can appear in many reels across themes.
Reuse is managed, not forbidden: clips used recently in approved reels are penalised
(cooldown), and a clip is not repeated within one reel unless nothing else fits.
"""
from __future__ import annotations

import json
import random
import sqlite3
from datetime import datetime, timedelta
from importlib import resources
from pathlib import Path

import yaml

from .config import Layout
from .db import connect
from .search import Unit, candidates

LIVE = ("approved", "rendered", "posted")


def load_yaml(L: Layout, kind: str, name: str) -> dict:
    user = (L.themes if kind == "themes" else L.formats) / f"{name}.yaml"
    if user.exists():
        return yaml.safe_load(user.read_text())
    if kind == "formats":
        return yaml.safe_load(resources.files("cpipe").joinpath(f"formats/{name}.yaml").read_text())
    raise FileNotFoundError(user)


def _recent_use(con: sqlite3.Connection, cooldown_days: int) -> tuple[dict[str, int], set[str]]:
    counts, recent = {}, set()
    since = (datetime.now() - timedelta(days=cooldown_days)).isoformat(sep=" ")
    q = f"SELECT u.clip_id, u.used_at FROM usages u JOIN reels r ON r.id=u.reel_id WHERE r.status IN {LIVE}"
    for r in con.execute(q):
        counts[r["clip_id"]] = counts.get(r["clip_id"], 0) + 1
        if r["used_at"] >= since:
            recent.add(r["clip_id"])
    return counts, recent


def _pair_bonus(u: Unit, anchor: Unit | None) -> float:
    if not anchor:
        return 0.0
    b = 0.0
    if u.tags.get("angle") and u.tags.get("angle") & anchor.tags.get("angle", set()):
        b += 3.0
    b += 1.0 * len(u.tags.get("space", set()) & anchor.tags.get("space", set()))
    return b


def group_key(u: Unit, by: list[str]) -> tuple:
    return tuple(",".join(sorted(u.tags.get(f, set()))) for f in by)


def series_pick(pool: list[Unit], series: dict, rng: random.Random, group: tuple | None = None
                ) -> tuple[tuple | None, list[Unit]]:
    """Order one subject's shots in time and pick from that timeline.

    A subject is a group of units sharing the `group_by` facets (e.g. zone + angle).
    Stage is not a tag: it is the unit's position in its group's timeline, so a
    space can go through any number of intermediate states.
    pick: first | last | spread (n evenly spaced, first and last included) | all
    """
    by = series.get("group_by", ["zone", "angle"])
    groups: dict[tuple, list[Unit]] = {}
    for u in pool:
        k = group_key(u, by)
        if all(k):  # every grouping facet must be present
            groups.setdefault(k, []).append(u)
    if not groups:
        return None, []
    if group is None or group not in groups:
        need = int(series.get("min", 2 if series.get("pick") != "first" else 1))
        ok = {k: v for k, v in groups.items() if len({x.clip_id for x in v}) >= need} or groups
        group = max(ok, key=lambda k: len(ok[k]) + sum(u.score for u in ok[k]) / len(ok[k]) + rng.random())
    tl = sorted(groups[group], key=lambda u: (u.taken_at, u.start))
    pick, n = series.get("pick", "all"), int(series.get("n", 4))
    if pick == "first":
        sel = tl[:1]
    elif pick == "last":
        sel = tl[-1:]
    elif pick == "spread" and len(tl) > n:
        sel = [tl[round(i * (len(tl) - 1) / (n - 1))] for i in range(n)] if n > 1 else tl[-1:]
    else:
        sel = tl
    return group, sel


def compose(L: Layout, theme_id: str, format_id: str, seed: int = 0, cooldown_days: int = 21,
            jitter: float = 0.8) -> dict:
    con = connect(L.db)
    theme = load_yaml(L, "themes", theme_id)
    fmt = load_yaml(L, "formats", format_id)
    rng = random.Random(f"{theme_id}/{format_id}/{seed}")
    counts, recent = _recent_use(con, cooldown_days)
    cache: dict[str, list[Unit]] = {}
    chosen: dict[str, Unit] = {}
    queues: dict[str, list[Unit]] = {}
    groups: dict[str, tuple] = {}
    used: set = set()
    segments, missing = [], []

    for i, slot in enumerate(fmt["slots"]):
        for k in range(int(slot.get("count", 1))):
            beat_name = slot["beat"]
            beat = theme["beats"].get(beat_name)
            if beat is None:
                missing.append(beat_name)
                continue
            if beat_name not in cache:
                cache[beat_name] = candidates(con, beat.get("want", {}), beat.get("prefer"),
                                              {**theme.get("avoid", {}), **beat.get("avoid", {})})
            pool = cache[beat_name]
            if not pool:
                missing.append(beat_name)
                continue
            if beat.get("series") and beat_name not in queues:
                g, sel = series_pick(pool, beat["series"], rng, groups.get(beat.get("same_group_as", "")))
                queues[beat_name] = list(sel)
                if g is not None:
                    groups[beat_name] = g
            q = queues.get(beat_name)
            if q:
                u = q.pop(0)
                used.add(u.key)
                chosen.setdefault(beat_name, u)
                segments.append(_segment(i, k, slot, beat_name, beat, theme, u))
                continue
            anchor = chosen.get(beat.get("pair_with", ""))
            scored = []
            for u in pool:
                s = u.score + _pair_bonus(u, anchor) + rng.random() * jitter
                s -= 0.3 * counts.get(u.clip_id, 0)
                if u.clip_id in recent:
                    s -= 2.0
                if u.key in used:
                    s -= 5.0
                elif any(u.clip_id == x[0] for x in used):
                    s -= 1.5
                scored.append((s, u))
            u = max(scored, key=lambda x: x[0])[1]
            used.add(u.key)
            chosen.setdefault(beat_name, u)
            segments.append(_segment(i, k, slot, beat_name, beat, theme, u))

    reel_id = f"{theme_id}--{format_id}--s{seed}"
    spec = {"id": reel_id, "theme": theme_id, "format": format_id, "seed": seed,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "hook": theme.get("hook"), "caption_seed": theme.get("caption"),
            "segments": segments, "missing": sorted(set(missing))}
    d = L.reels / reel_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "spec.json").write_text(json.dumps(spec, indent=1, ensure_ascii=False))
    con.execute("INSERT OR REPLACE INTO reels(id,theme,format,seed,status,spec_path) VALUES(?,?,?,?,'draft',?)",
                (reel_id, theme_id, format_id, seed, str((d / "spec.json").relative_to(L.root))))
    con.commit()
    return spec


def _segment(i: int, k: int, slot: dict, beat_name: str, beat: dict, theme: dict, u: Unit) -> dict:
    text = slot.get("text")
    if text == "hook":
        text = theme.get("hook") if k == 0 else None
    elif text == "end":
        text = theme.get("end_text")
    elif text == "beat":
        text = beat.get("text")
    return {"slot": f"{i}.{k}", "beat": beat_name, "clip_id": u.clip_id, "path": u.path, "kind": u.kind,
            "start": u.start, "dur": float(slot.get("dur", 2.0)), "label": u.label, "text": text,
            "taken_at": u.taken_at}


def set_status(L: Layout, reel_id: str, status: str) -> None:
    con = connect(L.db)
    row = con.execute("SELECT spec_path FROM reels WHERE id=?", (reel_id,)).fetchone()
    if not row:
        raise KeyError(reel_id)
    con.execute("UPDATE reels SET status=? WHERE id=?", (status, reel_id))
    if status == "approved":
        spec = json.loads((L.root / row["spec_path"]).read_text())
        con.execute("DELETE FROM usages WHERE reel_id=?", (reel_id,))
        for s in spec["segments"]:
            con.execute("INSERT INTO usages(reel_id,clip_id,slot) VALUES(?,?,?)", (reel_id, s["clip_id"], s["slot"]))
    con.commit()
