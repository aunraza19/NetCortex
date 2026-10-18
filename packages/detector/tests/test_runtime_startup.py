"""Lead acceptance: initialize the real detector before entering Temporal."""

import asyncio
import importlib
import sys
from pathlib import Path
from types import ModuleType

import pytest
from netcortex_core import ModuleUnavailable


@pytest.mark.parametrize("unavailable", [False, True])
def test_worker_launcher_prepares_before_starting_worker(monkeypatch, unavailable):
    runtime = importlib.import_module("netcortex_detector.runtime")
    calls = []

    def prepare(path):
        calls.append(("prepare", path))
        if unavailable:
            raise ModuleUnavailable("invalid test artifact")

    async def run():
        calls.append(("worker", None))

    worker = ModuleType("netcortex_worker.main")
    worker.run = run
    monkeypatch.setitem(sys.modules, "netcortex_worker.main", worker)
    monkeypatch.setattr(runtime, "configure_detector", prepare)
    artifact = Path("unused-training.json")
    if unavailable:
        with pytest.raises(ModuleUnavailable):
            asyncio.run(runtime.run_worker(artifact))
        assert calls == [("prepare", artifact)]
    else:
        asyncio.run(runtime.run_worker(artifact))
        assert calls == [("prepare", artifact), ("worker", None)]
