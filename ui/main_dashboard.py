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
from ui.test import TestGazeWindow
from ui.vlc import VLCMediaDashboard
from ui.draw import DrawWindow

import pyautogui
pyautogui.FAILSAFE = False   # ← add this line
# pyautogui.PAUSE = 0


class EyeTheiaDesktopUI:
    def __init__(self, window_root, tracking_engine, vision_pipeline_loop):
        self.root = window_root
        self.engine = tracking_engine

        self.root.title("EyeTheia")
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

        self.active_calib_view = None
        self.active_test_view  = None
        self.active_vlc        = None
        self.active_draw        = None

        self.latest_features = None

        # ── UI ────────────────────────────────────────────────────────────────
        self.title_label = ttk.Label(
            self.root,
            text="EyeTheia Gaze Control",
            font=("Arial", 18, "bold"),
        )
        self.title_label.pack(pady=30)

        self.coord_label = ttk.Label(
            self.root,
            text="Gaze stream initializing...",
            font=("Arial", 12, "italic"),
        )
        self.coord_label.pack(pady=15)

        self.calib_btn = ttk.Button(
            self.root,
            text="Calibrate",
            command=self.open_calibration,
            style="BigDashboard.TButton",
        )
        self.calib_btn.pack(pady=15)

        self.test_btn = ttk.Button(
            self.root,
            text="Test Gaze Control",
            command=self.open_testing,
            style="BigDashboard.TButton",
        )
        self.test_btn.pack(pady=15)

        self.vlc_btn = ttk.Button(
            self.root,
            text="Media Control",
            command=self.open_vlc_page,
            style="BigDashboard.TButton",
        )
        self.vlc_btn.pack(pady=15)
        
        self.draw_btn = ttk.Button(
            self.root,
            text="Draw",
            command=self.open_draw_page,
            style="BigDashboard.TButton",
        )
        self.draw_btn.pack(pady=15)
        
        self.offset_btn = ttk.Button(
        self.root,
        text="Measure Gaze Offset",
        command=self.open_offset_calibration,
        style="BigDashboard.TButton",
        )
        self.offset_btn.pack(pady=15)

        # ── Background pipeline ───────────────────────────────────────────────
        self.pipeline_thread = threading.Thread(
            target=vision_pipeline_loop,
            args=(self, self.engine, self.data_queue),
            daemon=True,
        )
        self.pipeline_thread.start()

        self.message_router_loop()

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
                        self.active_calib_view.on_new_gaze(self.smooth_x, self.smooth_y)
                        
                    if self.active_test_view and self.active_test_view.win.winfo_exists():
                        pyautogui.moveTo(self.smooth_x, self.smooth_y)
                        
                    if self.active_draw and self.active_draw.win.winfo_exists():
                        self.active_draw.move_mouse(self.smooth_x, self.smooth_y)

            except queue.Empty:
                pass

        except Exception as e:
            # Log but do not die — the loop must always reschedule
            print(f"[Router] Non-fatal error: {e}")

        finally:
            # Always reschedule regardless of what happened above
            if self.is_tracking:
                self.root.after(15, self.message_router_loop)

    # ── Window management ─────────────────────────────────────────────────────

    def open_calibration(self):
        if self.active_calib_view and self.active_calib_view.win.winfo_exists():
            return

        # Reset samples and reload original weights before each calibration
        self.engine.calibration_samples = []
        self.engine.reload_weights()

        self.active_calib_view = CalibrationWindow(
            self.root, self.engine, self.tuning_progress_queue
        )

    def open_testing(self):
        if self.active_test_view and self.active_test_view.win.winfo_exists():
            return
        self.active_test_view = TestGazeWindow(self.root, self)

    def open_vlc_page(self):
        if self.active_vlc and self.active_vlc.win.winfo_exists():
            return
        self.active_vlc = VLCMediaDashboard(self.root, self)
        
    def open_draw_page(self):
        if self.active_draw and self.active_draw.win.winfo_exists():
            return
        self.active_draw = DrawWindow(self.root)

    def finish_calibration_workflow(self):
        if self.active_calib_view and self.active_calib_view.win.winfo_exists():
            messagebox.showinfo(
                "EyeTheia",
                "Calibration complete.\nGaze tracking is now personalised to you.",
            )
            self.active_calib_view.win.destroy()
            self.active_calib_view = None
        
    def open_offset_calibration(self):
        """
        Simple offset measurement tool.
        Shows a dot in the centre of the screen.
        User looks at it for 3 seconds.
        Average gaze position is compared to dot position.
        Difference becomes the offset correction.
        """
        import time

        win = tk.Toplevel(self.root)
        win.attributes("-fullscreen", True)
        win.configure(bg="white")

        scr_w = win.winfo_screenwidth()
        scr_h = win.winfo_screenheight()

        # Target dot in the exact centre
        target_x = scr_w // 2
        target_y = scr_h // 2

        canvas = tk.Canvas(win, bg="white", highlightthickness=0)
        canvas.pack(fill=tk.BOTH, expand=True)

        canvas.create_text(
            target_x, target_y - 80,
            text="Look at the dot and hold still for 3 seconds",
            font=("Arial", 18),
            fill="#333333",
        )

        # Draw target dot
        canvas.create_oval(
            target_x - 15, target_y - 15,
            target_x + 15, target_y + 15,
            fill="#0f172a", outline="",
        )

        status_lbl = tk.Label(
            win, text="Collecting...",
            font=("Arial", 14), bg="white", fg="#666666",
        )
        status_lbl.place(relx=0.5, rely=0.7, anchor=tk.CENTER)

        gaze_samples = []
        start_time   = time.monotonic()
        collect_secs = 3.0

        def collect():
            elapsed = time.monotonic() - start_time
            remaining = max(0, collect_secs - elapsed)

            if elapsed < collect_secs:
                gaze_samples.append((self.smooth_x, self.smooth_y))
                status_lbl.config(
                    text=f"Hold still... {remaining:.1f}s  ({len(gaze_samples)} samples)"
                )
                win.after(30, collect)
            else:
                # Compute average gaze position
                avg_x = int(sum(s[0] for s in gaze_samples) / len(gaze_samples))
                avg_y = int(sum(s[1] for s in gaze_samples) / len(gaze_samples))

                # Offset = where button IS minus where gaze LANDED
                dx = target_x - avg_x
                dy = target_y - avg_y

                self.engine.set_gaze_offset(dx, dy)

                status_lbl.config(
                    text=f"Offset set: dx={dx}  dy={dy}  (gaze was at {avg_x},{avg_y}  target was {target_x},{target_y})"
                )
                canvas.create_oval(
                    avg_x - 8, avg_y - 8,
                    avg_x + 8, avg_y + 8,
                    fill="#ef4444", outline="",
                )
                canvas.create_text(
                    avg_x, avg_y + 25,
                    text=f"Your gaze: ({avg_x},{avg_y})",
                    font=("Arial", 11),
                    fill="#ef4444",
                )

                win.after(2000, win.destroy)

        win.after(500, collect)