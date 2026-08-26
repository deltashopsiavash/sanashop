#!/usr/bin/env python3
"""Stable SanaShop external bot entrypoint.

Keeps every v5 feature, but replaces the site HTTP transport and event polling loop
with persistent keep-alive connections, retries and failure backoff.
"""

import external_bot as core
import external_bot_plus as plus
import external_bot_v5 as v5
from bot_resilience import resilient_api, resilient_notification_loop


# All v5/plus handlers resolve core.api at runtime, so this upgrades every site
# action without duplicating the bot feature code.
core.api = resilient_api


async def notification_loop(application):
    await resilient_notification_loop(application, core, plus)


# plus.post_init resolves this global at runtime.
plus.notification_loop = notification_loop


def run():
    v5.run()


if __name__ == "__main__":
    run()
