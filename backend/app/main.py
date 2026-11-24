"""FastAPI application: live metrics, routing, missions, camera streams, websocket."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import cv2
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .config import Settings, load_settings
from .engine import Engine
from .routing import NoRouteError, plan_emergency_route

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

BOUNDARY = "frame"


class DispatchRequest(BaseModel):
    origin: str = Field(..., examples=["J3"], description="Junction where the incident is")
    destination: str | None = Field(None, examples=["H1"], description="Hospital id; omit for the best hospital")
    sim_speed: float = Field(6.0, ge=1.0, le=30.0, description="Simulation speed-up so demos finish quickly")


class ClosureRequest(BaseModel):
    node_id: str


class CongestionOverride(BaseModel):
    node_id: str
    level: float | None = Field(None, ge=0.0, le=1.0, description="0..1, or null to clear")


class CameraToggle(BaseModel):
    node_id: str
    online: bool


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = Engine(settings)
        engine.start()
        app.state.engine = engine
        yield
        engine.stop()

    app = FastAPI(
        title="Smart Traffic Analytics & Emergency Routing",
        version=__version__,
        description="Real-time vehicle counting (OpenCV) + congestion-aware ambulance routing.",
        lifespan=lifespan,
    )
    wildcard = "*" in settings.cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if wildcard else settings.cors_origins,
        allow_credentials=not wildcard,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def eng(request: Request) -> Engine:
        return request.app.state.engine

    def known_node(engine: Engine, node_id: str) -> None:
        if node_id not in engine.network.nodes:
            raise HTTPException(404, f"unknown node '{node_id}'")

    # ------------------------------------------------------------------ meta
    @app.get("/api/health")
    def health(request: Request):
        engine = eng(request)
        snap = engine.cameras.snapshot()
        return {
            "status": "ok",
            "version": __version__,
            "cameras_online": sum(1 for c in snap.values() if c["status"] == "online"),
            "cameras_total": len(snap),
            "uptime_s": round(__import__("time").time() - engine.started_at, 1),
        }

    @app.get("/api/network")
    def network(request: Request):
        return eng(request).network.to_dict()

    @app.get("/api/state")
    def state(request: Request):
        """Everything the dashboard needs in one call (HTTP alternative to the websocket)."""
        return eng(request).snapshot()

    @app.get("/api/traffic")
    def traffic(request: Request):
        snap = eng(request).snapshot()
        return {"ts": snap["ts"], "summary": snap["summary"], "nodes": snap["nodes"], "edges": snap["edges"]}

    # --------------------------------------------------------------- cameras
    @app.get("/api/cameras")
    def cameras(request: Request):
        return list(eng(request).cameras.snapshot().values())

    @app.get("/api/cameras/{node_id}")
    def camera(request: Request, node_id: str):
        engine = eng(request)
        known_node(engine, node_id)
        return engine.cameras.get(node_id).snapshot()

    @app.get("/api/cameras/{node_id}/snapshot.jpg")
    def camera_snapshot(request: Request, node_id: str):
        engine = eng(request)
        known_node(engine, node_id)
        jpeg = engine.cameras.get(node_id).jpeg
        if jpeg is None:
            raise HTTPException(503, "camera has not produced a frame yet")
        return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.get("/api/cameras/{node_id}/stream")
    async def camera_stream(request: Request, node_id: str):
        """MJPEG stream — drop it straight into an <img src=...> tag."""
        engine = eng(request)
        known_node(engine, node_id)
        worker = engine.cameras.get(node_id)
        delay = 1.0 / max(1.0, settings.camera_fps)

        async def frames():
            last_seq = -1
            while True:
                if await request.is_disconnected():
                    break
                jpeg, seq = worker.jpeg, worker.seq
                if jpeg is not None and seq != last_seq:
                    last_seq = seq
                    yield (
                        b"--" + BOUNDARY.encode() + b"\r\nContent-Type: image/jpeg\r\n"
                        b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n"
                    )
                await asyncio.sleep(delay / 2)

        return StreamingResponse(
            frames(),
            media_type=f"multipart/x-mixed-replace; boundary={BOUNDARY}",
            headers={"Cache-Control": "no-store"},
        )

    # --------------------------------------------------------------- routing
    @app.get("/api/route")
    def route(
        request: Request,
        source: str = Query(..., description="Start junction, e.g. J3"),
        destination: str | None = Query(None, description="Hospital id, or omit for the best hospital"),
        avoid: str = Query("", description="Comma-separated junction ids to avoid"),
    ):
        engine = eng(request)
        known_node(engine, source)
        if destination:
            known_node(engine, destination)
        avoid_set = {a.strip() for a in avoid.split(",") if a.strip()} | engine.closures
        try:
            plan = plan_emergency_route(
                engine.network, source, destination or None, engine.congestion(), avoid_set, settings.unknown_congestion
            )
        except NoRouteError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        net = engine.network
        return {
            "optimal": plan.optimal.to_dict(net),
            "baseline": plan.baseline.to_dict(net),
            "alternatives": [r.to_dict(net) for r in plan.alternatives],
            "time_saved_s": round(plan.time_saved_s, 1),
            "nodes_with_live_data": len(engine.congestion()),
            "closed_junctions": sorted(avoid_set & set(net.nodes)),
        }

    # -------------------------------------------------------------- missions
    @app.get("/api/missions")
    def missions(request: Request):
        return eng(request).missions.snapshot()

    @app.post("/api/dispatch", status_code=201)
    def dispatch(request: Request, body: DispatchRequest):
        engine = eng(request)
        try:
            mission = engine.missions.create(
                body.origin, body.destination, body.sim_speed, engine.congestion(), engine.closures
            )
        except NoRouteError as exc:
            raise HTTPException(409, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(429, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return next(m for m in engine.missions.snapshot() if m["id"] == mission.id)

    @app.delete("/api/missions/{mission_id}")
    def cancel_mission(request: Request, mission_id: str):
        if not eng(request).missions.cancel(mission_id):
            raise HTTPException(404, "mission not found")
        return {"cancelled": mission_id}

    # -------------------------------------------------------------- closures
    @app.get("/api/closures")
    def closures(request: Request):
        return sorted(eng(request).closures)

    @app.post("/api/closures", status_code=201)
    def close_junction(request: Request, body: ClosureRequest):
        engine = eng(request)
        known_node(engine, body.node_id)
        if engine.network.nodes[body.node_id].kind == "hospital":
            raise HTTPException(422, "hospitals cannot be closed")
        engine.closures.add(body.node_id)
        return sorted(engine.closures)

    @app.delete("/api/closures/{node_id}")
    def reopen_junction(request: Request, node_id: str):
        engine = eng(request)
        engine.closures.discard(node_id)
        return sorted(engine.closures)

    # ------------------------------------------------------------ simulation
    if settings.enable_simulation_api:

        @app.post("/api/simulate/congestion")
        def simulate_congestion(request: Request, body: CongestionOverride):
            engine = eng(request)
            known_node(engine, body.node_id)
            engine.scenario.set_override(body.node_id, body.level)
            return {"overrides": engine.scenario.overrides()}

        @app.post("/api/simulate/camera")
        def simulate_camera(request: Request, body: CameraToggle):
            engine = eng(request)
            known_node(engine, body.node_id)
            engine.cameras.set_forced_offline(body.node_id, not body.online)
            return engine.cameras.get(body.node_id).snapshot()

        @app.post("/api/simulate/reset")
        def simulate_reset(request: Request):
            engine = eng(request)
            engine.scenario.reset()
            engine.closures.clear()
            engine.missions.clear()
            for worker in engine.cameras.workers.values():
                worker.forced_offline = False
            return {"reset": True}

    # ------------------------------------------------------------- websocket
    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        engine: Engine = websocket.app.state.engine
        try:
            while True:
                await websocket.send_json(engine.snapshot())
                await asyncio.sleep(1.0)
        except (WebSocketDisconnect, RuntimeError):
            pass

    if settings.static_dir:
        app.mount("/dashboard", StaticFiles(directory=settings.static_dir, html=True), name="dashboard")

    @app.get("/")
    def root():
        if settings.static_dir:
            return RedirectResponse("/dashboard/")
        return {
            "name": "Smart Traffic Analytics & Emergency Routing",
            "version": __version__,
            "docs": "/docs",
            "endpoints": ["/api/state", "/api/route", "/api/dispatch", "/api/cameras", "/ws"],
        }

    return app


app = create_app()
