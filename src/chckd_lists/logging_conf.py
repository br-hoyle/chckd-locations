"""Stdlib logging, configured once. Console gets human-readable lines; a
rotating file under logs/ keeps history across runs. No structlog/loguru —
this is a small pipeline, stdlib logging is enough and one less dependency.
"""

import logging
import logging.handlers

from chckd_lists.config import LOGS_DIR

_CONFIGURED = False


def setup_logging(level: int = logging.INFO) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")

    console = logging.StreamHandler()
    console.setFormatter(fmt)

    file_handler = logging.handlers.RotatingFileHandler(
        LOGS_DIR / "pipeline.log", maxBytes=2_000_000, backupCount=5
    )
    file_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(console)
    root.addHandler(file_handler)

    _CONFIGURED = True
