"""Thread-safe snapshot of what the robot is doing, for the web UI.

The conversation runs in a background thread with its own event loop; Gradio
callbacks run on the main thread. Rather than reach across that boundary with
locks scattered through the app, everything the UI needs is pushed into this
one object and read back as an immutable snapshot.

Deliberately a plain object with a lock: the UI polls a few times a second, so
there is nothing here that warrants asyncio primitives, and a plain lock can be
touched from either side without caring which loop is running.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

# What the robot is doing right now, in the order a turn goes through.
PHASE_IDLE = "idle"
PHASE_LISTENING = "listening"
PHASE_THINKING = "thinking"
PHASE_SPEAKING = "speaking"


@dataclass
class Health:
    """One line per subsystem, for the status strip."""

    robot: bool = False
    openclaw: bool = False
    realtime: bool = False
    mcp_tools: int = 0
    camera: bool = False
    tracking_hz: float = 0.0


@dataclass
class UiState:
    """Everything the UI shows. Every accessor takes the lock."""

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # Conversation, capped: this is a live view, not an archive.
    _turns: deque = field(default_factory=lambda: deque(maxlen=200), repr=False)
    _turn_seq: int = 0

    _phase: str = PHASE_IDLE
    _phase_since: float = field(default_factory=time.monotonic)
    _detail: str = ""

    _health: Health = field(default_factory=Health)
    _error: Optional[str] = None
    _running: bool = False
    _started_at: Optional[float] = None

    # ------------------------------------------------------------------
    # Conversation
    # ------------------------------------------------------------------

    def add_turn(self, role: str, content: str) -> None:
        if not content or not content.strip():
            return
        with self._lock:
            self._turn_seq += 1
            self._turns.append(
                {"role": role, "content": content.strip(), "at": time.time()}
            )

    def turns(self) -> tuple[list[dict], int]:
        """Returns (messages, sequence). The sequence lets the UI skip
        rebuilding the transcript when nothing was said."""
        with self._lock:
            return (
                [{"role": t["role"], "content": t["content"]} for t in self._turns],
                self._turn_seq,
            )

    # ------------------------------------------------------------------
    # Phase
    # ------------------------------------------------------------------

    def set_phase(self, phase: str, detail: str = "") -> None:
        with self._lock:
            if phase != self._phase:
                self._phase_since = time.monotonic()
            self._phase = phase
            self._detail = detail

    def phase(self) -> tuple[str, str, float]:
        with self._lock:
            return self._phase, self._detail, time.monotonic() - self._phase_since

    # ------------------------------------------------------------------
    # Health / lifecycle
    # ------------------------------------------------------------------

    def update_health(self, **kwargs: Any) -> None:
        with self._lock:
            for k, v in kwargs.items():
                if hasattr(self._health, k):
                    setattr(self._health, k, v)

    def health(self) -> Health:
        with self._lock:
            return Health(**vars(self._health))

    def set_running(self, running: bool) -> None:
        with self._lock:
            self._running = running
            self._started_at = time.monotonic() if running else None
            if not running:
                self._phase = PHASE_IDLE
                self._detail = ""

    def running(self) -> tuple[bool, float]:
        with self._lock:
            uptime = (
                time.monotonic() - self._started_at if self._started_at else 0.0
            )
            return self._running, uptime

    def set_error(self, message: Optional[str]) -> None:
        """A failure the user must see. The UI surfaces it instead of leaving
        a stale 'Started successfully' on screen while nothing works."""
        with self._lock:
            self._error = message

    def error(self) -> Optional[str]:
        with self._lock:
            return self._error

    def reset(self) -> None:
        with self._lock:
            self._turns.clear()
            self._turn_seq = 0
            self._phase = PHASE_IDLE
            self._detail = ""
            self._error = None
            self._running = False
            self._started_at = None
            self._health = Health()


# One instance for the process. The UI and the conversation thread both import
# it rather than passing it through every constructor.
STATE = UiState()
