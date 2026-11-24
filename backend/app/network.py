"""Road network model: junctions, hospitals and the roads between them.

The demo network is a small fictional city. Every node has one camera. Swap
``default_network`` for your own city graph (e.g. built from OpenStreetMap) and
the rest of the system keeps working.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# 1 map unit (the dashboard draws on a 100 x 70 canvas) ~ 50 m on the ground.
KM_PER_UNIT = 0.05
WINDING_FACTOR = 1.1  # roads are rarely straight lines


@dataclass(frozen=True)
class Node:
    id: str
    name: str
    kind: str  # "junction" | "hospital"
    x: float
    y: float


@dataclass(frozen=True)
class Edge:
    a: str
    b: str
    length_km: float
    free_speed_kmh: float = 45.0

    def other(self, node_id: str) -> str:
        return self.b if node_id == self.a else self.a


class RoadNetwork:
    def __init__(self, nodes: list[Node], edges: list[Edge]):
        self.nodes: dict[str, Node] = {n.id: n for n in nodes}
        self.edges: list[Edge] = list(edges)
        self.adjacency: dict[str, list[tuple[str, Edge]]] = {nid: [] for nid in self.nodes}
        for edge in self.edges:
            if edge.a not in self.nodes or edge.b not in self.nodes:
                raise ValueError(f"edge {edge.a}-{edge.b} references an unknown node")
            self.adjacency[edge.a].append((edge.b, edge))
            self.adjacency[edge.b].append((edge.a, edge))

    def hospitals(self) -> list[Node]:
        return [n for n in self.nodes.values() if n.kind == "hospital"]

    def edge_between(self, a: str, b: str) -> Edge:
        for other, edge in self.adjacency[a]:
            if other == b:
                return edge
        raise KeyError(f"no road between {a} and {b}")

    def to_dict(self) -> dict:
        return {
            "nodes": [
                {"id": n.id, "name": n.name, "kind": n.kind, "x": n.x, "y": n.y}
                for n in self.nodes.values()
            ],
            "edges": [
                {"a": e.a, "b": e.b, "length_km": e.length_km, "free_speed_kmh": e.free_speed_kmh}
                for e in self.edges
            ],
            "canvas": {"width": 100, "height": 70},
        }


def default_network() -> RoadNetwork:
    nodes = [
        Node("J1", "Central Chowk", "junction", 12, 12),
        Node("J2", "Clock Tower", "junction", 42, 10),
        Node("J3", "Civil Lines", "junction", 74, 12),
        Node("J4", "Railway Road", "junction", 10, 38),
        Node("J5", "Market Square", "junction", 40, 36),
        Node("J6", "Bus Stand", "junction", 72, 40),
        Node("J7", "University Gate", "junction", 14, 62),
        Node("J8", "Ring Road Jn", "junction", 44, 60),
        Node("J9", "Highway Jn", "junction", 80, 62),
        Node("J10", "Old City Gate", "junction", 92, 36),
        Node("H1", "City General Hospital", "hospital", 58, 24),
        Node("H2", "Trauma Care Centre", "hospital", 26, 50),
    ]
    by_id = {n.id: n for n in nodes}
    pairs = [
        ("J1", "J2"), ("J2", "J3"), ("J1", "J4"), ("J1", "J5"), ("J2", "J5"),
        ("J3", "J6"), ("J3", "J10"), ("J4", "J5"), ("J4", "J7"), ("J5", "J6"),
        ("J5", "J8"), ("J6", "J9"), ("J6", "J10"), ("J7", "J8"), ("J8", "J9"),
        ("J9", "J10"),
        # hospital access roads
        ("H1", "J2"), ("H1", "J5"), ("H1", "J6"),
        ("H2", "J4"), ("H2", "J5"), ("H2", "J7"), ("H2", "J8"),
    ]
    edges = []
    for a, b in pairs:
        na, nb = by_id[a], by_id[b]
        dist_units = math.hypot(na.x - nb.x, na.y - nb.y)
        edges.append(Edge(a, b, round(dist_units * KM_PER_UNIT * WINDING_FACTOR, 2)))
    return RoadNetwork(nodes, edges)
