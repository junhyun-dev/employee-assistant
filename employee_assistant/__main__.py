"""Command-line entry point for the loopback-only preview."""

from __future__ import annotations

import argparse

from .server import run


def main() -> None:
    parser = argparse.ArgumentParser(description="직원 업무 도우미 로컬 미리보기")
    parser.add_argument("--port", type=int, default=8767)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    run(args.port)


if __name__ == "__main__":
    main()
