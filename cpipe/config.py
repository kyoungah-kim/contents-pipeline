"""Data-root layout. All content lives outside this repo, under one data root."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ROOT = "~/home_brand"


@dataclass(frozen=True)
class Layout:
    root: Path

    @property
    def raw(self) -> Path: return self.root / "raw"
    @property
    def catalog_dir(self) -> Path: return self.root / "catalog"
    @property
    def db(self) -> Path: return self.catalog_dir / "catalog.db"
    @property
    def frames(self) -> Path: return self.catalog_dir / "frames"
    @property
    def sheets(self) -> Path: return self.catalog_dir / "sheets"
    @property
    def themes(self) -> Path: return self.root / "themes"
    @property
    def formats(self) -> Path: return self.root / "formats"  # optional overrides
    @property
    def reels(self) -> Path: return self.root / "reels"

    def ensure(self) -> "Layout":
        for p in (self.raw, self.frames, self.sheets, self.themes, self.formats, self.reels):
            p.mkdir(parents=True, exist_ok=True)
        return self


def layout(root: str | None = None) -> Layout:
    r = root or os.environ.get("CPIPE_DATA") or DEFAULT_ROOT
    return Layout(Path(r).expanduser().resolve())
