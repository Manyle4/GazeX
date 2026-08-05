"""
ui/test.py
==========

Gaze Control Test Window.

Demonstrates dwell-based button selection and blink-to-click.
Uses DwellController for all timing logic — this file only handles
rendering and user feedback.
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
        self.win.title("Gaze Control Test")

        try:
            self.win.state("zoomed")
        except tk.TclError:
            self.win.attributes("-zoomed", True)

        scr_w = self.win.winfo_screenwidth()
        scr_h = self.win.winfo_screenheight()

        # DwellController owns all timing logic
        self._dwell = DwellController(
            entry_radius     = int(min(scr_w, scr_h) * 0.30),
            hold_radius      = int(min(scr_w, scr_h) * 0.42),
            dwell_seconds    = 1.5,
            grace_seconds    = 0.8,
            min_hold_seconds = 0.3,
            cooldown_seconds = 0.8,
        )

        self.count = 1
        self._last_snapshot = None

        self._build_ui()

        # Register buttons after UI is built
        self._dwell.set_buttons([self.click_btn, self.reset_btn])

        self.win.protocol("WM_DELETE_WINDOW", self._on_close)
        self.win.after(500, self._verify_layout)
        self._tick()

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self):
        outer = tk.Frame(self.win, bg="#0f172a")
        outer.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            outer,
            text="EyeTheia — Gaze Control Test",
            font=("Arial", 18, "bold"),
        ).pack(pady=(40, 8))

        ttk.Label(
            outer,
            text="Look at a button until the bar fills, then blink to activate",
            font=("Arial", 12, "italic"),
        ).pack(pady=(0, 20))

        self._counter_lbl = ttk.Label(
            outer,
            text="Counter: 0",
            font=("Arial", 16, "bold"),
        )
        self._counter_lbl.pack(pady=12)

        btn_frame = tk.Frame(outer, bg="#0f172a")
        btn_frame.pack(pady=30)
        
        self.reset_btn = ttk.Button(
            btn_frame,
            text="RESET",
            command=self._reset,
            style="BigDashboard.TButton",
        )
        self.reset_btn.pack(pady=30)

        self.click_btn = ttk.Button(
            btn_frame,
            text="INCREMENT",
            command=self._increment,
            style="BigDashboard.TButton",
        )
        self.click_btn.pack(pady=30)

        # Dwell progress bar
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

        self._status_lbl = ttk.Label(
            outer,
            text="Waiting for gaze...",
            font=("Arial", 11),
        )
        self._status_lbl.pack(pady=10)

        # Debug info — gaze position and dwell state
        self._debug_lbl = ttk.Label(
            outer,
            text="",
            font=("Arial", 9),
            foreground="#64748b",
        )
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

        # Check blink signal from pipeline
        if getattr(self.dashboard, "blink_triggered", False):
            self.dashboard.blink_triggered = False
            self._handle_blink()

        # Feed gaze to controller and get state snapshot
        snapshot = self._dwell.update(gx, gy)
        self._last_snapshot = snapshot

        # Render the snapshot
        self._render(snapshot, gx, gy)

        self.win.after(20, self._tick)

    # ── Rendering ─────────────────────────────────────────────────────────

    def _render(self, snapshot, gx, gy):
        self._progress_var.set(snapshot.progress * 100)
        self._status_lbl.config(text=snapshot.status_text)

        # Pin cursor to button center when fully selected and ready
        if snapshot.move_cursor_to is not None:
            btn = snapshot.move_cursor_to
            if btn.winfo_exists():
                cx = btn.winfo_rootx() + btn.winfo_width()  / 2
                cy = btn.winfo_rooty() + btn.winfo_height() / 2
                pyautogui.moveTo(int(cx), int(cy))

        # Button highlight styles
        for btn in [self.click_btn, self.reset_btn]:
            if not btn.winfo_exists():
                continue
            if btn is snapshot.target and snapshot.state == DwellState.SELECTED:
                btn.config(style="Snapped.TButton")
            else:
                btn.config(style="BigDashboard.TButton")

        self._debug_lbl.config(
            text=f"Gaze: ({int(gx)}, {int(gy)})  State: {snapshot.state.name}  Progress: {int(snapshot.progress*100)}%"
        )
        
        print(f"Gaze: ({int(gx)}, {int(gy)})  State: {snapshot.state.name}  Progress: {int(snapshot.progress*100)}%")

    # ── Blink handling ────────────────────────────────────────────────────

    def _handle_blink(self):
        btn = self._dwell.on_blink()
        if btn is not None:
            print(f"[Test] Blink activating: {btn.cget('text')}")
            # pyautogui.click() in app.py already fired at current cursor position
            # on_blink() handles entering cooldown so next selection can begin
        else:
            print("[Test] Blink received — no button ready or cooldown active.")
    # ── Button actions ────────────────────────────────────────────────────

    def _increment(self):
        self._counter_lbl.config(text=f"Counter: {self.count}")
        self.count += 1

    def _reset(self):
        self.count = 1
        self._counter_lbl.config(text="Counter: 0")

    # ── Layout verification ───────────────────────────────────────────────

    def _verify_layout(self):
        self.win.update_idletasks()
        for btn in [self.click_btn, self.reset_btn]:
            cx = btn.winfo_rootx() + btn.winfo_width()  / 2
            cy = btn.winfo_rooty() + btn.winfo_height() / 2
            print(
                f"[Layout] '{btn.cget('text')}' "
                f"center=({cx:.0f},{cy:.0f})  "
                f"entry_r={self._dwell.entry_radius}  "
                f"hold_r={self._dwell.hold_radius}"
            )

    # ── Cleanup ───────────────────────────────────────────────────────────

    def _on_close(self):
        self._dwell.reset()
        self.win.destroy()