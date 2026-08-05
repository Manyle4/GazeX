import math
import torch
import numpy as np


# ── One Euro Filter ───────────────────────────────────────────────────────────

class _LowPassFilter:
    """Single-pole low-pass filter with a configurable alpha."""

    def __init__(self):
        self._value = None      # None until first sample arrives

    def filter(self, x: float, alpha: float) -> float:
        if self._value is None:
            self._value = x
        self._value = alpha * x + (1.0 - alpha) * self._value
        return self._value

    @property
    def last(self) -> float | None:
        return self._value

    def reset(self):
        self._value = None


class _OneEuroFilter:
    """
    Single-axis One Euro Filter.

    Reference: Casiez et al., "1€ Filter: A Simple Speed-based Low-pass
    Filter for Noisy Input in Interactive Systems", CHI 2012.

    The cutoff frequency adapts to the estimated speed of the signal:
      - Slow / stationary  →  low cutoff  →  heavy smoothing
      - Fast movement      →  high cutoff →  minimal lag
    """

    def __init__(self, freq: float, mincutoff: float, beta: float, dcutoff: float):
        """
        :param freq:      Nominal sampling frequency in Hz (e.g. 30)
        :param mincutoff: Minimum cutoff frequency — controls smoothing at rest
        :param beta:      Speed coefficient — higher = faster response to motion
        :param dcutoff:   Cutoff for the derivative low-pass filter (usually 1.0)
        """
        self.freq      = freq
        self.mincutoff = mincutoff
        self.beta      = beta
        self.dcutoff   = dcutoff

        self._x_filt  = _LowPassFilter()   # filtered signal
        self._dx_filt = _LowPassFilter()   # filtered derivative

    @staticmethod
    def _alpha(cutoff: float, freq: float) -> float:
        """Compute the EMA alpha for a given cutoff frequency and sample rate."""
        tau = 1.0 / (2.0 * math.pi * cutoff)
        te  = 1.0 / freq
        return 1.0 / (1.0 + tau / te)

    def filter(self, x: float) -> float:
        """
        Filter a new sample and return the smoothed value.
        Call once per frame in arrival order.
        """
        # Estimate instantaneous derivative from previous filtered value
        prev = self._x_filt.last
        if prev is None:
            dx = 0.0
        else:
            dx = (x - prev) * self.freq

        # Smooth the derivative
        edx = self._dx_filt.filter(dx, self._alpha(self.dcutoff, self.freq))

        # Adaptive cutoff: rises with speed so fast movements pass through
        cutoff = self.mincutoff + self.beta * abs(edx)

        # Filter the signal with the adaptive cutoff
        return self._x_filt.filter(x, self._alpha(cutoff, self.freq))

    def reset(self):
        """Clear filter history — call when gaze stream restarts or after calibration."""
        self._x_filt.reset()
        self._dx_filt.reset()


class OneEuroFilterPair:
    """
    Convenience wrapper that filters X and Y gaze coordinates independently.
    This is what the dashboard and engine use directly.
    """

    def __init__(
        self,
        freq:      float = 30.0,
        mincutoff: float = 1.0,
        beta:      float = 0.05,
        dcutoff:   float = 1.0,
    ):
        self._fx = _OneEuroFilter(freq, mincutoff, beta, dcutoff)
        self._fy = _OneEuroFilter(freq, mincutoff, beta, dcutoff)

    def filter(self, x: float, y: float) -> tuple[float, float]:
        return self._fx.filter(x), self._fy.filter(y)

    def reset(self):
        self._fx.reset()
        self._fy.reset()


# ── Gaze Coordinate Scaler ────────────────────────────────────────────────────

class GazeCoordinateScaler:
    """
    Maps the model's raw normalised output to screen pixel coordinates.

    After fine-tuning, find_bounds() runs the personalised model over all
    calibration samples to discover the actual output range it produces for
    this user.  map_to_screen_pixels() then linearly remaps that range to
    the full screen.

    This compensates for the fact that the model rarely uses the full [-1, 1]
    theoretical range in practice — the actual spread is much narrower and
    varies per user.
    """

    def __init__(self):
        # Conservative defaults — replaced by find_bounds() after calibration
        self.min_x, self.max_x = -0.4,  0.4
        self.min_y, self.max_y = -0.4,  0.4
        
        self.offset_x = 0
        self.offset_y = 0

    def find_bounds(self, samples: list, model_instance) -> None:
        xs, ys = [], []

        for features, _ in samples:
            f, l, r, g = features
            with torch.no_grad():
                pred = model_instance(f, l, r, g).cpu().numpy().flatten()
            xs.append(float(pred[0]))
            ys.append(float(pred[1]))

        if not xs:
            return

        raw_w = max(xs) - min(xs)
        raw_h = max(ys) - min(ys)

        # Enforce a minimum range so tiny calibration spreads
        # don't get amplified into massive pixel jumps.
        # 0.3 is approximately the range a typical user produces
        # when looking from left to right of the screen.
        MIN_RANGE = 0.30

        if raw_w < MIN_RANGE:
            center_x = (max(xs) + min(xs)) / 2
            min_x = center_x - MIN_RANGE / 2
            max_x = center_x + MIN_RANGE / 2
        else:
            min_x = min(xs) + 0.05 * raw_w
            max_x = max(xs) - 0.05 * raw_w

        if raw_h < MIN_RANGE:
            center_y = (max(ys) + min(ys)) / 2
            min_y = center_y - MIN_RANGE / 2
            max_y = center_y + MIN_RANGE / 2
        else:
            min_y = min(ys) + 0.05 * raw_h
            max_y = max(ys) - 0.05 * raw_h

        self.min_x, self.max_x = min_x, max_x
        self.min_y, self.max_y = min_y, max_y

        print(
            f"[Scaler] Bounds updated — "
            f"x:[{self.min_x:.3f}, {self.max_x:.3f}]  "
            f"y:[{self.min_y:.3f}, {self.max_y:.3f}]  "
            f"raw_range=({raw_w:.3f}, {raw_h:.3f})"
        )

    def map_to_screen_pixels(self, pred_x, pred_y, screen_w, screen_h):
        x_ratio = (pred_x - self.min_x) / (self.max_x - self.min_x + 1e-6)
        y_ratio = (pred_y - self.min_y) / (self.max_y - self.min_y + 1e-6)

        x_ratio = max(0.0, min(1.0, x_ratio))
        y_ratio = max(0.0, min(1.0, y_ratio))

        px = int(x_ratio * screen_w) + self.offset_x
        py = int(y_ratio * screen_h) + self.offset_y

        # Clamp to screen after offset
        px = max(0, min(screen_w - 1, px))
        py = max(0, min(screen_h - 1, py))

        return px, py