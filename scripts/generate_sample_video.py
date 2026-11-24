"""Render a sample street video so you can test the real-video pipeline offline.

    python scripts/generate_sample_video.py --density 0.6 --seconds 30
    # then in backend/cameras.json:  {"node_id": "J1", "source": "videos/sample_junction.mp4"}
"""
import argparse
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from app.simulator import SyntheticTrafficSource  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "backend" / "videos" / "sample_junction.mp4"))
    ap.add_argument("--density", type=float, default=0.5, help="0 (empty) .. 1 (jammed)")
    ap.add_argument("--seconds", type=int, default=30)
    ap.add_argument("--fps", type=int, default=15)
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=360)
    args = ap.parse_args()

    src = SyntheticTrafficSource(args.width, args.height, fps=args.fps, density=args.density, seed=11)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(args.out, cv2.VideoWriter_fourcc(*"mp4v"), args.fps, (args.width, args.height))
    if not writer.isOpened():
        sys.exit("could not open the video writer (mp4v codec missing?)")
    for _ in range(args.seconds * args.fps):
        writer.write(src.read())
    writer.release()
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
