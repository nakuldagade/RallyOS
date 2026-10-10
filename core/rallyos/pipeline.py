"""End-to-end pipeline (Analyzer). Each stage writes its output to disk so a crash keeps partial results.

Usage (once implemented):
    python -m rallyos.pipeline <clip.mp4> --device auto --out demo/out/<clip>/
"""

from __future__ import annotations

import argparse

from rallyos.device import get_device


class Analyzer:
    def __init__(self, sport: str = "auto", device: str | None = None):
        self.sport = sport
        self.device = get_device(device)

    def run(self, video_path: str):
        raise NotImplementedError("pipeline stages land in §12 hours 1-8")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="rallyos.pipeline")
    ap.add_argument("video")
    ap.add_argument("--sport", default="auto")
    ap.add_argument("--device", default=None, choices=["auto", "cpu", "cuda"])
    ap.add_argument("--out", default=None)
    ap.add_argument("--max-width", type=int, default=None)
    args = ap.parse_args(argv)
    Analyzer(sport=args.sport, device=args.device).run(args.video)


if __name__ == "__main__":
    main()
