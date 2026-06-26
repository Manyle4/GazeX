import math
import time
import pyautogui
from tkinter import ttk

class GazeSnappingManager:
    def __init__(self, snapping_radius=220, timeout_seconds=2.5):
        self.snapping_radius = snapping_radius
        self.timeout_seconds = timeout_seconds
        
        self.active_button = None
        self.last_highlight_time = 0
        
    def update_snapping(self, current_gaze_x, current_gaze_y, buttons_list):
        """
        Calculates proximity to all visible buttons, highlights the closest one, 
        and warps the OS hardware mouse cursor to its center.
        """
        current_time = time.time()
        closest_button = None
        min_distance = float('inf')

        # 1. Find the closest button within the snapping radius
        for btn in buttons_list:
            if btn.winfo_exists() and btn.winfo_viewable():
                # Compute absolute center coordinate of the button on the screen
                bx = btn.winfo_rootx() + (btn.winfo_width() // 2)
                by = btn.winfo_rooty() + (btn.winfo_height() // 2)
                
                distance = math.sqrt((current_gaze_x - bx)**2 + (current_gaze_y - by)**2)
                
                if distance < min_distance and distance <= self.snapping_radius:
                    min_distance = distance
                    closest_button = btn

        # 2. Handle visual state updates and cursor warping
        if closest_button:
            # If the user's focus shifted to a different button, un-highlight the old one
            if self.active_button and self.active_button != closest_button:
                if self.active_button.winfo_exists():
                    self.active_button.config(style="BigDashboard.TButton")
            
            # Apply the highlighted style to the new button focus
            self.active_button = closest_button
            self.last_highlight_time = current_time
            if self.active_button.winfo_exists():
                self.active_button.config(style="Snapped.TButton")
            
            # Warp the physical cursor to the center of the target button
            btn_center_x = closest_button.winfo_rootx() + (closest_button.winfo_width() // 2)
            btn_center_y = closest_button.winfo_rooty() + (closest_button.winfo_height() // 2)
            pyautogui.moveTo(btn_center_x, btn_center_y)
            
        else:
            # De-highlight the active button if the gaze drifts away past the timeout
            if self.active_button and (current_time - self.last_highlight_time >= self.timeout_seconds):
                if self.active_button.winfo_exists():
                    self.active_button.config(style="BigDashboard.TButton")
                self.active_button = None