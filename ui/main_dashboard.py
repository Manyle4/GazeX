'''This is my main dashboard'''
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
import queue
import torch
import threading
import os
import time

from ui.styles import configure_application_themes
from ui.calibration_page import CalibrationWindow
from ui.calibration_prep import CalibrationPrepScreen   # ← NEW
from ui.vlc import VLCMediaDashboard
from core.dwell_controller import DwellController, DwellState 

import pyautogui
pyautogui.FAILSAFE = False   # ← add this line
# pyautogui.PAUSE = 0


class GazeXDesktopUI:
    def __init__(self, window_root, tracking_engine, vision_pipeline_loop):
        self.root = window_root
        self.engine = tracking_engine
        
        self.root.configure(bg="#0f172a")

        self.root.title("GazeX")
        try:
            self.root.state("zoomed")
        except tk.TclError:
            self.root.attributes("-zoomed", True)

        self.scr_w = self.root.winfo_screenwidth()
        self.scr_h = self.root.winfo_screenheight()
        self.root.resizable(False, False)

        configure_application_themes()

        self.is_tracking = True
        self.data_queue = queue.Queue(maxsize=2)
        self.tuning_progress_queue = queue.Queue()

        # Gaze coordinates — written by message_router_loop, read by child windows
        self.smooth_x = self.scr_w // 2
        self.smooth_y = self.scr_h // 2
        self.blink_triggered = False
        
        self.eyes_closing = False
        self._last_open_gaze = (self.smooth_x, self.smooth_y)
        self.debug_blink_score = 0.0

        # Windows of the application
        self.active_calib_view = None
        self.active_vlc        = None
        # self.active_draw        = None

        # ── NEW: tracks whether calibration (prep or real) is in progress.
        # While True, dashboard buttons are disabled so no DwellController-
        # driven window (Test/VLC) can be opened, and gaze during this
        # window is never interpreted as a dashboard interaction.
        self._calibration_active = False
        self.dwell_controller = None 

        # Extracted features passed from the worker thread
        self.latest_features = None

        # ── UI ────────────────────────────────────────────────────────────────
        self.title_label = ttk.Label(
            self.root,
            text="GazeX",
            font=("Arial", 18, "bold"),
        )
        self.title_label.pack(pady=30)

        self.coord_label = ttk.Label(
            self.root,
            text="Gaze stream initializing...",
            font=("Arial", 12, "italic"),
        )
        self.coord_label.pack(pady=15)

        btn_frame = tk.Frame(self.root, bg=self.root.cget("bg"))
        btn_frame.pack(fill="both", expand=True, padx=40, pady=40)
        
        btn_frame.grid_rowconfigure(0, weight=1)
        btn_frame.grid_rowconfigure(1, weight=1)
        btn_frame.grid_columnconfigure(0, weight=1, uniform="col")
        btn_frame.grid_columnconfigure(1, weight=1, uniform="col")

        self.calib_btn = ttk.Button(btn_frame, text="Calibrate", command=self.open_calibration, style="BigDashboard.TButton")
        self.calib_btn.grid(row=0, column=0)

        self.vlc_btn = ttk.Button(btn_frame, text="Media Control", command=self.open_vlc_page, style="BigDashboard.TButton")
        self.vlc_btn.grid(row=0, column=1)

        self.close_btn = ttk.Button(btn_frame, text="Close / Exit", command=self._on_app_close, style="BigDashboard.TButton")
        self.close_btn.grid(row=1, column=0, columnspan=2)
        
        self.dwell_status_lbl = ttk.Label(
            self.root,
            text="",
            font=("Arial", 11),
        )
        self.dwell_status_lbl.pack(pady=(10, 4))

        self._dwell_progress_var = tk.DoubleVar(value=0.0)
        self.dwell_progress_bar = ttk.Progressbar(
            self.root,
            variable=self._dwell_progress_var,
            maximum=100,
            length=320,
            mode="determinate",
            style="Dwell.Horizontal.TProgressbar",
        )
        self.dwell_progress_bar.pack(pady=4)
        
        self.debug_lbl = ttk.Label(self.root, text="blink: 0.00", font=("Arial", 9))
        self.debug_lbl.pack(pady=(0, 10))

        self.root.protocol("WM_DELETE_WINDOW", self._on_app_close)

        # ── Background pipeline ───────────────────────────────────────────────
        self.pipeline_thread = threading.Thread(
            target=vision_pipeline_loop,
            args=(self, self.engine, self.data_queue),
            daemon=True,
        )
        self.pipeline_thread.start()

        self.message_router_loop()

        # Auto-open the prep screen (which itself opens calibration when done)
        self.root.after(500, self._auto_start)

    def _auto_start(self):
        """Called 500ms after startup — shows the prep screen, then calibration."""
        self._lock_dashboard_interaction()
        CalibrationPrepScreen(self.root, on_done=self.open_calibration)

    # ── Dashboard lock/unlock — the actual gate for Part 2 ─────────────────────

    def _lock_dashboard_interaction(self):
        """
        Disables the buttons that are the only way a DwellController can be
        created (Test/VLC), plus re-Calibrate, for the duration of prep +
        calibration. This is what guarantees no dwell interaction can start
        until initial calibration has finished.
        """
        self._calibration_active = True
        self.calib_btn.config(state="disabled")
        self.vlc_btn.config(state="disabled")

    def _unlock_dashboard_interaction(self):
        self._calibration_active = False
        self.calib_btn.config(state="normal")
        self.vlc_btn.config(state="normal")

    # ── Main queue polling loop ───────────────────────────────────────────────

    def message_router_loop(self):
        try:
            # 1. Fine-tuning progress updates
            try:
                progress = self.tuning_progress_queue.get_nowait()
                self.tuning_progress_queue.task_done()
                if self.active_calib_view and self.active_calib_view.win.winfo_exists():
                    self.active_calib_view.current_progress = progress
                    self.active_calib_view.render_tick()
                    if progress >= 100:
                        self.root.after(400, self.finish_calibration_workflow)
            except queue.Empty:
                pass

            # 2. Gaze coordinate updates
            try:
                g_x, g_y = self.data_queue.get_nowait()
                self.data_queue.task_done()

                if g_x is not None and g_y is not None:
                    self.smooth_x = g_x
                    self.smooth_y = g_y

                    self.coord_label.config(
                        text=f"Gaze  X: {self.smooth_x}  Y: {self.smooth_y}"
                    )

                    if self.active_calib_view and self.active_calib_view.win.winfo_exists():
                        self.active_calib_view.latest_features = self.latest_features
                        self.active_calib_view.on_new_gaze()
                        
                    self.debug_lbl.config(text=f"blink: {getattr(self, 'debug_blink_score', 0.0):.2f}")

                    # if self.active_draw and self.active_draw.win.winfo_exists():
                    #     self.active_draw.move_mouse(self.smooth_x, self.smooth_y)

            except queue.Empty:
                pass
            
            if (self.active_calib_view is not None
                    and not self.active_calib_view.win.winfo_exists()
                    and self._calibration_active):
                # Calibration window was closed externally (not via finish_calibration_workflow)
                self.active_calib_view = None
                self._unlock_dashboard_interaction()
                
            if (self.dwell_controller is not None
                    and not self._calibration_active
                    and not self._child_window_open()):

                if self.blink_triggered:
                    print("[Dashboard] A blink has been received!")
                    self.blink_triggered = False
                    btn = self.dwell_controller.on_blink()
                    if btn is not None:
                        try:
                            btn.invoke()
                            print("[Dashboard] The button has been invoked")
                        except tk.TclError as e:
                            print(f"[Dashboard] invoke() failed: {e}")
                    elif self.dwell_controller.is_selected():
                        print("[Dashboard] Selection was ready but blink not accepted — trying cursor fallback")
                        self._invoke_button_under_cursor([self.calib_btn, self.vlc_btn, self.close_btn])
                    else:
                        print("[Dashboard] Blink received but no button fully selected yet — ignoring")

                auto_btn = self.dwell_controller.check_timeout(timeout_seconds=3.0)
                if auto_btn is not None:
                    try:
                        auto_btn.invoke()
                        print("[Dashboard] Auto-confirm (timeout) invoked the button")
                    except tk.TclError as e:
                        print(f"[Dashboard] Auto-confirm invoke() failed: {e}")

                if self.eyes_closing:
                    gx, gy = self._last_open_gaze
                else:
                    gx, gy = self.smooth_x, self.smooth_y
                    self._last_open_gaze = (gx, gy)

                snap = self.dwell_controller.update(gx, gy, frozen=self.eyes_closing)
                self._render_dashboard_dwell(snap)
            else:
                # Not actively dwelling right now — clear any stale visuals
                self._dwell_progress_var.set(0.0)
                self.dwell_status_lbl.config(text="")

        except Exception as e:
            # Log but do not die — the loop must always reschedule
            print(f"[Router] Non-fatal error: {e}")

        finally:
            # Always reschedule regardless of what happened above
            if self.is_tracking:
                self.root.after(15, self.message_router_loop)

    def _invoke_button_under_cursor(self, candidates) -> bool:
        """Plan B fallback: whatever button is literally under the mouse
        pointer right now, invoke it — independent of DwellController state."""
        x, y = pyautogui.position()
        try:
            widget = self.root.winfo_containing(x, y)
        except Exception:
            return False
        if widget in candidates:
            try:
                widget.invoke()
                print("[Dashboard] Fallback: invoked button under cursor")
                return True
            except tk.TclError as e:
                print(f"[Dashboard] Fallback invoke() failed: {e}")
        return False

    # ── Window management ─────────────────────────────────────────────────────

    def open_calibration(self):
        if self.active_calib_view and self.active_calib_view.win.winfo_exists():
            return

        # Belt-and-suspenders: even if something bypassed the disabled
        # button state, keep the dashboard locked for the duration of this
        # calibration run too (covers a user manually re-calibrating later).
        self._lock_dashboard_interaction()

        # Reset samples and reload original weights before each calibration
        self.engine.calibration_samples = []
        self.engine.reload_weights()

        self.active_calib_view = CalibrationWindow(
            self.root, self.engine, self.tuning_progress_queue
        )
        #dashboard

    def open_vlc_page(self):
        if self._calibration_active:
            return   # guards against any path that bypasses the disabled button
        if self.active_vlc and self.active_vlc.win.winfo_exists():
            return
        self.active_vlc = VLCMediaDashboard(self.root, self)

    # def open_draw_page(self):
    #     if self.active_draw and self.active_draw.win.winfo_exists():
    #         return
    #     self.active_draw = DrawWindow(self.root)

    def finish_calibration_workflow(self):
        if self.active_calib_view and self.active_calib_view.win.winfo_exists():
            self.active_calib_view.win.destroy()
            self.active_calib_view = None
        self._unlock_dashboard_interaction()   # ← NEW: dashboard mode begins here
        
        if self.dwell_controller is None:          # ← guard: never create a second instance
            self.dwell_controller = DwellController(
                dwell_seconds    = 1.2,
                switch_margin    = 70.0,
                min_hold_seconds = 0.3,
                cooldown_seconds = 0.8,
            )
            self.root.after(200, self._register_dwell_buttons)
        else:
            # User manually re-calibrated — same instance, just reset its state
            self.dwell_controller.reset()
            
    def _register_dwell_buttons(self):
        self.dwell_controller.set_buttons([self.calib_btn, self.vlc_btn, self.close_btn])
        
    def _child_window_open(self) -> bool:
        """True if Test or VLC window is currently open — main dashboard's
        dwell/blink handling must stay out of the way while one is up."""
        if self.active_vlc and self.active_vlc.win.winfo_exists():
            return True
        return False
    
    def _on_app_close(self):
        """Safe shutdown — stop the vision pipeline before tearing down windows."""
        self.is_tracking = False   # background_vision_pipeline_worker checks this each loop
        if self.active_vlc and self.active_vlc.win.winfo_exists():
            self.active_vlc._on_close()
        if self.pipeline_thread.is_alive():
            self.pipeline_thread.join(timeout=1.0)
        self.root.destroy()
    
    def _render_dashboard_dwell(self, snapshot):
        self._dwell_progress_var.set(snapshot.progress * 100)
        self.dwell_status_lbl.config(text=snapshot.status_text)

        if snapshot.move_cursor_to is not None:
            btn = snapshot.move_cursor_to
            try:
                if btn.winfo_exists():
                    cx = btn.winfo_rootx() + btn.winfo_width()  / 2
                    cy = btn.winfo_rooty() + btn.winfo_height() / 2
                    pyautogui.moveTo(int(cx), int(cy))
            except tk.TclError:
                pass

        for btn in [self.calib_btn, self.vlc_btn]:
            try:
                if not btn.winfo_exists():
                    continue
                style = "Snapped.TButton" if (
                    btn is snapshot.target and snapshot.state == DwellState.SELECTED
                ) else "BigDashboard.TButton"
                btn.config(style=style)
            except tk.TclError:
                pass
            
    # def _lock_dashboard_interaction(self):
    #     self._calibration_active = True
    #     self.calib_btn.config(state="disabled")
    #     self.test_btn.config(state="disabled")
    #     self.vlc_btn.config(state="disabled")
    #     if self.dwell_controller is not None:
    #         self.dwell_controller.reset()