"""Locate bundled assets in an installed wheel or a checkout."""

from pathlib import Path


def asset_root() -> Path:
    packaged = Path(__file__).with_name("assets")
    return packaged if packaged.is_dir() else Path(__file__).resolve().parents[2]
