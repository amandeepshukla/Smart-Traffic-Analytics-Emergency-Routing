"""Congestion-aware routing for emergency vehicles.

Travel time on a road segment depends on the live congestion score (0..1) at
both ends, and every junction an ambulance passes through adds a delay that
grows with congestion. Dijkstra then finds the fastest *clear* route instead of
the shortest one.

Rules worth knowing:
* hospitals are destinations, never transit nodes;
* ``avoid`` lets a dispatcher close junctions (accidents, road works);
* the junction delay is charged when *leaving* an intermediate node, so the
  cost of a path never depends on which destination is being evaluated.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from typing import Iterable, Mapping

from .network import Edge, RoadNetwork

EMERGENCY_SPEED_BOOST = 1.2  # sirens + right of way
CONGESTION_SLOWDOWN = 0.75  # max share of speed lost to congestion
MIN_SPEED_FACTOR = 0.15
DEFAULT_CONGESTION = 0.5  # used when a node has no data at all


class NoRouteError(Exception):
    """Raised when no path exists with the given constraints."""


@dataclass
class Segment:
    from_id: str
    to_id: str
    length_km: float
    speed_kmh: float
    congestion: float
    travel_s: float
    junction_delay_s: float


@dataclass
class Route:
    source: str
    destination: str
    path: list[str]
    distance_km: float
    eta_s: float
    segments: list[Segment]

    def to_dict(self, network: RoadNetwork) -> dict:
        return {
            "source": self.source,
            "destination": self.destination,
            "path": self.path,
            "path_names": [network.nodes[n].name for n in self.path],
            "distance_km": round(self.distance_km, 2),
            "eta_s": round(self.eta_s, 1),
            "segments": [
                {
                    "from": s.from_id,
                    "to": s.to_id,
                    "length_km": round(s.length_km, 2),
                    "speed_kmh": round(s.speed_kmh, 1),
                    "congestion": round(s.congestion, 3),
                    "travel_s": round(s.travel_s, 1),
                    "junction_delay_s": round(s.junction_delay_s, 1),
                }
                for s in self.segments
            ],
        }


# --------------------------------------------------------------------------
# cost model
# --------------------------------------------------------------------------
def edge_congestion(cu: float, cv: float) -> float:
    """Blend of the worse and the average end of a road segment."""
    return 0.5 * max(cu, cv) + 0.5 * (cu + cv) / 2.0


def effective_speed_kmh(free_speed_kmh: float, congestion: float) -> float:
    factor = max(MIN_SPEED_FACTOR, 1.0 - CONGESTION_SLOWDOWN * congestion)
    return free_speed_kmh * EMERGENCY_SPEED_BOOST * factor


def junction_delay_s(congestion: float) -> float:
    return 2.0 + 40.0 * congestion * congestion


def _c(congestion: Mapping[str, float], node_id: str, default: float) -> float:
    return min(1.0, max(0.0, congestion.get(node_id, default)))


def _segment(
    edge: Edge, u: str, v: str, congestion: Mapping[str, float], default: float, with_delay: bool
) -> Segment:
    cu, cv = _c(congestion, u, default), _c(congestion, v, default)
    ec = edge_congestion(cu, cv)
    speed = effective_speed_kmh(edge.free_speed_kmh, ec)
    travel = edge.length_km / speed * 3600.0
    delay = junction_delay_s(cu) if with_delay else 0.0
    return Segment(u, v, edge.length_km, speed, ec, travel, delay)


# --------------------------------------------------------------------------
# core algorithm
# --------------------------------------------------------------------------
def _dijkstra(network: RoadNetwork, source: str, cost_fn, avoid: set[str]):
    dist: dict[str, float] = {source: 0.0}
    prev: dict[str, str] = {}
    heap: list[tuple[float, str]] = [(0.0, source)]
    while heap:
        d, u = heapq.heappop(heap)
        if d > dist.get(u, math.inf):
            continue
        if u != source and network.nodes[u].kind == "hospital":
            continue  # destinations only, never a shortcut
        for v, edge in network.adjacency[u]:
            if v in avoid:
                continue
            nd = d + cost_fn(u, v, edge)
            if nd < dist.get(v, math.inf):
                dist[v] = nd
                prev[v] = u
                heapq.heappush(heap, (nd, v))
    return dist, prev


def _path(prev: dict[str, str], source: str, target: str) -> list[str]:
    path = [target]
    while path[-1] != source:
        path.append(prev[path[-1]])
    path.reverse()
    return path


def evaluate_path(
    network: RoadNetwork,
    path: list[str],
    congestion: Mapping[str, float],
    default: float = DEFAULT_CONGESTION,
) -> Route:
    """Price an explicit path under the given congestion."""
    segments: list[Segment] = []
    for i in range(len(path) - 1):
        u, v = path[i], path[i + 1]
        segments.append(
            _segment(network.edge_between(u, v), u, v, congestion, default, with_delay=i > 0)
        )
    return Route(
        source=path[0],
        destination=path[-1],
        path=list(path),
        distance_km=sum(s.length_km for s in segments),
        eta_s=sum(s.travel_s + s.junction_delay_s for s in segments),
        segments=segments,
    )


def _validate(network: RoadNetwork, *ids: str | None) -> None:
    for node_id in ids:
        if node_id is not None and node_id not in network.nodes:
            raise ValueError(f"unknown node '{node_id}'")


def _time_dijkstra(network, source, congestion, avoid, default):
    def cost(u: str, v: str, edge: Edge) -> float:
        seg = _segment(edge, u, v, congestion, default, with_delay=u != source)
        return seg.travel_s + seg.junction_delay_s

    return _dijkstra(network, source, cost, avoid)


def plan_route(
    network: RoadNetwork,
    source: str,
    destination: str,
    congestion: Mapping[str, float],
    avoid: Iterable[str] = (),
    default: float = DEFAULT_CONGESTION,
) -> Route:
    """Fastest route between two nodes under current congestion."""
    _validate(network, source, destination)
    avoid_set = set(avoid) - {source}
    if source == destination:
        raise ValueError("source and destination are the same node")
    if destination in avoid_set:
        raise NoRouteError(f"destination {destination} is closed")
    dist, prev = _time_dijkstra(network, source, congestion, avoid_set, default)
    if destination not in dist:
        raise NoRouteError(f"no route from {source} to {destination}")
    return evaluate_path(network, _path(prev, source, destination), congestion, default)


def rank_hospitals(
    network: RoadNetwork,
    source: str,
    congestion: Mapping[str, float],
    avoid: Iterable[str] = (),
    default: float = DEFAULT_CONGESTION,
) -> list[Route]:
    """Routes to every reachable hospital, fastest first (single Dijkstra run)."""
    _validate(network, source)
    avoid_set = set(avoid) - {source}
    dist, prev = _time_dijkstra(network, source, congestion, avoid_set, default)
    routes = [
        evaluate_path(network, _path(prev, source, h.id), congestion, default)
        for h in network.hospitals()
        if h.id != source and h.id in dist
    ]
    routes.sort(key=lambda r: r.eta_s)
    return routes


def _shortest_distance_path(
    network: RoadNetwork, source: str, targets: list[str], avoid: set[str]
) -> list[str] | None:
    """Baseline a naive navigator would use: fewest kilometres, ignoring traffic."""
    dist, prev = _dijkstra(network, source, lambda u, v, e: e.length_km, avoid)
    reachable = [t for t in targets if t in dist]
    if not reachable:
        return None
    best = min(reachable, key=lambda t: dist[t])
    return _path(prev, source, best)


@dataclass
class EmergencyPlan:
    optimal: Route
    baseline: Route
    alternatives: list[Route]

    @property
    def time_saved_s(self) -> float:
        return max(0.0, self.baseline.eta_s - self.optimal.eta_s)


def plan_emergency_route(
    network: RoadNetwork,
    source: str,
    destination: str | None,
    congestion: Mapping[str, float],
    avoid: Iterable[str] = (),
    default: float = DEFAULT_CONGESTION,
) -> EmergencyPlan:
    """Best route to ``destination`` — or to the best hospital when it is ``None``."""
    _validate(network, source, destination)
    avoid_set = set(avoid) - {source}

    if destination is None:
        ranked = rank_hospitals(network, source, congestion, avoid_set, default)
        if not ranked:
            raise NoRouteError(f"no hospital reachable from {source}")
        optimal, alternatives = ranked[0], ranked[1:]
        targets = [r.destination for r in ranked]
    else:
        optimal = plan_route(network, source, destination, congestion, avoid_set, default)
        alternatives = []
        targets = [destination]

    base_path = _shortest_distance_path(network, source, targets, avoid_set)
    baseline = evaluate_path(network, base_path, congestion, default) if base_path else optimal
    if baseline.eta_s < optimal.eta_s:  # numerical edge case; never report a loss
        baseline = optimal
    return EmergencyPlan(optimal=optimal, baseline=baseline, alternatives=alternatives)


def refresh_route(
    network: RoadNetwork,
    previous_path: list[str] | None,
    source: str,
    destination: str | None,
    congestion: Mapping[str, float],
    avoid: Iterable[str] = (),
    default: float = DEFAULT_CONGESTION,
    switch_ratio: float = 0.92,
) -> tuple[Route, bool]:
    """Re-plan a live mission with hysteresis.

    Switching routes mid-journey is only worth it when the new route is at least
    ~8 % faster than carrying on along the current one; otherwise the route would
    flap every time two scores cross. Returns ``(route, switched)``.
    """
    avoid_set = set(avoid) - {source}
    best = plan_emergency_route(network, source, destination, congestion, avoid_set, default).optimal
    if previous_path is None:
        return best, False

    still_open = not any(n in avoid_set for n in previous_path[1:])
    if still_open:
        current = evaluate_path(network, previous_path, congestion, default)
        if best.path == previous_path or best.eta_s >= current.eta_s * switch_ratio:
            return current, False
    return best, best.path != previous_path


def edge_states(
    network: RoadNetwork, congestion: Mapping[str, float], default: float = DEFAULT_CONGESTION
) -> list[dict]:
    """Per-road congestion and speed, for colouring the map."""
    out = []
    for e in network.edges:
        seg = _segment(e, e.a, e.b, congestion, default, with_delay=False)
        out.append(
            {
                "a": e.a,
                "b": e.b,
                "congestion": round(seg.congestion, 3),
                "speed_kmh": round(seg.speed_kmh, 1),
            }
        )
    return out


def leg_segment(
    network: RoadNetwork, u: str, v: str, congestion: Mapping[str, float], default: float = DEFAULT_CONGESTION
) -> Segment:
    """Live speed/time of one road segment (no junction delay) — used to move vehicles."""
    return _segment(network.edge_between(u, v), u, v, congestion, default, with_delay=False)


def clamp_congestion(congestion: Mapping[str, float], node_id: str, default: float = DEFAULT_CONGESTION) -> float:
    return _c(congestion, node_id, default)
