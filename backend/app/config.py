"""Runtime configuration, read from environment variables (see ``.env.example``)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: str = "") -> list[str]:
    return [part.strip() for part in os.getenv(name, default).split(",") if part.strip()]


def _static_dir() -> Path | None:
    raw = os.getenv("STATIC_DIR")
    candidates = [Path(raw)] if raw else [BASE_DIR.parent / "frontend-static", BASE_DIR / "frontend-static"]
    for c in candidates:
        if (c / "index.html").exists():
            return c
    return None


@dataclass(frozen=True)
class Settings:
    # --- vision -----------------------------------------------------------
    detector: str  # auto | yolo | motion
    yolo_model: str
    yolo_conf: float
    frame_width: int
    frame_height: int
    camera_fps: float
    lanes: int
    capacity: int  # vehicles visible in one frame at 100 % congestion
    occupancy_full: float  # fraction of the frame covered by vehicles at 100 %
    ema_alpha: float  # smoothing of the congestion score (0..1, lower = smoother)
    stale_after_s: float  # camera marked offline if no frame for this long
    # --- routing ----------------------------------------------------------
    unknown_congestion: float  # prior used for nodes with no live camera data
    # --- service ----------------------------------------------------------
    cors_origins: list[str]
    camera_config: Path
    camera_nodes: list[str]  # restrict cameras to these node ids (empty = all)
    autostart_cameras: bool
    enable_simulation_api: bool
    seed: int
    static_dir: Path | None  # folder served at /dashboard (the no-build frontend)


def load_settings() -> Settings:
    return Settings(
        detector=os.getenv("DETECTOR", "auto").strip().lower(),
        yolo_model=os.getenv("YOLO_MODEL", "yolov8n.pt"),
        yolo_conf=float(os.getenv("YOLO_CONF", "0.35")),
        frame_width=int(os.getenv("FRAME_WIDTH", "480")),
        frame_height=int(os.getenv("FRAME_HEIGHT", "270")),
        camera_fps=float(os.getenv("CAMERA_FPS", "8")),
        lanes=int(os.getenv("LANES", "3")),
        capacity=int(os.getenv("CAPACITY", "10")),
        occupancy_full=float(os.getenv("OCCUPANCY_FULL", "0.30")),
        ema_alpha=float(os.getenv("EMA_ALPHA", "0.08")),
        stale_after_s=float(os.getenv("STALE_AFTER_S", "5")),
        unknown_congestion=float(os.getenv("UNKNOWN_CONGESTION", "0.5")),
        cors_origins=_env_list("CORS_ORIGINS", "*"),
        camera_config=Path(os.getenv("CAMERA_CONFIG", str(BASE_DIR / "cameras.json"))),
        camera_nodes=_env_list("CAMERA_NODES"),
        autostart_cameras=_env_bool("AUTOSTART_CAMERAS", True),
        enable_simulation_api=_env_bool("ENABLE_SIMULATION_API", True),
        seed=int(os.getenv("SEED", "7")),
        static_dir=_static_dir(),
    )
