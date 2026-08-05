import torch
import torch.nn as nn

class FeatureImageModel(nn.Module):
    def __init__(self) -> None:
        super(FeatureImageModel, self).__init__()
        self.features = nn.Sequential(
            nn.Conv2d(3, 96, kernel_size=11, stride=4, padding=0),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=3, stride=2),
            nn.CrossMapLRN2d(size=5, alpha=0.0001, beta=0.75, k=1.0),
            nn.Conv2d(96, 256, kernel_size=5, stride=1, padding=2, groups=2), #feature processing map
            nn.ReLU(inplace=True), #activation states
            nn.MaxPool2d(kernel_size=3, stride=2), #pooling modules
            nn.CrossMapLRN2d(size=5, alpha=0.0001, beta=0.75, k=1.0),
            nn.Conv2d(256, 384, kernel_size=3, stride=1, padding=1),
            nn.ReLU(inplace=True),
            nn.Conv2d(384, 64, kernel_size=1, stride=1, padding=0),
            nn.ReLU(inplace=True),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.features(x)
        x = x.reshape(x.size(0), -1)
        return x

class FaceImageModel(nn.Module):
    def __init__(self) -> None:
        super(FaceImageModel, self).__init__()
        self.conv = FeatureImageModel()
        self.fc = nn.Sequential(
            nn.Linear(12 * 12 * 64, 128),
            nn.ReLU(inplace=True),
            nn.Linear(128, 64),
            nn.ReLU(inplace=True),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.conv(x)
        x = self.fc(x)
        return x

class FaceGridModel(nn.Module):
    def __init__(self, gridSize: int = 25) -> None:
        super(FaceGridModel, self).__init__()
        self.fc = nn.Sequential(
            nn.Linear(gridSize * gridSize, 256),
            nn.ReLU(inplace=True),
            nn.Linear(256, 128),
            nn.ReLU(inplace=True),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x.view(x.size(0), -1)
        x = self.fc(x)
        return x

class GazeModel(nn.Module):
    def __init__(self) -> None:
        super(GazeModel, self).__init__()
        self.eyeModel = FeatureImageModel()
        self.faceModel = FaceImageModel()
        self.gridModel = FaceGridModel()

        self.eyesFC = nn.Sequential(
            nn.Linear(2 * 12 * 12 * 64, 128),
            nn.ReLU(inplace=True),
        )

        self.fc = nn.Sequential(
            nn.Linear(128 + 64 + 128, 128),
            nn.ReLU(inplace=True),
            nn.Linear(128, 2),
        )

    def forward(self, faces: torch.Tensor, eyesLeft: torch.Tensor, eyesRight: torch.Tensor, faceGrids: torch.Tensor) -> torch.Tensor:
        xEyeL = self.eyeModel(eyesLeft)
        xEyeR = self.eyeModel(eyesRight)
        xEyes = torch.cat((xEyeL, xEyeR), 1)
        xEyes = self.eyesFC(xEyes)

        xFace = self.faceModel(faces)
        xGrid = self.gridModel(faceGrids)

        x = torch.cat((xEyes, xFace, xGrid), 1)
        x = self.fc(x)
        return x