"""Live ambulance missions.

A mission is *simulated* movement of an emergency vehicle along a planned route.
In production you would replace ``tick`` with real GPS pings; the planning,
re-routing and ETA logic stays the same.

Behaviour:
* at every junction the vehicle re-plans from where it actually is;
* while driving a road it keeps re-planning the rest of the route (the road it
  is already on is committed), so a newly jammed or closed junction ahead is
  avoided as soon as it appears — with 8 % hysteresis so the route doesn't flap;
* each intermediate junction costs a wait that grows with its congestion.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Iterable, Mapping

from .network import RoadNetwork
from .routing import (
    NoRouteError,
    clamp_congestion,
    evaluate_path,
    junction_delay_s,
    leg_segment,
    plan_emergency_route,
    refresh_route,
)

MAX_ACTIVE = 5
KEEP_FINISHED_S = 45.0
MAX_EVENTS = 25


@dataclass
class Mission:
    id: str
    origin: str
    destination: str | None
    sim_speed: float
    path: list[str]  # path[0] = last junction passed, path[1] = junction being driven to
    baseline_path: list[str]
    baseline_eta_s: float
    initial_eta_s: float
    created_at: float = field(default_factory=time.time)
    leg_km: float = 0.0
    wait_s: float = 0.0
    status: str = "enroute"  # enroute | arrived
    eta_s: float = 0.0
    remaining_km: float = 0.0
    elapsed_s: float = 0.0  # simulated seconds since dispatch
    reroutes: int = 0
    finished_at: float | None = None
    trail: list[str] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)

    @property
    def target(self) -> str:
        return self.path[-1]

    @property
    def time_saved_s(self) -> float:
        return max(0.0, self.baseline_eta_s - self.initial_eta_s)


class MissionManager:
    def __init__(self, network: RoadNetwork, default_congestion: float):
        self.network = network
        self.default = default_congestion
        self._lock = threading.RLock()
        self._missions: dict[str, Mission] = {}

    # -- commands --------------------------------------------------------
    def create(
        self,
        origin: str,
        destination: str | None,
        sim_speed: float,
        congestion: Mapping[str, float],
        avoid: Iterable[str],
    ) -> Mission:
        net = self.network
        if origin not in net.nodes or net.nodes[origin].kind != "junction":
            raise ValueError("origin must be a junction id (e.g. J3)")
        if destination is not None and (destination not in net.nodes or net.nodes[destination].kind != "hospital"):
            raise ValueError("destination must be a hospital id (e.g. H1) or empty for the best hospital")
        with self._lock:
            if sum(1 for m in self._missions.values() if m.status == "enroute") >= MAX_ACTIVE:
                raise RuntimeError(f"at most {MAX_ACTIVE} missions can be active at once")
            plan = plan_emergency_route(net, origin, destination, congestion, avoid, self.default)
            m = Mission(
                id=uuid.uuid4().hex[:8],
                origin=origin,
                destination=destination,
                sim_speed=sim_speed,
                path=list(plan.optimal.path),
                baseline_path=list(plan.baseline.path),
                baseline_eta_s=plan.baseline.eta_s,
                initial_eta_s=plan.optimal.eta_s,
                trail=[origin],
            )
            self._log(m, f"Dispatched from {net.nodes[origin].name} to {net.nodes[m.target].name}")
            self._update_metrics(m, congestion)
            self._missions[m.id] = m
            return m

    def cancel(self, mission_id: str) -> bool:
        with self._lock:
            return self._missions.pop(mission_id, None) is not None

    def clear(self) -> None:
        with self._lock:
            self._missions.clear()

    # -- simulation ------------------------------------------------------
    def tick(self, dt: float, congestion: Mapping[str, float], avoid: Iterable[str]) -> None:
        avoid_set = set(avoid)
        now = time.time()
        with self._lock:
            for mid in [k for k, m in self._missions.items() if m.finished_at and now - m.finished_at > KEEP_FINISHED_S]:
                del self._missions[mid]
            for m in self._missions.values():
                if m.status != "enroute":
                    continue
                budget = dt * m.sim_speed
                m.elapsed_s += budget
                self._advance(m, budget, congestion, avoid_set)
                if m.status == "enroute":
                    self._replan(m, congestion, avoid_set, at_node=False)
                self._update_metrics(m, congestion)

    def _advance(self, m: Mission, budget: float, congestion, avoid: set[str]) -> None:
        net = self.network
        while budget > 1e-9 and m.status == "enroute":
            if m.wait_s > 0:
                used = min(m.wait_s, budget)
                m.wait_s -= used
                budget -= used
                continue
            u, v = m.path[0], m.path[1]
            edge = net.edge_between(u, v)
            seg = leg_segment(net, u, v, congestion, self.default)
            need = (edge.length_km - m.leg_km) / seg.speed_kmh * 3600.0
            if budget < need:
                m.leg_km += seg.speed_kmh * budget / 3600.0
                return
            budget -= need
            m.leg_km = 0.0
            m.path = m.path[1:]
            m.trail.append(m.path[0])
            if len(m.path) == 1:
                m.status = "arrived"
                m.finished_at = time.time()
                m.eta_s = 0.0
                m.remaining_km = 0.0
                self._log(m, f"Arrived at {net.nodes[m.path[0]].name}")
                return
            m.wait_s = junction_delay_s(clamp_congestion(congestion, m.path[0], self.default))
            self._replan(m, congestion, avoid, at_node=True)

    def _replan(self, m: Mission, congestion, avoid: set[str], at_node: bool) -> None:
        net = self.network
        if at_node:
            source, previous, head = m.path[0], m.path, []
        else:
            if len(m.path) < 3:  # next node is the hospital itself: nothing left to decide
                return
            source, previous, head = m.path[1], m.path[1:], [m.path[0]]
        try:
            route, switched = refresh_route(net, previous, source, m.destination, congestion, avoid, self.default)
        except NoRouteError:
            if not any("blocked" in e["msg"] for e in m.events[-1:]):
                self._log(m, "All routes blocked — holding course")
            return
        if switched:
            m.path = head + route.path
            m.reroutes += 1
            via = " → ".join(net.nodes[n].name for n in route.path[:4])
            self._log(m, f"Rerouted: {via}{' …' if len(route.path) > 4 else ''}")

    def _update_metrics(self, m: Mission, congestion) -> None:
        if m.status != "enroute":
            return
        net = self.network
        u, v = m.path[0], m.path[1]
        edge = net.edge_between(u, v)
        seg = leg_segment(net, u, v, congestion, self.default)
        leg_left_km = max(0.0, edge.length_km - m.leg_km)
        eta = m.wait_s + leg_left_km / seg.speed_kmh * 3600.0
        dist = leg_left_km
        if len(m.path) > 2:
            tail = evaluate_path(net, m.path[1:], congestion, self.default)
            eta += junction_delay_s(clamp_congestion(congestion, v, self.default)) if m.wait_s == 0 and m.leg_km > 0 else 0.0
            eta += tail.eta_s
            dist += tail.distance_km
        m.eta_s, m.remaining_km = eta, dist

    def _log(self, m: Mission, msg: str) -> None:
        m.events.append({"t": round(m.elapsed_s, 1), "msg": msg})
        del m.events[:-MAX_EVENTS]

    # -- views -----------------------------------------------------------
    def _position(self, m: Mission) -> dict:
        a = self.network.nodes[m.path[0]]
        if len(m.path) < 2:
            return {"x": a.x, "y": a.y}
        b = self.network.nodes[m.path[1]]
        frac = min(1.0, m.leg_km / max(1e-6, self.network.edge_between(a.id, b.id).length_km))
        return {"x": round(a.x + (b.x - a.x) * frac, 2), "y": round(a.y + (b.y - a.y) * frac, 2)}

    def snapshot(self) -> list[dict]:
        net = self.network
        with self._lock:
            out = []
            for m in self._missions.values():
                out.append(
                    {
                        "id": m.id,
                        "status": m.status,
                        "origin": m.origin,
                        "destination": m.target,
                        "destination_name": net.nodes[m.target].name,
                        "auto_destination": m.destination is None,
                        "path": list(m.path),
                        "trail": list(m.trail),
                        "baseline_path": list(m.baseline_path),
                        "position": self._position(m),
                        "eta_s": round(m.eta_s, 1),
                        "remaining_km": round(m.remaining_km, 2),
                        "initial_eta_s": round(m.initial_eta_s, 1),
                        "baseline_eta_s": round(m.baseline_eta_s, 1),
                        "time_saved_s": round(m.time_saved_s, 1),
                        "elapsed_s": round(m.elapsed_s, 1),
                        "waiting_s": round(m.wait_s, 1),
                        "reroutes": m.reroutes,
                        "sim_speed": m.sim_speed,
                        "events": list(m.events[-6:]),
                    }
                )
            return out
