"""Scan raw/ for new media, register clips, extract keyframes, build contact sheets."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from . import media
from .config import Layout
from .db import connect
from .sheet import build_sheets


def ingest(L: Layout, sheet_cols: int = 4, sheet_rows: int = 3) -> dict:
    L.ensure()
    con = connect(L.db)
    known = {r["id"] for r in con.execute("SELECT id FROM clips")}
    new_ids, skipped, failed = [], 0, []
    files = [p for p in sorted(L.raw.rglob("*")) if p.is_file() and not p.name.startswith(".")]
    # A HEIC with a same-name JPEG next to it (e.g. from Finder > Convert Image) is superseded.
    jpeg_stems = {(p.parent, p.stem) for p in files if p.suffix.lower() in (".jpg", ".jpeg")}
    for p in files:
        k = media.kind_of(p)
        if not k:
            skipped += 1
            continue
        if p.suffix.lower() == ".heic" and (p.parent, p.stem) in jpeg_stems:
            continue
        cid = media.clip_id(p)
        rel = str(p.relative_to(L.root))
        if cid in known:
            con.execute("UPDATE clips SET path=? WHERE id=?", (rel, cid))  # follow moves
            continue
        try:
            info = media.probe(p) if k == "video" else media.probe_photo(p)
        except Exception as e:  # unreadable file: record and move on
            msg = "HEIC not decodable here; convert to JPEG (Finder > Quick Actions > Convert Image)" \
                if p.suffix.lower() == ".heic" else str(e)[:200]
            failed.append((rel, msg))
            continue
        if not info["taken_at"]:
            info["taken_at"] = datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")
        con.execute(
            "INSERT INTO clips(id,path,kind,taken_at,duration,width,height) VALUES(?,?,?,?,?,?,?)",
            (cid, rel, k, info["taken_at"], info["duration"], info["width"], info["height"]),
        )
        for t, fp in media.extract_frames(p, L.frames / cid, k, info["duration"]):
            con.execute("INSERT OR IGNORE INTO frames VALUES(?,?,?)", (cid, t, str(fp.relative_to(L.root))))
        known.add(cid)
        new_ids.append(cid)
    con.commit()
    batch = datetime.now().strftime("%Y%m%d-%H%M%S")
    sheets = build_sheets(L, con, new_ids, batch, sheet_cols * sheet_rows, sheet_cols) if new_ids else []
    return {"new": len(new_ids), "skipped": skipped, "failed": failed, "sheets": [str(s) for s in sheets], "batch": batch}
