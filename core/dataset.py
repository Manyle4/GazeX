import torch
from torch.utils.data import Dataset

class LocalCalibrationDataset(Dataset):
    def __init__(self, samples_list):
        self.samples = samples_list

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        features, target = self.samples[idx]
        face, left, right, grid = features
        return face.squeeze(0), left.squeeze(0), right.squeeze(0), grid.squeeze(0), torch.tensor(target, dtype=torch.float32)