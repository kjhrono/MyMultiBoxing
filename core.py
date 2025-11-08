#!/usr/bin/env python3
# core.py — app controller (no GTK widgets here)

import time
import logging
import threading

from pynput import keyboard
from Xlib import X, XK, display
from gi.repository import GLib

from shortcuts import ShortcutHandler, normalize_shortcut

logger = logging.getLogger(__name__)


class CoreController:
    """
    Wires together: config, x11_utils, Overlay, broadcaster, and global key/focus logic.
    The GUI calls into this class; this class never touches GUI widgets directly.
    """

    def __init__(self, cfg, x11_module, OverlayClass, broadcaster):
        # External services
        self.config = cfg
        self.x11 = x11_module
        self.Overlay = OverlayClass
        self.broadcaster = broadcaster

        # X11 display for optional grabs
        self._d = display.Display()
        self._root = self._d.screen().root

        # State
        self.wins = []
        self.overlays = {}         # win_id -> Overlay()
        self.original_titles = {}  # win_id -> original title
        self.active_window = self.x11.get_active_window()
        self.running = False

        # Input
        self.current_keys = set()
        self.inhibit_keys = set(k.strip().lower() for k in self.config.get("inhibit_keys", []))
        self.shortcut_handler = ShortcutHandler(self.config)

        # Threads
        self._poll_thread = None
        self._key_listener = None

        # Grabbed keys bookkeeping (optional)
        self._grabbed_keycodes = []

    # ---------------- Windows & overlays ----------------

    def refresh_windows(self, pattern: str, custom_prefix: str = "WoW Window"):
        """
        Rescan windows by pattern and our custom prefix; rename with prefix + index;
        create/update overlays accordingly. Returns ordered list of window ids.
        """
        wins1 = self.x11.rescan_windows(pattern.strip())
        wins2 = self.x11.rescan_windows(custom_prefix)

        all_wins = list(set(wins1 + wins2))
        self.wins = sorted([w for w in all_wins if w])

        # Save original title (once), then retitle
        wmap = self.x11.wmctrl_list()
        for idx, w in enumerate(self.wins):
            if w not in self.original_titles:
                tup = wmap.get(str(w), ("", "", "", "", "", "", ""))
                if tup:
                    self.original_titles[w] = tup[-1]
            new_title = f"{custom_prefix} {idx+1}"
            self.x11.set_window_title(w, new_title)

        self._sync_overlays()
        return self.wins[:]

    def _sync_overlays(self):
        font_size = self.config.get("overlay_font_size", 36000)
        color = self.config.get("overlay_color", "#00FF00")
        show_broadcast = self.config.get("broadcast_enabled", False)

        cur_ids = set(self.overlays.keys())
        tgt_ids = set(self.wins)

        for w in list(cur_ids - tgt_ids):
            try:
                self.overlays[w].destroy()
            except Exception:
                pass
            self.overlays.pop(w, None)

        for idx, w in enumerate(self.wins):
            if w not in self.overlays:
                ov = self.Overlay(
                    w, idx,
                    color=color,
                    font_size=font_size,
                    show_broadcast=show_broadcast
                )
                self.overlays[w] = ov
            else:
                self.overlays[w].update(
                    index=idx,
                    color=color,
                    font_size=font_size,
                    show_broadcast=show_broadcast
                )

        for _, ov in self.overlays.items():
            ov.place_on_window()

        # Ensure visibility follows current focus
        GLib.idle_add(self.update_overlay_visibility)

    def update_overlay_visibility(self):
        if not self.config.get("overlay_enabled", True):
            for ov in self.overlays.values():
                ov.hide()
            return False

        active = self.active_window
        if not active or active not in self.wins:
            for ov in self.overlays.values():
                ov.hide()
        else:
            is_broadcast = self.config.get("broadcast_enabled", False)
            font_size = self.config.get("overlay_font_size", 36000)
            color = self.config.get("overlay_color", "#00FF00")

            for wid, ov in self.overlays.items():
                if wid == active:
                    ov.update(
                        is_active=True,
                        show_broadcast=is_broadcast,
                        font_size=font_size,
                        color=color
                    )
                    ov.show()
                    ov.place_on_window()
                else:
                    ov.hide()
        return False

    # ---------------- Layout / actions ----------------

    def apply_layout(self, mode: str, size_w: int, size_h: int, scr_w: int, scr_h: int):
        if not self.wins:
            return "No captured windows"

        if mode == "Maximize all":
            for w in self.wins:
                self.x11.maximize_window(w)

        elif mode == "Tile horizontally":
            n = len(self.wins)
            if n == 0:
                return "No windows"
            h = max(10, scr_h // n)
            y = 0
            for w in self.wins:
                self.x11.move_resize_window(w, 0, y, scr_w, h)
                y += h

        elif mode == "Main left + stack right":
            main = self.wins[0]
            others = self.wins[1:]
            main_w = scr_w // 2
            self.x11.move_resize_window(main, 0, 0, main_w, scr_h)
            if others:
                right_w = scr_w - main_w
                h = max(10, scr_h // len(others))
                y = 0
                for w in others:
                    self.x11.move_resize_window(w, main_w, y, right_w, h)
                    y += h

        else:  # "None" -> grid using given size
            if size_w <= 0 or size_h <= 0:
                return "Invalid size"
            per_row = max(1, scr_w // size_w)
            x = y = 0
            cur = 0
            for w in self.wins:
                self.x11.move_resize_window(w, x, y, size_w, size_h)
                cur += 1
                x += size_w
                if cur >= per_row:
                    cur = 0
                    x = 0
                    y += size_h

        GLib.timeout_add(300, self._sync_overlays)
        return "Layout applied"

    def minimize_all(self):
        for w in self.wins:
            self.x11.minimize_window(w)

    def close_all(self):
        for w in self.wins:
            self.x11.close_window(w)
        GLib.timeout_add(700, self._after_close_all_refresh)

    def _after_close_all_refresh(self):
        # no-op here (GUI will call refresh again if needed)
        return False

    def switch_next(self):
        if not self.wins:
            return
        active = self.x11.get_active_window()
        if active in self.wins:
            i = (self.wins.index(active) + 1) % len(self.wins)
        else:
            i = 0
        self.x11.activate_window(self.wins[i])

    def switch_prev(self):
        if not self.wins:
            return
        active = self.x11.get_active_window()
        if active in self.wins:
            i = (self.wins.index(active) - 1) % len(self.wins)
        else:
            i = 0
        self.x11.activate_window(self.wins[i])

    def focus_index(self, idx: int):
        if 0 <= idx < len(self.wins):
            self.x11.activate_window(self.wins[idx])

    # ---------------- Config knobs used by GUI ----------------

    def set_broadcast_enabled(self, enabled: bool):
        self.config["broadcast_enabled"] = bool(enabled)
        self.broadcaster.set_enabled(bool(enabled))
        GLib.idle_add(self.update_overlay_visibility)

    def set_overlay_enabled(self, enabled: bool):
        self.config["overlay_enabled"] = bool(enabled)
        GLib.idle_add(self.update_overlay_visibility)

    def set_overlay_color(self, hex_color: str):
        self.config["overlay_color"] = hex_color
        self._sync_overlays()

    def set_overlay_font_size(self, pts: int):
        self.config["overlay_font_size"] = int(pts)
        self._sync_overlays()

    def set_inhibit_keys(self, keys_iterable):
        self.config["inhibit_keys"] = [s.strip() for s in keys_iterable if s.strip()]
        self.inhibit_keys = set(k.lower() for k in self.config["inhibit_keys"])

    def reparse_shortcuts(self):
        self.shortcut_handler = ShortcutHandler(self.config)

    # ---------------- Focus/keys listener ----------------

    def start(self):
        if self.running:
            return
        self.running = True
        self._start_focus_poller()
        self._start_key_listener()
        self._try_grab_shortcuts()  # best-effort

    def stop(self):
        self.running = False

        try:
            if self._key_listener:
                self._key_listener.stop()
        except Exception:
            logger.exception("Stopping key listener")

        try:
            self._ungrab_shortcuts()
        except Exception:
            logger.exception("Ungrab shortcuts")

        # Restore titles
        for wid, original in self.original_titles.items():
            if original:
                try:
                    self.x11.set_window_title(wid, original)
                except Exception:
                    pass
        # Destroy overlays
        for ov in list(self.overlays.values()):
            try:
                ov.destroy()
            except Exception:
                pass
        self.overlays.clear()

        try:
            self._d.flush()
            self._d.close()
        except Exception:
            pass

    def _start_focus_poller(self):
        def run():
            last = None
            try:
                while self.running:
                    cur = self.x11.get_active_window()
                    if cur != last:
                        last = cur
                        self.active_window = cur
                        GLib.idle_add(self.update_overlay_visibility)
                    time.sleep(0.05)
            except Exception:
                logger.exception("focus poller crashed")
        self._poll_thread = threading.Thread(target=run, daemon=True)
        self._poll_thread.start()

    def _start_key_listener(self):
        def on_press(key):
            if not self.running:
                return False

            # always track pressed set
            try:
                self.current_keys.add(key)
            except Exception:
                pass

            # Only react when focus is on one of our target windows
            active = self.x11.get_active_window()
            if active not in self.wins:
                return True

            # Build normalized combo string
            key_name, alt, ctrl, shift = self._decode_key(key)
            combo_now = normalize_shortcut("+".join(
                (["alt"] if alt else []) +
                (["control"] if ctrl else []) +
                (["shift"] if shift else []) +
                [key_name]
            ))

            # 1) Shortcuts handled internally (no broadcast)
            matched = self.shortcut_handler.match(combo_now)
            if matched:
                kind, payload = matched
                if kind == "action":
                    self._exec_action(payload)
                elif kind == "window":
                    self.focus_index(payload)
                return True  # don't broadcast

            # 2) Normal key: broadcast if enabled
            if not self.config.get("broadcast_enabled", False):
                return True

            if key_name in self.inhibit_keys or combo_now in self.inhibit_keys:
                return True

            # Compose xdotool sequence (e.g., alt+ctrl+a or Return)
            seq_parts = []
            if alt: seq_parts.append("alt")
            if ctrl: seq_parts.append("ctrl")
            if shift: seq_parts.append("shift")

            # name mapping
            send_key = key_name
            if send_key == "enter":
                send_key = "Return"
            elif send_key == "tab":
                send_key = "Tab"
            elif send_key == "backspace":
                send_key = "BackSpace"
            elif send_key.startswith("f") and send_key[1:].isdigit():
                send_key = send_key.upper()  # F1..F12
            # else keep lower for letters/digits/punct

            seq = "+".join(seq_parts + [send_key]) if seq_parts else send_key
            self.broadcaster.broadcast(seq, self.wins, exclude=active)
            return True

        def on_release(key):
            try:
                if key in self.current_keys:
                    self.current_keys.remove(key)
                else:
                    s = str(key)
                    for k in list(self.current_keys):
                        if str(k) == s:
                            self.current_keys.remove(k)
            except Exception:
                pass
            return True

        self._key_listener = keyboard.Listener(
            on_press=on_press, on_release=on_release, suppress=False
        )
        self._key_listener.start()

    def _decode_key(self, key):
        """
        Returns (key_name, alt, ctrl, shift)
        key_name is lower-case; letters/digits are plain, special as pynput names (enter, space,...)
        """
        # key name
        if hasattr(key, "char") and key.char:
            key_name = key.char.lower()
        else:
            # e.g., Key.space -> "space"
            key_name = str(key).replace("Key.", "").lower()

        # modifiers from the pressed set
        alt = any("alt" in str(k).lower() for k in self.current_keys)
        ctrl = any("ctrl" in str(k).lower() for k in self.current_keys)
        shift = any("shift" in str(k).lower() for k in self.current_keys)

        return key_name, alt, ctrl, shift

    # ---------------- Shortcuts grab (optional best-effort) ----------------

    def _try_grab_shortcuts(self):
        """Best effort X11 grab to improve shortcut reliability. Non-fatal."""
        try:
            self._grabbed_keycodes = []
            for combo in self.shortcut_handler.all_shortcut_combos():
                parts = combo.split("+")
                keyname = parts[-1]
                modifiers = parts[:-1]
                mask = self._modifiers_to_mask(modifiers)

                keysym = XK.string_to_keysym(keyname)
                if keysym == 0:
                    keysym = XK.string_to_keysym("Key_" + keyname)
                if keysym == 0:
                    continue

                keycode = self._d.keysym_to_keycode(keysym)
                if keycode == 0:
                    continue

                try:
                    self._root.grab_key(
                        keycode, mask, True,
                        X.GrabModeAsync, X.GrabModeAsync
                    )
                    self._grabbed_keycodes.append((keycode, mask))
                except Exception:
                    pass
            self._d.flush()
        except Exception:
            logger.exception("grab shortcuts failed")

    def _ungrab_shortcuts(self):
        try:
            for keycode, mask in list(self._grabbed_keycodes):
                try:
                    self._root.ungrab_key(keycode, mask)
                except Exception:
                    pass
            self._d.flush()
        except Exception:
            pass
        self._grabbed_keycodes = []

    def _modifiers_to_mask(self, modifiers):
        modmap = {
            "shift": X.ShiftMask,
            "control": X.ControlMask,
            "ctrl": X.ControlMask,
            "alt": X.Mod1Mask,
            "mod1": X.Mod1Mask,
            "mod4": X.Mod4Mask,
            "super": X.Mod4Mask,
            "win": X.Mod4Mask,
            "meta": X.Mod4Mask,
        }
        mask = 0
        for m in modifiers:
            mask |= modmap.get(m, 0)
        return mask

    # ---------------- Execute shortcut actions ----------------

    def _exec_action(self, action_name: str):
        if action_name == "prev":
            self.switch_prev()
        elif action_name == "next":
            self.switch_next()
        elif action_name == "minimize_all":
            self.minimize_all()
        elif action_name == "close_all":
            self.close_all()
        elif action_name == "toggle_broadcast":
            self.set_broadcast_enabled(not self.config.get("broadcast_enabled", False))
        elif action_name == "toggle_overlay":
            self.set_overlay_enabled(not self.config.get("overlay_enabled", True))
