"""Render a reel spec to a silent 1080x1920 draft (audio is added in-app at posting time)."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from .config import Layout
from .db import connect

W, H, FPS = 1080, 1920, 30
FONT_CANDIDATES = [
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def find_font(L: Layout) -> str | None:
    for p in [os.environ.get("CPIPE_FONT"), str(L.root / "brand" / "font.ttf"), *FONT_CANDIDATES]:
        if p and Path(p).exists():
            return p
    return None


def _segment(src: Path, kind: str, start: float, dur: float, text: str | None, font: str | None,
             out: Path, tmp: Path) -> None:
    vf = [f"scale={W}:{H}:force_original_aspect_ratio=increase", f"crop={W}:{H}", f"fps={FPS}", "setsar=1",
          f"tpad=stop_mode=clone:stop_duration={dur}"]
    if text and font:
        tf = tmp / f"{out.stem}.txt"
        tf.write_text(text)
        # Top safe zone: clear of the Reels header and the caption/buttons at the bottom.
        vf.append(f"drawtext=fontfile='{font}':textfile='{tf}':fontsize=64:fontcolor=white:"
                  f"box=1:boxcolor=black@0.35:boxborderw=24:x=(w-text_w)/2:y=h*0.16")
    cmd = ["ffmpeg", "-v", "error", "-y"]
    cmd += ["-loop", "1", "-t", str(dur), "-i", str(src)] if kind == "photo" else ["-ss", str(start), "-t", str(dur), "-i", str(src)]
    cmd += ["-vf", ",".join(vf), "-t", str(dur), "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", str(out)]
    subprocess.run(cmd, check=True)


def render(L: Layout, reel_id: str) -> Path:
    con = connect(L.db)
    row = con.execute("SELECT spec_path FROM reels WHERE id=?", (reel_id,)).fetchone()
    if not row:
        raise KeyError(reel_id)
    spec = json.loads((L.root / row["spec_path"]).read_text())
    font = find_font(L)
    out = L.reels / reel_id / "draft.mp4"
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        parts = []
        for i, s in enumerate(spec["segments"]):
            p = tmp / f"seg{i:02d}.mp4"
            _segment(L.root / s["path"], s["kind"], s["start"], s["dur"], s.get("text"), font, p, tmp)
            parts.append(p)
        lst = tmp / "list.txt"
        lst.write_text("".join(f"file '{p}'\n" for p in parts))
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-c", "copy", "-movflags", "+faststart", str(out)], check=True)
    con.execute("UPDATE reels SET status='rendered' WHERE id=? AND status IN ('draft','approved')", (reel_id,))
    con.commit()
    return out
