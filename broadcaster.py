#!/usr/bin/env python3
# broadcaster.py — small helper to fan-out key sequences

import logging

logger = logging.getLogger(__name__)


class Broadcaster:
    def __init__(self, x11_module, enabled: bool = False):
        self.x11 = x11_module
        self._enabled = bool(enabled)

    def set_enabled(self, enabled: bool):
        self._enabled = bool(enabled)

    def broadcast(self, seq: str, targets, exclude=None):
        if not self._enabled:
            return
        for wid in targets:
            if exclude and wid == exclude:
                continue
            try:
                self.x11.send_key_to_window(wid, seq)
            except Exception:
                logger.exception("broadcast send failed to %s", wid)
