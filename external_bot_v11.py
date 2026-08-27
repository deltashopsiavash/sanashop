#!/usr/bin/env python3
import logging

from bot_single_instance import acquire_single_instance_lock
import external_bot_v10 as v10

logger = logging.getLogger(__name__)


def run():
    try:
        acquire_single_instance_lock()
    except RuntimeError as exc:
        logger.error("SanaShop bot refused duplicate startup: %s", exc)
        raise SystemExit(73) from exc
    v10.run()


if __name__ == "__main__":
    run()
