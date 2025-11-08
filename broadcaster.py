#!/usr/bin/env python3
# broadcaster.py — helper to fan-out key sequences / typed chars, with 2 modes:
#   - "background": use xdotool --window (may be ignored by some apps)
#   - "focus_sweep": briefly focus each window, inject, then restore focus (reliable)

import subprocess
import time
import logging

import x11_utils  # used for focusing/restoring and fetching titles

logger = logging.getLogger(__name__)


class Broadcaster:
    def __init__(self, x11_module, enabled: bool = False, mode: str = "focus_sweep"):
        """
        mode: "background" or "focus_sweep"
        """
        self.x11 = x11_module
        self._enabled = bool(enabled)
        self._mode = mode if mode in ("background", "focus_sweep") else "focus_sweep"

        # Tunables for focus-sweep
        self._focus_settle_ms = 10   # tiny wait after focusing a window
        self._restore_settle_ms = 6  # tiny wait after restoring original focus

    # ---- external control ----
    def set_enabled(self, enabled: bool):
        self._enabled = bool(enabled)

    def set_mode(self, mode: str):
        self._mode = mode if mode in ("background", "focus_sweep") else self._mode

    def is_focus_sweep(self) -> bool:
        return self._mode == "focus_sweep"

    # ---- public API used by CoreController ----
    def send_key(self, seq: str, targets, exclude=None):
        if not self._enabled or not seq:
            return
        if self._mode == "background":
            self._send_key_background(seq, targets, exclude)
        else:
            self._send_key_focus_sweep(seq, targets, exclude)

    def send_literal(self, ch: str, targets, exclude=None):
        if not self._enabled or not ch:
            return
        if self._mode == "background":
            self._send_literal_background(ch, targets, exclude)
        else:
            self._send_literal_focus_sweep(ch, targets, exclude)

    # ---------- BACKEND: background (per-window) ----------
    def _send_key_background(self, seq, targets, exclude):
        wmap = self._wm_titles_safe()
        for wid in targets:
            if exclude and wid == exclude:
                continue
            title = wmap.get(str(wid), ("", "", "", "", "", "", ""))[-1]
            try:
                logger.debug("SEND KEY (background) -> win=%s title=%r seq=%r", wid, title, seq)
                self.x11.send_key_to_window(wid, seq)
            except Exception:
                logger.exception("KEY background failed to %s (%r)", wid, title)

    def _send_literal_background(self, ch, targets, exclude):
        wmap = self._wm_titles_safe()
        for wid in targets:
            if exclude and wid == exclude:
                continue
            title = wmap.get(str(wid), ("", "", "", "", "", "", ""))[-1]
            try:
                logger.debug("SEND TYPE (background) -> win=%s title=%r char=%r", wid, title, ch)
                subprocess.run(
                    ["xdotool", "type", "--window", str(wid), "--clearmodifiers", "--delay", "0", "--", ch],
                    check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            except Exception:
                logger.exception("TYPE background failed to %s (%r)", wid, title)

    # ---------- BACKEND: focus-sweep (reliable) ----------
    def _send_key_focus_sweep(self, seq, targets, exclude):
        active = self._get_active_safe()
        wmap = self._wm_titles_safe()
        try:
            for wid in targets:
                if exclude and wid == exclude:
                    continue
                title = wmap.get(str(wid), ("", "", "", "", "", "", ""))[-1]
                logger.debug("SEND KEY (focus_sweep) -> focus=%s title=%r seq=%r", wid, title, seq)
                self._focus(wid)
                self._settle(self._focus_settle_ms)
                subprocess.run(
                    ["xdotool", "key", "--clearmodifiers", "--delay", "0", "--", seq],
                    check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
        finally:
            if active:
                self._focus(active)
                self._settle(self._restore_settle_ms)

    def _send_literal_focus_sweep(self, ch, targets, exclude):
        active = self._get_active_safe()
        wmap = self._wm_titles_safe()
        try:
            for wid in targets:
                if exclude and wid == exclude:
                    continue
                title = wmap.get(str(wid), ("", "", "", "", "", "", ""))[-1]
                logger.debug("SEND TYPE (focus_sweep) -> focus=%s title=%r char=%r", wid, title, ch)
                self._focus(wid)
                self._settle(self._focus_settle_ms)
                subprocess.run(
                    ["xdotool", "type", "--clearmodifiers", "--delay", "0", "--", ch],
                    check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
        finally:
            if active:
                self._focus(active)
                self._settle(self._restore_settle_ms)

    # ---------- utils ----------
    def _focus(self, wid):
        try:
            self.x11.activate_window(wid)
        except Exception:
            logger.exception("activate_window failed for %s", wid)

    def _get_active_safe(self):
        try:
            return self.x11.get_active_window()
        except Exception:
            return None

    def _wm_titles_safe(self):
        try:
            return x11_utils.wmctrl_list()
        except Exception:
            return {}

    @staticmethod
    def _settle(ms):
        if ms and ms > 0:
            time.sleep(ms / 1000.0)
