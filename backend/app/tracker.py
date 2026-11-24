"""Tiny centroid tracker used to give vehicles stable ids and estimate flow."""
from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass
from typing import Sequence


@dataclass
class Track:
    id: int
    cx: float
    cy: float
    missed: int = 0
    hits: int = 1
    confirmed: bool = False


class CentroidTracker:
    """Greedy nearest-centroid matching.

    A track only counts as a real vehicle after ``min_hits`` consecutive-ish
    sightings, which filters out one-frame noise blobs from the flow estimate.
    """

    def __init__(self, max_distance: float = 80.0, max_missed: int = 6, min_hits: int = 3):
        self.max_distance = max_distance
        self.max_missed = max_missed
        self.min_hits = min_hits
        self.total_seen = 0
        self._tracks: dict[int, Track] = {}
        self._next_id = 1
        self._births: deque[float] = deque()
        self._t0 = time.monotonic()

    def reset(self) -> None:
        self._tracks.clear()
        self._births.clear()
        self._t0 = time.monotonic()

    def update(self, detections: Sequence, now: float | None = None) -> list[tuple[int, object]]:
        """Match detections to tracks. Returns ``[(track_id, detection), ...]``."""
        now = time.monotonic() if now is None else now
        pairs: list[tuple[float, int, int]] = []
        for tid, track in self._tracks.items():
            for di, det in enumerate(detections):
                dist = math.hypot(track.cx - det.cx, track.cy - det.cy)
                if dist <= self.max_distance:
                    pairs.append((dist, tid, di))
        pairs.sort()

        used_tracks: set[int] = set()
        used_dets: set[int] = set()
        assigned: list[tuple[int, object]] = []
        for _, tid, di in pairs:
            if tid in used_tracks or di in used_dets:
                continue
            track = self._tracks[tid]
            track.cx, track.cy = detections[di].cx, detections[di].cy
            track.missed = 0
            track.hits += 1
            self._maybe_confirm(track, now)
            used_tracks.add(tid)
            used_dets.add(di)
            assigned.append((tid, detections[di]))

        for tid in list(self._tracks):
            if tid not in used_tracks:
                self._tracks[tid].missed += 1
                if self._tracks[tid].missed > self.max_missed:
                    del self._tracks[tid]

        for di, det in enumerate(detections):
            if di in used_dets:
                continue
            track = Track(self._next_id, det.cx, det.cy)
            self._next_id += 1
            self._tracks[track.id] = track
            self._maybe_confirm(track, now)
            assigned.append((track.id, det))
        return assigned

    def _maybe_confirm(self, track: Track, now: float) -> None:
        if not track.confirmed and track.hits >= self.min_hits:
            track.confirmed = True
            self.total_seen += 1
            self._births.append(now)

    def flow_per_min(self, now: float | None = None) -> float:
        """Approximate vehicles per minute entering the view (rolling 60 s window)."""
        now = time.monotonic() if now is None else now
        while self._births and now - self._births[0] > 60.0:
            self._births.popleft()
        window = min(60.0, max(10.0, now - self._t0))
        return len(self._births) * 60.0 / window
