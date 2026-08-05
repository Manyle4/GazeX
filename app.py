import os
import tkinter as tk
import threading
import pyautogui
import sys

from mediapipe.tasks import python
from mediapipe.tasks.python import vision

from core.engine import ProjectGazeEngine
from ui.splash import SplashScreen
from ui.main_dashboard import EyeTheiaDesktopUI
from utils.filters import OneEuroFilterPair

if getattr(sys, "frozen", False):
    dir_path = sys._MEIPASS
else:
    dir_path = os.path.dirname(os.path.abspath(__file__))


# ── Vision pipeline ───────────────────────────────────────────────────────────

def background_vision_pipeline_worker(ui_handle, engine, data_queue):
    import cv2
    import torch
    import numpy as np
    import mediapipe as mp

    model_path   = os.path.join(dir_path, "models", "face_landmarker.task")
    base_options = python.BaseOptions(model_asset_path=model_path)
    options      = vision.FaceLandmarkerOptions(
        base_options=base_options,
        num_faces=1,
    )
    landmarker = vision.FaceLandmarker.create_from_options(options)
    cap        = cv2.VideoCapture(0)

    gaze_filter = OneEuroFilterPair(
        freq=30,
        mincutoff=0.5,   # was 1.0 — lower = much smoother when still
        beta=0.003,      # was 0.05 — lower = less responsive to speed changes
        dcutoff=0.5,     # was 1.0 — smoother derivative estimate
    )

    blink_counter  = 0
    EAR_THRESHOLD  = 0.22
    was_calibrated = False

    while ui_handle.is_tracking and cap.isOpened():
        success, image = cap.read()
        if not success:
            break

        image     = cv2.flip(image, 1)
        rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        mp_image  = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_image)
        result    = landmarker.detect(mp_image)

        if not result.face_landmarks:
            continue

        landmarks = result.face_landmarks[0]

        # ── Blink detection ───────────────────────────────────────────────
        p_top = landmarks[159]
        p_bot = landmarks[145]
        p_l   = landmarks[33]
        p_r   = landmarks[133]

        v_dist   = ((p_top.x - p_bot.x)**2 + (p_top.y - p_bot.y)**2) ** 0.5
        h_dist   = ((p_l.x   - p_r.x  )**2 + (p_l.y   - p_r.y  )**2) ** 0.5
        left_ear = v_dist / max(1e-6, h_dist)

        if left_ear < EAR_THRESHOLD:
            blink_counter += 1
        else:
            if 3 <= blink_counter <= 12:
                print("[Pipeline] Intentional blink detected.")
                ui_handle.blink_triggered = True
                pyautogui.click()
            blink_counter = 0

        # ── Inference ─────────────────────────────────────────────────────
        extracted = engine.extract_tensors(image, landmarks)
        if extracted is None:
            print("[Pipeline] extract_tensors returned None")
            continue

        ui_handle.latest_features = extracted
        print(f"[Pipeline] features set on ui_handle: {type(extracted)}")

        with torch.no_grad():
            pred = engine.model(*extracted).cpu().numpy().flatten()

        raw_x, raw_y = engine.scaler.map_to_screen_pixels(
            pred[0], pred[1],
            ui_handle.scr_w, ui_handle.scr_h,
        )

        calib_samples = len(engine.calibration_samples)
        if calib_samples >= 9 and not was_calibrated:
            gaze_filter.reset()
            was_calibrated = True
            print("[Pipeline] Filter reset after calibration.")

        smooth_x, smooth_y = gaze_filter.filter(float(raw_x), float(raw_y))

        try:
            data_queue.put_nowait((int(smooth_x), int(smooth_y)))
        except Exception:
            pass

    cap.release()
    landmarker.close()


# ── Splash initialisation worker ──────────────────────────────────────────────

def _startup_worker(splash: SplashScreen, weights_file: str, result: dict):
    """
    Runs on a background thread.
    Loads every heavy resource and reports progress to the splash screen.
    Stores the ready engine in result['engine'] for the main thread to use.
    """
    import cv2
    import mediapipe as mp

    try:
        # Step 1 — Load gaze model weights
        splash.update_status("Loading EyeTheia gaze model")
        splash.set_progress(10, "Initialising neural network...")
        engine = ProjectGazeEngine(weights_file)
        splash.set_progress(35, "Gaze model loaded.")

        # Step 2 — Load MediaPipe face landmarker
        splash.update_status("Loading facial landmark detector")
        splash.set_progress(40, "Initialising MediaPipe...")
        model_path   = os.path.join(dir_path, "models", "face_landmarker.task")
        base_options = python.BaseOptions(model_asset_path=model_path)
        options      = vision.FaceLandmarkerOptions(
            base_options=base_options,
            num_faces=1,
        )
        # Create and immediately close — this pre-loads the .task file into memory
        _lm = vision.FaceLandmarker.create_from_options(options)
        _lm.close()
        splash.set_progress(60, "Face detector ready.")

        # Step 3 — Initialise webcam
        splash.update_status("Initialising webcam")
        splash.set_progress(65, "Opening camera...")
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            splash.update_status("Warning: webcam not found")
            splash.set_progress(75, "Camera unavailable — continuing.")
        else:
            # Warm up — read and discard several frames so the first real
            # frames have correct exposure and white balance
            splash.set_progress(70, "Warming up camera...")
            for _ in range(8):
                cap.read()
            cap.release()
            splash.set_progress(80, "Camera ready.")

        # Step 4 — Run a dummy inference pass to warm up PyTorch
        # The first inference call is always slow due to JIT compilation.
        # Doing it here means the first real frame is fast.
        splash.update_status("Preparing gaze estimator")
        splash.set_progress(82, "Warming up inference engine...")
        import torch
        import numpy as np
        dummy_face = torch.zeros(1, 3, 224, 224)
        dummy_eye  = torch.zeros(1, 3, 224, 224)
        dummy_grid = torch.zeros(1, 625)
        with torch.no_grad():
            _ = engine.model(dummy_face, dummy_eye, dummy_eye, dummy_grid)
        splash.set_progress(95, "Inference engine ready.")

        # Step 5 — Done
        splash.update_status("All systems ready")
        splash.set_progress(100, "Starting dashboard...")

        result["engine"] = engine

    except Exception as e:
        splash.update_status(f"Error during startup: {e}")
        print(f"[Startup] ERROR: {e}")
        result["engine"] = None

    # Signal main thread to show dashboard
    splash.finish(result["on_done"])


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    weights_file = os.path.join(dir_path, "models", "mpiiface_production.pth")

    root = tk.Tk()

    # Force Tkinter to report full tracebacks from callbacks
    def _tk_err(exc, val, tb):
        import traceback
        traceback.print_exception(exc, val, tb)
    root.report_callback_exception = _tk_err

    splash = SplashScreen(root)

    # result dict is shared between the background thread and the callback
    result = {}

    def _on_done():
        """Called on the main thread once startup completes."""
        engine = result.get("engine")
        if engine is None:
            print("[Startup] Engine failed to load — exiting.")
            root.destroy()
            return
        app = EyeTheiaDesktopUI(root, engine, background_vision_pipeline_worker)

    result["on_done"] = _on_done

    # Start initialisation on background thread
    threading.Thread(
        target=_startup_worker,
        args=(splash, weights_file, result),
        daemon=True,
    ).start()

    root.mainloop()


if __name__ == "__main__":
    main()