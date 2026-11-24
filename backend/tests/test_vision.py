import numpy as np

from app.analytics import FrameAnalyzer, congestion_level, lane_stats
from app.config import load_settings
from app.detector import Detection, MotionDetector
from app.simulator import SyntheticTrafficSource, TrafficScenario
from app.tracker import CentroidTracker

SETTINGS = load_settings()


def run(density: float, frames: int = 140, seed: int = 3):
    src = SyntheticTrafficSource(density=density, seed=seed)
    analyzer = FrameAnalyzer(MotionDetector(), SETTINGS)
    counts, truth, cong = [], [], []
    for i in range(frames):
        metrics, _ = analyzer.process(src.read(), now=i * 0.125)
        if metrics.ready and i > 60:
            counts.append(metrics.count)
            truth.append(src.ground_truth)
            cong.append(metrics.congestion)
    return np.array(counts), np.array(truth), cong


def test_detector_counts_close_to_ground_truth():
    counts, truth, _ = run(0.4)
    assert abs(counts.mean() - truth.mean()) <= 1.5


def test_congestion_increases_with_traffic():
    levels = [run(d)[2][-1] for d in (0.1, 0.5, 0.95)]
    assert levels[0] < levels[1] < levels[2]


def test_empty_road_is_free_flowing():
    _, _, cong = run(0.0)
    assert cong[-1] < 0.1


def test_detector_warms_up_before_reporting():
    src = SyntheticTrafficSource(density=0.5)
    analyzer = FrameAnalyzer(MotionDetector(warmup_frames=20), SETTINGS)
    metrics, _ = analyzer.process(src.read())
    assert metrics.ready is False


def test_lane_stats_bins_by_x():
    dets = [Detection(10, 0, 20, 20), Detection(250, 0, 20, 20), Detection(260, 40, 20, 20), Detection(450, 0, 20, 20)]
    counts, density = lane_stats(dets, 480, 3, 9)
    assert counts == [1, 2, 1]
    assert all(0 <= d <= 1 for d in density)


def test_levels():
    assert [congestion_level(x) for x in (None, 0.1, 0.4, 0.7, 0.95)] == ["unknown", "free", "moderate", "heavy", "gridlock"]


def test_tracker_keeps_ids_and_counts_confirmed_only():
    t = CentroidTracker(max_distance=40, min_hits=3)
    ids = []
    for i in range(5):
        pairs = t.update([Detection(100 + i * 5, 50, 30, 30)], now=i)
        ids.append(pairs[0][0])
    assert len(set(ids)) == 1 and t.total_seen == 1
    t2 = CentroidTracker(min_hits=3)
    t2.update([Detection(0, 0, 10, 10)], now=0)
    assert t2.total_seen == 0  # one-frame blobs are ignored


def test_scenario_override_and_bounds():
    sc = TrafficScenario(["A", "B"], seed=1)
    for _ in range(200):
        sc.tick(1.0)
    assert all(0 <= sc.density(n) <= 1 for n in "AB")
    sc.set_override("A", 0.9)
    assert sc.density("A") == 0.9
    sc.reset()
    assert sc.density("A") != 0.9


def test_real_video_file_pipeline(tmp_path):
    """Video file -> VideoSource -> detector -> metrics (the path real CCTV footage takes)."""
    import cv2

    from app.cameras import VideoSource

    path = str(tmp_path / "road.mp4")
    src = SyntheticTrafficSource(320, 180, fps=15, density=0.6, seed=5)
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 15, (320, 180))
    assert writer.isOpened()
    for _ in range(150):
        writer.write(src.read())
    writer.release()

    vs = VideoSource(path, 480, 270, camera_fps=8)
    analyzer = FrameAnalyzer(MotionDetector(), SETTINGS)
    last = None
    for i in range(60):  # more frames than the file has -> also exercises looping
        last, _ = analyzer.process(vs.read(), now=i * 0.125)
    vs.close()
    assert last.ready and last.count >= 1 and last.congestion > 0.15
