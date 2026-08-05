import tkinter as tk
from tkinter import ttk
import threading
import time


class SplashScreen:
    """
    Full-screen splash shown while the engine and camera initialise.

    The caller runs initialisation steps on a background thread and
    reports progress via update_status() and set_progress().
    When done, call finish() to close the splash and show the dashboard.

    Usage in app.py:
        splash = SplashScreen(root)
        threading.Thread(target=_init_worker, args=(splash,), daemon=True).start()
        root.mainloop()
    """

    # Design tokens matching the rest of the app
    BG          = "#0f172a"
    ACCENT      = "#06b6d4"
    TEXT_LIGHT  = "#f8fafc"
    TEXT_MUTED  = "#94a3b8"

    def __init__(self, root: tk.Tk):
        self.root = root

        # Make root invisible — splash is drawn on top
        self.root.withdraw()

        self.win = tk.Toplevel(self.root)
        self.win.overrideredirect(True)   # no title bar or borders
        self.win.configure(bg=self.BG)
        self.win.attributes("-topmost", True)

        # Centre splash on screen
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        w, h = 520, 320
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.win.geometry(f"{w}x{h}+{x}+{y}")

        self._build_ui(w, h)
        self._animate_dots()

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self, w: int, h: int):
        canvas = tk.Canvas(
            self.win, width=w, height=h,
            bg=self.BG, highlightthickness=0,
        )
        canvas.pack(fill=tk.BOTH, expand=True)

        # App name
        canvas.create_text(
            w // 2, 90,
            text="EyeTheia",
            font=("Arial", 36, "bold"),
            fill=self.TEXT_LIGHT,
        )

        # Tagline
        canvas.create_text(
            w // 2, 135,
            text="Gaze-controlled accessibility suite",
            font=("Arial", 13),
            fill=self.ACCENT,
        )

        # Divider line
        canvas.create_line(
            60, 162, w - 60, 162,
            fill="#1e3a5f", width=1,
        )

        # Status message label
        self._status_var = tk.StringVar(value="Starting up...")
        self._status_lbl = tk.Label(
            self.win,
            textvariable=self._status_var,
            font=("Arial", 11),
            fg=self.TEXT_MUTED,
            bg=self.BG,
        )
        self._status_lbl.place(x=w // 2, y=185, anchor="center")

        # Animated dots label (appended to status)
        self._dots_var = tk.StringVar(value="")
        self._dots_lbl = tk.Label(
            self.win,
            textvariable=self._dots_var,
            font=("Arial", 11),
            fg=self.ACCENT,
            bg=self.BG,
        )
        self._dots_lbl.place(x=w // 2 + 90, y=185, anchor="w")

        # Progress bar
        style = ttk.Style()
        style.configure(
            "Splash.Horizontal.TProgressbar",
            troughcolor="#1e293b",
            background=self.ACCENT,
            bordercolor=self.BG,
            lightcolor=self.ACCENT,
            darkcolor=self.ACCENT,
        )
        self._progress_var = tk.DoubleVar(value=0.0)
        self._progress_bar = ttk.Progressbar(
            self.win,
            variable=self._progress_var,
            maximum=100,
            length=400,
            mode="determinate",
            style="Splash.Horizontal.TProgressbar",
        )
        self._progress_bar.place(x=w // 2, y=230, anchor="center")

        # Step label
        self._step_var = tk.StringVar(value="")
        tk.Label(
            self.win,
            textvariable=self._step_var,
            font=("Arial", 10),
            fg=self.TEXT_MUTED,
            bg=self.BG,
        ).place(x=w // 2, y=260, anchor="center")

        # Version / credit line
        tk.Label(
            self.win,
            text="Final Year Project  •  CPU-only  •  Offline",
            font=("Arial", 9),
            fg="#334155",
            bg=self.BG,
        ).place(x=w // 2, y=300, anchor="center")

    # ── Public API (called from background thread) ────────────────────────

    def update_status(self, message: str):
        """Update the main status message."""
        self.root.after(0, self._status_var.set, message)

    def set_progress(self, percent: float, step_label: str = ""):
        """Set progress bar value and optional step description."""
        self.root.after(0, self._progress_var.set, percent)
        if step_label:
            self.root.after(0, self._step_var.set, step_label)

    def finish(self, on_done_callback):
        """
        Close the splash and invoke on_done_callback on the main thread.
        on_done_callback should build and show the main dashboard.
        """
        self.root.after(0, self._do_finish, on_done_callback)

    def _do_finish(self, on_done_callback):
        self._progress_var.set(100)
        self._status_var.set("Ready")
        self._step_var.set("Launching dashboard...")
        # Brief pause so user sees 100% before the dashboard appears
        self.win.after(400, lambda: self._show_dashboard(on_done_callback))

    def _show_dashboard(self, on_done_callback):
        self.win.destroy()
        self.root.deiconify()   # show the main root window
        on_done_callback()

    # ── Animated dots ─────────────────────────────────────────────────────

    def _animate_dots(self):
        """Cycle through '', '.', '..', '...' to show activity."""
        if not self.win.winfo_exists():
            return
        current = self._dots_var.get()
        next_dots = {
            "":    ".",
            ".":   "..",
            "..":  "...",
            "...": "",
        }.get(current, "")
        self._dots_var.set(next_dots)
        self.win.after(400, self._animate_dots)