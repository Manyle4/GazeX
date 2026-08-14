"""
ui/vlc.py
=========

VLC Media Control Dashboard with right-side panel overlay.

Layout:
  - Main dashboard: full screen, Launch VLC + Load Movie (+ controls when VLC running)
  - Right panel: 160px wide strip on the RIGHT edge, appears when VLC is detected,
                 contains playback controls stacked vertically
  - Gaze routing: if gx >= scr_w - 200, gaze goes to panel dwell controller

Why right panel instead of bottom strip:
  - Bottom-edge gaze is unreliable (eyelid occlusion when looking down)
  - Right-edge gaze sits in the reliable centre-to-right zone
  - Video is never obscured
"""

import os
import subprocess
import time
import tkinter as tk
from tkinter import ttk
import psutil
import pyautogui

from core.dwell_controller import DwellController, DwellState


# ── Configuration ─────────────────────────────────────────────────────────────
MOVIE_FOLDER     = os.path.join(os.path.expanduser("~"), "Videos")
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".m4v", ".mpg", ".mpeg"}
VLC_PATHS        = [
    r"C:\Program Files\VideoLAN\VLC\vlc.exe",
    r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
]
PANEL_WIDTH      = 160    # px — right panel width
PANEL_GAZE_ZONE  = 600    # px from right edge — gaze here activates panel controller
PANEL_HIDE_AFTER = 4.0    # seconds without gaze before panel fades (Milestone 3)


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

        self.scr_w = self.win.winfo_screenwidth()  or 1366
        self.scr_h = self.win.winfo_screenheight() or 768

        pyautogui.PAUSE    = 0
        pyautogui.FAILSAFE = False

        self.vlc_process = None

        # Right panel state
        self._panel_win     = None
        self._panel_dwell   = None
        self._panel_buttons = []
        self._panel_last_gaze_time = time.monotonic()
        self._panel_visible = True

        # View state
        self._view          = "main"
        self._movie_buttons = []

        # Main dwell controller
        self._main_dwell = self._make_dwell_controller()

        self._build_main_view()

        self.win.protocol("WM_DELETE_WINDOW", self._on_close)
        self.win.focus_force()

        self._poll_vlc()
        self._tick()

    # ── Dwell controller factory ──────────────────────────────────────────

    def _make_dwell_controller(self) -> DwellController:
        return DwellController(
            dwell_seconds    = 1.5,
            switch_margin    = 40.0,
            min_hold_seconds = 0.3,
            cooldown_seconds = 0.8,
        )

    # ── Main view ─────────────────────────────────────────────────────────

    def _build_main_view(self):
        self._clear_canvas()
        self._view = "main"
        self._movie_buttons = []

        self._canvas = tk.Canvas(self.win, bg="#1e293b", highlightthickness=0)
        self._canvas.pack(fill=tk.BOTH, expand=True)

        self._canvas.create_text(
            self.scr_w // 2, 80,
            text="GazeX Media Control",
            font=("Arial", 22, "bold"),
            fill="#f8fafc",
        )
        self._canvas.create_text(
            self.scr_w // 2, 120,
            text="Look at a button and hold gaze — blink to activate",
            font=("Arial", 12, "italic"),
            fill="#06b6d4",
        )

        # Centre button frame — leave right 160px clear for panel
        btn_frame = tk.Frame(self.win, bg="#1e293b")
        btn_frame.place(
            x=(self.scr_w - PANEL_WIDTH) // 2,
            rely=0.42,
            anchor=tk.CENTER,
        )

        # self._launch_btn = ttk.Button(
        #     btn_frame, text="LAUNCH VLC",
        #     command=self._launch_vlc,
        #     style="BigDashboard.TButton",
        # )
        # self._launch_btn.pack(pady=20, ipadx=20)

        self._load_btn = ttk.Button(
            btn_frame, text="LOAD MOVIE",
            command=self._show_movie_list,
            style="BigDashboard.TButton",
        )
        self._load_btn.pack(pady=20, ipadx=20)
        
        self._close_btn = ttk.Button(
            btn_frame, text="CLOSE",
            command=self._on_close,
            style="BigDashboard.TButton",
        )
        self._close_btn.pack(pady=20, ipadx=20)

        self._status_lbl = ttk.Label(
            self.win,
            text="Look at a button to begin",
            font=("Arial", 11),
            background="#1e293b",
            foreground="#94a3b8",
        )
        self._status_lbl.place(relx=0.45, rely=0.88, anchor=tk.CENTER)

        self._progress_var = tk.DoubleVar(value=0.0)
        self._progress_bar = ttk.Progressbar(
            self.win,
            variable=self._progress_var,
            maximum=100,
            length=320,
            mode="determinate",
        )
        self._progress_bar.place(relx=0.45, rely=0.93, anchor=tk.CENTER)

        self._main_dwell = self._make_dwell_controller()
        self.win.after(300, self._register_main_buttons)

    def _register_main_buttons(self):
        self.win.update_idletasks()
        self._main_dwell.set_buttons([self._load_btn, self._close_btn])

    # ── Movie list view ───────────────────────────────────────────────────
    
    # def _show_movie_list(self):
    #     movies = _scan_movies()
    #     self._clear_canvas()
    #     self._view = "movie_list"
    #     self._movie_buttons = []
    #     self._main_dwell = self._make_dwell_controller()

    #     self._canvas = tk.Canvas(self.win, bg="#1e293b", highlightthickness=0)
    #     self._canvas.pack(fill=tk.BOTH, expand=True)

    #     self._canvas.create_text(
    #         (self.scr_w - PANEL_WIDTH) // 2, 60,
    #         text="Select a Movie",
    #         font=("Arial", 20, "bold"),
    #         fill="#f8fafc",
    #     )
    #     self._canvas.create_text(
    #         (self.scr_w - PANEL_WIDTH) // 2, 95,
    #         text=f"Folder: {MOVIE_FOLDER}",
    #         font=("Arial", 10),
    #         fill="#64748b",
    #     )

    #     list_frame = tk.Frame(self.win, bg="#1e293b")
    #     list_frame.place(
    #         x=(self.scr_w - PANEL_WIDTH) // 2,
    #         rely=0.55,
    #         anchor=tk.CENTER,
    #         width=min(700, self.scr_w - PANEL_WIDTH - 40),
    #     )

    #     if not movies:
    #         self._canvas.create_text(
    #             (self.scr_w - PANEL_WIDTH) // 2, self.scr_h // 2,
    #             text=f"No video files found in:\n{MOVIE_FOLDER}",
    #             font=("Arial", 13),
    #             fill="#94a3b8",
    #             justify=tk.CENTER,
    #         )
    #     else:
    #         for filepath in movies[:6]:
    #             name = os.path.splitext(os.path.basename(filepath))[0]
    #             if len(name) > 45:
    #                 name = name[:42] + "..."
    #             btn = ttk.Button(
    #                 list_frame,
    #                 text=name,
    #                 command=lambda fp=filepath: self._play_movie(fp),
    #                 style="BigDashboard.TButton",
    #             )
    #             btn.pack(fill=tk.X, pady=6, padx=20)
    #             self._movie_buttons.append(btn)

    #     back_btn = ttk.Button(
    #         self.win, text="BACK",
    #         command=self._build_main_view,
    #         style="BigDashboard.TButton",
    #     )
    #     back_btn.place(relx=0.45, rely=0.92, anchor=tk.CENTER)
    #     self._movie_buttons.append(back_btn)

    #     self._status_lbl = ttk.Label(
    #         self.win,
    #         text="Look at a movie — blink to play",
    #         font=("Arial", 11),
    #         background="#1e293b",
    #         foreground="#94a3b8",
    #     )
    #     self._status_lbl.place(relx=0.45, rely=0.85, anchor=tk.CENTER)

    #     self._progress_var = tk.DoubleVar(value=0.0)
    #     self._progress_bar = ttk.Progressbar(
    #         self.win,
    #         variable=self._progress_var,
    #         maximum=100,
    #         length=320,
    #         mode="determinate",
    #     )
    #     self._progress_bar.place(relx=0.45, rely=0.89, anchor=tk.CENTER)

    #     self.win.after(300, lambda: self._main_dwell.set_buttons(self._movie_buttons))

    def _show_movie_list(self, page: int = 0):
        MOVIES_PER_PAGE = 3
        
        movies = _scan_movies()
        self._clear_canvas()
        self._view = "movie_list"
        self._movie_buttons = []
        self._main_dwell = self._make_dwell_controller()
        self._movie_page = page

        self._canvas = tk.Canvas(self.win, bg="#1e293b", highlightthickness=0)
        self._canvas.pack(fill=tk.BOTH, expand=True)

        total_pages = max(1, (len(movies) + MOVIES_PER_PAGE - 1) // MOVIES_PER_PAGE)
        self._canvas.create_text(
            (self.scr_w - PANEL_WIDTH) // 2, 60,
            text=f"Select a Movie   (page {page + 1} of {total_pages})",
            font=("Arial", 20, "bold"),
            fill="#f8fafc",
        )

        list_frame = tk.Frame(self.win, bg="#1e293b")
        list_frame.place(
            x=(self.scr_w - PANEL_WIDTH) // 2,
            rely=0.5,
            anchor=tk.CENTER,
            width=min(700, self.scr_w - PANEL_WIDTH - 40),
        )

        start = page * MOVIES_PER_PAGE
        page_movies = movies[start:start + MOVIES_PER_PAGE]

        if not movies:
            self._canvas.create_text(
                (self.scr_w - PANEL_WIDTH) // 2, self.scr_h // 2,
                text=f"No video files found in:\n{MOVIE_FOLDER}",
                font=("Arial", 13), fill="#94a3b8", justify=tk.CENTER,
            )
        else:
            for filepath in page_movies:
                name = os.path.splitext(os.path.basename(filepath))[0]
                if len(name) > 45:
                    name = name[:42] + "..."
                btn = ttk.Button(
                    list_frame, text=name,
                    command=lambda fp=filepath: self._play_movie(fp),
                    style="BigDashboard.TButton",
                )
                # generous vertical spacing — this is the whole point of pagination
                btn.pack(fill=tk.X, pady=16, padx=20, ipady=10)
                self._movie_buttons.append(btn)

        # ── Nav row: CLOSE / PREV / NEXT — always exactly these, never more ──
        nav_frame = tk.Frame(self.win, bg="#1e293b")
        nav_frame.place(relx=0.45, rely=0.85, anchor=tk.CENTER)

        close_btn = ttk.Button(
            nav_frame, text="CLOSE",
            command=self._build_main_view,   # "close this page" = back to main
            style="BigDashboard.TButton",
        )
        close_btn.pack(side=tk.LEFT, padx=20)
        self._movie_buttons.append(close_btn)

        if page > 0:
            prev_btn = ttk.Button(
                nav_frame, text="PREV",
                command=lambda: self._show_movie_list(page - 1),
                style="BigDashboard.TButton",
            )
            prev_btn.pack(side=tk.LEFT, padx=20)
            self._movie_buttons.append(prev_btn)

        if start + MOVIES_PER_PAGE < len(movies):
            next_btn = ttk.Button(
                nav_frame, text="NEXT",
                command=lambda: self._show_movie_list(page + 1),
                style="BigDashboard.TButton",
            )
            next_btn.pack(side=tk.LEFT, padx=20)
            self._movie_buttons.append(next_btn)

        self._status_lbl = ttk.Label(
            self.win, text="Look at a movie — blink to play",
            font=("Arial", 11), background="#1e293b", foreground="#94a3b8",
        )
        self._status_lbl.place(relx=0.45, rely=0.92, anchor=tk.CENTER)

        self._progress_var = tk.DoubleVar(value=0.0)
        self._progress_bar = ttk.Progressbar(
            self.win, variable=self._progress_var, maximum=100,
            length=320, mode="determinate",
        )
        self._progress_bar.place(relx=0.45, rely=0.96, anchor=tk.CENTER)

        self.win.after(300, lambda: self._main_dwell.set_buttons(self._movie_buttons))
    
    # ──End Movie list view End───────────────────────────────────────────────────

    # ── Movie playback ────────────────────────────────────────────────────

    def _play_movie(self, filepath: str):
        vlc = _find_vlc()
        if vlc is None:
            print("[VLC] vlc.exe not found.")
            return
        print(f"[VLC] Playing: {os.path.basename(filepath)}")
        if self.vlc_process is not None:
            pass
        else:
            self.vlc_process = subprocess.Popen([vlc, filepath])

        # Reset dwell so stale button references are cleared immediately
        self._main_dwell.reset()

        # Move cursor to screen centre so it is not stuck on the dead movie button.
        # The panel will appear on the right edge — moving to centre gives the user
        # a neutral starting position from which gaze can reach the panel.
        pyautogui.moveTo(self.scr_w // 2, self.scr_h // 2)

        self.win.after(800, self._build_main_view)

    # ── Canvas management ─────────────────────────────────────────────────

    def _clear_canvas(self):
        for widget in self.win.winfo_children():
            if self._panel_win and widget is self._panel_win:
                continue
            widget.destroy()

    # ── Right panel ───────────────────────────────────────────────────────

    def _spawn_panel(self):
        print("[VLC] Spawning right panel.")
        
        self._panel_win = tk.Toplevel(self.win)
        self._panel_win.title("GazeX Controls")
        self._panel_win.overrideredirect(True)
        self._panel_win.attributes("-topmost", True)
        self._panel_win.geometry(
            f"{PANEL_WIDTH}x{self.scr_h}+{self.scr_w - PANEL_WIDTH}+0"
        )
        self._panel_win.update_idletasks()
        
        panel_canvas = tk.Canvas(
            self._panel_win, bg="#0f172a", highlightthickness=0
        )
        panel_canvas.pack(fill=tk.BOTH, expand=True)
        
        frame = tk.Frame(self._panel_win, bg="#0f172a")
        frame.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        # s_play = ttk.Button(frame, text="PLAY\nPAUSE",  command=self._vlc_play_pause,                  style="Panel.TButton")
        s_play = ttk.Button(frame, text="PLAY\nPAUSE",  command=self._close_panel,                  style="Panel.TButton")
        s_up   = ttk.Button(frame, text="VOL\nUP",      command=lambda: pyautogui.press("volumeup"),   style="Panel.TButton")
        s_down = ttk.Button(frame, text="VOL\nDOWN",    command=lambda: pyautogui.press("volumedown"), style="Panel.TButton")
        s_close = ttk.Button(frame, text="CLOSE",       command=self._close_panel,                 style="Panel.TButton")
        
        for btn in [s_play, s_up, s_down, s_close]:
            btn.pack(pady=18, padx=8, fill=tk.X)

        self._panel_buttons = [s_play, s_up, s_down, s_close]
        self._panel_dwell   = self._make_dwell_controller()
        self._panel_last_gaze_time = time.monotonic()
        self._panel_visible = True

        # Re-assert topmost after 700ms — VLC steals window focus when it opens
        # and knocks our panel behind it. Lifting again puts it back on top.
        def _reassert_top():
            if self._panel_win and self._panel_win.winfo_exists():
                self._panel_win.lift()
                self._panel_win.attributes("-topmost", True)
                self._panel_dwell.set_buttons(self._panel_buttons)
                # Print actual button positions so you can verify gaze reaches them
                self._panel_win.update_idletasks()
                for btn in self._panel_buttons:
                    cx = btn.winfo_rootx() + btn.winfo_width()  / 2
                    cy = btn.winfo_rooty() + btn.winfo_height() / 2
                    print(f"[Panel] '{btn.cget('text').replace(chr(10),' ')}' center=({cx:.0f},{cy:.0f})")
                print(f"[Panel] Gaze zone: gx >= {self.scr_w - PANEL_GAZE_ZONE}  (panel right edge: {self.scr_w})")

        self._panel_win.after(700, _reassert_top)


    def _destroy_panel(self):
        if self._panel_win and self._panel_win.winfo_exists():
            self._panel_win.destroy()
        self._panel_win     = None
        self._panel_dwell   = None
        self._panel_buttons = []
        print("[VLC] Panel destroyed.")

    # ── Gaze routing ──────────────────────────────────────────────────────

    def _gaze_on_panel(self, gx: float) -> bool:
        """Returns True if gaze X is within the panel gaze zone (right edge area)."""
        return gx >= (self.scr_w - PANEL_GAZE_ZONE)

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

        # Blink handling
        if getattr(self.dashboard, "blink_triggered", False):
            self.dashboard.blink_triggered = False
            self._handle_blink(gx, gy)

        panel_active = (
            self._panel_win is not None
            and self._panel_win.winfo_exists()
            and self._panel_dwell is not None
        )
        
        # Temporary debug — remove after confirming panel works
        if panel_active:
            print(f"[Tick] gx={int(gx)} screen width={self.scr_w} panel_threshold={self.scr_w - PANEL_GAZE_ZONE}  on_panel={self._gaze_on_panel(gx)}")

        if panel_active and self._gaze_on_panel(gx):
            # Gaze is in panel zone
            self._panel_last_gaze_time = time.monotonic()
            self._set_panel_visibility(True)

            snap = self._panel_dwell.update(gx, gy)
            self._render_panel(snap)
            self._main_dwell.reset()

        else:
            # Gaze is on main dashboard
            snap = self._main_dwell.update(gx, gy)
            self._render_main(snap)

            if panel_active:
                self._panel_dwell.reset()
                # Milestone 3: fade panel if gaze has been away too long
                elapsed = time.monotonic() - self._panel_last_gaze_time
                if elapsed >= PANEL_HIDE_AFTER:
                    self._set_panel_visibility(False)
                elif elapsed < 0.5:
                    # Gaze just left — keep visible for a moment
                    self._set_panel_visibility(True)

        self.win.after(20, self._tick)

    # ── Blink handling ────────────────────────────────────────────────────

    # def _handle_blink(self, gx: float, gy: float):
    #     panel_active = (
    #         self._panel_win is not None
    #         and self._panel_win.winfo_exists()
    #         and self._panel_dwell is not None
    #     )

    #     if panel_active and self._gaze_on_panel(gx):
    #         btn = self._panel_dwell.on_blink()
    #     else:
    #         btn = self._main_dwell.on_blink()

    #     if btn is not None:
    #         print(f"[VLC] Blink registered on: {btn.cget('text')}")
    #     else:
    #         print("[VLC] Blink — no button ready.")
    
    def _handle_blink(self, gx: float, gy: float):
        strip_active = (
            self._panel_win is not None
            and self._panel_win.winfo_exists()
            and self._panel_dwell is not None
        )

        if strip_active and self._gaze_on_panel(gx):
            btn = self._panel_dwell.on_blink()
        else:
            btn = self._main_dwell.on_blink()

        if btn is not None:
            print(f"[VLC] Blink activating: {btn.cget('text')}")
            try:
                btn.invoke()
            except tk.TclError as e:
                print(f"[VLC] invoke() failed: {e}")
        else:
            print("[VLC] Blink — no button ready.")

    # ── Panel visibility (Milestone 3) ────────────────────────────────────

    def _set_panel_visibility(self, visible: bool):
        """Fade panel in/out based on gaze presence."""
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

    # ── Rendering ─────────────────────────────────────────────────────────

    def _render_main(self, snapshot):
        try:
            self._progress_var.set(snapshot.progress * 100)
            self._status_lbl.config(text=snapshot.status_text)
        except (tk.TclError, AttributeError):
            pass

        # Pin cursor to selected button
        if snapshot.move_cursor_to is not None:
            btn = snapshot.move_cursor_to
            try:
                if btn.winfo_exists():
                    cx = btn.winfo_rootx() + btn.winfo_width()  / 2
                    cy = btn.winfo_rooty() + btn.winfo_height() / 2
                    pyautogui.moveTo(int(cx), int(cy))
            except tk.TclError:
                pass

        all_btns = (
            self._movie_buttons if self._view == "movie_list"
            else [self._load_btn, self._close_btn]
        )
        for btn in all_btns:
            try:
                if not btn.winfo_exists():
                    continue
                style = "Snapped.TButton" if (
                    btn is snapshot.target
                    and snapshot.state == DwellState.SELECTED
                ) else "BigDashboard.TButton"
                btn.config(style=style)
            except tk.TclError:
                pass

    def _render_panel(self, snapshot):
        # Pin cursor to selected panel button
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
                style = "Snapped.TButton" if (
                    btn is snapshot.target
                    and snapshot.state == DwellState.SELECTED
                ) else "BigDashboard.TButton"
                btn.config(style=style)
            except tk.TclError:
                pass

    # ── VLC process watcher ───────────────────────────────────────────────

    def _poll_vlc(self):
        if not self.win.winfo_exists():
            return

        vlc_running  = any(
            "vlc" in (p.info.get("name") or "").lower()
            for p in psutil.process_iter(["name"])
        )
        panel_exists = (
            self._panel_win is not None
            and self._panel_win.winfo_exists()
        )

        if vlc_running and not panel_exists:
            self._spawn_panel()
        elif not vlc_running and panel_exists:
            self._destroy_panel()

        self.win.after(1500, self._poll_vlc)

    # ── VLC commands ──────────────────────────────────────────────────────

    def _launch_vlc(self):
        vlc = _find_vlc()
        if vlc:
            if self.vlc_process is not None:
                pass
            else:
                self.vlc_process = subprocess.Popen([vlc])
        else:
            print("[VLC] vlc.exe not found.")

    def _vlc_play_pause(self):
        try:
            import pygetwindow as gw
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
        
    def _close_panel(self):
        print(f"[Panel] 'Close' clicked on the panel. Closing VLC also.")
        if self.vlc_process is not None and self.vlc_process.poll() is None:
            # poll() is None means the process is still running
            self.vlc_process.terminate()  # Graceful close
            # self.vlc_process.kill()     # Force close if terminate doesn't work
            self.vlc_process = None
            print("[VLC] Closed VLC process successfully.")
        
        self._destroy_panel()