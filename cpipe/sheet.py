"""Contact sheets: one labelled grid image per page of clips, for fast agent tagging.

Each cell shows a clip's middle keyframe plus a strip of up to 4 frames, labelled
with the clip id, kind and duration. A JSON sidecar maps cells to clip ids and
lists every frame path, so a tagger can open individual frames when it needs detail.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from PIL import Image, ImageDraw

from .config import Layout

CELL_W, CELL_H, STRIP_H, LABEL_H = 360, 270, 60, 22


def _cell(L: Layout, con: sqlite3.Connection, cid: str) -> tuple[Image.Image, dict]:
    clip = con.execute("SELECT * FROM clips WHERE id=?", (cid,)).fetchone()
    frames = [L.root / r["path"] for r in con.execute("SELECT path FROM frames WHERE clip_id=? ORDER BY t", (cid,))]
    img = Image.new("RGB", (CELL_W, CELL_H + STRIP_H + LABEL_H), (245, 245, 242))
    if frames:
        mid = Image.open(frames[len(frames) // 2]).convert("RGB")
        mid.thumbnail((CELL_W, CELL_H))
        img.paste(mid, ((CELL_W - mid.width) // 2, LABEL_H + (CELL_H - mid.height) // 2))
        picks = frames[:: max(1, len(frames) // 4)][:4]
        sw = CELL_W // 4
        for i, f in enumerate(picks):
            th = Image.open(f).convert("RGB")
            th.thumbnail((sw - 2, STRIP_H - 2))
            img.paste(th, (i * sw + 1, LABEL_H + CELL_H + 1))
    d = ImageDraw.Draw(img)
    dur = f"{clip['duration']:.1f}s" if clip["duration"] else "photo"
    d.rectangle([0, 0, CELL_W, LABEL_H], fill=(30, 42, 38))
    d.text((6, 4), f"{cid}  {clip['kind']}  {dur}", fill=(255, 255, 255))
    meta = {"clip_id": cid, "path": clip["path"], "kind": clip["kind"], "duration": clip["duration"],
            "taken_at": clip["taken_at"], "frames": [str(f.relative_to(L.root)) for f in frames]}
    return img, meta


def build_sheets(L: Layout, con: sqlite3.Connection, ids: list[str], batch: str,
                 per_page: int = 12, cols: int = 4) -> list[Path]:
    out = []
    for page, start in enumerate(range(0, len(ids), per_page)):
        chunk = ids[start:start + per_page]
        cells = [_cell(L, con, c) for c in chunk]
        rows = (len(cells) + cols - 1) // cols
        cw, ch = cells[0][0].size
        sheet = Image.new("RGB", (cw * cols + 4 * (cols - 1), ch * rows + 4 * (rows - 1)), (200, 205, 200))
        for i, (im, _) in enumerate(cells):
            sheet.paste(im, ((i % cols) * (cw + 4), (i // cols) * (ch + 4)))
        p = L.sheets / f"{batch}-p{page + 1:02d}.jpg"
        sheet.save(p, quality=85)
        p.with_suffix(".json").write_text(json.dumps([m for _, m in cells], indent=1, ensure_ascii=False))
        out.append(p)
    return out
