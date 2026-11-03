# contents-pipeline

Content-agnostic functions for turning a pile of raw phone media into many short vertical reels.
This repo holds code only. All media, catalogs, themes and reels live in a separate **data root**
(default `~/home_brand`, or `CPIPE_DATA`, or `--data`), and `.gitignore` blocks media and data from being committed.

## Model

- **Clip**: one photo or video, identified by a content hash so renames and moves don't break it.
  Clips are tagged with what is visible (space, state, content, shot, action, light, quality, privacy),
  plus optional **moments** (usable sub-ranges). Clips are never assigned to a theme.
- **Theme**: a lens over the catalog, written as YAML in `<data>/themes/`. Each beat is a facet query.
  Themes can be added at any time; existing clips are re-used across themes.
- **Format**: the shape of a reel (slot order and durations). Built-ins: `reveal`, `process3`, `diff`.
  Override or add formats in `<data>/formats/`.
- **Reel** = theme × format × seed. Each seed is a different variation. Selection is many-to-many,
  with a cooldown on clips used in recently approved reels, before/after angle pairing (`pair_with`),
  and exclusion of anything tagged `privacy` or poor `quality`.
- **Lineage**: approving a reel records which clips filled which slots (`usages`), so per-clip and
  per-theme performance can be read later against `metrics`.

## Data root layout

```
<data>/raw/            drop media here, any nesting
<data>/catalog/        catalog.db, frames/, sheets/   (generated)
<data>/themes/         <theme>.yaml
<data>/formats/        optional format overrides
<data>/reels/<id>/     spec.json, draft.mp4
<data>/brand/font.ttf  optional caption font
```

## Workflow

```
cpipe init                         # create the layout
cpipe ingest                       # register new media, keyframes, contact sheets
cpipe untagged                     # what still needs tags
cpipe import-tags tags.json        # agent-written tags (see cpipe/tags.py for the format)
cpipe facets                       # current tag vocabulary
cpipe search state=before space=living
cpipe compose <theme> reveal --variants 5
cpipe render <reel-id>             # silent 1080x1920 draft; add audio in-app when posting
cpipe approve <reel-id>            # records usage for cooldown and lineage
cpipe log-metrics insights.csv
cpipe stats
```

Tagging is done by an agent reading the contact sheets in `catalog/sheets/` (a grid image plus a
JSON sidecar listing each clip's frames) and writing `tags.json`.

## Requirements

Python 3.10+, `ffmpeg`/`ffprobe` on PATH (with libfreetype for captions), `pip install -e .`.
Optional: `.[heic]` for HEIC stills, `.[embed]` for image embeddings (planned: text-to-clip search).

## Test

`pytest` runs an end-to-end pass on synthetic clips (ingest, tag, compose variants, approve, render).
