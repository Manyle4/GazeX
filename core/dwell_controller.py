"""
core/dwell_controller.py
========================

DwellController — a self-contained state machine for gaze dwell selection.

Completely decoupled from the GUI. Accepts gaze coordinates and timestamps,
returns state snapshots that the UI renders. No Tkinter imports, no pyautogui,
no side effects.

State machine:
    IDLE → DWELLING → SELECTED → (blink) → ACTIVATED → IDLE

Hysteresis design:
    - Entry: gaze must enter entry_radius to begin dwelling
    - Hold:  gaze can leave up to hold_radius for up to grace_seconds
             without resetting the timer (pause, not cancel)
    - Exit:  gaze must leave hold_radius AND stay outside for grace_seconds
             before the timer fully resets
"""

import time
import math
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Any


class DwellState(Enum):
    IDLE     = auto()   # no button targeted
    DWELLING = auto()   # accumulating dwell time toward a button
    SELECTED = auto()   # dwell complete, waiting for blink confirmation
    COOLDOWN = auto()   # post-click freeze before accepting new dwells


@dataclass
class DwellSnapshot:
    """
    Immutable snapshot of dwell state for the GUI to render.
    Produced by DwellController.update() on every call.
    """
    state:           DwellState
    target:          Optional[Any]    # the button object, or None
    progress:        float            # 0.0 → 1.0 dwell fill
    can_click:       bool             # True when SELECTED and hold time met
    status_text:     str              # human-readable status for display
    move_cursor_to:  Optional[Any] = None # button to move cursor to, or None


class DwellController:
    """
    Gaze dwell state machine.

    Usage:
        controller = DwellController(buttons_list)

        # Every tick:
        snapshot = controller.update(gx, gy)

        # On blink:
        activated_button = controller.on_blink()
    """

    def __init__(
        self,
        entry_radius:      float = 160.0,   # px — start dwelling when inside this
        hold_radius:       float = 220.0,   # px — grace zone, timer pauses not resets
        dwell_seconds:     float = 1.2,     # seconds to fill the dwell bar
        grace_seconds:     float = 0.4,     # seconds outside hold_radius before reset
        min_hold_seconds:  float = 0.3,     # seconds after SELECTED before blink fires
        cooldown_seconds:  float = 1.0,     # seconds after click before new dwell
    ):
        self.entry_radius     = entry_radius
        self.hold_radius      = hold_radius
        self.dwell_seconds    = dwell_seconds
        self.grace_seconds    = grace_seconds
        self.min_hold_seconds = min_hold_seconds
        self.cooldown_seconds = cooldown_seconds

        # ── State ─────────────────────────────────────────────────────────
        self._state:         DwellState   = DwellState.IDLE
        self._target:        Optional[Any] = None   # current button
        self._selected:      Optional[Any] = None   # confirmed selected button

        # ── Timing ────────────────────────────────────────────────────────
        # All times are from time.monotonic() — never frame counts
        self._dwell_start:    float = 0.0   # when dwelling began on _target
        self._dwell_accum:    float = 0.0   # accumulated dwell seconds (survives grace)
        self._exit_start:     float = 0.0   # when gaze left hold_radius
        self._selected_at:    float = 0.0   # when SELECTED state was entered
        self._cooldown_start: float = 0.0   # when cooldown began

        # ── Registered buttons ────────────────────────────────────────────
        self._buttons: list = []

    # ── Public API ────────────────────────────────────────────────────────

    def set_buttons(self, buttons: list) -> None:
        """Register the list of Tkinter buttons to evaluate proximity against."""
        self._buttons = buttons

    def update(self, gx: float, gy: float) -> DwellSnapshot:
        """
        Feed a new gaze coordinate. Returns a DwellSnapshot describing
        the current state for the GUI to render.

        Call this once per tick from the UI thread.
        """
        now = time.monotonic()

        if self._state == DwellState.COOLDOWN:
            return self._handle_cooldown(now)

        if self._state == DwellState.SELECTED:
            return self._handle_selected(gx, gy, now)

        if self._state == DwellState.DWELLING:
            return self._handle_dwelling(gx, gy, now)

        # IDLE
        return self._handle_idle(gx, gy, now)

    def on_blink(self) -> Optional[Any]:
        """
        Called when an intentional blink is detected.
        Returns the button to activate, or None if no button is ready.

        The caller is responsible for invoking the button.
        """
        now = time.monotonic()

        if self._state != DwellState.SELECTED:
            return None

        if (now - self._selected_at) < self.min_hold_seconds:
            # Selection completed too recently — likely an accidental blink
            # during the dwell fill animation. Ignore it.
            return None

        btn = self._selected
        self._enter_cooldown(now)
        return btn

    def reset(self) -> None:
        """Force back to IDLE — call when the window closes or view changes."""
        self._state    = DwellState.IDLE
        self._target   = None
        self._selected = None
        self._dwell_accum = 0.0

    # ── State handlers ────────────────────────────────────────────────────

    def _handle_idle(self, gx: float, gy: float, now: float) -> DwellSnapshot:
        closest, dist = self._find_closest(gx, gy, self.entry_radius)

        if closest is None:
            return DwellSnapshot(
                state=DwellState.IDLE,
                target=None,
                progress=0.0,
                can_click=False,
                status_text="Look at a button to begin",
            )

        # Gaze entered entry_radius — begin dwelling
        self._target      = closest
        self._dwell_accum = 0.0
        self._dwell_start = now
        self._state       = DwellState.DWELLING

        return DwellSnapshot(
            state=DwellState.DWELLING,
            target=closest,
            progress=0.0,
            can_click=False,
            status_text=f"Dwelling: {self._btn_name(closest)}  0%",
        )

    def _handle_dwelling(self, gx: float, gy: float, now: float) -> DwellSnapshot:
        target = self._target
        cx, cy = self._btn_center(target)
        dist   = math.hypot(gx - cx, gy - cy)

        # Only consider switching if gaze is outside the hold zone
        # AND another button is meaningfully closer.
        # "Meaningfully" = at least 60px closer, not just 1px.
        # This prevents jitter between adjacent buttons from resetting the timer.
        SWITCH_MARGIN = 60.0

        if dist > self.hold_radius:
            # Gaze left current button — check if switching to another
            other, other_dist = self._find_closest(gx, gy, self.entry_radius)

            if other is not None and other is not target:
                current_dist_to_other_center = math.hypot(
                    gx - self._btn_center(other)[0],
                    gy - self._btn_center(other)[1],
                )
                dist_to_current = dist  # already computed above

                # Only switch if the other button is SIGNIFICANTLY closer
                if dist_to_current - current_dist_to_other_center > SWITCH_MARGIN:
                    self._target      = other
                    self._dwell_accum = 0.0
                    self._dwell_start = now
                    self._exit_start  = 0.0
                    return DwellSnapshot(
                        state=DwellState.DWELLING,
                        target=other,
                        progress=0.0,
                        can_click=False,
                        status_text=f"Dwelling: {self._btn_name(other)}  0%",
                    )

            # Not switching — handle as normal exit/grace
            if self._exit_start == 0.0:
                self._exit_start = now

            time_outside = now - self._exit_start

            if time_outside >= self.grace_seconds:
                self._state       = DwellState.IDLE
                self._target      = None
                self._dwell_accum = 0.0
                self._exit_start  = 0.0
                return DwellSnapshot(
                    state=DwellState.IDLE,
                    target=None,
                    progress=0.0,
                    can_click=False,
                    status_text="Look at a button to begin",
                )

            # Within grace period — preserve progress
            progress = self._dwell_accum / self.dwell_seconds
            return DwellSnapshot(
                state=DwellState.DWELLING,
                target=target,
                progress=progress,
                can_click=False,
                status_text=f"Holding: {self._btn_name(target)}  {int(progress * 100)}%",
            )

        # Gaze inside hold zone — accumulate
        self._dwell_accum = min(
            self.dwell_seconds,
            self._dwell_accum + (now - self._dwell_start)
        )
        self._dwell_start = now
        self._exit_start  = 0.0

        progress = self._dwell_accum / self.dwell_seconds

        if self._dwell_accum >= self.dwell_seconds:
            self._selected    = target
            self._selected_at = now
            self._state       = DwellState.SELECTED
            return DwellSnapshot(
                state=DwellState.SELECTED,
                target=target,
                progress=1.0,
                can_click=False,
                status_text=f"READY: {self._btn_name(target)}",
            )

        return DwellSnapshot(
            state=DwellState.DWELLING,
            target=target,
            progress=progress,
            can_click=False,
            status_text=f"Dwelling: {self._btn_name(target)}  {int(progress * 100)}%",
        )

    def _handle_selected(self, gx: float, gy: float, now: float) -> DwellSnapshot:
        can_click = (now - self._selected_at) >= self.min_hold_seconds

        other, _ = self._find_closest(gx, gy, self.entry_radius)
        if other is not None and other is not self._selected:
            self._target      = other
            self._dwell_accum = 0.0
            self._dwell_start = now
            self._exit_start  = 0.0
            self._selected    = None
            self._state       = DwellState.DWELLING
            return DwellSnapshot(
                state=DwellState.DWELLING,
                target=other,
                progress=0.0,
                can_click=False,
                status_text=f"Dwelling: {self._btn_name(other)}  0%",
            )

        return DwellSnapshot(
            state=DwellState.SELECTED,
            target=self._selected,
            progress=1.0,
            can_click=can_click,
            # Once min_hold is met, tell the UI to pin the cursor to this button
            move_cursor_to=self._selected if can_click else None,
            status_text=(
                f"READY: {self._btn_name(self._selected)}  — blink to activate"
                if can_click
                else f"Confirming: {self._btn_name(self._selected)}..."
            ),
        )

    def _handle_cooldown(self, now: float) -> DwellSnapshot:
        if (now - self._cooldown_start) >= self.cooldown_seconds:
            self._state = DwellState.IDLE
            return DwellSnapshot(
                state=DwellState.IDLE,
                target=None,
                progress=0.0,
                can_click=False,
                status_text="Look at a button to begin",
            )

        remaining = self.cooldown_seconds - (now - self._cooldown_start)
        return DwellSnapshot(
            state=DwellState.COOLDOWN,
            target=None,
            progress=0.0,
            can_click=False,
            status_text=f"Activated — next selection in {remaining:.1f}s",
        )

    # ── Transitions ───────────────────────────────────────────────────────

    def _enter_cooldown(self, now: float) -> None:
        self._state          = DwellState.COOLDOWN
        self._cooldown_start = now
        self._selected       = None
        self._target         = None
        self._dwell_accum    = 0.0

    # ── Geometry helpers ──────────────────────────────────────────────────

    def _btn_center(self, btn) -> tuple[float, float]:
        return (
            btn.winfo_rootx() + btn.winfo_width()  / 2,
            btn.winfo_rooty() + btn.winfo_height() / 2,
        )

    def _btn_name(self, btn) -> str:
        try:
            return btn.cget("text")
        except Exception:
            return "?"

    def _find_closest(self, gx: float, gy: float, radius: float):
        """Return (closest_button, distance) within radius, or (None, inf)."""
        closest  = None
        min_dist = float("inf")
        for btn in self._buttons:
            try:
                if not (btn.winfo_exists() and btn.winfo_viewable()):
                    continue
                cx, cy = self._btn_center(btn)
                d = math.hypot(gx - cx, gy - cy)
                if d < min_dist and d <= radius:
                    min_dist = d
                    closest  = btn
            except Exception:
                continue
        return closest, min_dist