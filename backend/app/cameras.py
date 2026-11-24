"""Camera workers: one thread per junction camera.

Each worker pulls frames from its source (synthetic road, video file, webcam
index or RTSP/HTTP stream), runs the detector + analytics, and publishes the
latest metrics and an annotated JPEG for the dashboard.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from .analytics import FrameAnalyzer, FrameMetrics, congestion_level
from .config import Settings
from .detector import build_detector
from .network import Node, RoadNetwork
from .simulator import SyntheticTrafficSource, TrafficScenario

log = logging.getLogger(__name__)

SYNTHETIC = "synthetic"


@dataclass(frozen=True)
class CameraConfig:
    node_id: str
    source: str = SYNTHETIC  # "synthetic" | file path | webcam index | rtsp:// | http://

    @property
    def kind(self) -> str:
        src = self.source.strip()
        if src.lower() == SYNTHETIC:
            return "synthetic"
        if src.isdigit():
            return "webcam"
        if "://" in src:
            return "stream"
        return "video"


def load_camera_configs(path: Path, network: RoadNetwork, only: list[str]) -> list[CameraConfig]:
    """Read ``cameras.json`` (``[{"node_id": "J1", "source": "..."}]``). Missing nodes get synthetic cameras."""
    configured: dict[str, CameraConfig] = {}
    if path.exists():
        try:
            for item in json.loads(path.read_text(encoding="utf-8")):
                if item["node_id"] in network.nodes:
                    configured[item["node_id"]] = CameraConfig(item["node_id"], str(item.get("source", SYNTHETIC)))
                else:
                    log.warning("cameras.json: unknown node %s ignored", item.get("node_id"))
        except (ValueError, KeyError, TypeError) as exc:
            log.warning("could not parse %s (%s) — using synthetic cameras", path, exc)
    configs = [configured.get(nid, CameraConfig(nid)) for nid in network.nodes]
    if only:
        configs = [c for c in configs if c.node_id in set(only)]
    return configs


class VideoSource:
    """OpenCV capture for files, webcams and network streams."""

    def __init__(self, target: str, width: int, height: int, camera_fps: float):
        self.width, self.height = width, height
        self.cap = cv2.VideoCapture(int(target) if target.isdigit() else target)
        if not self.cap.isOpened():
            raise RuntimeError(f"cannot open video source {target!r}")
        self.is_file = "://" not in target and not target.isdigit()
        native = self.cap.get(cv2.CAP_PROP_FPS) or 0.0
        # skip frames so playback runs in real time at the processing rate
        self.skip = max(0, round(native / camera_fps) - 1) if native > 1 else 0

    def read(self) -> np.ndarray:
        for _ in range(self.skip):
            self.cap.grab()
        ok, frame = self.cap.read()
        if not ok and self.is_file:  # loop recorded footage forever
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self.cap.read()
        if not ok or frame is None:
            raise RuntimeError("video stream ended or dropped")
        return cv2.resize(frame, (self.width, self.height))

    def close(self) -> None:
        self.cap.release()


def _text_frame(width: int, height: int, title: str, message: str) -> np.ndarray:
    frame = np.full((height, width, 3), (30, 30, 34), np.uint8)
    cv2.putText(frame, title, (14, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (230, 230, 230), 1, cv2.LINE_AA)
    cv2.putText(frame, message, (14, height // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (80, 80, 240), 2, cv2.LINE_AA)
    return frame


class CameraWorker(threading.Thread):
    def __init__(
        self,
        config: CameraConfig,
        node: Node,
        settings: Settings,
        density_provider: Callable[[], float] | None = None,
        seed: int = 0,
    ):
        super().__init__(daemon=True, name=f"camera-{node.id}")
        self.config, self.node, self.settings = config, node, settings
        self._density_provider = density_provider
        self._seed = seed
        self._halt = threading.Event()
        self._lock = threading.Lock()
        self._frame_cond = threading.Condition(self._lock)
        self.forced_offline = False
        self.error: str | None = None
        self.metrics = FrameMetrics(lane_counts=[0] * settings.lanes, lane_density=[0.0] * settings.lanes)
        self.detector_name = "-"
        self.jpeg: bytes | None = None
        self.seq = 0
        self.last_frame_ts = 0.0
        self.fps = 0.0

    # -- lifecycle -------------------------------------------------------
    def stop(self) -> None:
        self._halt.set()

    def run(self) -> None:
        period = 1.0 / max(1.0, self.settings.camera_fps)
        source = analyzer = None
        while not self._halt.is_set():
            started = time.monotonic()
            if self.forced_offline:
                self._publish_text("SIGNAL LOST", "simulated outage")
                self.metrics = FrameMetrics(lane_counts=[0] * self.settings.lanes, lane_density=[0.0] * self.settings.lanes)
                source = analyzer = None
                self._halt.wait(0.5)
                continue
            try:
                if source is None:
                    source, analyzer = self._open()
                frame = source.read()
                metrics, detections = analyzer.process(frame, started)
                annotated = analyzer.annotate(frame, detections, metrics, f"{self.node.id} {self.node.name}")
                self._publish(annotated, metrics, started)
                self.error = None
            except Exception as exc:  # camera dropped, bad file, model failure...
                self.error = str(exc)
                log.warning("camera %s: %s — retrying in 3 s", self.node.id, exc)
                if hasattr(source, "close"):
                    source.close()
                source = analyzer = None
                self._publish_text("CAMERA ERROR", str(exc)[:46])
                self._halt.wait(3.0)
                continue
            self._halt.wait(max(0.0, period - (time.monotonic() - started)))
        if hasattr(source, "close"):
            source.close()

    def _open(self):
        s = self.settings
        real = self.config.kind != "synthetic"
        if real:
            source = VideoSource(self.config.source, s.frame_width, s.frame_height, s.camera_fps)
        else:
            source = SyntheticTrafficSource(
                s.frame_width, s.frame_height, s.lanes, s.capacity, s.camera_fps,
                seed=self._seed, density_provider=self._density_provider,
            )
        detector = build_detector(s.detector, s.yolo_model, s.yolo_conf, real_source=real)
        self.detector_name = detector.name
        return source, FrameAnalyzer(detector, s)

    # -- publishing ------------------------------------------------------
    def _publish(self, frame: np.ndarray, metrics: FrameMetrics, ts: float) -> None:
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 72])
        with self._frame_cond:
            self.metrics = metrics
            if ok:
                self.jpeg = buf.tobytes()
                self.seq += 1
            elapsed = ts - self.last_frame_ts if self.last_frame_ts else 0
            if elapsed > 0:
                self.fps = round(0.8 * self.fps + 0.2 / elapsed, 1) if self.fps else round(1 / elapsed, 1)
            self.last_frame_ts = ts
            self._frame_cond.notify_all()

    def _publish_text(self, title: str, message: str) -> None:
        s = self.settings
        ok, buf = cv2.imencode(".jpg", _text_frame(s.frame_width, s.frame_height, f"{self.node.id} {self.node.name}", f"{title}: {message}" if message else title))
        if ok:
            with self._frame_cond:
                self.jpeg = buf.tobytes()
                self.seq += 1
                self._frame_cond.notify_all()

    # -- reads -----------------------------------------------------------
    @property
    def status(self) -> str:
        if self.forced_offline or self.error:
            return "offline"
        if self.last_frame_ts == 0.0:
            return "calibrating"
        if time.monotonic() - self.last_frame_ts > self.settings.stale_after_s:
            return "offline"
        return "online" if self.metrics.ready else "calibrating"

    def current_congestion(self) -> float | None:
        """Live congestion, or ``None`` when the camera cannot be trusted."""
        if self.status != "online":
            return None
        return self.metrics.congestion

    def snapshot(self) -> dict:
        m = self.metrics
        status = self.status
        live = status == "online"
        return {
            "node_id": self.node.id,
            "name": self.node.name,
            "status": status,
            "source": self.config.kind,
            "detector": self.detector_name,
            "count": m.count if live else None,
            "lane_counts": m.lane_counts if live else None,
            "lane_density": m.lane_density if live else None,
            "congestion": m.congestion if live else None,
            "level": m.level if live else "unknown",
            "flow_per_min": m.flow_per_min if live else None,
            "total_seen": m.total_seen,
            "fps": self.fps if live else 0.0,
            "error": self.error,
        }


class CameraManager:
    def __init__(self, network: RoadNetwork, settings: Settings, scenario: TrafficScenario):
        self.network, self.settings, self.scenario = network, settings, scenario
        configs = load_camera_configs(settings.camera_config, network, settings.camera_nodes)
        self.workers: dict[str, CameraWorker] = {}
        for i, cfg in enumerate(configs):
            node = network.nodes[cfg.node_id]
            provider = (lambda nid=cfg.node_id: scenario.density(nid)) if cfg.kind == "synthetic" else None
            self.workers[cfg.node_id] = CameraWorker(cfg, node, settings, provider, seed=settings.seed + i)

    def start(self) -> None:
        for w in self.workers.values():
            if not w.is_alive():
                w.start()

    def stop(self) -> None:
        for w in self.workers.values():
            w.stop()
        for w in self.workers.values():
            if w.is_alive():
                w.join(timeout=2.0)

    def snapshot(self) -> dict[str, dict]:
        return {nid: w.snapshot() for nid, w in self.workers.items()}

    def congestion_map(self) -> dict[str, float]:
        """Only nodes with a healthy live camera appear; routing uses a prior for the rest."""
        out = {}
        for nid, w in self.workers.items():
            c = w.current_congestion()
            if c is not None:
                out[nid] = c
        return out

    def set_forced_offline(self, node_id: str, offline: bool) -> None:
        self.workers[node_id].forced_offline = offline

    def get(self, node_id: str) -> CameraWorker:
        return self.workers[node_id]


__all__ = ["CameraConfig", "CameraWorker", "CameraManager", "load_camera_configs", "congestion_level"]
