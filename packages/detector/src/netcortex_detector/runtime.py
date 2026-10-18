"""Configured startup path for the Temporal worker process."""

from __future__ import annotations

import asyncio
import importlib
import logging
from pathlib import Path
from typing import Any

from netcortex_detector.preparation import configure_detector


async def run_worker(artifact: Path) -> Any:
    """Configure the real detector, then lazily enter the unchanged worker."""
    await asyncio.to_thread(configure_detector, Path(artifact))
    worker = importlib.import_module("netcortex_worker.main")
    return await worker.run()


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Start the NetCortex worker with a prepared detector"
    )
    parser.add_argument("--artifact", type=Path, required=True, help="prepared detector JSON")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        asyncio.run(run_worker(args.artifact))
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        logging.getLogger(__name__).error(
            "detector worker failed (%s)", type(exc).__name__
        )
        return 1
    return 0
