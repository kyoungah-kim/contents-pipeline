"""ffprobe / ffmpeg helpers."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

VIDEO_EXT = {".mov", ".mp4", ".m4v"}
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".heic"}
CHUNK = 1 << 20


def kind_of(p: Path) -> str | None:
    e = p.suffix.lower()
    return "video" if e in VIDEO_EXT else "photo" if e in PHOTO_EXT else None


def clip_id(p: Path) -> str:
    """Fast stable id: size + first and last MiB. Survives renames and moves."""
    h = hashlib.sha1()
    size = p.stat().st_size
    h.update(str(size).encode())
    with p.open("rb") as f:
        h.update(f.read(CHUNK))
        if size > CHUNK:
            f.seek(max(size - CHUNK, CHUNK))
            h.update(f.read(CHUNK))
    return h.hexdigest()[:12]


def probe(p: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(p)],
        capture_output=True, text=True, check=True,
    ).stdout
    info = json.loads(out)
    v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    w, h = v.get("width"), v.get("height")
    rot = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(sd["rotation"])
    if abs(rot) in (90, 270) and w and h:
        w, h = h, w
    tags = {**info.get("format", {}).get("tags", {}), **v.get("tags", {})}
    taken = tags.get("com.apple.quicktime.creationdate") or tags.get("creation_time")
    dur = info.get("format", {}).get("duration")
    return {"width": w, "height": h, "duration": float(dur) if dur else None, "taken_at": taken}


def extract_frames(src: Path, out_dir: Path, kind: str, duration: float | None,
                   every: float = 2.0, max_frames: int = 12) -> list[tuple[float, Path]]:
    """Small JPEG keyframes (480px tall) for agent vision and contact sheets."""
    out_dir.mkdir(parents=True, exist_ok=True)
    if kind == "photo" or not duration:
        times = [0.0]
    else:
        n = max(1, min(max_frames, int(duration // every) + 1))
        step = duration / n
        times = [round(step * i + step / 2, 2) for i in range(n)]
    res = []
    for t in times:
        dst = out_dir / f"{t:07.2f}.jpg"
        if not dst.exists():
            cmd = ["ffmpeg", "-v", "error", "-y"]
            if kind == "video":
                cmd += ["-ss", str(t)]
            cmd += ["-i", str(src), "-frames:v", "1", "-vf", "scale=-2:480", "-q:v", "4", str(dst)]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0 or not dst.exists():
                continue
        res.append((t, dst))
    return res
