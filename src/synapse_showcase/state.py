"""Saved guide progress and the practice board, kept as one version 1 JSON file."""

import json
import math
import os
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeGuard

from synapse_showcase.content import CATALOG, FOCUS, STEP_IDS, STEPS

# A writer holds the lock for one read and replace, which takes milliseconds.
STALE_LOCK_SECONDS = 10.0
UNREADABLE = "The saved walkthrough could not be read. Its file was left unchanged."
BUSY = "Another guide action is finishing. Read the current state, then try again."
STATUSES = ("todo", "doing", "done")
MAX_SAFE_INTEGER = 2**53 - 1

State = dict[str, Any]


def fresh() -> State:
    return {
        "version": 1,
        "revision": 0,
        "step": "welcome",
        "completed": [],
        "skipped": [],
        "pace": "guided",
        "theme": "host",
        "view": {"zoom": 1, "playing": False, "focus": "shared"},
        "cards": [
            {"id": "first", "title": "Try moving this task", "status": "todo"},
            {"id": "second", "title": "Explore an app together", "status": "todo"},
        ],
    }


def _number(value: Any) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _compact(state: State) -> str:
    return json.dumps(state, separators=(",", ":"), ensure_ascii=False)


class GuideStore:
    """One saved guide shared by every process that opens the same file.

    Writes take a short lock directory beside the file and replace the file atomically, so an
    HTTP server and any stdio connection can share progress without losing a change. Reads never
    rewrite the file, and a file that cannot be read is reported and left as it was.
    """

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)

    def read(self) -> State:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return fresh()
        try:
            state = json.loads(text)
        except ValueError:
            raise ValueError(UNREADABLE) from None
        revision = state.get("revision") if isinstance(state, dict) else None
        if (
            not isinstance(state, dict)
            or not (_number(state.get("version")) and state["version"] == 1)
            or not (_number(revision) and float(revision).is_integer())
            or abs(revision) > MAX_SAFE_INTEGER
            or state.get("step") not in STEP_IDS
            or not isinstance(state.get("cards"), list)
            or not isinstance(state.get("completed"), list)
            or not isinstance(state.get("view"), dict)
        ):
            raise ValueError(UNREADABLE)
        state["revision"] = int(revision)
        # Older guides gain the newer optional preferences in memory; reading never rewrites them.
        return {
            **state,
            "skipped": state["skipped"] if isinstance(state.get("skipped"), list) else [],
            "pace": "quick" if state.get("pace") == "quick" else "guided",
            "theme": state["theme"] if state.get("theme") in ("light", "dark") else "host",
        }

    def change(self, edit: Callable[[State], None]) -> State:
        """Apply one edit under the file lock. An edit that changes nothing writes nothing."""
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock = self.path.with_name(f"{self.path.name}.lock")
        self._lock(lock)
        try:
            state = self.read()
            before = _compact(state)
            edit(state)
            if _compact(state) == before:
                return state
            state["revision"] += 1
            temporary = self.path.with_name(f"{self.path.name}.tmp-{os.getpid()}")
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(state, indent=2, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            return state
        finally:
            os.rmdir(lock)

    def _lock(self, lock: Path) -> None:
        try:
            lock.mkdir()
            return
        except FileExistsError:
            pass
        # A lock older than STALE_LOCK_SECONDS was left by a process that stopped mid-write.
        # Clear it once and retry; a lock that is still fresh belongs to a live writer.
        try:
            held = lock.stat().st_mtime
        except FileNotFoundError:
            held = None
        if held is not None and time.time() - held < STALE_LOCK_SECONDS:
            raise ValueError(BUSY)
        try:
            if held is not None:
                lock.rmdir()
            lock.mkdir()
        except OSError:
            raise ValueError(BUSY) from None

    def step(self, step_id: str, complete: bool = False, skip: bool = False) -> State:
        step = next((item for item in STEPS if item["id"] == step_id), None)
        if step is None:
            raise ValueError("Choose a step from guide_status.")
        if complete and skip:
            raise ValueError("A step can be completed or skipped, not both.")

        def edit(state: State) -> None:
            state["step"] = step_id
            state["view"]["focus"] = step["target"]
            if complete:
                _mark_complete(state, step_id)
            if skip and step_id not in state["completed"] and step_id not in state["skipped"]:
                state["skipped"].append(step_id)

        return self.change(edit)

    def complete(self, step_id: str) -> State:
        if step_id not in STEP_IDS:
            raise ValueError("Choose a step from guide_status.")
        return self.change(lambda state: _mark_complete(state, step_id))

    def preferences(self, pace: str | None = None, theme: str | None = None) -> State:
        if pace is not None and pace not in ("guided", "quick"):
            raise ValueError("Choose guided or quick.")
        if theme is not None and theme not in ("host", "light", "dark"):
            raise ValueError("Choose host, light or dark.")

        def edit(state: State) -> None:
            if pace:
                state["pace"] = pace
            if theme:
                state["theme"] = theme

        return self.change(edit)

    def connected(self) -> State:
        def edit(state: State) -> None:
            now = datetime.now(UTC).isoformat(timespec="milliseconds")
            state["agentCheck"] = now.replace("+00:00", "Z")
            _mark_complete(state, "agents")

        return self.change(edit)

    def view(self, changes: dict[str, Any]) -> State:
        """Change only the given view fields; a focus of None clears the highlight."""
        changes = dict(changes)
        if "zoom" in changes:
            zoom = changes["zoom"]
            if not _number(zoom) or not math.isfinite(zoom) or not 0.75 <= zoom <= 1.6:
                raise ValueError("Zoom must be between 0.75 and 1.6.")
            # JSON numbers have one type: 1.0 and 1 are the same zoom and save the same bytes.
            changes["zoom"] = int(zoom) if float(zoom).is_integer() else zoom
        focus = changes.get("focus")
        if focus is not None and focus not in FOCUS:
            raise ValueError("Choose a known guide focus target.")
        return self.change(lambda state: state["view"].update(changes))

    def add(self, title: str) -> State:
        clean = title.strip()
        if not clean or len(clean) > 120:
            raise ValueError("Use 1–120 characters for a sample task.")

        def edit(state: State) -> None:
            if len(state["cards"]) >= 100:
                raise ValueError("This practice board holds up to 100 cards.")
            state["cards"].append({"id": str(uuid.uuid4()), "title": clean, "status": "todo"})
            _mark_complete(state, "board")

        return self.change(edit)

    def move(self, card_id: str, status: str) -> State:
        if status not in STATUSES:
            raise ValueError("Choose todo, doing, or done.")

        def edit(state: State) -> None:
            card = next((item for item in state["cards"] if item.get("id") == card_id), None)
            if card is None:
                raise ValueError(
                    "That sample task is no longer on this board. Read the board again."
                )
            if card.get("status") != status:
                card["status"] = status
                _mark_complete(state, "board")

        return self.change(edit)

    def catalogue(self, query: str = "") -> list[dict[str, Any]]:
        needle = query.strip().lower()
        return [
            dict(item)
            for item in CATALOG
            if needle in f"{item['title']} {item['description']}".lower()
        ]


def _mark_complete(state: State, step_id: str) -> None:
    if step_id not in state["completed"]:
        state["completed"].append(step_id)
    state["skipped"] = [step for step in state["skipped"] if step != step_id]
