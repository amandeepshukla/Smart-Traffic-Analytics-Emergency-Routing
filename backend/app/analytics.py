"""Turns raw detections into traffic metrics: density, lane load and a congestion score."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import cv2
import numpy as np

from .config import Settings
from .detector import Detection, VehicleDetector
from .tracker import CentroidTracker

LEVEL_COLORS_BGR = {
    "free": (94, 197, 34),
    "moderate": (8, 179, 234),
    "heavy": (22, 115, 249),
    "gridlock": (68, 68, 239),
    "unknown": (160, 160, 160),
}


def congestion_level(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score < 0.30:
        return "free"
    if score < 0.60:
        return "moderate"
    if score < 0.85:
        return "heavy"
    return "gridlock"


def lane_stats(
    detections: Sequence[Detection], frame_width: int, lanes: int, capacity: int
) -> tuple[list[int], list[float]]:
    """Vehicles per lane and lane density (0..1). Lanes are equal vertical strips."""
    counts = [0] * lanes
    for det in detections:
        idx = min(lanes - 1, max(0, int(det.cx / max(1, frame_width) * lanes)))
        counts[idx] += 1
    per_lane_capacity = max(1.0, capacity / lanes)
    density = [round(min(1.0, c / per_lane_capacity), 3) for c in counts]
    return counts, density


@dataclass
class FrameMetrics:
    ready: bool = False
    count: int = 0
    lane_counts: list[int] = field(default_factory=list)
    lane_density: list[float] = field(default_factory=list)
    occupancy: float = 0.0
    raw_congestion: float = 0.0
    congestion: float | None = None
    level: str = "unknown"
    flow_per_min: float = 0.0
    total_seen: int = 0


class FrameAnalyzer:
    """Runs the detector on a frame and maintains smoothed per-camera metrics."""

    def __init__(self, detector: VehicleDetector, settings: Settings):
        self.detector = detector
        self.settings = settings
        self.tracker = CentroidTracker(max_distance=settings.frame_width * 0.18)
        self._ema: float | None = None

    def reset(self) -> None:
        self._ema = None
        self.tracker.reset()

    def process(self, frame: np.ndarray, now: float | None = None) -> tuple[FrameMetrics, list[Detection]]:
        s = self.settings
        h, w = frame.shape[:2]
        detections = self.detector.detect(frame)
        ready = self.detector.ready
        if not ready:
            return FrameMetrics(ready=False, lane_counts=[0] * s.lanes, lane_density=[0.0] * s.lanes), []

        count = len(detections)
        lane_counts, lane_density = lane_stats(detections, w, s.lanes, s.capacity)
        occupancy = min(1.0, sum(d.area for d in detections) / float(w * h))

        count_ratio = min(1.0, count / max(1, s.capacity))
        occupancy_ratio = min(1.0, occupancy / max(1e-6, s.occupancy_full))
        raw = 0.6 * count_ratio + 0.4 * occupancy_ratio
        self._ema = raw if self._ema is None else s.ema_alpha * raw + (1 - s.ema_alpha) * self._ema

        self.tracker.update(detections, now)
        metrics = FrameMetrics(
            ready=True,
            count=count,
            lane_counts=lane_counts,
            lane_density=lane_density,
            occupancy=round(occupancy, 3),
            raw_congestion=round(raw, 3),
            congestion=round(self._ema, 3),
            level=congestion_level(self._ema),
            flow_per_min=round(self.tracker.flow_per_min(now), 1),
            total_seen=self.tracker.total_seen,
        )
        return metrics, detections

    def annotate(
        self, frame: np.ndarray, detections: Sequence[Detection], metrics: FrameMetrics, title: str
    ) -> np.ndarray:
        """Draw boxes, lane dividers and a HUD strip onto a copy of the frame."""
        out = frame.copy()
        h, w = out.shape[:2]
        color = LEVEL_COLORS_BGR[metrics.level]
        lanes = self.settings.lanes
        for i in range(1, lanes):
            x = int(w * i / lanes)
            for y in range(0, h, 14):
                cv2.line(out, (x, y), (x, min(h, y + 6)), (255, 255, 255), 1)
        for det in detections:
            cv2.rectangle(out, (det.x, det.y), (det.x + det.w, det.y + det.h), color, 2)
        cv2.rectangle(out, (0, 0), (w, 24), (20, 20, 24), -1)
        cv2.rectangle(out, (0, 0), (6, 24), color, -1)
        if metrics.ready and metrics.congestion is not None:
            hud = f"{title}  |  {metrics.count} veh  |  {int(metrics.congestion * 100)}% {metrics.level}"
        else:
            hud = f"{title}  |  calibrating..."
        cv2.putText(out, hud, (12, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (240, 240, 240), 1, cv2.LINE_AA)
        return out
