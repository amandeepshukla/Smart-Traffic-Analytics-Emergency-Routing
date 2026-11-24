# 🚑 Smart Traffic Analytics & Emergency Routing

Urban congestion delays ambulances. This project watches street cameras, measures how busy each junction is,
and calculates the **fastest clear route** for an ambulance — re-planning live while it drives.

![Dashboard](docs/dashboard.png)

## What it does

| Layer | What happens |
| --- | --- |
| **Vision** (OpenCV) | Each camera feed is analysed frame by frame: vehicles are detected, tracked, counted per lane, and turned into a smoothed **congestion score (0–1)**. |
| **Routing** (Dijkstra) | Travel time per road depends on live congestion at both ends; every junction adds a delay that grows with congestion. Closed junctions are avoided. |
| **API** (FastAPI) | Live metrics, camera streams (MJPEG), route planning, ambulance missions and a WebSocket push feed. |
| **Dashboard** (React + Vite) | Real-time node map, camera status grid, dispatch panel, live ambulance tracking with automatic re-routing. |
| **Deploy frontend** (plain HTML/JS) | A dependency-free dashboard with the same features. Host it anywhere static, or let the backend serve it at `/dashboard`. |

Everything runs **with no cameras and no downloads** — a built-in traffic simulator renders synthetic street video, and the
real OpenCV pipeline analyses it exactly like it would analyse CCTV footage.

## Architecture

```
 camera feeds ──► CameraWorker (1 thread / junction)
 (synthetic,        │  detector (OpenCV MOG2  or  YOLO)
  video file,       │  → centroid tracker → lane density → congestion score (EMA)
  webcam, RTSP)     ▼
              congestion map ──► routing (Dijkstra, congestion-aware) ──► missions (live re-routing)
                    │                                                         │
                    └───────────────►  FastAPI  ◄─────────────────────────────┘
                                        │  REST · WebSocket /ws · MJPEG streams
                         ┌──────────────┴──────────────┐
                  React + Vite dashboard      Static dashboard (/dashboard)
```

## Quick start

### 1. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

API docs: <http://localhost:8000/docs> · Dashboard (no-build): <http://localhost:8000/dashboard/>

### 2. React dashboard (development)

```bash
cd frontend
npm install
npm run dev            # http://localhost:5173  (proxies /api and /ws to :8000)
```

### 3. Or run everything with Docker

```bash
docker compose up --build      # http://localhost:8000
```

## Try the demo

1. Open the dashboard — 12 cameras calibrate in ~5 s and the map colours roads by live congestion.
2. Pick an **incident junction**, leave destination on *Auto*, press **Dispatch**. The preview shows the ETA and how much
   faster it is than the shortest-distance route.
3. Click a junction → **Simulate jam** on the ambulance's path, or **Close junction**. Watch it **re-route**.
4. **Kill camera** shows graceful degradation: that node falls back to a neutral prior and the status turns *offline*.
5. **Reset demo** clears everything.

## Use real footage

Edit `backend/cameras.json` — one entry per junction (`source` can be a file, webcam index or stream URL):

```json
[
  { "node_id": "J1", "source": "videos/junction1.mp4" },
  { "node_id": "J2", "source": "rtsp://user:pass@192.168.1.20/stream1" },
  { "node_id": "J3", "source": "0" },
  { "node_id": "J4", "source": "synthetic" }
]
```

No footage handy? `python scripts/generate_sample_video.py --density 0.6` renders a test video.

**Detectors**

| `DETECTOR` | When | Notes |
| --- | --- | --- |
| `motion` | default for synthetic video | OpenCV MOG2 background subtraction. Needs a fixed camera; parked vehicles slowly fade into the background. |
| `yolo` | recommended for real streets | `pip install -r requirements-yolo.txt` — YOLOv8 restricted to car / motorcycle / bus / truck. |
| `auto` *(default)* | — | YOLO for real sources if installed, otherwise OpenCV motion. |

Tune `CAPACITY` (vehicles in frame = 100 % congestion) and `LANES` per camera view. See `backend/.env.example`.

## How the congestion score works

```
count_ratio     = vehicles / CAPACITY
occupancy_ratio = (vehicle pixel area / frame area) / OCCUPANCY_FULL
raw             = 0.6 · count_ratio + 0.4 · occupancy_ratio
congestion      = EMA(raw)            # smoothed so the route doesn't flap
level           = free < 0.30 ≤ moderate < 0.60 ≤ heavy < 0.85 ≤ gridlock
```

## How routing works

* **Road speed** = free speed × 1.2 (siren) × max(0.15, 1 − 0.75 · congestion), using a blend of the worse and the mean
  congestion at both ends of the road.
* **Junction delay** = 2 s + 40 s · congestion² each time the ambulance passes through a junction.
* Hospitals are destinations only — never shortcuts. With no destination the planner picks the **fastest hospital**.
* Nodes without a healthy camera use a neutral prior (`UNKNOWN_CONGESTION`, 0.5) so routing keeps working.
* **Live re-planning**: at every junction the vehicle re-plans from where it is; while driving a road it keeps re-planning the
  rest of the route. A new route is adopted only if it is ≥ 8 % faster (hysteresis), or the old one is blocked.
* Every plan is compared with the **shortest-distance baseline** (what a traffic-blind navigator would do) to show time saved.

## API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/api/state` | Everything the dashboard needs (nodes, edges, cameras, missions) |
| WS | `/ws` | Same payload pushed every second |
| GET | `/api/traffic` · `/api/cameras` · `/api/cameras/{id}` | Metrics per junction / camera |
| GET | `/api/cameras/{id}/stream` · `/snapshot.jpg` | Annotated MJPEG stream / single frame |
| GET | `/api/route?source=J3&destination=H1&avoid=J5` | Optimal route, baseline, alternatives, time saved |
| POST | `/api/dispatch` `{origin, destination?, sim_speed}` | Start a live ambulance mission |
| GET / DELETE | `/api/missions` · `/api/missions/{id}` | List / remove missions |
| GET / POST / DELETE | `/api/closures` | Close or reopen junctions |
| POST | `/api/simulate/congestion` · `/camera` · `/reset` | Demo controls (disable with `ENABLE_SIMULATION_API=false`) |

## Deployment

The backend needs a **long-running server** (it runs camera threads) — use Docker, Render, Railway, Fly.io or a VPS.
**Do not** put the backend on Vercel/Netlify functions.

| Goal | How |
| --- | --- |
| **Everything on one URL** (easiest) | Deploy the Docker image (`render.yaml` is included → Render: *New → Blueprint*). Dashboard at `/dashboard/`. |
| **Backend on Render/Railway + frontend on Vercel/Netlify** | 1. Deploy the backend. 2. Deploy `frontend/` (React) with env var `VITE_API_URL=https://your-api`, **or** deploy `frontend-static/` as-is after setting `API_URL` in `frontend-static/config.js`. 3. Set `CORS_ORIGINS` on the backend to your frontend URL. |
| **GitHub Pages** | Publish `frontend-static/` and set `API_URL` in `config.js` (the API must be `https://`). |

`vercel.json` / `netlify.toml` are included for the React app. On free tiers CPU is tiny — lower `CAMERA_FPS`
and set `CAMERA_NODES=J1,J2,J5,H1` to run only a few cameras.

## Tests

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest -q          # 30 tests: routing, detector accuracy, API, mission re-routing, video pipeline
```

## Project structure

```
backend/
  app/
    detector.py    OpenCV MOG2 + YOLO detectors
    tracker.py     centroid tracker, flow estimate
    analytics.py   lane density, congestion score, frame annotation
    simulator.py   synthetic street video + traffic scenario
    cameras.py     per-camera worker threads, video/RTSP sources
    network.py     road graph (demo city — replace with your own)
    routing.py     congestion-aware Dijkstra, baseline, hysteresis
    missions.py    live ambulance simulation + re-planning
    engine.py      wires everything together
    main.py        FastAPI app
  tests/ · cameras.json · Dockerfile · requirements*.txt
frontend/          React + Vite dashboard
frontend-static/   dependency-free dashboard for static hosting
scripts/           sample video generator
docs/ · render.yaml · docker-compose.yml · .github/workflows/ci.yml
```

## Limitations & ideas

* Ambulance movement is **simulated**; plug real GPS pings into `MissionManager.tick` for live vehicles.
* The demo road graph is fictional. Build yours from OpenStreetMap (`osmnx`) and map each camera to a node in `cameras.json`.
* OpenCV motion detection is a lightweight default; use YOLO for dense, real-world scenes.
* Ideas: signal pre-emption (green corridor), historical congestion forecasting, multi-camera per junction, auth on dispatch.

## License

MIT — see [LICENSE](LICENSE).
#   S m a r t - T r a f f i c - A n a l y t i c s - E m e r g e n c y - R o u t i n g  
 