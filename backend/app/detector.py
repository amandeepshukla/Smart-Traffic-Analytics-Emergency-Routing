"""Vehicle detectors.

Two interchangeable implementations behind one tiny interface:

* ``YoloDetector``   — Ultralytics YOLO, the accurate option for real street video
                       (``pip install -r requirements-yolo.txt``).
* ``MotionDetector`` — OpenCV MOG2 background subtraction. Zero extra downloads,
                       runs anywhere, ideal for demos and fixed CCTV angles. Its
                       limits: stationary vehicles slowly fade into the background
                       and touching vehicles can merge into one blob.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

import cv2
import numpy as np

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Detection:
    x: int
    y: int
    w: int
    h: int
    conf: float = 1.0
    label: str = "vehicle"

    @property
    def cx(self) -> float:
        return self.x + self.w / 2.0

    @property
    def cy(self) -> float:
        return self.y + self.h / 2.0

    @property
    def area(self) -> int:
        return self.w * self.h


class VehicleDetector(Protocol):
    name: str

    @property
    def ready(self) -> bool: ...

    def detect(self, frame: np.ndarray) -> list[Detection]: ...


class MotionDetector:
    """Background-subtraction vehicle detector (OpenCV MOG2)."""

    name = "opencv-mog2"

    def __init__(
        self,
        warmup_frames: int = 30,
        min_area_ratio: float = 0.0015,
        max_area_ratio: float = 0.30,
        learning_rate: float = 0.004,
        var_threshold: float = 28.0,
    ):
        self.warmup_frames = warmup_frames
        self.min_area_ratio = min_area_ratio
        self.max_area_ratio = max_area_ratio
        self.learning_rate = learning_rate
        self._bg = cv2.createBackgroundSubtractorMOG2(
            history=200, varThreshold=var_threshold, detectShadows=True
        )
        self._k_open = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        self._k_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
        self._frames = 0

    @property
    def ready(self) -> bool:
        return self._frames >= self.warmup_frames

    def detect(self, frame: np.ndarray) -> list[Detection]:
        self._frames += 1
        # learn the empty scene fast during warm-up, then adapt slowly
        lr = 0.05 if self._frames <= self.warmup_frames else self.learning_rate
        mask = self._bg.apply(frame, learningRate=lr)
        if not self.ready:
            return []
        mask = cv2.threshold(mask, 200, 255, cv2.THRESH_BINARY)[1]  # drop shadow pixels (127)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self._k_open)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self._k_close)

        h, w = frame.shape[:2]
        frame_area = float(h * w)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        detections: list[Detection] = []
        for contour in contours:
            area = cv2.contourArea(contour)
            ratio = area / frame_area
            if ratio < self.min_area_ratio or ratio > self.max_area_ratio:
                continue
            x, y, bw, bh = cv2.boundingRect(contour)
            conf = float(min(1.0, 0.5 + ratio * 20))
            detections.append(Detection(x, y, bw, bh, conf))
        return detections


class YoloDetector:
    """Ultralytics YOLO restricted to road-vehicle classes."""

    name = "yolo"
    # COCO ids: car, motorcycle, bus, truck
    VEHICLE_CLASSES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}

    def __init__(self, model_path: str = "yolov8n.pt", conf: float = 0.35, imgsz: int = 640):
        from ultralytics import YOLO  # imported lazily: optional dependency

        self.model = YOLO(model_path)
        self.conf = conf
        self.imgsz = imgsz
        self.name = f"yolo:{model_path}"

    @property
    def ready(self) -> bool:
        return True

    def detect(self, frame: np.ndarray) -> list[Detection]:
        result = self.model.predict(
            frame,
            conf=self.conf,
            imgsz=self.imgsz,
            classes=list(self.VEHICLE_CLASSES),
            verbose=False,
        )[0]
        detections: list[Detection] = []
        for box in result.boxes:
            x1, y1, x2, y2 = (int(v) for v in box.xyxy[0].tolist())
            label = self.VEHICLE_CLASSES.get(int(box.cls[0]), "vehicle")
            detections.append(Detection(x1, y1, x2 - x1, y2 - y1, float(box.conf[0]), label))
        return detections


def build_detector(kind: str, yolo_model: str, yolo_conf: float, real_source: bool) -> VehicleDetector:
    """Pick a detector.

    ``auto`` uses YOLO for real footage when ultralytics is installed, and the
    motion detector otherwise. Synthetic cameras always use the motion detector
    because YOLO cannot recognise the simulator's plain rectangles as cars.
    """
    kind = kind.lower()
    wants_yolo = kind == "yolo" or (kind == "auto" and real_source)
    if wants_yolo:
        try:
            return YoloDetector(yolo_model, yolo_conf)
        except Exception as exc:  # ImportError, missing weights, offline download...
            log.warning("YOLO unavailable (%s) — falling back to the OpenCV motion detector", exc)
    return MotionDetector()
