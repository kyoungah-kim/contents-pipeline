"""cpipe CLI. Every command takes --data (or CPIPE_DATA) pointing at the content root."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from .config import layout


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cpipe")
    ap.add_argument("--data", help="content root (default: $CPIPE_DATA or ~/home_brand)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="create the data-root folder layout")
    sub.add_parser("ingest", help="register new media in raw/, extract frames, build contact sheets")
    sub.add_parser("untagged", help="list clips that have no tags yet")
    p = sub.add_parser("import-tags", help="load agent tags from a JSON file"); p.add_argument("file")
    p.add_argument("--source", default="agent")
    sub.add_parser("facets", help="show tag vocabulary with counts")
    p = sub.add_parser("search", help="find units: facet=value[,value] ...")
    p.add_argument("query", nargs="+")
    p = sub.add_parser("compose", help="draft reel specs for a theme and format")
    p.add_argument("theme"); p.add_argument("format")
    p.add_argument("--variants", type=int, default=3); p.add_argument("--seed", type=int, default=0)
    p.add_argument("--cooldown", type=int, default=21)
    for name in ("approve", "reject", "posted"):
        p = sub.add_parser(name); p.add_argument("reel")
    p = sub.add_parser("render", help="render a reel spec to reels/<id>/draft.mp4"); p.add_argument("reel")
    p = sub.add_parser("log-metrics", help="import CSV: reel_id,captured_at,views,saves,shares,likes,comments")
    p.add_argument("file")
    sub.add_parser("stats")
    a = ap.parse_args(argv)
    L = layout(a.data)

    if a.cmd == "init":
        L.ensure(); print(L.root)
    elif a.cmd == "ingest":
        from .ingest import ingest
        print(json.dumps(ingest(L), indent=1, ensure_ascii=False))
    elif a.cmd == "untagged":
        from .tags import untagged
        print(json.dumps(untagged(L), indent=1, ensure_ascii=False))
    elif a.cmd == "import-tags":
        from .tags import import_tags
        print(f"tagged {import_tags(L, Path(a.file), a.source)} clips")
    elif a.cmd == "facets":
        from .tags import facet_counts
        print(json.dumps(facet_counts(L), indent=1, ensure_ascii=False))
    elif a.cmd == "search":
        from .db import connect
        from .search import candidates
        want = {}
        for q in a.query:
            f, _, v = q.partition("=")
            want[f] = v.split(",")
        for u in candidates(connect(L.db), want)[:30]:
            print(f"{u.score:5.2f}  {u.clip_id}  {u.start:6.1f}-{u.end or 0:6.1f}  {u.label}  {u.path}")
    elif a.cmd == "compose":
        from .compose import compose
        for s in range(a.seed, a.seed + a.variants):
            spec = compose(L, a.theme, a.format, s, a.cooldown)
            clips = ",".join(x["clip_id"] for x in spec["segments"])
            miss = f"  missing={spec['missing']}" if spec["missing"] else ""
            print(f"{spec['id']}  [{clips}]{miss}")
    elif a.cmd in ("approve", "reject", "posted"):
        from .compose import set_status
        set_status(L, a.reel, {"approve": "approved", "reject": "rejected", "posted": "posted"}[a.cmd])
        print(f"{a.reel}: {a.cmd}")
    elif a.cmd == "render":
        from .render import render
        print(render(L, a.reel))
    elif a.cmd == "log-metrics":
        from .db import connect
        con = connect(L.db)
        with open(a.file, newline="") as f:
            rows = [(r["reel_id"], r["captured_at"], int(r["views"]), int(r["saves"]), int(r["shares"]),
                     int(r["likes"]), int(r["comments"])) for r in csv.DictReader(f)]
        con.executemany("INSERT INTO metrics VALUES(?,?,?,?,?,?,?)", rows); con.commit()
        print(f"logged {len(rows)} rows")
    elif a.cmd == "stats":
        from .db import connect
        con = connect(L.db)
        q = lambda s: con.execute(s).fetchone()[0]
        out = {"clips": q("SELECT COUNT(*) FROM clips"),
               "tagged": q("SELECT COUNT(DISTINCT clip_id) FROM tags"),
               "videos": q("SELECT COUNT(*) FROM clips WHERE kind='video'"),
               "minutes": round((q("SELECT COALESCE(SUM(duration),0) FROM clips") or 0) / 60, 1),
               "reels": {r[0]: r[1] for r in con.execute("SELECT status, COUNT(*) FROM reels GROUP BY status")}}
        print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
