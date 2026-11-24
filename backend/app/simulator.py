"""Synthetic traffic so the whole system runs with no cameras or video files.

``SyntheticTrafficSource`` renders a top-down three-lane road with moving
vehicles whose number and speed follow a congestion level. ``TrafficScenario``
drives those levels over time (slow random drift) and lets the dashboard force
a jam on any junction for demos.
"""
from __future__ import annotations

import random
import threading
from dataclasses import dataclass
from typing import Callable

import cv2
import numpy as np

_PALETTE = [
    (40, 40, 210), (210, 90, 40), (225, 225, 225), (30, 200, 215),
    (60, 170, 60), (200, 60, 170), (230, 150, 40), (150, 150, 235),
]


@dataclass
class _Vehicle:
    lane: int
    y: float
    length: int
    width: int
    color: tuple[int, int, int]
    speed_factor: float
    x_jitter: int


class SyntheticTrafficSource:
    """Renders frames of an artificial road. Call ``read()`` once per frame."""

    GAP_PX = 16

    def __init__(
        self,
        width: int = 480,
        height: int = 270,
        lanes: int = 3,
        capacity: int = 10,
        fps: float = 8.0,
        seed: int = 0,
        density: float = 0.3,
        density_provider: Callable[[], float] | None = None,
    ):
        self.width, self.height, self.lanes = width, height, lanes
        self.capacity = capacity
        self.dt = 1.0 / fps
        self._rng = random.Random(seed)
        self._np_rng = np.random.default_rng(seed)
        self._density = density
        self._provider = density_provider
        self._vehicles: list[_Vehicle] = []
        self._road_left = int(width * 0.1)
        self._road_right = int(width * 0.9)
        self._lane_w = (self._road_right - self._road_left) / lanes
        self._background = self._render_background()

    # -- public ----------------------------------------------------------
    def set_density(self, value: float) -> None:
        self._density = min(1.0, max(0.0, value))

    @property
    def ground_truth(self) -> int:
        """Vehicles currently visible (for tests / benchmarking the detector)."""
        return sum(1 for v in self._vehicles if v.y + v.length > 0 and v.y < self.height)

    def read(self) -> np.ndarray:
        if self._provider is not None:
            self.set_density(self._provider())
        self._step()
        frame = self._background.copy()
        for v in sorted(self._vehicles, key=lambda item: item.y):
            self._draw_vehicle(frame, v)
        noise = self._np_rng.normal(0, 1.6, frame.shape)
        return np.clip(frame.astype(np.float32) + noise, 0, 255).astype(np.uint8)

    # -- internals -------------------------------------------------------
    def _render_background(self) -> np.ndarray:
        bg = np.full((self.height, self.width, 3), (58, 92, 62), np.uint8)  # verges
        cv2.rectangle(bg, (self._road_left, 0), (self._road_right, self.height), (72, 72, 74), -1)
        cv2.line(bg, (self._road_left, 0), (self._road_left, self.height), (200, 200, 200), 2)
        cv2.line(bg, (self._road_right, 0), (self._road_right, self.height), (200, 200, 200), 2)
        for i in range(1, self.lanes):
            x = int(self._road_left + self._lane_w * i)
            for y in range(0, self.height, 28):
                cv2.line(bg, (x, y), (x, y + 14), (190, 190, 190), 2)
        return bg

    def _lane_center(self, lane: int) -> int:
        return int(self._road_left + self._lane_w * (lane + 0.5))

    def _step(self) -> None:
        target = round(self._density * self.capacity)
        base_speed = 150.0 * (1.0 - 0.85 * self._density)  # px / s

        by_lane: dict[int, list[_Vehicle]] = {i: [] for i in range(self.lanes)}
        for v in self._vehicles:
            by_lane[v.lane].append(v)
        for lane_vehicles in by_lane.values():
            lane_vehicles.sort(key=lambda item: -item.y)  # front of the queue first
            ahead: _Vehicle | None = None
            for v in lane_vehicles:
                new_y = v.y + base_speed * v.speed_factor * self.dt
                if ahead is not None:
                    new_y = min(new_y, ahead.y - v.length - self.GAP_PX)
                v.y = new_y
                ahead = v
        self._vehicles = [v for v in self._vehicles if v.y < self.height]

        if len(self._vehicles) < target and self._rng.random() < 0.45:
            lane = self._rng.randrange(self.lanes)
            rear = min((v.y for v in by_lane[lane] if v in self._vehicles), default=None)
            length = self._rng.choice([66, 72, 78, 96])
            if rear is None or rear > self.GAP_PX + 4:
                self._vehicles.append(
                    _Vehicle(
                        lane=lane,
                        y=-float(length),
                        length=length,
                        width=int(self._lane_w * 0.5),
                        color=self._rng.choice(_PALETTE),
                        speed_factor=self._rng.uniform(0.9, 1.1),
                        x_jitter=self._rng.randint(-5, 5),
                    )
                )

    def _draw_vehicle(self, frame: np.ndarray, v: _Vehicle) -> None:
        cx = self._lane_center(v.lane) + v.x_jitter
        x1, x2 = cx - v.width // 2, cx + v.width // 2
        y1, y2 = int(v.y), int(v.y) + v.length
        cv2.rectangle(frame, (x1, y1), (x2, y2), v.color, -1)
        cv2.rectangle(frame, (x1, y1), (x2, y2), (15, 15, 15), 1)
        wind_top = y2 - int(v.length * 0.38)  # windscreen toward the direction of travel
        cv2.rectangle(frame, (x1 + 5, wind_top), (x2 - 5, y2 - 8), (60, 50, 40), -1)
        cv2.circle(frame, (x1 + 6, y2 - 3), 2, (180, 240, 255), -1)
        cv2.circle(frame, (x2 - 6, y2 - 3), 2, (180, 240, 255), -1)


class TrafficScenario:
    """Slowly drifting congestion per node, with manual overrides for demos."""

    def __init__(self, node_ids: list[str], seed: int = 7):
        self._rng = random.Random(seed)
        self._lock = threading.Lock()
        self._base = {n: self._rng.uniform(0.12, 0.55) for n in node_ids}
        self._level = dict(self._base)
        self._overrides: dict[str, float] = {}

    def tick(self, dt: float = 1.0) -> None:
        with self._lock:
            for node, level in self._level.items():
                if self._rng.random() < 0.02 * dt:  # occasional rush / lull
                    self._base[node] = self._rng.uniform(0.08, 0.85)
                drift = 0.12 * (self._base[node] - level) * dt
                level += drift + self._rng.gauss(0, 0.02)
                self._level[node] = min(0.95, max(0.03, level))

    def density(self, node_id: str) -> float:
        with self._lock:
            return self._overrides.get(node_id, self._level.get(node_id, 0.3))

    def set_override(self, node_id: str, value: float | None) -> None:
        with self._lock:
            if value is None:
                self._overrides.pop(node_id, None)
            else:
                self._overrides[node_id] = min(1.0, max(0.0, value))

    def overrides(self) -> dict[str, float]:
        with self._lock:
            return dict(self._overrides)

    def reset(self) -> None:
        with self._lock:
            self._overrides.clear()
