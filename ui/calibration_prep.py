"""
ui/calibration_prep.py
=======================

A brief, auto-advancing instruction screen shown between the splash
screen and the real calibration.

Deliberately has zero gaze/calibration logic of its own: it doesn't
read self.smooth_x/y, doesn't touch engine.calibration_samples, and
doesn't create a DwellController. It exists purely to give the user
a few seconds to understand what's about to happen and get into
position, then calls back into main_dashboard.py to start the real
CalibrationWindow.
"""

import tkinter as tk

PREP_SECONDS = 4.0   # see reasoning in the accompanying message


class CalibrationPrepScreen:
    """
    Usage:
        CalibrationPrepScreen(root, on_done=self.open_calibration)

    on_done is called automatically once PREP_SECONDS has elapsed,
    after this window has destroyed itself. No user interaction
    (click/keypress) is required or accepted.
    """

    def __init__(self, parent_root, on_done, seconds: float = PREP_SECONDS):
        self.root    = parent_root
        self.on_done = on_done
        self.seconds = seconds

        self.win = tk.Toplevel(self.root)
        self.win.title("GazeX — Get Ready")
        try:
            self.win.state("zoomed")
        except tk.TclError:
            self.win.attributes("-zoomed", True)

        # Modal-ish: block interaction with anything behind it while it's up.
        # This also means calibration cannot be skipped by clicking through.
        self.win.grab_set()
        self.win.focus_force()
        # Deliberately no WM_DELETE_WINDOW handler that lets the user
        # close this early — it's a timed prep step, not a dismissible dialog.
        self.win.protocol("WM_DELETE_WINDOW", lambda: None)

        w = self.win.winfo_screenwidth()
        h = self.win.winfo_screenheight()

        canvas = tk.Canvas(self.win, width=w, height=h, bg="#0f172a", highlightthickness=0)
        canvas.pack(fill=tk.BOTH, expand=True)

        cx, cy = w // 2, h // 2

        canvas.create_text(
            cx, cy - 130,
            text="Get Ready for Calibration",
            font=("Arial", 26, "bold"), fill="#94a3b8",
        )

        lines = [
            "A dot will appear on screen — just look directly at it.",
            "It will move to a new spot every couple of seconds — follow it with your eyes.",
            "Try to keep your head still; move your eyes, not your head.",
        ]
        for i, line in enumerate(lines):
            canvas.create_text(
                cx, cy - 40 + i * 34,
                text=line,
                font=("Arial", 14), fill="#94a3b8",
            )

        self._countdown_lbl = canvas.create_text(
            cx, cy + 110,
            text="",
            font=("Arial", 15, "bold"), fill="#06b6d4",
        )
        self._canvas = canvas

        self._start_ms = self.win.after_idle(lambda: None)  # ensures window painted first
        self.win.after(10, self._tick_start)

    def _tick_start(self):
        import time
        self._t0 = time.monotonic()
        self._tick()

    def _tick(self):
        import time
        if not self.win.winfo_exists():
            return

        elapsed   = time.monotonic() - self._t0
        remaining = max(0.0, self.seconds - elapsed)
        secs_left = int(remaining) + 1 if remaining > 0 else 0

        self._canvas.itemconfig(
            self._countdown_lbl,
            text=f"Starting in {secs_left}..." if secs_left > 0 else "Starting...",
        )

        if remaining <= 0:
            self._finish()
        else:
            self.win.after(100, self._tick)

    def _finish(self):
        if self.win.winfo_exists():
            self.win.grab_release()
            self.win.destroy()
        self.on_done()