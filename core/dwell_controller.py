"""
core/dwell_controller.py
========================

DwellController — forced-choice gaze dwell state machine.

Design: gaze in this application has exactly one job — pick one of the
registered on-screen buttons. There is no free-form cursor and no valid
"pointing at nothing" state. So instead of radius/margin hit-testing
(which can leave dead zones between buttons, or let two buttons' hit
boxes overlap and both claim the same gaze point), every gaze sample is
forced to resolve to the single nearest button by center distance.

Stability against jitter comes from `switch_margin`: once dwelling has
started on a button, a different button must be at least `switch_margin`
pixels closer (by center distance) before it steals the target. This
makes the boundary between two adjacent buttons "sticky" instead of
flickering when gaze sits near the midpoint.

State machine:
    IDLE/DWELLING (merged — always tracking the nearest button)
        → SELECTED (dwell filled, waiting for blink confirmation)
        → COOLDOWN (post-click freeze)
        → back to tracking

No Tkinter imports beyond winfo_* introspection, no pyautogui, no side
effects — the caller (ui/vlc.py, ui/test.py) is responsible for actually
moving the cursor and invoking the button.
"""

import time
import math
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Any


class DwellState(Enum):
    IDLE     = auto()   # no buttons registered yet
    DWELLING = auto()   # accumulating dwell time toward the nearest button
    SELECTED = auto()   # dwell complete, waiting for blink confirmation
    COOLDOWN = auto()   # post-click freeze before accepting new dwells


@dataclass
class DwellSnapshot:
    """Immutable snapshot of dwell state for the GUI to render."""
    state:           DwellState
    target:          Optional[Any]
    progress:        float
    can_click:       bool
    status_text:     str
    move_cursor_to:  Optional[Any] = None


class DwellController:
    """
    Usage:
        controller = DwellController()
        controller.set_buttons([btn_a, btn_b, btn_c])

        # Every tick:
        snapshot = controller.update(gx, gy)

        # On blink:
        activated_button = controller.on_blink()
        if activated_button is not None:
            activated_button.invoke()   # <-- caller MUST do this, controller never clicks
    """

    def __init__(
        self,
        dwell_seconds:     float = 1.2,    # seconds of continuous dwell to fill the bar
        switch_margin:     float = 40.0,   # px a new button must be closer by to steal the target
        min_hold_seconds:  float = 0.3,    # seconds after SELECTED before blink is accepted
        cooldown_seconds:  float = 1.0,    # seconds after click before new dwell can start
    ):
        self.dwell_seconds    = dwell_seconds
        self.switch_margin    = switch_margin
        self.min_hold_seconds = min_hold_seconds
        self.cooldown_seconds = cooldown_seconds

        # ── State ─────────────────────────────────────────────────────────
        self._state:    DwellState    = DwellState.IDLE
        self._target:   Optional[Any] = None   # button currently being dwelled on
        self._selected: Optional[Any] = None   # confirmed selected button

        # ── Timing (time.monotonic() only — never frame counts) ────────────
        self._dwell_start:    float = 0.0
        self._dwell_accum:    float = 0.0
        self._selected_at:    float = 0.0
        self._cooldown_start: float = 0.0

        # ── Registered buttons ────────────────────────────────────────────
        self._buttons: list = []

    # ── Public API ────────────────────────────────────────────────────────

    def set_buttons(self, buttons: list) -> None:
        """Register the list of Tkinter buttons gaze can select between."""
        self._buttons = buttons

    def update(self, gx: float, gy: float) -> DwellSnapshot:
        """Feed a new gaze coordinate. Call once per tick from the UI thread."""
        now = time.monotonic()

        if self._state == DwellState.COOLDOWN:
            return self._handle_cooldown(now)

        if self._state == DwellState.SELECTED:
            return self._handle_selected(gx, gy, now)

        return self._handle_tracking(gx, gy, now)

    def on_blink(self) -> Optional[Any]:
        """
        Called when an intentional blink is detected.
        Returns the button to activate, or None if no button is ready.
        The caller is responsible for actually invoking the button
        (e.g. `btn.invoke()`) — this method never clicks anything itself.
        """
        now = time.monotonic()

        if self._state != DwellState.SELECTED:
            return None

        if (now - self._selected_at) < self.min_hold_seconds:
            # Selection completed too recently — likely an accidental blink
            # during the dwell-fill animation. Ignore it.
            return None

        btn = self._selected
        self._enter_cooldown(now)
        return btn

    def reset(self) -> None:
        """Force back to tracking with no target — call on window close/view change."""
        self._state       = DwellState.IDLE
        self._target       = None
        self._selected      = None
        self._dwell_accum = 0.0

    # ── Core: forced nearest-button classification ─────────────────────────

    def _nearest_button(self, gx: float, gy: float):
        """Always returns the closest live, viewable button — None only if none exist."""
        best, best_d = None, float("inf")
        for btn in self._buttons:
            try:
                if not btn.winfo_exists():
                    continue
                cx, cy = self._btn_center(btn)
                d = math.hypot(gx - cx, gy - cy)
                if d < best_d:
                    best_d, best = d, btn
            except Exception:
                continue
        return best, best_d

    def _distance_to(self, btn, gx: float, gy: float) -> float:
        cx, cy = self._btn_center(btn)
        return math.hypot(gx - cx, gy - cy)

    def _set_target(self, btn, now: float) -> None:
        self._target      = btn
        self._dwell_accum = 0.0
        self._dwell_start = now

    def _handle_tracking(self, gx: float, gy: float, now: float) -> DwellSnapshot:
        if not self._buttons:
            return DwellSnapshot(
                state=DwellState.IDLE, 
                target=None, 
                progress=0.0,
                can_click=False, 
                status_text="No buttons registered",
            )

        nearest, nearest_d = self._nearest_button(gx, gy)
        if nearest is None:
            return DwellSnapshot(
                state=DwellState.IDLE, target=None, progress=0.0,
                can_click=False, status_text="No visible buttons",
            )

        if self._target is None:
            self._set_target(nearest, now)
        elif nearest is not self._target:
            current_d = self._distance_to(self._target, gx, gy)
            # Only steal the target if the new one is meaningfully closer —
            # this is what keeps the boundary between two buttons from flickering.
            if current_d - nearest_d >= self.switch_margin:
                self._set_target(nearest, now)
            # else: gaze is near the boundary — keep dwelling on current target

        elapsed = now - self._dwell_start
        self._dwell_start  = now
        self._dwell_accum  = min(self.dwell_seconds, self._dwell_accum + elapsed)
        progress = self._dwell_accum / self.dwell_seconds

        if self._dwell_accum >= self.dwell_seconds:
            self._selected     = self._target
            self._selected_at  = now
            self._state        = DwellState.SELECTED
            return DwellSnapshot(
                state=DwellState.SELECTED, target=self._target, progress=1.0,
                can_click=True, move_cursor_to=self._target,
                status_text=f"READY: {self._btn_name(self._target)}",
            )

        self._state = DwellState.DWELLING
        return DwellSnapshot(
            state=DwellState.DWELLING, target=self._target, progress=progress,
            can_click=False, move_cursor_to=self._target,
            status_text=f"Dwelling: {self._btn_name(self._target)}  {int(progress * 100)}%",
        )

    def _handle_selected(self, gx: float, gy: float, now: float) -> DwellSnapshot:
        can_click = (now - self._selected_at) >= self.min_hold_seconds

        nearest, nearest_d = self._nearest_button(gx, gy)
        if nearest is not None and nearest is not self._selected:
            sel_d = self._distance_to(self._selected, gx, gy)
            if sel_d - nearest_d >= self.switch_margin:
                # User has clearly moved on to a different button — drop this
                # selection and start dwelling on the new one instead.
                self._selected = None
                self._state    = DwellState.DWELLING
                self._set_target(nearest, now)
                return DwellSnapshot(
                    state=DwellState.DWELLING, target=nearest, progress=0.0,
                    can_click=False,
                    status_text=f"Dwelling: {self._btn_name(nearest)}  0%",
                )

        return DwellSnapshot(
            state=DwellState.SELECTED, target=self._selected, progress=1.0,
            can_click=can_click,
            move_cursor_to=self._selected if can_click else None,
            status_text=(
                f"READY: {self._btn_name(self._selected)} — blink to activate"
                if can_click
                else f"Confirming: {self._btn_name(self._selected)}..."
            ),
        )

    def _handle_cooldown(self, now: float) -> DwellSnapshot:
        if (now - self._cooldown_start) >= self.cooldown_seconds:
            self._state = DwellState.IDLE
            return DwellSnapshot(
                state=DwellState.IDLE, target=None, progress=0.0,
                can_click=False, status_text="Look at a button to begin",
            )

        remaining = self.cooldown_seconds - (now - self._cooldown_start)
        return DwellSnapshot(
            state=DwellState.COOLDOWN, target=None, progress=0.0,
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

    # ── Geometry / display helpers ───────────────────────────────────────

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