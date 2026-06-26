import tkinter as tk
from tkinter import ttk
import subprocess
import os
import psutil
import pyautogui

class VLCMediaDashboard:
    def __init__(self, parent_root):
        self.root = parent_root
        
        # ─── 1. INITIALIZE MAIN VLC DASHBOARD WINDOW ───
        self.win = tk.Toplevel(self.root)
        self.win.title("EyeTheia Media Command Center")
        
        try:
            self.win.state("zoomed")
        except tk.TclError:
            self.win.attributes("-zoomed", True)
            
        self.scr_w = self.win.winfo_screenwidth()
        self.scr_h = self.win.winfo_screenheight()
        
        if self.scr_w == 0 or self.scr_h == 0:
            self.scr_w = 1366
            self.scr_h = 768
            
        pyautogui.PAUSE = 0
        pyautogui.FAILSAFE = True
        
        # Track the active instance of our secondary control strip window
        self.strip_window_instance = None
        
        # Draw Main Dashboard UI Elements
        self.sheet = tk.Canvas(self.win, bg="#1e293b", highlightthickness=0)
        self.sheet.pack(fill=tk.BOTH, expand=True)
        
        self.sheet.create_text(self.scr_w // 2, 80, text="EyeTheia Media Control Center", font=("Arial", 22, "bold"), fill="#f8fafc")
        self.sheet.create_text(self.scr_w // 2, 120, text="Look and blink to execute commands globally", font=("Arial", 12, "italic"), fill="#06b6d4")
        
        self.button_frame = tk.Frame(self.win, bg="#1e293b")
        self.button_frame.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        
        self.launch_vlc_btn = ttk.Button(self.button_frame, text="🚀  LAUNCH VLC PLAYER", command=self.launch_vlc_application, style="BigDashboard.TButton")
        self.launch_vlc_btn.grid(row=0, column=0, columnspan=2, padx=15, pady=15, sticky="ew")
        
        self.play_btn = ttk.Button(self.button_frame, text="▶  PLAY / PAUSE", command=lambda: pyautogui.press("playpause"), style="BigDashboard.TButton")
        self.play_btn.grid(row=1, column=0, columnspan=2, padx=15, pady=15, sticky="ew")
        
        self.vol_up_btn = ttk.Button(self.button_frame, text="🔊  VOLUME UP", command=lambda: pyautogui.press("volumeup"), style="BigDashboard.TButton")
        self.vol_up_btn.grid(row=2, column=0, padx=15, pady=15)
        
        self.vol_down_btn = ttk.Button(self.button_frame, text="🔉  VOLUME DOWN", command=lambda: pyautogui.press("volumedown"), style="BigDashboard.TButton")
        self.vol_down_btn.grid(row=2, column=1, padx=15, pady=15)
        
        self.next_btn = ttk.Button(self.button_frame, text="⏭  NEXT TRACK", command=lambda: pyautogui.press("nexttrack"), style="BigDashboard.TButton")
        self.next_btn.grid(row=3, column=0, columnspan=2, padx=15, pady=15, sticky="ew")
        
        self.win.bind("<Key>", lambda e: self.close_all_media_windows() if e.keysym.lower() == 'q' else None)
        self.win.focus_force()
        
        # Start scanning system tasks to control the secondary strip window lifecycle
        self.poll_vlc_process_lifecycle()

    def poll_vlc_process_lifecycle(self):
        """ Scans active background system processes to safely open or close the secondary strip """
        vlc_active = False
        
        for proc in psutil.process_iter(['name']):
            try:
                if proc.info['name'] and 'vlc' in proc.info['name'].lower():
                    vlc_active = True
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
                
        # Handle the lifecycle allocation of the secondary window object
        if vlc_active:
            if self.strip_window_instance is None or not self.strip_window_instance.winfo_exists():
                self.spawn_secondary_control_strip()
        else:
            if self.strip_window_instance is not None and self.strip_window_instance.winfo_exists():
                print("[Media Manager] VLC closed. Dismantling secondary control strip window.")
                self.strip_window_instance.destroy()
                self.strip_window_instance = None
                
        if self.win.winfo_exists():
            self.win.after(1500, self.poll_vlc_process_lifecycle)

    # ─── 2. SPAWN SECONDARY CONTROL STRIP WINDOW ───
    def spawn_secondary_control_strip(self):
        """ Spawns a dedicated, horizontal secondary window locked permanently on top """
        print("[Media Manager] Movie loaded in VLC. Spawning secondary control strip overlay...")
        
        # Create secondary window off our main layout frame reference
        self.strip_window_instance = tk.Toplevel(self.win)
        self.strip_window_instance.title("EyeTheia Accessible Overlay Strip")
        
        # Configure borderless kiosk behavior styling rules
        self.strip_window_instance.overrideredirect(True)
        self.strip_window_instance.attributes("-topmost", True)
        
        # Calculate window boundary sizes (Height: 140px, placed perfectly at screen bottom)
        strip_h = 140
        start_y = self.scr_h - strip_h
        self.strip_window_instance.geometry(f"{self.scr_w}x{strip_h}+0+{start_y}")
        
        # Layout Canvas Surface
        strip_sheet = tk.Canvas(self.strip_window_instance, bg="#0f172a", highlightthickness=0)
        strip_sheet.pack(fill=tk.BOTH, expand=True)
        
        # Flat horizontal layout frame mapping panel
        strip_frame = tk.Frame(self.strip_window_instance, bg="#0f172a")
        strip_frame.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        
        # Pack identical hotkey buttons into a single horizontal row structure
        s_play = ttk.Button(strip_frame, text="▶  PLAY / PAUSE", command=self.trigger_vlc_play_pause, style="BigDashboard.TButton")
        s_up = ttk.Button(strip_frame, text="🔊  VOL UP", command=lambda: pyautogui.press("volumeup"), style="BigDashboard.TButton")
        s_down = ttk.Button(strip_frame, text="🔉  VOL DOWN", command=lambda: pyautogui.press("volumedown"), style="BigDashboard.TButton")
        s_next = ttk.Button(strip_frame, text="⏭  NEXT", command=lambda: pyautogui.press("nexttrack"), style="BigDashboard.TButton")
        
        s_play.grid(row=0, column=0, padx=15, pady=5)
        s_up.grid(row=0, column=1, padx=15, pady=5)
        s_down.grid(row=0, column=2, padx=15, pady=5)
        s_next.grid(row=0, column=3, padx=15, pady=5)

    def launch_vlc_application(self):
        standard_path = "C:\\Program Files\\VideoLAN\\VLC\\vlc.exe"
        secondary_path = "C:\\Program Files (x86)\\VideoLAN\\VLC\\vlc.exe"
        try:
            if os.path.exists(standard_path):
                subprocess.Popen([standard_path])
            elif os.path.exists(secondary_path):
                subprocess.Popen([secondary_path])
            else:
                subprocess.Popen(["vlc"])
        except Exception as error:
            print(f"[Launcher Error] Failed calling subprocess path link: {error}")

    def close_all_media_windows(self):
        """ Clean clean exit dismantling all active child process window trackers """
        if self.strip_window_instance is not None and self.strip_window_instance.winfo_exists():
            self.strip_window_instance.destroy()
        self.win.destroy()
        
    # 1. Add this function inside your VLCMediaDashboard class body:
    def trigger_vlc_play_pause(self):
        """ Dynamically targets the running VLC instance and toggles play/pause using the spacebar """
        import pygetwindow as gw
        import pyautogui
        import time
        
        try:
            # Look for any active window that has "VLC" in its title bar
            vlc_windows = [w for w in gw.getAllTitles() if 'vlc' in w.lower()]
            
            if vlc_windows:
                # Target the first matching VLC window instance found
                target_win = gw.getWindowsWithTitle(vlc_windows[0])[0]
                
                # If minimized, restore it safely
                if target_win.isMinimized:
                    target_win.restore()
                    
                # Force the movie window to the absolute front of the OS desk row
                target_win.activate()
                time.sleep(0.05) # Tiny delay to allow window focus to switch safely
                
                # Fire the native spacebar tap to toggle play/pause instantly!
                pyautogui.press("space")
                
                # Optional: Send focus right back to your control strip so eye-tracking stays locked
                if self.strip_window_instance and self.strip_window_instance.winfo_exists():
                    self.strip_window_instance.focus_force()
            else:
                # Fallback to the generic media key string if no open window title matches
                pyautogui.press("playpause")
        except Exception as e:
            # Safe structural fallback to prevent crashes if pygetwindow experiences an error
            pyautogui.press("playpause")