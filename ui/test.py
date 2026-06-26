import tkinter as tk
from tkinter import ttk
import pyautogui
from utils.snapping import GazeSnappingManager

class TestGazeWindow:
    def __init__(self, parent_root):
        self.root = parent_root
        self.win = tk.Toplevel(self.root)
        self.win.title("System Verification Arena")
        
        try:
            self.win.state("zoomed")
        except tk.TclError:
            self.win.attributes("-zoomed", True)
            
            
        self.snapping_manager = GazeSnappingManager(snapping_radius=220, timeout_seconds=2.5)
        
        self.count = 1
        
        # Styled UI display elements inside child frames
        self.lbl = ttk.Label(self.win, text="Click Counter Status -> 0", font=("Arial", 14, "bold"))
        self.lbl.pack(pady=40)
        
        # Re-apply our heavy styled button token to the child page layout
        self.click_target_btn = ttk.Button(
            self.win, 
            text="CLICK TARGET ME", 
            command=self.increment_action,
            style="BigDashboard.TButton"  # ◄── Uses your big custom colored button look!
        )
        self.click_target_btn.pack(pady=20)
        
        self.reset_counter_btn = ttk.Button(
            self.win,
            text="🔄  RESET TRACKER COUNT",
            command=self.reset_action,
            style="BigDashboard.TButton"
        )
        self.reset_counter_btn.pack(pady=20)
        
        # ─── 2. REGISTER TARGET BUTTONS FOR SNAPPING ───
        # Simply add any button you want to be gaze-snappable straight into this list!
        self.buttons_registry = [self.click_target_btn, self.reset_counter_btn]
        
        # Start the local real-time snapping coordinate tracking tick
        self.gaze_tracking_loop_tick()
        
    def gaze_tracking_loop_tick(self):
        """ Periodically pulls smooth coordinates from the main runtime and runs snapping updates """
        try:
            # Dynamically grab the real-time smooth coordinates from your app's main script core
            current_x = self.root.smooth_x
            current_y = self.root.smooth_y
        except Exception:
            # Fallback to mouse position if properties aren't accessible during thread handshake initialization
            current_x, current_y = pyautogui.position()

        # ─── 3. EXECUTE REUSABLE SNAPPING LOGIC ───
        # This single line handles distance checking, visual highlighting, and cursor warping!
        self.snapping_manager.update_snapping(current_x, current_y, self.buttons_registry)
        
        # Re-schedule the tracking tick pass every 20ms to match incoming worker frame changes
        if self.win.winfo_exists():
            self.win.after(20, self.gaze_tracking_loop_tick)

    def increment_action(self):
        self.lbl.config(text=f"Click Counter Status -> {self.count}")
        self.count += 1
    
    def reset_action(self):
        self.count = 1
        self.lbl.config(text="Click Counter Status -> 0")