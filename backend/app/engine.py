"""Engine: wires cameras, traffic scenario, road network and missions together."""
from __future__ import annotations

import logging
import threading
import time

from .config import Settings
from .cameras import CameraManager
from .missions import MissionManager
from .network import RoadNetwork, default_network
from .routing import edge_states
from .simulator import TrafficScenario
from .analytics import congestion_level

log = logging.getLogger(__name__)

TICK_S = 0.5


class Engine:
    def __init__(self, settings: Settings, network: RoadNetwork | None = None):
        self.settings = settings
        self.network = network or default_network()
        self.scenario = TrafficScenario(list(self.network.nodes), settings.seed)
        self.cameras = CameraManager(self.network, settings, self.scenario)
        self.missions = MissionManager(self.network, settings.unknown_congestion)
        self.closures: set[str] = set()
        self._halt = threading.Event()
        self._thread: threading.Thread | None = None
        self.started_at = time.time()

    # -- lifecycle -------------------------------------------------------
    def start(self) -> None:
        if self.settings.autostart_cameras:
            self.cameras.start()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="engine")
        self._thread.start()

    def stop(self) -> None:
        self._halt.set()
        self.cameras.stop()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _loop(self) -> None:
        last = time.monotonic()
        while not self._halt.wait(TICK_S):
            now = time.monotonic()
            dt, last = now - last, now
            try:
                self.scenario.tick(dt)
                self.missions.tick(dt, self.cameras.congestion_map(), self.closures)
            except Exception:  # never let one bad tick kill the simulation
                log.exception("engine tick failed")

    # -- helpers used by the API ----------------------------------------
    def congestion(self) -> dict[str, float]:
        return self.cameras.congestion_map()

    def snapshot(self) -> dict:
        net = self.network
        cams = self.cameras.snapshot()
        congestion = self.congestion()
        nodes = []
        for n in net.nodes.values():
            cam = cams.get(n.id)
            nodes.append(
                {
                    "id": n.id,
                    "name": n.name,
                    "kind": n.kind,
                    "x": n.x,
                    "y": n.y,
                    "closed": n.id in self.closures,
                    "congestion": cam["congestion"] if cam else None,
                    "level": cam["level"] if cam else "unknown",
                    "camera_status": cam["status"] if cam else "none",
                    "count": cam["count"] if cam else None,
                }
            )
        live = [c for c in cams.values() if c["congestion"] is not None]
        avg = sum(c["congestion"] for c in live) / len(live) if live else None
        missions = self.missions.snapshot()
        return {
            "ts": time.time(),
            "summary": {
                "cameras_total": len(cams),
                "cameras_online": sum(1 for c in cams.values() if c["status"] == "online"),
                "cameras_offline": sum(1 for c in cams.values() if c["status"] == "offline"),
                "avg_congestion": round(avg, 3) if avg is not None else None,
                "avg_level": congestion_level(avg),
                "vehicles_in_view": sum(c["count"] or 0 for c in cams.values()),
                "active_missions": sum(1 for m in missions if m["status"] == "enroute"),
                "closed_junctions": len(self.closures),
            },
            "nodes": nodes,
            "edges": edge_states(net, congestion, self.settings.unknown_congestion),
            "cameras": list(cams.values()),
            "missions": missions,
            "closures": sorted(self.closures),
            "overrides": self.scenario.overrides(),
        }
