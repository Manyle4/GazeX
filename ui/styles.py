import tkinter as tk
from tkinter import ttk

def configure_application_themes():
    """ Allocates and registers custom visual style maps globally """
    style = ttk.Style()
    
    # We choose a modern layout theme engine foundation
    style.theme_use("clam")
    
    # --- DESIGN TOKEN CONSTANTS ---
    BG_DARK = "#1e293b"       # Sleek slate gray background
    TEXT_LIGHT = "#f8fafc"    # Off-white crisp text
    ACCENT_CYAN = "#06b6d4"   # Eye-catching cyan accent token
    BORDER_COLOR = "#334155"  # Clean custom button boundary color
    
    # Configure the base main window background frame look
    style.configure(".", background=BG_DARK, foreground=TEXT_LIGHT)
    
    # --- CUSTOM BIG BUTTON STYLES ---
    style.configure(
        "BigDashboard.TButton",
        font=("Arial", 20, "bold"),
        foreground=TEXT_LIGHT,
        background=BORDER_COLOR,      # Core body color
        borderwidth=3,                # Thick border layout array
        bordercolor=ACCENT_CYAN,      # ◄── YOUR CUSTOM OUTLINE COLOR HERE!
        lightcolor=ACCENT_CYAN,       # Secondary bevel highlights matching theme
        darkcolor=ACCENT_CYAN,
        padding=(40, 20)              # ◄── MAKES BUTTONS BIGGER (Horizontal, Vertical padding)
    )
    
    style.configure(
        "Snapped.TButton",
        font=("Arial", 13, "bold"),
        foreground="#f8fafc",     # Off-white crisp text
        background="#06b6d4",     # High-visibility Cyan accent focus fill!
        borderwidth=3,
        bordercolor="#22d3ee"
    )
    
    # Interactive hovering state feedback animation configurations
    style.map("BigDashboard.TButton",
        background=[("active", "#475569"), ("pressed", "#0f172a")],
        bordercolor=[("active", "#22d3ee")]
    )