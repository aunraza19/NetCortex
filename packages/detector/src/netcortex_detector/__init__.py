"""Network telemetry features and TabPFN detector adapters."""

from netcortex_detector.engine import (
    DetectorConfig,
    DetectorUnavailable,
    build_features,
    detect,
    run_engine,
)
from netcortex_detector.preparation import (
    clear_prepared_detector,
    configure_detector,
    prepare_detector,
)

__all__ = [
    "DetectorConfig",
    "DetectorUnavailable",
    "build_features",
    "clear_prepared_detector",
    "configure_detector",
    "detect",
    "prepare_detector",
    "run_engine",
]
__version__ = "0.1.0"
