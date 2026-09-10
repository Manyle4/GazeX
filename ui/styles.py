import tkinter as tk
from tkinter import ttk

def configure_application_themes():
    """ Allocates and registers custom visual style maps globally """
    style = ttk.Style()
    
    # We choose a modern layout theme engine foundation
    style.theme_use("clam")
    
    # --- DESIGN TOKEN CONSTANTS ---
    BG_DARK      = "#0f172a"   # window/canvas background — use everywhere
    SURFACE_DARK = "#1e293b"   # button/panel body color
    TEXT_LIGHT   = "#f8fafc"
    ACCENT_CYAN  = "#06b6d4"
    ACCENT_CYAN_LIGHT = "#22d3ee"
    BORDER_COLOR = "#334155"
    MUTED_TEXT   = "#94a3b8"
    
    # Configure the base main window background frame look
    style.configure(".", background=BG_DARK, foreground=TEXT_LIGHT)
    
    style.configure("AppTitle.TLabel", font=("Arial", 28, "bold"), background=BG_DARK, foreground=TEXT_LIGHT)
    style.configure("Body.TLabel",      font=("Arial", 12),         background=BG_DARK, foreground=TEXT_LIGHT)
    style.configure("Debug.TLabel",     font=("Consolas", 10),      background=BG_DARK, foreground=MUTED_TEXT)
    
    style.configure(
        "Dwell.Horizontal.TProgressbar",
        troughcolor=SURFACE_DARK,
        background=ACCENT_CYAN,
        bordercolor=BORDER_COLOR,
        lightcolor=ACCENT_CYAN,
        darkcolor=ACCENT_CYAN,
    )
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
        bordercolor="#22d3ee",
        padding=(40, 20) 
    )
    
    # Interactive hovering state feedback animation configurations
    style.map("BigDashboard.TButton",
        background=[("active", "#475569"), ("pressed", "#0f172a")],
        bordercolor=[("active", "#22d3ee")]
    )