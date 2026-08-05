"""
ui/calibration_page.py
======================

Automatic 9-point dwell calibration followed by automatic offset measurement.

Flow:
  Phase 1 — Calibration: 9 dots, timed countdown, auto-capture
  Phase 2 — Fine-tuning: model adapts to user in background
  Phase 3 — Offset: single centre dot, user looks at it, offset computed
  Phase 4 — Done: signals dashboard to show completion dialog
"""

import math
import time
import tkinter as tk
import threading
from collections import deque


# ── Layout ────────────────────────────────────────────────────────────────────
MARGIN_X_FRAC = 0.10
MARGIN_Y_FRAC = 0.12

HOLD_SECONDS  = 2.0
FLASH_MS      = 400

DOT_RADIUS    = 14
RING_RADIUS   = 38
RING_WIDTH    = 7
RING_IDLE     = "#cbd5e1"
RING_FILL     = "#06b6d4"
FLASH_COLOR   = "#22c55e"
GHOST_COLOR   = "#e2e8f0"

# Offset measurement
OFFSET_COLLECT_SECONDS = 2.0   # how long to collect gaze for offset


def _make_grid(screen_w: int, screen_h: int) -> list[tuple[int, int]]:
    mx = int(screen_w * MARGIN_X_FRAC)
    my = int(screen_h * MARGIN_Y_FRAC)
    xs = [mx, screen_w // 2, screen_w - mx]
    ys = [my, screen_h // 2, screen_h - my]
    return [(x, y) for y in ys for x in xs]


class CalibrationWindow:

    # Phases
    PHASE_CALIBRATION = "calibration"
    PHASE_FINETUNING  = "finetuning"
    PHASE_OFFSET      = "offset"
    PHASE_DONE        = "done"

    def __init__(self, parent_root, engine, tuning_progress_queue):
        self.root   = parent_root
        self.engine = engine
        self.tuning_progress_queue = tuning_progress_queue

        self.win = tk.Toplevel(self.root)
        self.win.title("EyeTheia — Calibration")
        try:
            self.win.state("zoomed")
        except tk.TclError:
            self.win.attributes("-zoomed", True)

        self.w = self.win.winfo_screenwidth()
        self.h = self.win.winfo_screenheight()

        self.sheet = tk.Canvas(
            self.win, width=self.w, height=self.h,
            bg="white", highlightthickness=0,
        )
        self.sheet.pack(fill=tk.BOTH, expand=True)

        # Phase tracking
        self._phase = self.PHASE_CALIBRATION

        # Calibration state
        self.targets         = _make_grid(self.w, self.h)
        self.target_idx      = 0
        self._dot_shown_at   = time.monotonic()
        self._countdown_pct  = 0.0
        self.is_flashing     = False
        self.current_progress = 0
        self.latest_features = None
        self._feature_buffer: deque = deque(maxlen=6)

        # Offset measurement state
        self._offset_samples: list[tuple[int, int]] = []
        self._offset_start   = 0.0
        self._offset_pct     = 0.0   # 0.0 → 1.0 for the offset ring

        self.win.focus_force()
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)

        self._render_loop()
        self._countdown_tick()

    # ── Gaze input ────────────────────────────────────────────────────────────

    def on_new_gaze(self, gx: float, gy: float):
        if not self.win.winfo_exists():
            return

        if self._phase == self.PHASE_CALIBRATION:
            if self.latest_features is not None:
                self._feature_buffer.append(self.latest_features)

        elif self._phase == self.PHASE_OFFSET:
            # Collect gaze samples for offset calculation
            self._offset_samples.append((int(gx), int(gy)))

    # ── Calibration countdown ─────────────────────────────────────────────────

    def _countdown_tick(self):
        if not self.win.winfo_exists():
            return
        if self._phase != self.PHASE_CALIBRATION:
            return
        if self.is_flashing:
            self.win.after(50, self._countdown_tick)
            return

        elapsed = time.monotonic() - self._dot_shown_at
        self._countdown_pct = min(1.0, elapsed / HOLD_SECONDS)

        if self._countdown_pct >= 1.0:
            self._capture_sample()
        else:
            self.win.after(50, self._countdown_tick)

    # ── Calibration capture ───────────────────────────────────────────────────

    def _capture_sample(self):
        features = None
        if self._feature_buffer:
            features = self._feature_buffer[-1]
        elif self.latest_features is not None:
            features = self.latest_features

        if features is None:
            print("[Calibration] Waiting for first camera frame...")
            self._dot_shown_at = time.monotonic()
            self.win.after(50, self._countdown_tick)
            return

        tx, ty = self.targets[self.target_idx]
        norm_x  = (tx / self.w) * 2.0 - 1.0
        norm_y  = (ty / self.h) * 2.0 - 1.0

        self.engine.calibration_samples.append((features, (norm_x, norm_y)))
        print(f"[Calibration] Captured {self.target_idx + 1}/{len(self.targets)} — screen=({tx},{ty})")

        self.is_flashing    = True
        self._countdown_pct = 1.0
        self._feature_buffer.clear()
        self.win.after(FLASH_MS, self._advance)

    def _advance(self):
        self.is_flashing = False
        self.target_idx += 1

        if self.target_idx >= len(self.targets):
            self._start_finetuning()
        else:
            self._countdown_pct = 0.0
            self._dot_shown_at  = time.monotonic()
            self.win.after(50, self._countdown_tick)

    # ── Fine-tuning ───────────────────────────────────────────────────────────

    def _start_finetuning(self):
        self._phase = self.PHASE_FINETUNING

        def _hook(pct: int):
            self.tuning_progress_queue.put(pct)
            if pct >= 100:
                # Fine-tuning complete — start offset measurement
                self.win.after(600, self._start_offset_measurement)

        threading.Thread(
            target=self.engine.local_fine_tune,
            args=(_hook,),
            daemon=True,
        ).start()

    # ── Offset measurement ────────────────────────────────────────────────────

    def _start_offset_measurement(self):
        """
        Show a single dot in the screen centre.
        Collect gaze samples for OFFSET_COLLECT_SECONDS.
        Compute and apply the offset automatically.
        """
        if not self.win.winfo_exists():
            return

        self._phase          = self.PHASE_OFFSET
        self._offset_samples = []
        self._offset_start   = time.monotonic()
        self._offset_pct     = 0.0

        print("[Offset] Starting automatic offset measurement...")
        self._offset_tick()

    def _offset_tick(self):
        """Advance the offset collection ring. Fires every 50ms."""
        if not self.win.winfo_exists():
            return
        if self._phase != self.PHASE_OFFSET:
            return

        elapsed = time.monotonic() - self._offset_start
        self._offset_pct = min(1.0, elapsed / OFFSET_COLLECT_SECONDS)

        if self._offset_pct >= 1.0:
            self._apply_offset()
        else:
            self.win.after(50, self._offset_tick)

    def _apply_offset(self):
        """Compute the average gaze position and derive the correction offset."""
        if not self._offset_samples:
            print("[Offset] No samples collected — skipping offset correction.")
            self._finish()
            return

        target_x = self.w // 2
        target_y = self.h // 2

        avg_x = int(sum(s[0] for s in self._offset_samples) / len(self._offset_samples))
        avg_y = int(sum(s[1] for s in self._offset_samples) / len(self._offset_samples))

        dx = target_x - avg_x
        dy = target_y - avg_y

        self.engine.set_gaze_offset(dx, dy)

        print(
            f"[Offset] Target=({target_x},{target_y})  "
            f"Avg gaze=({avg_x},{avg_y})  "
            f"Correction: dx={dx}, dy={dy}  "
            f"(from {len(self._offset_samples)} samples)"
        )

        # Brief pause so the user sees the completion flash
        self.win.after(500, self._finish)

    def _finish(self):
        self._phase = self.PHASE_DONE
        # Signal the dashboard that calibration + offset are complete
        self.tuning_progress_queue.put(100)

    # ── Render loop ───────────────────────────────────────────────────────────

    def _render_loop(self):
        if not self.win.winfo_exists():
            return
        self._draw_frame()
        self.win.after(16, self._render_loop)

    def _draw_frame(self):
        self.sheet.delete("all")

        if self._phase == self.PHASE_CALIBRATION:
            self._draw_calibration()
        elif self._phase == self.PHASE_FINETUNING:
            self._draw_finetuning()
        elif self._phase == self.PHASE_OFFSET:
            self._draw_offset()
        elif self._phase == self.PHASE_DONE:
            self._draw_done()

    def _draw_calibration(self):
        self.sheet.create_text(
            self.w // 2, 44,
            text=f"Look at each dot and hold still  —  {self.target_idx} of {len(self.targets)} captured",
            font=("Arial", 15), fill="#475569",
        )

        for i, (tx, ty) in enumerate(self.targets):
            if i < self.target_idx:
                continue
            if i == self.target_idx:
                self._draw_active_dot(tx, ty)
            else:
                self.sheet.create_oval(
                    tx - 5, ty - 5, tx + 5, ty + 5,
                    fill=GHOST_COLOR, outline="",
                )

    def _draw_active_dot(self, tx: int, ty: int):
        if self.is_flashing:
            self.sheet.create_oval(
                tx - RING_RADIUS, ty - RING_RADIUS,
                tx + RING_RADIUS, ty + RING_RADIUS,
                fill=FLASH_COLOR, outline="",
            )
            return

        self.sheet.create_oval(
            tx - RING_RADIUS, ty - RING_RADIUS,
            tx + RING_RADIUS, ty + RING_RADIUS,
            outline=RING_IDLE, width=RING_WIDTH, fill="white",
        )

        if self._countdown_pct > 0:
            self.sheet.create_arc(
                tx - RING_RADIUS, ty - RING_RADIUS,
                tx + RING_RADIUS, ty + RING_RADIUS,
                start=90, extent=-(self._countdown_pct * 360.0),
                outline=RING_FILL, width=RING_WIDTH, style=tk.ARC,
            )

        self.sheet.create_oval(
            tx - DOT_RADIUS, ty - DOT_RADIUS,
            tx + DOT_RADIUS, ty + DOT_RADIUS,
            fill="#0f172a", outline="",
        )

        pct = int(self._countdown_pct * 100)
        if pct > 0:
            self.sheet.create_text(
                tx, ty + RING_RADIUS + 20,
                text=f"{pct}%", font=("Arial", 11), fill="#64748b",
            )

    def _draw_finetuning(self):
        cx, cy = self.w // 2, self.h // 2

        self.sheet.create_text(
            cx, cy - 70,
            text="Adapting model to your eyes...",
            font=("Arial", 17, "bold"), fill="#1e293b",
        )
        self.sheet.create_text(
            cx, cy - 38,
            text="Please keep still — this takes a few seconds",
            font=("Arial", 11, "italic"), fill="#64748b",
        )

        bar_w, bar_h = 420, 28
        bx1, by1 = cx - bar_w // 2, cy - bar_h // 2
        bx2, by2 = cx + bar_w // 2, cy + bar_h // 2

        self.sheet.create_rectangle(
            bx1, by1, bx2, by2,
            outline="#334155", width=2, fill="#f1f5f9",
        )
        prog = self.current_progress
        if prog > 0:
            fill_x = bx1 + int((prog / 100) * bar_w)
            self.sheet.create_rectangle(
                bx1 + 2, by1 + 2, fill_x - 2, by2 - 2,
                fill="#06b6d4", outline="",
            )
        self.sheet.create_text(
            cx, cy + 40,
            text=f"{prog}%", font=("Arial", 13, "bold"), fill="#0f172a",
        )

    def _draw_offset(self):
        """Draw the offset measurement dot in the screen centre."""
        cx = self.w // 2
        cy = self.h // 2

        self.sheet.create_text(
            cx, cy - 90,
            text="Almost done — look at the dot below",
            font=("Arial", 16, "bold"), fill="#1e293b",
        )
        self.sheet.create_text(
            cx, cy - 58,
            text="Hold your gaze steady on the dot",
            font=("Arial", 12, "italic"), fill="#64748b",
        )

        # Progress ring (same visual language as calibration dots)
        self.sheet.create_oval(
            cx - RING_RADIUS, cy - RING_RADIUS,
            cx + RING_RADIUS, cy + RING_RADIUS,
            outline=RING_IDLE, width=RING_WIDTH, fill="white",
        )

        if self._offset_pct > 0:
            self.sheet.create_arc(
                cx - RING_RADIUS, cy - RING_RADIUS,
                cx + RING_RADIUS, cy + RING_RADIUS,
                start=90, extent=-(self._offset_pct * 360.0),
                outline="#f59e0b",   # amber — distinct from calibration cyan
                width=RING_WIDTH, style=tk.ARC,
            )

        self.sheet.create_oval(
            cx - DOT_RADIUS, cy - DOT_RADIUS,
            cx + DOT_RADIUS, cy + DOT_RADIUS,
            fill="#0f172a", outline="",
        )

        pct = int(self._offset_pct * 100)
        if pct > 0:
            self.sheet.create_text(
                cx, cy + RING_RADIUS + 20,
                text=f"Measuring... {pct}%",
                font=("Arial", 11), fill="#64748b",
            )

    def _draw_done(self):
        cx, cy = self.w // 2, self.h // 2
        self.sheet.create_text(
            cx, cy,
            text="Calibration complete ✓",
            font=("Arial", 18, "bold"), fill="#1D9E75",
        )

    # ── Called by dashboard progress update ───────────────────────────────────

    def render_tick(self):
        pass   # render loop handles drawing independently

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def _on_close(self):
        self.win.destroy()