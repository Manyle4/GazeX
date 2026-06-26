import os
import cv2
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from core.model import GazeModel
from core.dataset import LocalCalibrationDataset
from utils.landmarks import make_bounding_box, compute_face_grid
from utils.filters import GazeCoordinateScaler

class ProjectGazeEngine:
    def __init__(self, weights_filename: str):
        self.device = torch.device("cpu")
        print("[Engine] Hardware Target Initialized: Standalone CPU processing pipeline.")
        
        self.model = GazeModel()
        if os.path.exists(weights_filename):
            print(f"[Engine] Loading weight matrices: {weights_filename}")
            state_dict = torch.load(weights_filename, map_location=self.device)
            self.model.load_state_dict(state_dict, strict=True)
        else:
            print("[Warning] Weights file not found! Running with randomized structure layers.")
            
        self.model.to(self.device)
        self.model.eval()
        self.calibration_samples = []
        self.scaler = GazeCoordinateScaler()

    def extract_tensors(self, bgr_frame, face_landmarks):
        h, w, _ = bgr_frame.shape
        
        left_eye_idx = [33, 133, 159, 145, 153, 154, 155, 163]
        right_eye_idx = [362, 263, 386, 374, 381, 382, 385, 390]
        face_idx = list(range(0, 468))
        
        fx1, fy1, fx2, fy2 = make_bounding_box(face_landmarks, face_idx, w, h, padding=20)
        lx1, ly1, lx2, ly2 = make_bounding_box(face_landmarks, left_eye_idx, w, h, padding=12)
        rx1, ry1, rx2, ry2 = make_bounding_box(face_landmarks, right_eye_idx, w, h, padding=12)
        
        if (fx2-fx1 <= 0) or (lx2-lx1 <= 0) or (rx2-rx1 <= 0):
            return None

        face_crop = cv2.resize(bgr_frame[fy1:fy2, fx1:fx2], (224, 224))
        left_crop = cv2.resize(bgr_frame[ly1:ly2, lx1:lx2], (224, 224))
        right_crop = cv2.resize(bgr_frame[ry1:ry2, rx1:rx2], (224, 224))
        
        face_t = torch.tensor((face_crop / 255.0 - 0.5) * 2.0, dtype=torch.float32).permute(2, 0, 1).unsqueeze(0).to(self.device)
        left_t = torch.tensor((left_crop / 255.0 - 0.5) * 2.0, dtype=torch.float32).permute(2, 0, 1).unsqueeze(0).to(self.device)
        right_t = torch.tensor((right_crop / 255.0 - 0.5) * 2.0, dtype=torch.float32).permute(2, 0, 1).unsqueeze(0).to(self.device)
        
        grid_v = compute_face_grid((fx1, fy1, fx2, fy2), bgr_frame.shape)
        grid_t = torch.tensor(grid_v, dtype=torch.float32).view(1, -1).to(self.device)
        
        return face_t, left_t, right_t, grid_t

    # def local_fine_tune(self):
    #     if len(self.calibration_samples) < 5:
    #         print("[Calibration] Insufficient points collected to initiate user adaptation tuning.")
    #         return
            
    #     print(f"\n[Calibration] Tuning network layers on {len(self.calibration_samples)} local samples...")
    #     self.model.train()
    #     dataset = LocalCalibrationDataset(self.calibration_samples)
    #     loader = DataLoader(dataset, batch_size=4, shuffle=True)
    #     optimizer = torch.optim.Adam(self.model.parameters(), lr=1e-4)
    #     criterion = nn.MSELoss()
        
    #     for epoch in range(10):
    #         loss_accum = 0.0
    #         for faces, left_eyes, right_eyes, grids, targets in loader:
    #             optimizer.zero_grad()
    #             outputs = self.model(faces, left_eyes, right_eyes, grids)
    #             loss = criterion(outputs, targets)
    #             loss.backward()
    #             optimizer.step()
    #             loss_accum += loss.item()
    #         print(f"Tuning Epoch {epoch+1}/10 | Loss: {loss_accum/len(loader):.4f}")
            
    #     self.model.eval()
    #     print("[Calibration] Fine-tuning complete. Model set to inference mode.\n")

    def local_fine_tune(self, progress_callback=None):
        if len(self.calibration_samples) < 5:
            print("[Calibration] Insufficient points collected to initiate user adaptation tuning.")
            return
            
        print(f"\n[Calibration] Tuning network layers on {len(self.calibration_samples)} local samples...")
        self.model.train()
        dataset = LocalCalibrationDataset(self.calibration_samples)
        loader = DataLoader(dataset, batch_size=4, shuffle=True)
        optimizer = torch.optim.Adam(self.model.parameters(), lr=1e-4)
        criterion = nn.MSELoss()
        
        total_epochs = 10
        for epoch in range(total_epochs):
            loss_accum = 0.0
            for faces, left_eyes, right_eyes, grids, targets in loader:
                optimizer.zero_grad()
                outputs = self.model(faces, left_eyes, right_eyes, grids)
                loss = criterion(outputs, targets)
                loss.backward()
                optimizer.step()
                loss_accum += loss.item()
            print(f"Tuning Epoch {epoch+1}/{total_epochs} | Loss: {loss_accum/len(loader):.4f}")
            
            # Broadcast progress back to the UI thread
            if progress_callback is not None:
                percent_complete = int(((epoch + 1) / total_epochs) * 100)
                progress_callback(percent_complete)
                
        self.model.eval()
        self.scaler.find_bounds(self.calibration_samples, self.model)
        print("[Calibration] Fine-tuning complete. Model set to inference mode.\n")
