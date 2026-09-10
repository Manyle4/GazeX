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
CALIB_HOLD_SECONDS = 2.0
TEST_HOLD_SECONDS = 3.0

class PostCalibrationAccuracyTest:
    def __init__(self, root):
        self.root = root
        self.root.title("Post-Calibration Accuracy Test")
        try:
            self.root.state("zoomed")
        except tk.TclError:
            self.root.attributes("-zoomed", True)

        self.w = self.root.winfo_screenwidth()
        self.h = self.root.winfo_screenheight()

        self.canvas = tk.Canvas(self.root, width=self.w, height=self.h, bg="#0f172a", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # 13 Calibration target layout matching your CalibrationWindow
        mx, my = int(self.w * 0.10), int(self.h * 0.12)
        cx, cy = self.w // 2, self.h // 2
        outer = [(x, y) for y in [my, cy, self.h - my] for x in [mx, cx, self.w - mx]]
        inner = [
            ((mx + cx) // 2, (my + cy) // 2),
            ((cx + self.w - mx) // 2, (my + cy) // 2),
            ((mx + cx) // 2, (cy + self.h - my) // 2),
            ((cx + self.w - mx) // 2, (cy + self.h - my) // 2),
        ]
        self.calib_targets = outer + inner

        # 5 Test Targets (Same as pre-calibration test)
        pad_x, pad_y = int(self.w * 0.15), int(self.h * 0.15)
        self.test_targets = [
            (cx, cy),
            (pad_x, pad_y),
            (self.w - pad_x, pad_y),
            (pad_x, self.h - pad_y),
            (self.w - pad_x, self.h - pad_y),
        ]
        self.test_target_names = ["Center", "Top-Left", "Top-Right", "Bottom-Left", "Bottom-Right"]

        # Pipelines
        self.engine = ProjectGazeEngine(WEIGHTS_FILE)
        self.filter = OneEuroFilterPair(freq=30, mincutoff=0.5, beta=0.003, dcutoff=0.5)

        base_opts = python.BaseOptions(model_asset_path=LANDMARKER_FILE)
        opts = vision.FaceLandmarkerOptions(base_options=base_opts, num_faces=1)
        self.landmarker = vision.FaceLandmarker.create_from_options(opts)
        self.cap = cv2.VideoCapture(0)

        # State tracking: "CALIBRATION" -> "TRAINING" -> "TESTING" -> "DONE"
        self.state = "CALIBRATION"
        self.calib_idx = 0
        self.test_idx = 0
        self.latest_features = None
        self.point_samples = []
        self.results = []
        self.step_start_time = time.monotonic()

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
                    self.latest_features = tensors
                    
                    # Run live prediction during testing phase
                    if self.state == "TESTING":
                        with torch.no_grad():
                            pred = self.engine.model(*tensors).cpu().numpy().flatten()
                        raw_x, raw_y = self.engine.scaler.map_to_screen_pixels(
                            pred[0], pred[1], self.w, self.h
                        )
                        smooth_x, smooth_y = self.filter.filter(float(raw_x), float(raw_y))

                        # Allow 1 second for eye movement to settle
                        if (time.monotonic() - self.step_start_time) > 1.0:
                            self.point_samples.append((smooth_x, smooth_y))

        # Handle phase state changes
        now = time.monotonic()
        if self.state == "CALIBRATION":
            if (now - self.step_start_time) >= CALIB_HOLD_SECONDS:
                self._capture_calib_point()
        elif self.state == "TESTING":
            if (now - self.step_start_time) >= TEST_HOLD_SECONDS:
                self._record_test_point()

        self._render()
        if self.state != "DONE":
            self.root.after(16, self._tick)

    def _capture_calib_point(self):
        tx, ty = self.calib_targets[self.calib_idx]
        norm_x = (tx / self.w) * 2.0 - 1.0
        norm_y = (ty / self.h) * 2.0 - 1.0

        if self.latest_features is not None:
            self.engine.calibration_samples.append((self.latest_features, (norm_x, norm_y)))

        self.calib_idx += 1
        self.step_start_time = time.monotonic()

        if self.calib_idx >= len(self.calib_targets):
            self.state = "TRAINING"
            self._render()
            self.root.update()
            # Run local fine-tuning
            print("\n[Test] Fine-tuning model on captured targets...")
            self.engine.local_fine_tune()
            self.filter.reset()
            self.state = "TESTING"
            self.step_start_time = time.monotonic()

    def _record_test_point(self):
        tx, ty = self.test_targets[self.test_idx]
        name = self.test_target_names[self.test_idx]

        if self.point_samples:
            avg_x = sum(p[0] for p in self.point_samples) / len(self.point_samples)
            avg_y = sum(p[1] for p in self.point_samples) / len(self.point_samples)
            error = math.hypot(tx - avg_x, ty - avg_y)
            self.results.append((name, (tx, ty), (int(avg_x), int(avg_y)), error))
        else:
            self.results.append((name, (tx, ty), (0, 0), float("nan")))

        self.point_samples.clear()
        self.test_idx += 1
        self.step_start_time = time.monotonic()

        if self.test_idx >= len(self.test_targets):
            self.state = "DONE"
            self._print_summary()
            self.cap.release()
            self.landmarker.close()
            self.root.destroy()

    def _render(self):
        self.canvas.delete("all")
        now = time.monotonic()

        if self.state == "CALIBRATION":
            tx, ty = self.calib_targets[self.calib_idx]
            rem = max(0.0, CALIB_HOLD_SECONDS - (now - self.step_start_time))
            self.canvas.create_text(
                self.w // 2, 50,
                text=f"Phase 1: Calibrating ({self.calib_idx + 1}/13) — Hold still ({rem:.1f}s)",
                font=("Arial", 16, "bold"), fill="#f8fafc"
            )
            self.canvas.create_oval(tx - 16, ty - 16, tx + 16, ty + 16, fill="#06b6d4", outline="white", width=2)

        elif self.state == "TRAINING":
            self.canvas.create_text(
                self.w // 2, self.h // 2,
                text="Phase 2: Fine-Tuning Neural Network...\nPlease wait a few seconds",
                font=("Arial", 20, "bold"), fill="#38bdf8"
            )

        elif self.state == "TESTING":
            tx, ty = self.test_targets[self.test_idx]
            name = self.test_target_names[self.test_idx]
            rem = max(0.0, TEST_HOLD_SECONDS - (now - self.step_start_time))
            self.canvas.create_text(
                self.w // 2, 50,
                text=f"Phase 3: Testing Post-Calibration Accuracy: {name} ({rem:.1f}s)",
                font=("Arial", 16, "bold"), fill="#4ade80"
            )
            self.canvas.create_oval(tx - 18, ty - 18, tx + 18, ty + 18, fill="#22c55e", outline="white", width=3)
            self.canvas.create_oval(tx - 5, ty - 5, tx + 5, ty + 5, fill="white", outline="")

    def _print_summary(self):
        print("\n" + "=" * 65)
        print("POST-CALIBRATION ACCURACY RESULTS")
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
            print(f"Mean Post-Calibration Error: {mean_error:.1f} px")
        print("=" * 65 + "\n")

if __name__ == "__main__":
    root = tk.Tk()
    app = PostCalibrationAccuracyTest(root)
    root.mainloop()