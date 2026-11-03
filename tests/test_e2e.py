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
