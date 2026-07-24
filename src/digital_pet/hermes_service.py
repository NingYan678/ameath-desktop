from __future__ import annotations

import argparse
import sys

from .config import load_settings
from .hermes_bridge import LocalHermesBridge


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage the persistent local Hermes service.")
    parser.add_argument("action", choices=("start", "status", "stop"))
    args = parser.parse_args()
    bridge = LocalHermesBridge(load_settings())
    if args.action == "stop":
        bridge.stop_service()
        print("Hermes background service stop requested.")
        return 0
    ready = bridge.wait_until_ready()
    if args.action == "status":
        print("Hermes background service: " + ("ready" if ready else "unavailable"))
        return 0 if ready else 1
    print("Hermes background service: " + ("ready" if ready else "failed to start"))
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
