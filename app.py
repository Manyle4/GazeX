import os
import tkinter as tk
import threading
import pyautogui
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

from core.engine import ProjectGazeEngine
from ui.main_dashboard import EyeTheiaDesktopUI

# The pipeline function remains unchanged but lives neatly inside app.py background scope
def background_vision_pipeline_worker(ui_handle, engine, data_queue):
    import cv2
    import torch
    import numpy as np
    import mediapipe as mp
    
    base_options = python.BaseOptions(model_asset_path='face_landmarker.task')
    options = vision.FaceLandmarkerOptions(base_options=base_options, num_faces=1)
    landmarker = vision.FaceLandmarker.create_from_options(options)
    cap = cv2.VideoCapture(0)
    
    blink_counter = 0
    EAR_THRESHOLD = 0.22
    
    while ui_handle.is_tracking and cap.isOpened():
        success, image = cap.read()
        if not success: break
        
        image = cv2.flip(image, 1)
        rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_image)
        detection_result = landmarker.detect(mp_image)
        
        if detection_result.face_landmarks:
            landmarks = detection_result.face_landmarks[0]
            
            # Click Processing
            p_top, p_bot = landmarks[159], landmarks[145]
            p_l, p_r = landmarks[33], landmarks[133]
            v_dist = np.sqrt((p_top.x - p_bot.x)**2 + (p_top.y - p_bot.y)**2)
            h_dist = np.sqrt((p_l.x - p_r.x)**2 + (p_l.y - p_r.y)**2)
            left_ear = v_dist / max(1e-6, h_dist)
            
            if left_ear < EAR_THRESHOLD:
                blink_counter += 1
            else:
                if 3 <= blink_counter <= 12:
                    print("[Gaze Thread Core] Intentional Click Sensed!")
                    pyautogui.click()
                blink_counter = 0
            
            # Neural Inference Extraction Passes
            extracted = engine.extract_tensors(image, landmarks)
            if extracted is not None:
                ui_handle.latest_features = extracted
                with torch.no_grad():
                    pred = engine.model(*extracted).cpu().numpy().flatten()
                
                g_x, g_y = engine.scaler.map_to_screen_pixels(pred[0], pred[1], ui_handle.scr_w, ui_handle.scr_h)
                try: data_queue.put_nowait((g_x, g_y))
                except Exception: pass
                
    cap.release()
    landmarker.close()

def main():
    WEIGHTS = "models/mpiiface_production.pth"
    gaze_engine = ProjectGazeEngine(WEIGHTS)
    
    root = tk.Tk()
    # Spin up our cleanly modularized component view dashboard frame manager
    app = EyeTheiaDesktopUI(root, gaze_engine, background_vision_pipeline_worker)
    root.mainloop()

if __name__ == "__main__":
    main()