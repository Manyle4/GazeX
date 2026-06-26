import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
import queue
import cv2
import torch
import numpy as np
import mediapipe as mp
import threading
import os

from ui.styles import configure_application_themes
from ui.calibration_page import CalibrationWindow
from ui.test import TestGazeWindow
from ui.draw import DrawWindow
from ui.vlc import VLCMediaDashboard

class EyeTheiaDesktopUI:
    def __init__(self, window_root, tracking_engine, vision_pipeline_loop):
        self.root = window_root
        self.engine = tracking_engine
        
        self.root.title("Eyetheia Command Center")
        try: self.root.state("zoomed")
        except tk.TclError: self.root.attributes("-zoomed", True)
            
        self.scr_w = self.root.winfo_screenwidth()
        self.scr_h = self.root.winfo_screenheight()
        self.root.resizable(False, False)
        
        configure_application_themes()
        
        self.is_tracking = True
        self.data_queue = queue.Queue(maxsize=2)
        
        # New queue strictly tracking network fine-tuning states
        self.tuning_progress_queue = queue.Queue()
        
        self.smooth_x, self.smooth_y = self.scr_w // 2, self.scr_h // 2
        
        self.active_calib_view = None
        self.active_test_view = None
        self.active_draw = None
        self.active_vlc = None
        
        self.latest_features = None
        
        self.title_label = ttk.Label(self.root, text="EyeTheia Local Processing Matrix Center", font=("Arial", 18, "bold"))
        self.title_label.pack(pady=30)
        
        self.coord_label = ttk.Label(self.root, text="System Idle. Gaze Stream -> X: 0 | Y: 0", font=("Arial", 12, "italic"))
        self.coord_label.pack(pady=15)
        
        self.calib_btn = ttk.Button(self.root, text="Open Calibration Window", command=self.open_calibration, style="BigDashboard.TButton")
        self.calib_btn.pack(pady=15)
        
        self.test_btn = ttk.Button(self.root, text="Open Testing Arena", command=self.open_testing, style="BigDashboard.TButton")
        self.test_btn.pack(pady=15)
        
        self.draw_btn = ttk.Button(self.root, text="Open Drawing Arena", command=self.open_draw_page, style="BigDashboard.TButton")
        self.draw_btn.pack(pady=15)
        
        self.vlc_btn = ttk.Button(self.root, text="Open VLC", command=self.open_vlc_page, style="BigDashboard.TButton")
        self.vlc_btn.pack(pady=15)
        
        
        self.pipeline_thread = threading.Thread(
            target=vision_pipeline_loop, 
            args=(self, self.engine, self.data_queue), 
            daemon=True
        )
        self.pipeline_thread.start()
        
        self.message_router_loop()

    def message_router_loop(self):
        # 1. Listen for background deep learning progress updates
        try:
            progress = self.tuning_progress_queue.get_nowait()
            if self.active_calib_view and self.active_calib_view.win.winfo_exists():
                self.active_calib_view.current_progress = progress
                self.active_calib_view.render_tick()
                
                if progress >= 100:
                    # Give the bar a moment to render 100%, then prompt and close
                    self.root.after(400, self.finish_calibration_workflow)
            self.tuning_progress_queue.task_done()
        except queue.Empty:
            pass

        # 2. Listen for standard gaze coordinates coordinates
        try:
            g_x, g_y = self.data_queue.get_nowait()
            if g_x is not None and g_y is not None:
                self.coord_label.config(text=f"Gaze Stream Coordinates -> X: {g_x} | Y: {g_y}")
                
                alpha = 0.18
                self.smooth_x = int((alpha * g_x) + ((1.0 - alpha) * self.smooth_x))
                self.smooth_y = int((alpha * g_y) + ((1.0 - alpha) * self.smooth_y))
                
                if self.active_calib_view and self.active_calib_view.win.winfo_exists():
                    self.active_calib_view.features = self.latest_features
                    self.active_calib_view.render_tick()
                    
                if self.active_test_view and self.active_test_view.win.winfo_exists():
                    import pyautogui
                    pyautogui.moveTo(self.smooth_x, self.smooth_y)
                    
                if self.active_draw and self.active_draw.win.winfo_exists():
                    self.active_draw.move_mouse(self.smooth_x, self.smooth_y)
                    
            self.data_queue.task_done()
        except queue.Empty:
            pass
        
        if self.is_tracking:
            self.root.after(15, self.message_router_loop)

    def open_calibration(self):
        if self.active_calib_view and self.active_calib_view.win.winfo_exists(): return
        
        # Reset data arrays and restore original weights file to fix overfitting bounds
        self.engine.calibration_samples = []
        WEIGHTS_FILE = "models/mpiiface_production.pth"
        if os.path.exists(WEIGHTS_FILE):
            print(f"[Reset] Overwriting running RAM parameters with pristine weights baseline: {WEIGHTS_FILE}")
            state_dict = torch.load(WEIGHTS_FILE, map_location=self.engine.device)
            self.engine.model.load_state_dict(state_dict, strict=True)
            self.engine.model.eval()
            
        self.active_calib_view = CalibrationWindow(self.root, self.engine)
        self.active_calib_view.win.bind("<Key>", self.route_global_keys)

    def open_testing(self):
        if self.active_test_view and self.active_test_view.win.winfo_exists(): return
        self.active_test_view = TestGazeWindow(self.root)
        
    def open_draw_page(self):
        if self.active_draw and self.active_draw.win.winfo_exists(): return
        self.active_draw = DrawWindow(self.root)
        
    def open_vlc_page(self):
        if self.active_vlc and self.active_vlc.winfo_exists(): return
        self.active_vlc = VLCMediaDashboard(self.root)
        
    def route_global_keys(self, event):
        key = event.keysym.lower()
        if self.active_calib_view and self.active_calib_view.win.winfo_exists():
            # If currently training, lock inputs to avoid corrupting data mid-run
            if getattr(self.active_calib_view, 'is_tuning', False):
                return
                
            if key == "space":
                tx, ty = self.active_calib_view.targets[self.active_calib_view.target_idx]
                norm_tx = (tx / self.active_calib_view.w) * 2.0 - 1.0
                norm_ty = (ty / self.active_calib_view.h) * 2.0 - 1.0
                
                if self.latest_features is not None:
                    self.engine.calibration_samples.append((self.latest_features, (norm_tx, norm_ty)))
                    print(f"[Captured Blueprint] Row logged to target: {(tx, ty)}")
                    self.active_calib_view.target_idx = (self.active_calib_view.target_idx + 1) % len(self.active_calib_view.targets)
            
            elif key == "t":
                print("[Key]: T has been pressed. Swifting optimization algorithms to worker background thread...")
                self.active_calib_view.is_tuning = True
                
                def progress_hook(percentage):
                    self.tuning_progress_queue.put(percentage)
                    
                tune_thread = threading.Thread(
                    target=self.engine.local_fine_tune,
                    args=(progress_hook,),
                    daemon=True
                )
                tune_thread.start()
                
            elif key == "q":
                self.active_calib_view.win.destroy()
                self.active_calib_view = None

    def finish_calibration_workflow(self):
        if self.active_calib_view and self.active_calib_view.win.winfo_exists():
            # Bring up a clean modal popup alert confirming completion status
            messagebox.showinfo("EyeTheia Engine", "User Calibration Fine-Tuning Complete!\nYour custom layout profiles have been saved successfully.")
            self.active_calib_view.win.destroy()
            self.active_calib_view = None
            print("[Dashboard Hub] Calibration window cleanly dismantled automatically.")