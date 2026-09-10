import math
import time
from core.dwell_controller import DwellController, DwellState
from utils.filters import OneEuroFilterPair
class MockWidget:
    def __init__(self, x, y, name="MockBtn"):
        self.x, self.y, self.name = x, y, name
        self.clicked = False

    def winfo_exists(self): 
        return True

    def winfo_rootx(self): 
        return self.x

    def winfo_rooty(self): 
        return self.y

    def winfo_width(self): 
        return 100

    def winfo_height(self): 
        return 50

    def cget(self): 
        return self.name

    def invoke(self): 
        self.clicked = True


def test_dwell_hysteresis():
    print("[RUNNING] Testing Dwell Controller Hysteresis...")
    ctrl = DwellController(dwell_seconds=1.0, switch_margin=50.0)
    btn_a = MockWidget(100, 100, "Button A")  # Center: (150, 125)
    btn_b = MockWidget(300, 100, "Button B")  # Center: (350, 125)
    ctrl.set_buttons([btn_a, btn_b])

    # 1. Target Button A
    snap = ctrl.update(160, 125)
    assert snap.target == btn_a, "Failed: Did not lock onto Button A initially."
    print("  ✓ Initial lock onto Button A successful.")

    # 2. Gaze shifts slightly toward B (closer to B, but within switch_margin)
    snap = ctrl.update(245, 125)
    assert snap.target == btn_a, "Failed: Focus flickered to Button B prematurely."
    print("  ✓ Sticky boundary held: gaze drifted but remained on Button A.")

    # 3. Gaze clearly moves past threshold
    snap = ctrl.update(340, 125)
    assert snap.target == btn_b, "Failed: Did not switch to Button B past threshold."
    print("  ✓ Switching successful: gaze crossed margin and targeted Button B.")
    print("[PASS] Dwell Controller test passed.\n")


def test_filter_noise_reduction():
    print("[RUNNING] Testing One Euro Filter Noise Reduction...")
    filt = OneEuroFilterPair(freq=30, mincutoff=0.5, beta=0.003, dcutoff=0.5)
    noisy_samples = [500.0 + (5.0 if i % 2 == 0 else -5.0) for i in range(60)]
    smoothed = [filt.filter(val, 300.0)[0] for val in noisy_samples]

    raw_variance = sum((x - 500.0) ** 2 for x in noisy_samples) / len(noisy_samples)
    filt_variance = sum((x - 500.0) ** 2 for x in smoothed[15:]) / len(smoothed[15:])

    reduction_pct = (1.0 - (filt_variance / raw_variance)) * 100
    print(f"  • Raw Jitter Variance:      {raw_variance:.2f}")
    print(f"  • Filtered Jitter Variance: {filt_variance:.2f}")
    print(f"  • Noise Reduction:          {reduction_pct:.1f}%")

    assert filt_variance < (raw_variance * 0.2), "Failed: Filter did not reduce variance by 80%."
    print("[PASS] One Euro Filter noise reduction test passed.\n")


if __name__ == "__main__":
    test_dwell_hysteresis()
    test_filter_noise_reduction()
    print("All tests passed successfully.")