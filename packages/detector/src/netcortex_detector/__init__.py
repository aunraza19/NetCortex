"""Network telemetry features and TabPFN detector adapters."""

from netcortex_detector.engine import (
    DetectorConfig,
    DetectorUnavailable,
    build_features,
    detect,
    run_engine,
)

__all__ = ["DetectorConfig", "DetectorUnavailable", "build_features", "detect", "run_engine"]
__version__ = "0.1.0"
