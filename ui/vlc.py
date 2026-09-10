"""
ui/vlc.py
=========
VLC Media Control Dashboard with right-side panel overlay.

Key Layout Constraints:
  - Main view: Clean paginated list of available movies with high-visibility buttons.
  - Right panel: 160px overlay restricted to the top 75% screen height to avoid
    eyelid occlusion artifacts in the lower quadrant.
"""

import os
import subprocess
import time
import tkinter as tk
from tkinter import ttk
import psutil
import pyautogui

try:
    import pygetwindow as gw
except ImportError:
    gw = None

from core.dwell_controller import DwellController, DwellState


# ── Configuration ─────────────────────────────────────────────────────────────
MOVIE_FOLDER     = os.path.join(os.path.expanduser("~"), "Videos")
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".m4v", ".mpg", ".mpeg"}
VLC_PATHS        = [
    r"C:\Program Files\VideoLAN\VLC\vlc.exe",
    r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
]

PANEL_WIDTH       = 160    # px — right panel width
PANEL_GAZE_ZONE   = 500    # px from right edge — gaze activates panel controller
PANEL_HIDE_AFTER  = 3.0    # seconds without gaze before panel dims
PANEL_ZONE_HEIGHT = 0.75 
PANEL_ZONE_TOP    = 0.20   # top offset margin

def _find_vlc() -> str | None:
    for path in VLC_PATHS:
        if os.path.exists(path):
            return path
    return None


def _scan_movies() -> list[str]:
    if not os.path.isdir(MOVIE_FOLDER):
        return []
    return [
        os.path.join(MOVIE_FOLDER, name)
        for name in sorted(os.listdir(MOVIE_FOLDER))
        if os.path.splitext(name)[1].lower() in VIDEO_EXTENSIONS
    ]


class VLCMediaDashboard:

    def __init__(self, parent_root, dashboard):
        self.root      = parent_root
        self.dashboard = dashboard

        self.win = tk.Toplevel(self.root)
        self.win.title("GazeX Media Control")

        try:
            self.win.state("zoomed")
        except tk.TclError:
            self.win.attributes("-zoomed", True)

        self.scr_w = self.win.winfo_screenwidth() or 1366
        self.scr_h = self.win.winfo_screenheight() or 768

        # Fallback point to hold steady during blinks
        self._last_open_gaze = (self.scr_w // 2, self.scr_h // 2)

        pyautogui.PAUSE    = 0
        pyautogui.FAILSAFE = False

        self.vlc_process = None

        # Right panel state
        self._panel_win            = None
        self._panel_dwell          = None
        self._panel_buttons        = []
        self._panel_last_gaze_time = time.monotonic()
        self._panel_visible        = True

        # Panel button slots (relabeled in place)
        self._panel_page       = 0
        self._panel_btn_top    = None
        self._panel_btn_mid    = None
        self._panel_btn_bottom = None

        # Main view state
        self._movie_buttons = []
        self._movie_page    = 0
        self._main_dwell    = self._make_dwell_controller()

        # Build persistent UI frame layout
        self._init_layout()
        self._show_movie_list(page=0)

        self.win.protocol("WM_DELETE_WINDOW", self._on_close)
        self.win.focus_force()

        self._poll_vlc()
        self._tick()

    # ── Dwell controller factory ──────────────────────────────────────────

    def _make_dwell_controller(self) -> DwellController:
        return DwellController(
            dwell_seconds=1.5,
            switch_margin=40.0,
            min_hold_seconds=0.3,
            cooldown_seconds=0.8,
        )

    # ── UI Layout ─────────────────────────────────────────────────────────

    def _init_layout(self):
        """Initializes constant UI elements to prevent destroy/rebuild flickering."""
        dash_w = self.scr_w - PANEL_WIDTH
        center_x = dash_w // 2

        self._main_container = tk.Frame(self.win, bg="#1e293b")
        self._main_container.pack(fill=tk.BOTH, expand=True)

        self._title_lbl = tk.Label(
            self._main_container,
            text="Select a Movie",
            font=("Arial", 22, "bold"),
            bg="#1e293b",
            fg="#f8fafc",
        )
        self._title_lbl.place(x=center_x, y=50, anchor=tk.CENTER)

        # Dynamic containers for movie options and navigation
        self._list_frame = tk.Frame(self._main_container, bg="#1e293b")
        self._list_frame.place(
            x=center_x, rely=0.42, anchor=tk.CENTER, width=min(800, dash_w - 80)
        )

        self._nav_frame = tk.Frame(self._main_container, bg="#1e293b")
        self._nav_frame.place(
            x=center_x, rely=0.80, anchor=tk.CENTER, width=min(850, dash_w - 60)
        )
        self._nav_frame.grid_columnconfigure(0, weight=1, uniform="nav")
        self._nav_frame.grid_columnconfigure(1, weight=1, uniform="nav")
        self._nav_frame.grid_columnconfigure(2, weight=1, uniform="nav")

        # Status indicators
        self._status_lbl = ttk.Label(
            self._main_container,
            text="Look at a movie — blink to play",
            font=("Arial", 12),
            background="#1e293b",
            foreground="#94a3b8",
        )
        self._status_lbl.place(x=center_x, rely=0.91, anchor=tk.CENTER)

        self._progress_var = tk.DoubleVar(value=0.0)
        self._progress_bar = ttk.Progressbar(
            self._main_container,
            variable=self._progress_var,
            maximum=100,
            length=350,
            mode="determinate",
        )
        self._progress_bar.place(x=center_x, rely=0.95, anchor=tk.CENTER)

    def _show_movie_list(self, page: int = 0):
        MOVIES_PER_PAGE = 3
        movies = _scan_movies()
        self._movie_page = page
        self._movie_buttons.clear()
        self._main_dwell = self._make_dwell_controller()

        # Clear existing dynamic buttons inside frames
        for w in self._list_frame.winfo_children():
            w.destroy()
        for w in self._nav_frame.winfo_children():
            w.destroy()

        total_pages = max(1, (len(movies) + MOVIES_PER_PAGE - 1) // MOVIES_PER_PAGE)
        self._title_lbl.config(text=f"Select a Movie   (page {page + 1} of {total_pages})")

        start = page * MOVIES_PER_PAGE
        page_movies = movies[start : start + MOVIES_PER_PAGE]

        # ── Grid setup: 2 columns, same pattern as the main dashboard ──
        self._list_frame.grid_columnconfigure(0, weight=1, uniform="movie_col")
        self._list_frame.grid_columnconfigure(1, weight=1, uniform="movie_col")
        self._list_frame.grid_rowconfigure(0, weight=1)
        self._list_frame.grid_rowconfigure(1, weight=1)

        if not movies:
            lbl = tk.Label(
                self._list_frame,
                text=f"No video files found in:\n{MOVIE_FOLDER}",
                font=("Arial", 14),
                bg="#1e293b",
                fg="#94a3b8",
                justify=tk.CENTER,
            )
            lbl.grid(row=0, column=0, columnspan=2, pady=20)
        else:
            # Grid slots for up to 3 buttons: two on top, one spanning the
            # bottom — identical layout logic to btn_frame in main_dashboard.py
            slots = [(0, 0, 1), (0, 1, 1), (1, 0, 2)]  # (row, col, columnspan)

            for i, filepath in enumerate(page_movies):
                name = os.path.splitext(os.path.basename(filepath))[0]
                if len(name) > 40:
                    name = name[:37] + "..."
                btn = ttk.Button(
                    self._list_frame,
                    text=name,
                    command=lambda fp=filepath: self._play_movie(fp),
                    style="BigDashboard.TButton",
                )
                row, col, span = slots[i]
                btn.grid(
                    row=row, column=col, columnspan=span,
                    padx=20, pady=20, ipadx=10, ipady=28, sticky="nsew",
                )
                self._movie_buttons.append(btn)

        # ── Navigation row (already grid-based — unchanged) ──
        if page > 0:
            prev_btn = ttk.Button(
                self._nav_frame,
                text="PREV",
                command=lambda: self._show_movie_list(page - 1),
                style="BigDashboard.TButton",
            )
            prev_btn.grid(row=0, column=0, ipady=12, padx=15, sticky="w")
            self._movie_buttons.append(prev_btn)

        close_btn = ttk.Button(
            self._nav_frame,
            text="CLOSE",
            command=self._on_close,
            style="BigDashboard.TButton",
        )
        close_btn.grid(row=0, column=1, ipady=12, padx=15)

        if start + MOVIES_PER_PAGE < len(movies):
            next_btn = ttk.Button(
                self._nav_frame,
                text="NEXT",
                command=lambda: self._show_movie_list(page + 1),
                style="BigDashboard.TButton",
            )
            next_btn.grid(row=0, column=2, ipady=12, padx=15, sticky="e")
            self._movie_buttons.append(next_btn)

        self.win.after(300, lambda: self._main_dwell.set_buttons(self._movie_buttons + [close_btn]))

    # ── Movie playback ────────────────────────────────────────────────────

    def _play_movie(self, filepath: str):
        vlc = _find_vlc()
        if vlc is None:
            print("[VLC] vlc.exe not found.")
            return

        if self.vlc_process is None or self.vlc_process.poll() is not None:
            self.vlc_process = subprocess.Popen([vlc, filepath])

        self._main_dwell.reset()
        pyautogui.moveTo(self.scr_w // 2, self.scr_h // 2)


    # ── Right panel ───────────────────────────────────────────────────────

    def _spawn_panel(self):
        self._panel_win = tk.Toplevel(self.win)
        self._panel_win.title("GazeX Controls")
        self._panel_win.overrideredirect(True)
        self._panel_win.attributes("-topmost", True)
        self._panel_win.geometry(f"{PANEL_WIDTH}x{self.scr_h}+{self.scr_w - PANEL_WIDTH}+0")

        frame = tk.Frame(self._panel_win, bg="#0f172a")
        frame.place(relx=0, rely=0, relwidth=1, relheight=1)

        self._panel_page       = 0
        self._panel_btn_top    = ttk.Button(frame, style="BigDashboard.TButton")
        self._panel_btn_mid    = ttk.Button(frame, style="BigDashboard.TButton")
        self._panel_btn_bottom = ttk.Button(frame, style="BigDashboard.TButton")

        self._apply_panel_page()

        self._panel_buttons = [self._panel_btn_top, self._panel_btn_mid, self._panel_btn_bottom]
        self._layout_panel_buttons(self._panel_buttons)

        self._panel_dwell          = DwellController(
            dwell_seconds=1.5,
            switch_margin=60.0,
            min_hold_seconds=0.3,
            cooldown_seconds=0.8,
        )
        self._panel_last_gaze_time = time.monotonic()
        self._panel_visible        = True

        def _reassert_top():
            if self._panel_win and self._panel_win.winfo_exists():
                self._panel_win.lift()
                self._panel_win.attributes("-topmost", True)
                self._panel_dwell.set_buttons(self._panel_buttons)
                
                print(f"[Panel] Gaze zone: gx >= {self.scr_w - PANEL_GAZE_ZONE}  (panel right edge: {self.scr_w})")

        self._panel_win.after(700, _reassert_top)

    def _layout_panel_buttons(self, buttons, top_margin=PANEL_ZONE_TOP, zone_height=PANEL_ZONE_HEIGHT):
        n = len(buttons)
        if n == 1:
            buttons[0].place(relx=0.5, rely=zone_height / 2, anchor=tk.CENTER, relwidth=0.85)
            return
        usable = zone_height - top_margin
        for i, btn in enumerate(buttons):
            rely = top_margin + (usable * i / (n - 1))
            btn.place(relx=0.5, rely=rely, anchor=tk.CENTER, relwidth=0.85)

    def _apply_panel_page(self):
        if self._panel_page == 0:
            # CLOSE moved to the TOP slot (best accuracy in the strip) since
            # it's the highest-consequence action; NEXT (low-cost, retryable
            # if mis-selected) takes the bottom slot instead.
            self._panel_btn_top.config(text="CLOSE", command=self._destroy_panel)
            self._panel_btn_mid.config(text="PLAY\nPAUSE", command=self._vlc_play_pause)
            self._panel_btn_bottom.config(text="NEXT", command=self._panel_next_page)
        else:
            self._panel_btn_top.config(text="PREV", command=self._panel_prev_page)
            self._panel_btn_mid.config(text="VOL\nUP", command=lambda: pyautogui.press("volumeup"))
            self._panel_btn_bottom.config(text="VOL\nDOWN", command=lambda: pyautogui.press("volumedown"))

    def _panel_next_page(self):
        self._panel_page = 1
        self._apply_panel_page()
        if self._panel_dwell is not None:
            self._panel_dwell.reset()

    def _panel_prev_page(self):
        self._panel_page = 0
        self._apply_panel_page()
        if self._panel_dwell is not None:
            self._panel_dwell.reset()

    def _destroy_panel(self):
        if self.vlc_process is not None and self.vlc_process.poll() is None:
            self.vlc_process.terminate()
        self.vlc_process = None

        if self._panel_win and self._panel_win.winfo_exists():
            self._panel_win.destroy()

        self._panel_win            = None
        self._panel_dwell          = None
        self._panel_buttons        = []
        self._panel_page           = 0
        self._panel_btn_top        = None
        self._panel_btn_mid        = None
        self._panel_btn_bottom     = None

    # ── Gaze routing & Loop ───────────────────────────────────────────────

    def _gaze_on_panel(self, gx: float) -> bool:
        return gx >= (self.scr_w - PANEL_GAZE_ZONE)

    def _tick(self):
        if not self.win.winfo_exists():
            return

        try:
            raw_gx = float(self.dashboard.smooth_x)
            raw_gy = float(self.dashboard.smooth_y)
        except AttributeError:
            self.win.after(20, self._tick)
            return

        try:
            if getattr(self.dashboard, "eyes_closing", False):
                gx, gy = self._last_open_gaze
            else:
                gx, gy = raw_gx, raw_gy
                self._last_open_gaze = (gx, gy)

            if getattr(self.dashboard, "blink_triggered", False):
                self.dashboard.blink_triggered = False
                self._handle_blink(gx, gy)

            panel_active = (
                self._panel_win is not None
                and self._panel_win.winfo_exists()
                and self._panel_dwell is not None
            )
        

            if panel_active and self._gaze_on_panel(gx):
                self._panel_last_gaze_time = time.monotonic()
                self._set_panel_visibility(True)

                snap = self._panel_dwell.update(gx, gy)
                self._render_panel(snap)
                self._main_dwell.reset()
                self._check_auto_confirm(self._panel_dwell, self._panel_buttons)
            else:
                snap = self._main_dwell.update(gx, gy)
                self._render_main(snap)
                self._check_auto_confirm(self._main_dwell, self._movie_buttons)
                
                if panel_active and self._panel_dwell is not None:   # ← guard added
                    self._panel_dwell.reset()
                    elapsed = time.monotonic() - self._panel_last_gaze_time
                    if elapsed >= PANEL_HIDE_AFTER:
                        self._set_panel_visibility(False)
                    elif elapsed < 0.5:
                        self._set_panel_visibility(True)
        except Exception as e:
            print(f"[VLC] Non-fatal error in _tick: {e}")

        finally:
            self.win.after(20, self._tick)

    def _handle_blink(self, gx: float, gy: float):
        strip_active = (
            self._panel_win is not None
            and self._panel_win.winfo_exists()
            and self._panel_dwell is not None
        )

        if strip_active and self._gaze_on_panel(gx):
            btn = self._panel_dwell.on_blink()
            dwell = self._panel_dwell
            print("[Panel] A blink has been received!")
        else:
            btn = self._main_dwell.on_blink()
            dwell = self._main_dwell
            print("[VLC] A blink has been received!")

        if btn is not None:
            try:
                btn.invoke()
                print("[VLC] The button has been invoked")
            except tk.TclError as e:
                print(f"[VLC] invoke() failed: {e}")
        elif dwell.is_selected():
            print("[VLC/Panel] Selection was ready but blink not accepted — trying gaze-based fallback")
            self._invoke_nearest_button(dwell, gx, gy)
        else:
            print("[VLC/Panel] Blink received but no button fully selected yet — ignoring")
            
    def _set_panel_visibility(self, visible: bool):
        if self._panel_win is None or not self._panel_win.winfo_exists():
            return
        if visible == self._panel_visible:
            return
        self._panel_visible = visible
        alpha = 1.0 if visible else 0.15
        try:
            self._panel_win.attributes("-alpha", alpha)
        except tk.TclError:
            pass
        
    def _invoke_nearest_button(self, dwell_controller, gx, gy) -> bool:
        btn = dwell_controller.get_nearest_button(gx, gy)
        if btn is not None:
            try:
                btn.invoke()
                print("[VLC] Fallback: invoked nearest button (gaze-based)")
                return True
            except tk.TclError as e:
                print(f"[VLC] Fallback invoke() failed: {e}")
        else:
            print("[VLC] Fallback: no live button found near gaze")
        return False

    def _check_auto_confirm(self, dwell_controller, candidates):
        """Plan C fallback — independent of blink entirely."""
        btn = dwell_controller.check_timeout(timeout_seconds=3.0)
        if btn is not None and btn in candidates:
            try:
                btn.invoke()
                print("[VLC] Auto-confirm (timeout) invoked the button")
            except tk.TclError as e:
                print(f"[VLC] Auto-confirm invoke() failed: {e}")

    # ── Rendering ─────────────────────────────────────────────────────────

    def _render_main(self, snapshot):
        try:
            self._progress_var.set(snapshot.progress * 100)
            self._status_lbl.config(text=snapshot.status_text)
        except (tk.TclError, AttributeError):
            pass
        
        if snapshot.move_cursor_to is not None:
            btn = snapshot.move_cursor_to
            try:
                if btn.winfo_exists():
                    cx = btn.winfo_rootx() + btn.winfo_width()  / 2
                    cy = btn.winfo_rooty() + btn.winfo_height() / 2
                    pyautogui.moveTo(int(cx), int(cy))
            except tk.TclError:
                pass

        for btn in self._movie_buttons:
            try:
                if not btn.winfo_exists():
                    continue
                style = (
                    "Snapped.TButton"
                    if (btn is snapshot.target and snapshot.state == DwellState.SELECTED)
                    else "BigDashboard.TButton"
                )
                btn.config(style=style)
            except tk.TclError:
                pass

    def _render_panel(self, snapshot):
        if snapshot.move_cursor_to is not None:
            btn = snapshot.move_cursor_to
            try:
                if btn.winfo_exists():
                    cx = btn.winfo_rootx() + btn.winfo_width()  / 2
                    cy = btn.winfo_rooty() + btn.winfo_height() / 2
                    pyautogui.moveTo(int(cx), int(cy))
            except tk.TclError:
                pass
        
        for btn in self._panel_buttons:
            try:
                if not btn.winfo_exists():
                    continue
                style = (
                    "Snapped.TButton"
                    if (btn is snapshot.target and snapshot.state == DwellState.SELECTED)
                    else "BigDashboard.TButton"
                )
                btn.config(style=style)
            except tk.TclError:
                pass

    # ── VLC process watcher & controls ────────────────────────────────────

    def _poll_vlc(self):
        if not self.win.winfo_exists():
            return

        vlc_running = self.vlc_process is not None and self.vlc_process.poll() is None
        panel_exists = self._panel_win is not None and self._panel_win.winfo_exists()

        if vlc_running and not panel_exists:
            self._spawn_panel()
        elif not vlc_running and panel_exists:
            self._destroy_panel()

        self.win.after(1500, self._poll_vlc)
    def _vlc_play_pause(self):
        if gw is not None:
            try:
                matches = [t for t in gw.getAllTitles() if "vlc" in t.lower()]
                if matches:
                    w = gw.getWindowsWithTitle(matches[0])[0]
                    if w.isMinimized:
                        w.restore()
                    w.activate()
                    time.sleep(0.05)
                    pyautogui.press("space")
                    if self._panel_win and self._panel_win.winfo_exists():
                        self._panel_win.focus_force()
                    return
            except Exception:
                pass
        pyautogui.press("playpause")

    # ── Cleanup ───────────────────────────────────────────────────────────

    def _on_close(self):
        self._main_dwell.reset()
        if self._panel_dwell:
            self._panel_dwell.reset()
        self._destroy_panel()
        self.win.destroy()