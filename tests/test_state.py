"""Saved progress: refused writes, the writer lock and older saved files."""

import json
import math
import os
import time

import pytest

from synapse_showcase.state import GuideStore


def test_invalid_writes_and_a_live_writer_lock_preserve_saved_bytes(data_file):
    store = GuideStore(data_file)
    store.step("board")
    before = data_file.read_bytes()
    for refused in (
        lambda: store.move("missing", "done"),
        lambda: store.step("body"),
        lambda: store.view({"zoom": math.inf}),
        lambda: store.add(" "),
        lambda: store.preferences(theme="unknown"),
    ):
        with pytest.raises(ValueError):
            refused()
    assert data_file.read_bytes() == before

    data_file.with_name(f"{data_file.name}.lock").mkdir()
    with pytest.raises(ValueError, match="Another guide action"):
        store.add("Do not overwrite")
    assert data_file.read_bytes() == before


def test_a_lock_left_by_a_stopped_writer_is_cleared_once_it_is_stale(data_file):
    store = GuideStore(data_file)
    store.step("board")
    lock = data_file.with_name(f"{data_file.name}.lock")
    lock.mkdir()
    old = time.time() - 60
    os.utime(lock, (old, old))
    store.add("After a crash")
    assert store.read()["cards"][-1]["title"] == "After a crash"
    assert not lock.exists()


def test_legacy_preferences_are_read_without_rewriting_and_skipping_is_not_completing(data_file):
    store = GuideStore(data_file)
    old = store.read()
    for key in ("skipped", "pace", "theme"):
        del old[key]
    data_file.parent.mkdir(parents=True)
    data_file.write_text(json.dumps(old))
    saved = data_file.read_bytes()
    assert store.read()["theme"] == "host"
    assert data_file.read_bytes() == saved

    store.step("catalog", skip=True)
    assert store.read()["skipped"] == ["catalog"]
    assert store.read()["completed"] == []
    other = GuideStore(data_file)
    other.preferences(pace="quick", theme="dark")
    store.step("build")
    other.complete("catalog")
    current = store.read()
    assert current["step"] == "build"
    assert current["skipped"] == []
    assert current["completed"] == ["catalog"]
    assert current["pace"] == "quick"
    assert current["theme"] == "dark"
