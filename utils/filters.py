import torch

class GazeCoordinateScaler:
    def __init__(self):
        self.min_x, self.max_x = -0.4, 0.4
        self.min_y, self.max_y = -0.4, 0.4

    def find_bounds(self, samples, model_instance):
        x_predictions = []
        y_values = []
        
        for features, _ in samples:
            f, l, r, g = features
            with torch.no_grad():
                pred = model_instance(f, l, r, g).cpu().numpy().flatten()
            x_predictions.append(pred[0])
            y_values.append(pred[1])
            
        if len(x_predictions) > 0:
            raw_width = max(x_predictions) - min(x_predictions)
            raw_height = max(y_values) - min(y_values)
            
            self.min_x = min(x_predictions) + (0.05 * raw_width)
            self.max_x = max(x_predictions) - (0.05 * raw_width)
            self.min_y = min(y_values) + (0.05 * raw_height)
            self.max_y = max(y_values) - (0.05 * raw_height)

    def map_to_screen_pixels(self, pred_x, pred_y, screen_w, screen_h):
        x_ratio = (pred_x - self.min_x) / (self.max_x - self.min_x + 1e-6)
        y_ratio = (pred_y - self.min_y) / (self.max_y - self.min_y + 1e-6)
        
        x_ratio = max(0.0, min(1.0, x_ratio))
        y_ratio = max(0.0, min(1.0, y_ratio))
        
        return int(x_ratio * screen_w), int(y_ratio * screen_h)