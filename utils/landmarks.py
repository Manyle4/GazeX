import numpy as np

def make_bounding_box(landmarks, points_indices, img_w, img_h, padding=15):
    x_points = [int(landmarks[i].x * img_w) for i in points_indices]
    y_points = [int(landmarks[i].y * img_h) for i in points_indices]
    
    x1 = max(0, min(x_points) - padding)
    y1 = max(0, min(y_points) - padding)
    x2 = min(img_w, max(x_points) + padding)
    y2 = min(img_h, max(y_points) + padding)
    return int(x1), int(y1), int(x2), int(y2)

def compute_face_grid(bbox_face, frame_shape, grid_size=25):
    f_h, f_w, _ = frame_shape
    grid = np.zeros((grid_size, grid_size), dtype=np.float32)
    
    x1, y1, x2, y2 = bbox_face
    start_col = int(max(0, min(grid_size - 1, (x1 / f_w) * grid_size)))
    end_col = int(max(0, min(grid_size - 1, (x2 / f_w) * grid_size)))
    start_row = int(max(0, min(grid_size - 1, (y1 / f_h) * grid_size)))
    end_row = int(max(0, min(grid_size - 1, (y2 / f_h) * grid_size)))
    
    grid[start_row:end_row+1, start_col:end_col+1] = 1.0
    return grid.flatten()