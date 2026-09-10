"""
ui/test.py
==========

Emergency Dashboard.

Gaze-and-blink-operated panic screen. Uses DwellController for all
timing logic — this file only handles rendering, user feedback, and
what the emergency actions actually do.
"""

import tkinter as tk
from tkinter import ttk
import pyautogui

from core.dwell_controller import DwellController, DwellState


class TestGazeWindow:

    def __init__(self, parent_root, dashboard):
        self.root      = parent_root
        self.dashboard = dashboard

        self.win = tk.Toplevel(self.root)
        self.win.title("EyeTheia — Emergency")

        try:
            self.win.state("zoomed")
        except tk.TclError:
            self.win.attributes("-zoomed", True)

        # Shorter dwell for panic actions — this screen should react fast,
        # not make someone in distress hold a gaze for 1.5s.
        self._dwell = DwellController(
            dwell_seconds    = 0.9,
            switch_margin    = 40.0,
            min_hold_seconds = 0.2,
            cooldown_seconds = 0.8,
        )

        self._alarm_active  = False
        self._last_snapshot = None

        self._build_ui()

        self._dwell.set_buttons([self.alarm_btn, self.alert_btn, self.back_btn])

        self.win.protocol("WM_DELETE_WINDOW", self._on_close)
        self.win.after(500, self._verify_layout)
        self._tick()

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self):
        outer = tk.Frame(self.win, bg="#0f172a")
        outer.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            outer,
            text="EMERGENCY",
            font=("Arial", 22, "bold"),
        ).pack(pady=(40, 8))

        ttk.Label(
            outer,
            text="Look at a button until the bar fills, then blink to activate",
            font=("Arial", 12, "italic"),
        ).pack(pady=(0, 20))

        self._state_lbl = ttk.Label(
            outer,
            text="",
            font=("Arial", 16, "bold"),
        )
        self._state_lbl.pack(pady=12)

        btn_frame = tk.Frame(outer, bg="#0f172a")
        btn_frame.pack(pady=30)

        self.alarm_btn = ttk.Button(
            btn_frame,
            text="SOUND ALARM",
            command=self._toggle_alarm,
            style="BigDashboard.TButton",
        )
        self.alarm_btn.pack(pady=20)

        self.alert_btn = ttk.Button(
            btn_frame,
            text="ALERT CAREGIVER",
            command=self._alert_caregiver,
            style="BigDashboard.TButton",
        )
        self.alert_btn.pack(pady=20)

        self.back_btn = ttk.Button(
            btn_frame,
            text="BACK TO DASHBOARD",
            command=self._on_close,
            style="BigDashboard.TButton",
        )
        self.back_btn.pack(pady=20)

        bar_frame = tk.Frame(outer, bg="#0f172a")
        bar_frame.pack(pady=8)

        ttk.Label(bar_frame, text="Dwell:", font=("Arial", 11)).pack(side=tk.LEFT, padx=(0, 10))

        self._progress_var = tk.DoubleVar(value=0.0)
        ttk.Progressbar(
            bar_frame,
            variable=self._progress_var,
            maximum=100,
            length=320,
            mode="determinate",
        ).pack(side=tk.LEFT)

        self._status_lbl = ttk.Label(outer, text="Waiting for gaze...", font=("Arial", 11))
        self._status_lbl.pack(pady=10)

        self._debug_lbl = ttk.Label(outer, text="", font=("Arial", 9), foreground="#64748b")
        self._debug_lbl.pack(pady=2)

    # ── Main tick ─────────────────────────────────────────────────────────

    def _tick(self):
        if not self.win.winfo_exists():
            return

        try:
            gx = float(self.dashboard.smooth_x)
            gy = float(self.dashboard.smooth_y)
        except AttributeError:
            self.win.after(20, self._tick)
            return

        if getattr(self.dashboard, "blink_triggered", False):
            self.dashboard.blink_triggered = False
            self._handle_blink()

        snapshot = self._dwell.update(gx, gy)
        self._last_snapshot = snapshot
        self._render(snapshot, gx, gy)

        self.win.after(20, self._tick)

    # ── Rendering ─────────────────────────────────────────────────────────

    def _render(self, snapshot, gx, gy):
        self._progress_var.set(snapshot.progress * 100)
        self._status_lbl.config(text=snapshot.status_text)
        self._state_lbl.config(text="ALARM ACTIVE" if self._alarm_active else "")

        if snapshot.move_cursor_to is not None:
            btn = snapshot.move_cursor_to
            if btn.winfo_exists():
                cx = btn.winfo_rootx() + btn.winfo_width()  / 2
                cy = btn.winfo_rooty() + btn.winfo_height() / 2
                pyautogui.moveTo(int(cx), int(cy))

        for btn in [self.alarm_btn, self.alert_btn, self.back_btn]:
            if not btn.winfo_exists():
                continue
            if btn is snapshot.target and snapshot.state == DwellState.SELECTED:
                btn.config(style="Snapped.TButton")
            else:
                btn.config(style="BigDashboard.TButton")

        self._debug_lbl.config(
            text=f"Gaze: ({int(gx)}, {int(gy)})  State: {snapshot.state.name}  Progress: {int(snapshot.progress*100)}%"
        )

    # ── Blink handling ────────────────────────────────────────────────────

    def _handle_blink(self):
        btn = self._dwell.on_blink()
        if btn is not None:
            print(f"[Emergency] Blink activating: {btn.cget('text')}")
            try:
                btn.invoke()
            except tk.TclError as e:
                print(f"[Emergency] invoke() failed: {e}")
        else:
            print("[Emergency] Blink received — no button ready or cooldown active.")

    # ── Emergency actions ────────────────────────────────────────────────
    # TODO: wire these up to whatever you actually have available
    # (buzzer/speaker, SMS/email API, a caregiver-side app, etc).
    # They're stubbed with a loud local signal so the screen is usable now.

    def _toggle_alarm(self):
        self._alarm_active = not self._alarm_active
        state = "ON" if self._alarm_active else "OFF"
        print(f"[Emergency] Alarm {state}")
        if self._alarm_active:
            self.win.bell()

    def _alert_caregiver(self):
        print("[Emergency] Caregiver alert triggered — TODO: send SMS/email/notification here")
        self.win.bell()

    # ── Layout verification ───────────────────────────────────────────────

    def _verify_layout(self):
        self.win.update_idletasks()
        for btn in [self.alarm_btn, self.alert_btn, self.back_btn]:
            cx = btn.winfo_rootx() + btn.winfo_width()  / 2
            cy = btn.winfo_rooty() + btn.winfo_height() / 2
            print(
                f"[Layout] '{btn.cget('text')}' "
                f"center=({cx:.0f},{cy:.0f})  "
                f"dwell_seconds={self._dwell.dwell_seconds}  "
                f"switch_margin={self._dwell.switch_margin}"
            )

    # ── Cleanup ───────────────────────────────────────────────────────────

    def _on_close(self):
        self._dwell.reset()
        self.win.destroy()