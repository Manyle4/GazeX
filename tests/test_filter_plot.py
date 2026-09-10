import numpy as np
import matplotlib.pyplot as plt
from utils.filters import OneEuroFilterPair

def run_filter_evaluation():
    # 1. Instantiate the filter with your pipeline's exact parameters
    filt = OneEuroFilterPair(
        freq=30.0,
        mincutoff=0.5,
        beta=0.003,
        dcutoff=0.5
    )

    # 2. Synthesize realistic gaze data (120 frames at 30 Hz = 4.0 seconds)
    # Frames 0-60: Staring at target center (500 px) with high-frequency noise
    # Frames 61-120: Quick gaze shift to Button B (850 px) + noise
    np.random.seed(42)
    n_frames = 120
    time_steps = np.arange(n_frames) / 30.0  # seconds

    ground_truth = np.concatenate([
        np.full(60, 500.0),
        np.full(60, 850.0)
    ])

    # Add Gaussian jitter (webcam eye tracking noise)
    noise = np.random.normal(loc=0.0, scale=12.0, size=n_frames)
    raw_gaze_x = ground_truth + noise
    raw_gaze_y = np.full(n_frames, 400.0) + np.random.normal(0, 8.0, n_frames)

    # 3. Filter the simulated coordinates frame-by-frame
    filtered_x = []
    for rx, ry in zip(raw_gaze_x, raw_gaze_y):
        fx, fy = filt.filter(rx, ry)
        filtered_x.append(fx)
    filtered_x = np.array(filtered_x)

    # 4. Calculate Variance during the static fixation phase (Frames 15-60)
    static_raw = raw_gaze_x[15:60]
    static_filt = filtered_x[15:60]

    var_raw = np.var(static_raw)
    var_filt = np.var(static_filt)
    reduction = (1.0 - (var_filt / var_raw)) * 100.0

    print("=" * 50)
    print("ONE EURO FILTER JITTER EVALUATION")
    print("=" * 50)
    print(f"Static Raw Gaze Variance:      {var_raw:.2f} px^2")
    print(f"Static Filtered Gaze Variance: {var_filt:.2f} px^2")
    print(f"Jitter Variance Reduction:     {reduction:.1f}%")
    print("=" * 50)

    # 5. Generate Dissertation-Grade Plot
    plt.figure(figsize=(10, 5), dpi=300)
    plt.plot(time_steps, raw_gaze_x, color="#94a3b8", alpha=0.7, label="Raw Gaze (Unfiltered)", linewidth=1.2)
    plt.plot(time_steps, ground_truth, "k--", alpha=0.4, label="Ideal Fixation Point", linewidth=1.0)
    plt.plot(time_steps, filtered_x, color="#06b6d4", label="1€ Filtered Gaze", linewidth=2.2)

    plt.axvline(x=2.0, color="#ef4444", linestyle=":", alpha=0.7, label="Saccade Shift (Gaze Jump)")

    plt.title("One Euro Filter Jitter Damping vs. Saccadic Response", fontsize=13, pad=12, fontweight="bold")
    plt.xlabel("Time (seconds)", fontsize=11)
    plt.ylabel("Gaze Position    X (pixels)", fontsize=11)
    plt.legend(loc="upper left", frameon=True, facecolor="white", edgecolor="#cbd5e1")
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.tight_layout()

    # Save to disk
    plot_filename = "filter_smoothing_evaluation.png"
    plt.savefig(plot_filename)
    print(f"[Success] Plot saved directly to: {plot_filename}")
    plt.show()

if __name__ == "__main__":
    run_filter_evaluation()