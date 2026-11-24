import dataclasses
import time

import pytest
from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app


@pytest.fixture(scope="module")
def client():
    settings = dataclasses.replace(
        load_settings(), camera_nodes=["J1", "J2", "J5", "H1"], camera_fps=20.0, autostart_cameras=True
    )
    with TestClient(create_app(settings)) as c:
        yield c


def test_health_and_network(client):
    assert client.get("/api/health").json()["status"] == "ok"
    net = client.get("/api/network").json()
    assert len(net["nodes"]) == 12 and len(net["edges"]) >= 20


def test_route_endpoint(client):
    r = client.get("/api/route", params={"source": "J3"}).json()
    assert r["optimal"]["path"][0] == "J3" and r["optimal"]["eta_s"] > 0
    assert r["time_saved_s"] >= 0


def test_route_errors(client):
    assert client.get("/api/route", params={"source": "NOPE"}).status_code == 404
    assert client.get("/api/route", params={"source": "J1", "destination": "J1"}).status_code == 422
    assert client.get("/api/route", params={"source": "J1", "destination": "H1", "avoid": "J2,J4,J5"}).status_code == 409


def test_dispatch_validation(client):
    assert client.post("/api/dispatch", json={"origin": "H1"}).status_code == 422
    assert client.post("/api/dispatch", json={"origin": "J1", "destination": "J2"}).status_code == 422


def test_cameras_go_live_and_stream_metrics(client):
    deadline = time.time() + 25
    online = []
    while time.time() < deadline:
        online = [c for c in client.get("/api/cameras").json() if c["status"] == "online"]
        if len(online) == 4:
            break
        time.sleep(0.5)
    assert len(online) == 4, "all 4 test cameras should calibrate and go online"
    cam = online[0]
    assert cam["congestion"] is not None and cam["level"] != "unknown"
    img = client.get(f"/api/cameras/{cam['node_id']}/snapshot.jpg")
    assert img.status_code == 200 and img.content[:2] == b"\xff\xd8"
    state = client.get("/api/state").json()
    assert state["summary"]["cameras_online"] == 4


def test_offline_camera_reported_and_route_still_works(client):
    client.post("/api/simulate/camera", json={"node_id": "J2", "online": False})
    time.sleep(0.8)
    cams = {c["node_id"]: c for c in client.get("/api/cameras").json()}
    assert cams["J2"]["status"] == "offline" and cams["J2"]["congestion"] is None
    assert client.get("/api/route", params={"source": "J1"}).status_code == 200
    client.post("/api/simulate/camera", json={"node_id": "J2", "online": True})


def test_mission_runs_to_arrival_and_closure_triggers_reroute(client):
    client.post("/api/simulate/reset")
    m = client.post("/api/dispatch", json={"origin": "J1", "destination": "H1", "sim_speed": 30}).json()
    assert m["status"] == "enroute" and m["path"][0] == "J1"
    client.post("/api/closures", json={"node_id": m["path"][1]})
    deadline, final = time.time() + 40, m
    while time.time() < deadline:
        final = next(x for x in client.get("/api/missions").json() if x["id"] == m["id"])
        if final["status"] == "arrived":
            break
        time.sleep(0.5)
    assert final["status"] == "arrived" and final["destination"] == "H1"
    client.delete(f"/api/closures/{m['path'][1]}")


def test_closures_and_overrides_roundtrip(client):
    assert client.post("/api/closures", json={"node_id": "H1"}).status_code == 422
    assert client.post("/api/closures", json={"node_id": "J4"}).json() == ["J4"]
    assert "J4" in client.get("/api/route", params={"source": "J1", "destination": "H2"}).json()["closed_junctions"]
    client.post("/api/simulate/reset")
    assert client.get("/api/closures").json() == []


def test_websocket_pushes_state(client):
    with client.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
    assert {"summary", "nodes", "edges", "cameras", "missions"} <= set(msg)
