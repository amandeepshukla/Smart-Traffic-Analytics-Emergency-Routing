import pytest

from app.network import default_network
from app.routing import (
    NoRouteError, effective_speed_kmh, plan_emergency_route, plan_route, rank_hospitals, refresh_route,
)

NET = default_network()
CLEAR = {n: 0.1 for n in NET.nodes}


def test_route_exists_and_ends_at_hospital():
    plan = plan_emergency_route(NET, "J3", None, CLEAR)
    assert plan.optimal.path[0] == "J3"
    assert NET.nodes[plan.optimal.path[-1]].kind == "hospital"
    assert plan.optimal.eta_s > 0


def test_hospitals_are_never_transit_nodes():
    for src in ["J1", "J3", "J9", "J10"]:
        for r in rank_hospitals(NET, src, CLEAR):
            assert all(NET.nodes[n].kind == "junction" for n in r.path[:-1])


def test_congestion_makes_trip_slower():
    base = plan_route(NET, "J1", "H1", CLEAR).eta_s
    jam = plan_route(NET, "J1", "H1", {n: 0.9 for n in NET.nodes}).eta_s
    assert jam > base * 1.5


def test_route_avoids_jammed_junction():
    clear = plan_route(NET, "J1", "H1", CLEAR)
    mid = [n for n in clear.path[1:-1]]
    assert mid, "expected at least one intermediate junction"
    jam = dict(CLEAR)
    jam[mid[0]] = 1.0
    rerouted = plan_route(NET, "J1", "H1", jam)
    assert mid[0] not in rerouted.path or rerouted.eta_s >= clear.eta_s


def test_closed_junction_is_never_used():
    plan = plan_route(NET, "J1", "H1", CLEAR, avoid={"J2", "J5"})
    assert "J2" not in plan.path and "J5" not in plan.path


def test_no_route_when_all_neighbours_closed():
    with pytest.raises(NoRouteError):
        plan_route(NET, "J1", "H1", CLEAR, avoid={"J2", "J4", "J5"})


def test_unknown_node_rejected():
    with pytest.raises(ValueError):
        plan_route(NET, "J1", "ZZ", CLEAR)


def test_optimal_never_slower_than_baseline():
    import random
    rng = random.Random(1)
    for _ in range(40):
        cong = {n: rng.random() for n in NET.nodes}
        src = rng.choice([f"J{i}" for i in range(1, 11)])
        plan = plan_emergency_route(NET, src, None, cong)
        assert plan.optimal.eta_s <= plan.baseline.eta_s + 1e-6
        assert plan.time_saved_s >= 0


def test_best_hospital_is_fastest_of_ranked():
    ranked = rank_hospitals(NET, "J7", CLEAR)
    assert ranked == sorted(ranked, key=lambda r: r.eta_s)


def test_missing_data_uses_prior():
    with_prior = plan_route(NET, "J1", "H1", {}, default=0.5).eta_s
    explicit = plan_route(NET, "J1", "H1", {n: 0.5 for n in NET.nodes}).eta_s
    assert with_prior == pytest.approx(explicit)


def test_speed_drops_with_congestion():
    assert effective_speed_kmh(45, 0.0) > effective_speed_kmh(45, 0.5) > effective_speed_kmh(45, 1.0) > 0


def test_refresh_route_hysteresis_and_forced_switch():
    first = plan_emergency_route(NET, "J1", "H1", CLEAR).optimal
    route, switched = refresh_route(NET, first.path, "J1", "H1", CLEAR)
    assert not switched and route.path == first.path
    # close a junction on the current path -> must switch
    blocked = first.path[1]
    route2, switched2 = refresh_route(NET, first.path, "J1", "H1", CLEAR, avoid={blocked})
    assert switched2 and blocked not in route2.path
