import os
import cv2
import torch
import torch.nn as nn
import scipy.io
import numpy as np
import sys
from torch.utils.data import DataLoader

from core.model import GazeModel
from core.dataset import LocalCalibrationDataset
from utils.landmarks import make_bounding_box, compute_face_grid
from utils.filters import GazeCoordinateScaler


# ── Face oval landmark indices ────────────────────────────────────────────────
# These 36 indices define the face boundary used during MPIIFaceGaze training.
# Using all 468 landmarks produces a bounding box that includes ears, hair, and
# background — regions the model was never trained on.
FACE_OVAL_IDX = [
    10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288,
    397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136,
    172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109,
]

# ── Eye landmark indices ──────────────────────────────────────────────────────
# These match the EyeTheia extraction pipeline exactly.
LEFT_EYE_IDX  = [33, 133, 159, 145, 153, 154, 155, 163]
RIGHT_EYE_IDX = [362, 263, 386, 374, 381, 382, 385, 390]


class ProjectGazeEngine:
    """
    Core gaze estimation engine.

    Responsibilities:
      - Load GazeModel weights and mean images
      - Extract face/eye/grid tensors from webcam frames
      - Run inference
      - Fine-tune on calibration samples
      - Map predictions to screen coordinates via GazeCoordinateScaler
    """

    # Paths to mean image files relative to the models/ directory
    MEAN_FILES = {
        "face":  "mean_face_224_MPIIFace.mat",
        "left":  "mean_left_224_MPIIFace.mat",
        "right": "mean_right_224_MPIIFace.mat",
    }

    def __init__(self, weights_filename: str):
        self.device = torch.device("cpu")
        self.weights_filename = weights_filename
        if getattr(sys, "frozen", False):
            self._models_dir = os.path.join(sys._MEIPASS, "models")
        else:
            self._models_dir = os.path.dirname(os.path.abspath(weights_filename))

        print("[Engine] CPU-only inference pipeline initialised.")

        # Load model
        self.model = GazeModel()
        if os.path.exists(weights_filename):
            print(f"[Engine] Loading weights: {weights_filename}")
            state_dict = torch.load(
                weights_filename,
                map_location=self.device,
                weights_only=True,
            )
            # strict=False: tolerates minor key mismatches without crashing
            self.model.load_state_dict(state_dict, strict=False)
        else:
            print("[Engine] WARNING: Weights file not found. Using random weights.")

        self.model.to(self.device)
        self.model.eval()

        # Load mean images for MPIIFaceGaze normalisation
        self._face_mean  = self._load_mean("face",  "mean_face")
        self._left_mean  = self._load_mean("left",  "mean_eye_left")
        self._right_mean = self._load_mean("right", "mean_eye_right")

        self.calibration_samples = []
        self.scaler = GazeCoordinateScaler()

    # ── Mean image loading ────────────────────────────────────────────────────

    def _load_mean(self, key: str, mat_key: str) -> np.ndarray:
        """
        Load a mean image from a .mat file.

        Returns the raw array as-is from the .mat file (shape (3, 224, 224),
        values in [0, 255]).  _to_tensor handles normalisation and transposition.
        """
        path = os.path.join(self._models_dir, self.MEAN_FILES[key])

        if not os.path.exists(path):
            print(f"[Engine] WARNING: Mean file not found: {path}")
            return np.zeros((3, 224, 224), dtype=np.float32)

        mat  = scipy.io.loadmat(path)
        mean = mat[mat_key].astype(np.float32)
        print(f"[Engine] Loaded mean image: {os.path.basename(path)}  shape={mean.shape}")
        return mean
    # ── Feature extraction ────────────────────────────────────────────────────

    def extract_tensors(self, bgr_frame: np.ndarray, face_landmarks):
        """
        Extract the four tensors GazeModel expects from a single webcam frame.

        Returns (face_t, left_t, right_t, grid_t) or None if any crop fails.

        Normalisation pipeline per crop:
          1. Resize crop to (224, 224)
          2. Convert BGR → RGB
          3. Divide by 255 → [0, 1]
          4. Subtract training mean → centred distribution
          5. Permute HWC → CHW, add batch dimension
        """
        h, w, _ = bgr_frame.shape

        # Compute bounding boxes using the correct landmark subsets
        fx1, fy1, fx2, fy2 = make_bounding_box(face_landmarks, FACE_OVAL_IDX,  w, h, padding=20)
        lx1, ly1, lx2, ly2 = make_bounding_box(face_landmarks, LEFT_EYE_IDX,   w, h, padding=12)
        rx1, ry1, rx2, ry2 = make_bounding_box(face_landmarks, RIGHT_EYE_IDX,  w, h, padding=12)

        # Reject degenerate crops
        if (fx2 - fx1) <= 0 or (lx2 - lx1) <= 0 or (rx2 - rx1) <= 0:
            return None

        # Crop and resize
        face_crop  = cv2.resize(bgr_frame[fy1:fy2, fx1:fx2], (224, 224))
        left_crop  = cv2.resize(bgr_frame[ly1:ly2, lx1:lx2], (224, 224))
        right_crop = cv2.resize(bgr_frame[ry1:ry2, rx1:rx2], (224, 224))

        # Convert BGR → RGB (MediaPipe and training data both use RGB)
        face_crop  = cv2.cvtColor(face_crop,  cv2.COLOR_BGR2RGB)
        left_crop  = cv2.cvtColor(left_crop,  cv2.COLOR_BGR2RGB)
        right_crop = cv2.cvtColor(right_crop, cv2.COLOR_BGR2RGB)

        # Normalise and subtract training mean
        face_t  = self._to_tensor(face_crop,  self._face_mean)
        left_t  = self._to_tensor(left_crop,  self._left_mean)
        right_t = self._to_tensor(right_crop, self._right_mean)

        # Face grid encodes the face's position within the full frame
        grid_v = compute_face_grid((fx1, fy1, fx2, fy2), bgr_frame.shape)
        grid_t = torch.tensor(grid_v, dtype=torch.float32).view(1, -1).to(self.device)

        return face_t, left_t, right_t, grid_t

    def _to_tensor(self, rgb_crop: np.ndarray, mean: np.ndarray) -> torch.Tensor:
        """
        Convert a (224, 224, 3) uint8 RGB crop to a (1, 3, 224, 224) float32
        tensor with MPIIFaceGaze mean subtraction applied.

        mean shape from .mat: (3, 224, 224), values in [0, 255]
        crop shape from OpenCV: (224, 224, 3), values in [0, 255] uint8

        Steps:
        1. Transpose mean to (224, 224, 3) to match crop layout
        2. Divide both by 255 to get [0, 1] range
        3. Subtract — result is centred around 0
        4. Permute to (3, 224, 224), add batch dim
        """
        if mean.shape == (3, 224, 224):
            mean_hwc = mean.transpose(1, 2, 0)   # → (224, 224, 3)
        else:
            mean_hwc = mean                        # already (224, 224, 3)

        normalised = rgb_crop.astype(np.float32) / 255.0 - mean_hwc / 255.0

        tensor = torch.tensor(normalised, dtype=torch.float32)
        tensor = tensor.permute(2, 0, 1).unsqueeze(0).to(self.device)
        return tensor
    # ── Weight reset ──────────────────────────────────────────────────────────

    def reload_weights(self):
        """
        Reload the original pre-trained weights from disk.
        Called before each calibration session to prevent fine-tuning accumulation.
        """
        if not os.path.exists(self.weights_filename):
            print("[Engine] Cannot reload weights — file not found.")
            return
        state_dict = torch.load(
            self.weights_filename,
            map_location=self.device,
            weights_only=True,
        )
        self.model.load_state_dict(state_dict, strict=False)
        self.model.eval()
        self.scaler = GazeCoordinateScaler()
        print("[Engine] Weights reloaded. Scaler reset.")

    # ── Fine-tuning ───────────────────────────────────────────────────────────

    def local_fine_tune(self, progress_callback=None):
        """
        Fine-tune the model on user-specific calibration samples.

        With 9 calibration points this gives the DataLoader enough samples to
        form meaningful batches.  The scaler bounds are recomputed after tuning
        so coordinate mapping reflects the personalised model output.
        """
        n = len(self.calibration_samples)
        if n < 5:
            print(f"[Calibration] Only {n} samples — need at least 5. Aborting.")
            return

        print(f"[Calibration] Fine-tuning on {n} samples...")
        self.model.train()

        dataset   = LocalCalibrationDataset(self.calibration_samples)
        loader    = DataLoader(dataset, batch_size=4, shuffle=True)
        optimizer = torch.optim.Adam(self.model.parameters(), lr=1e-4)
        criterion = nn.MSELoss()

        total_epochs = 10
        for epoch in range(total_epochs):
            loss_accum = 0.0
            for faces, left_eyes, right_eyes, grids, targets in loader:
                optimizer.zero_grad()
                outputs = self.model(faces, left_eyes, right_eyes, grids)
                loss    = criterion(outputs, targets)
                loss.backward()
                optimizer.step()
                loss_accum += loss.item()

            avg_loss = loss_accum / len(loader)
            print(f"  Epoch {epoch + 1}/{total_epochs}  loss={avg_loss:.5f}")

            if progress_callback is not None:
                progress_callback(int(((epoch + 1) / total_epochs) * 100))

        self.model.eval()

        # Recompute scaler bounds using the now-personalised model
        self.scaler.find_bounds(self.calibration_samples, self.model)
        print("[Calibration] Fine-tuning complete.")
        
    def set_gaze_offset(self, dx: int, dy: int):
        """
        Apply a static pixel correction to all gaze predictions.
        Call this after measuring the systematic offset between
        where gaze lands and where buttons actually are.
        """
        self.scaler.offset_x = dx
        self.scaler.offset_y = dy
        print(f"[Engine] Gaze offset applied: dx={dx}, dy={dy}")