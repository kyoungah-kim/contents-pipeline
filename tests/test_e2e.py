"""End-to-end on synthetic media: ingest -> tag -> compose variants -> approve -> render."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from cpipe.compose import compose, set_status
from cpipe.config import layout
from cpipe.db import connect
from cpipe.ingest import ingest
from cpipe.render import render
from cpipe.tags import import_tags, untagged

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")


def _video(p: Path, color: str, secs: int = 4):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=640x360:d={secs}",
                    "-pix_fmt", "yuv420p", str(p)], check=True)


THEME = """
id: t
hook: "Hook text"
end_text: "End"
beats:
  before: {want: {state: [before]}}
  after:  {want: {state: [after]}, pair_with: before}
  detail: {want: {shot: [closeup]}}
"""


def test_pipeline(tmp_path):
    L = layout(str(tmp_path)).ensure()
    colors = ["red", "green", "blue", "yellow", "white", "gray"]
    for i, c in enumerate(colors):
        _video(L.raw / f"clip{i}.mp4", c, 3 + i % 2)
    r = ingest(L)
    assert r["new"] == 6 and r["sheets"]
    assert Path(r["sheets"][0]).exists()
    assert ingest(L)["new"] == 0  # idempotent

    ids = [u["id"] for u in untagged(L)]
    tags = {
        ids[0]: {"state": ["before"], "space": ["room-a"], "angle": ["a1"]},
        ids[1]: {"state": ["after"], "space": ["room-a"], "angle": ["a1"]},
        ids[2]: {"state": ["after"], "space": ["room-b"]},
        ids[3]: {"shot": ["closeup"], "state": ["detail"]},
        ids[4]: {"shot": ["closeup"], "state": ["detail"], "moments": [{"start": 0.5, "end": 2.0, "label": "m"}]},
        ids[5]: {"state": ["before"], "privacy": ["face"]},  # must be excluded
    }
    tf = tmp_path / "tags.json"; tf.write_text(json.dumps(tags))
    assert import_tags(L, tf) == 6
    (L.themes / "t.yaml").write_text(THEME)

    specs = [compose(L, "t", "reveal", seed=s) for s in range(3)]
    for sp in specs:
        assert not sp["missing"]
        used = {s["clip_id"] for s in sp["segments"]}
        assert ids[5] not in used                      # privacy-flagged clip never used
        assert sp["segments"][1]["clip_id"] == ids[1]  # after paired to same angle as before

    set_status(L, specs[0]["id"], "approved")
    con = connect(L.db)
    assert con.execute("SELECT COUNT(*) FROM usages").fetchone()[0] == len(specs[0]["segments"])

    out = render(L, specs[0]["id"])
    assert out.exists() and out.stat().st_size > 0
    info = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                           "stream=width,height", "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout
    assert info.strip() == "1080,1920"


SERIES_THEME = """
id: s
hook: "Hook"
end_text: "End"
beats:
  timeline: {want: {space: [room]}, series: {group_by: [zone, angle], pick: spread, n: 3, min: 3}}
  final: {want: {space: [room]}, series: {group_by: [zone, angle], pick: last}, same_group_as: timeline}
"""


def test_series_timeline(tmp_path):
    L = layout(str(tmp_path)).ensure()
    for i, c in enumerate(["red", "orange", "yellow", "green", "blue"]):
        _video(L.raw / f"s{i}.mp4", c, 2)
    ingest(L)
    con = connect(L.db)
    rows = con.execute("SELECT id, path FROM clips ORDER BY path").fetchall()
    # five stages of one subject, capture times deliberately out of file-name order
    times = ["2026-11-05", "2026-11-01", "2026-11-03", "2026-11-09", "2026-11-07"]
    for (cid, _), t in zip(rows, times):
        con.execute("UPDATE clips SET taken_at=? WHERE id=?", (t, cid))
    con.commit()
    tags = {cid: {"space": ["room"], "zone": ["shelf"], "angle": ["front"]} for cid, _ in rows}
    tf = tmp_path / "t.json"; tf.write_text(json.dumps(tags)); import_tags(L, tf)
    (L.themes / "s.yaml").write_text(SERIES_THEME)
    spec = compose(L, "s", "progress")
    by_time = [cid for _, cid in sorted((t, r[0]) for r, t in zip(rows, times))]
    seg = [s["clip_id"] for s in spec["segments"]]
    assert seg[:3] == [by_time[0], by_time[2], by_time[4]]  # spread: first, middle, last in time
    assert seg[-1] == by_time[-1]                            # final = latest stage
    assert spec["segments"][0]["text"] == "Hook" and spec["segments"][1]["text"] is None
