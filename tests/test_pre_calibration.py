import time
import math
import tkinter as tk
import cv2
import torch
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

from core.engine import ProjectGazeEngine
from utils.filters import OneEuroFilterPair

WEIGHTS_FILE = "models/mpiiface_production.pth"
LANDMARKER_FILE = "models/face_landmarker.task"
POINT_HOLD_SECONDS = 3.0

class PreCalibrationAccuracyTest:
    def __init__(self, root):
        self.root = root
        self.root.title("Pre-Calibration Accuracy Test")
        try:
            self.root.state("zoomed")
        except tk.TclError:
            self.root.attributes("-zoomed", True)

        self.w = self.root.winfo_screenwidth()
        self.h = self.root.winfo_screenheight()

        self.canvas = tk.Canvas(self.root, width=self.w, height=self.h, bg="#0f172a", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # 5 Target Points: Top-Left, Top-Right, Bottom-Left, Bottom-Right, Center
        pad_x = int(self.w * 0.15)
        pad_y = int(self.h * 0.15)
        self.targets = [
            (self.w // 2, self.h // 2),        # Center
            (pad_x, pad_y),                    # Top-Left
            (self.w - pad_x, pad_y),            # Top-Right
            (pad_x, self.h - pad_y),            # Bottom-Left
            (self.w - pad_x, self.h - pad_y),   # Bottom-Right
        ]
        self.target_names = ["Center", "Top-Left", "Top-Right", "Bottom-Left", "Bottom-Right"]
        self.current_idx = 0
        self.results = []
        self.point_samples = []

        # Initialize tracking engine without fine-tuning
        self.engine = ProjectGazeEngine(WEIGHTS_FILE)
        self.filter = OneEuroFilterPair(freq=30, mincutoff=0.5, beta=0.003, dcutoff=0.5)

        # MediaPipe landmarker setup
        base_opts = python.BaseOptions(model_asset_path=LANDMARKER_FILE)
        opts = vision.FaceLandmarkerOptions(base_options=base_opts, num_faces=1)
        self.landmarker = vision.FaceLandmarker.create_from_options(opts)

        self.cap = cv2.VideoCapture(0)
        self.point_start_time = time.monotonic()

        self._tick()

    def _tick(self):
        if not self.root.winfo_exists():
            return

        success, frame = self.cap.read()
        if success:
            frame = cv2.flip(frame, 1)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result = self.landmarker.detect(mp_img)

            if result.face_landmarks:
                landmarks = result.face_landmarks[0]
                tensors = self.engine.extract_tensors(frame, landmarks)
                if tensors is not None:
                    with torch.no_grad():
                        pred = self.engine.model(*tensors).cpu().numpy().flatten()
                    
                    # Map using default scaler bounds before calibration
                    raw_x, raw_y = self.engine.scaler.map_to_screen_pixels(
                        pred[0], pred[1], self.w, self.h
                    )
                    smooth_x, smooth_y = self.filter.filter(float(raw_x), float(raw_y))

                    # Discard the first 1.0s of each point to allow eye movement to settle
                    elapsed = time.monotonic() - self.point_start_time
                    if elapsed > 1.0:
                        self.point_samples.append((smooth_x, smooth_y))

        # Check if hold duration completed
        elapsed = time.monotonic() - self.point_start_time
        if elapsed >= POINT_HOLD_SECONDS:
            self._record_and_advance()
        else:
            self._render()
            self.root.after(16, self._tick)

    def _record_and_advance(self):
        tx, ty = self.targets[self.current_idx]
        name = self.target_names[self.current_idx]

        if self.point_samples:
            avg_x = sum(p[0] for p in self.point_samples) / len(self.point_samples)
            avg_y = sum(p[1] for p in self.point_samples) / len(self.point_samples)
            error = math.hypot(tx - avg_x, ty - avg_y)
            self.results.append((name, (tx, ty), (int(avg_x), int(avg_y)), error))
        else:
            self.results.append((name, (tx, ty), (0, 0), float("nan")))

        self.point_samples.clear()
        self.current_idx += 1

        if self.current_idx < len(self.targets):
            self.point_start_time = time.monotonic()
            self._render()
            self.root.after(16, self._tick)
        else:
            self._print_summary()
            self.cap.release()
            self.landmarker.close()
            self.root.destroy()

    def _render(self):
        self.canvas.delete("all")
        tx, ty = self.targets[self.current_idx]
        name = self.target_names[self.current_idx]
        time_left = max(0.0, POINT_HOLD_SECONDS - (time.monotonic() - self.point_start_time))

        self.canvas.create_text(
            self.w // 2, 60,
            text=f"Stare at the dot: {name} ({time_left:.1f}s)",
            font=("Arial", 18, "bold"), fill="#f8fafc"
        )
        self.canvas.create_oval(tx - 18, ty - 18, tx + 18, ty + 18, fill="#06b6d4", outline="white", width=3)
        self.canvas.create_oval(tx - 5, ty - 5, tx + 5, ty + 5, fill="white", outline="")

    def _print_summary(self):
        print("\n" + "=" * 65)
        print("PRE-CALIBRATION ACCURACY RESULTS")
        print("=" * 65)
        print(f"{'Target':<15} {'Screen Target':<18} {'Predicted (Avg)':<18} {'Error (px)':<10}")
        print("-" * 65)
        errors = []
        for name, (tx, ty), (px, py), err in self.results:
            print(f"{name:<15} ({tx}, {ty}){'':<6} ({px}, {py}){'':<6} {err:.1f} px")
            if not math.isnan(err):
                errors.append(err)
        print("-" * 65)
        if errors:
            mean_error = sum(errors) / len(errors)
            print(f"Mean Pre-Calibration Error: {mean_error:.1f} px")
        print("=" * 65 + "\n")

if __name__ == "__main__":
    root = tk.Tk()
    app = PreCalibrationAccuracyTest(root)
    root.mainloop()