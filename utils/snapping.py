import math
import time
import pyautogui


class GazeSnappingManager:
    """
    Three-state gaze snapping machine: IDLE → DWELLING → LOCKED.

    Exit from LOCKED uses a dual mechanism:
      - Consecutive frames outside exit_radius (jitter-proof for small drift)
      - Cumulative time outside exit_radius (guarantees release for sustained look-away)
    """

    _STATE_IDLE     = "idle"
    _STATE_DWELLING = "dwelling"
    _STATE_LOCKED   = "locked"

    def __init__(
        self,
        screen_w:    int   = 1920,
        screen_h:    int   = 1080,
        dwell_time:  float = 0.8,
        exit_frames: int   = 3,
        exit_time:   float = 0.3,   # seconds outside exit_radius to force release
    ):
        self.entry_radius = int(min(screen_w, screen_h) * 0.10)
        self.exit_radius  = int(min(screen_w, screen_h) * 0.20)

        self.dwell_time           = dwell_time
        self.exit_frames_required = exit_frames
        self.exit_time            = exit_time

        self._state         = self._STATE_IDLE
        self._locked_button = None
        self._dwell_button  = None
        self._dwell_start   = 0.0
        self._exit_counter  = 0
        self._exit_start    = None   # monotonic time when exit countdown began

        print(
            f"[Snapping] entry={self.entry_radius}px  "
            f"exit={self.exit_radius}px  "
            f"screen={screen_w}×{screen_h}"
        )

    # ── Public ────────────────────────────────────────────────────────────────

    def update_snapping(self, gaze_x: float, gaze_y: float, buttons_list: list):
        now = time.monotonic()
        if self._state == self._STATE_LOCKED:
            return self._handle_locked(gaze_x, gaze_y, now)
        if self._state == self._STATE_DWELLING:
            return self._handle_dwelling(gaze_x, gaze_y, buttons_list, now)
        return self._handle_idle(gaze_x, gaze_y, buttons_list, now)

    def reset(self):
        if self._locked_button and self._locked_button.winfo_exists():
            self._locked_button.config(style="BigDashboard.TButton")
        if self._dwell_button and self._dwell_button.winfo_exists():
            self._dwell_button.config(style="BigDashboard.TButton")
        self._state         = self._STATE_IDLE
        self._locked_button = None
        self._dwell_button  = None
        self._exit_counter  = 0
        self._exit_start    = None

    # ── State handlers ────────────────────────────────────────────────────────

    def _handle_locked(self, gaze_x, gaze_y, now):
        btn = self._locked_button
        if not (btn and btn.winfo_exists()):
            self._transition_idle()
            return None

        cx, cy = self._button_center(btn)
        dist   = math.hypot(gaze_x - cx, gaze_y - cy)

        if dist > self.exit_radius:
            # Gaze is outside — accumulate exit evidence
            self._exit_counter += 1

            if self._exit_start is None:
                self._exit_start = now

            time_outside = now - self._exit_start

            # Release if EITHER condition is met:
            #   - enough consecutive frames outside (handles clean look-away)
            #   - enough cumulative time outside (handles jittery look-away)
            if (self._exit_counter >= self.exit_frames_required
                    or time_outside >= self.exit_time):
                self._transition_idle()
                return None

            # During exit countdown — do NOT pin cursor so user sees movement
            return btn

        else:
            # Back inside — reset exit tracking
            self._exit_counter = 0
            self._exit_start   = None
            # Pin cursor only when gaze is confirmed inside the zone
            pyautogui.moveTo(cx, cy)
            return btn

    def _handle_dwelling(self, gaze_x, gaze_y, buttons_list, now):
        btn = self._dwell_button
        if not (btn and btn.winfo_exists()):
            self._transition_idle()
            return None

        cx, cy = self._button_center(btn)
        dist   = math.hypot(gaze_x - cx, gaze_y - cy)

        if dist > self.entry_radius:
            self._transition_idle()
            return self._handle_idle(gaze_x, gaze_y, buttons_list, now)

        if (now - self._dwell_start) >= self.dwell_time:
            self._transition_locked(btn)
            return btn

        return None

    def _handle_idle(self, gaze_x, gaze_y, buttons_list, now):
        closest, _ = self._closest_button(gaze_x, gaze_y, buttons_list)
        if closest is None:
            return None
        self._dwell_button = closest
        self._dwell_start  = now
        self._state        = self._STATE_DWELLING
        return None

    # ── Transitions ───────────────────────────────────────────────────────────

    def _transition_locked(self, btn):
        self._locked_button = btn
        self._dwell_button  = None
        self._exit_counter  = 0
        self._exit_start    = None
        self._state         = self._STATE_LOCKED
        if btn.winfo_exists():
            btn.config(style="Snapped.TButton")
        cx, cy = self._button_center(btn)
        pyautogui.moveTo(cx, cy)

    def _transition_idle(self):
        if self._locked_button and self._locked_button.winfo_exists():
            self._locked_button.config(style="BigDashboard.TButton")
        self._locked_button = None
        self._dwell_button  = None
        self._exit_counter  = 0
        self._exit_start    = None
        self._state         = self._STATE_IDLE

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _button_center(self, btn) -> tuple[float, float]:
        return (
            btn.winfo_rootx() + btn.winfo_width()  / 2,
            btn.winfo_rooty() + btn.winfo_height() / 2,
        )

    def _closest_button(self, gaze_x, gaze_y, buttons_list):
        closest  = None
        min_dist = float("inf")
        for btn in buttons_list:
            if not (btn.winfo_exists() and btn.winfo_viewable()):
                continue
            cx, cy = self._button_center(btn)
            d = math.hypot(gaze_x - cx, gaze_y - cy)
            if d < min_dist and d <= self.entry_radius:
                min_dist = d
                closest  = btn
        return closest, min_dist