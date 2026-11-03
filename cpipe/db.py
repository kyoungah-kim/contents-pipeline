"""SQLite catalog. Clips are theme-agnostic atoms; reels reference clips many-to-many."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS clips(
  id TEXT PRIMARY KEY,          -- content hash prefix, stable across renames
  path TEXT NOT NULL,           -- relative to data root
  kind TEXT NOT NULL,           -- video | photo
  taken_at TEXT,
  duration REAL,
  width INTEGER, height INTEGER,
  added_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS frames(
  clip_id TEXT, t REAL, path TEXT,
  PRIMARY KEY(clip_id, t)
);
-- Facet tags describe what is visible, never which theme a clip belongs to.
CREATE TABLE IF NOT EXISTS tags(
  clip_id TEXT, facet TEXT, value TEXT, source TEXT DEFAULT 'agent',
  PRIMARY KEY(clip_id, facet, value)
);
-- Usable sub-ranges inside a video (e.g. 'wide after shot' at 3.0-6.5s).
CREATE TABLE IF NOT EXISTS moments(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  clip_id TEXT, start REAL, end REAL, label TEXT
);
CREATE TABLE IF NOT EXISTS notes(clip_id TEXT PRIMARY KEY, text TEXT);
CREATE TABLE IF NOT EXISTS embeddings(clip_id TEXT, model TEXT, vec BLOB, PRIMARY KEY(clip_id, model));
CREATE TABLE IF NOT EXISTS reels(
  id TEXT PRIMARY KEY, theme TEXT, format TEXT, seed INTEGER,
  status TEXT DEFAULT 'draft',  -- draft | approved | rendered | posted | rejected
  created_at TEXT DEFAULT (datetime('now')), spec_path TEXT
);
-- Lineage: which clip went into which reel, in which slot. Drives cooldown and per-clip performance.
CREATE TABLE IF NOT EXISTS usages(
  reel_id TEXT, clip_id TEXT, slot TEXT, used_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS metrics(
  reel_id TEXT, captured_at TEXT, views INTEGER, saves INTEGER, shares INTEGER, likes INTEGER, comments INTEGER
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con
