#!/usr/bin/env python3
# shortcuts.py — parse/normalize and match shortcuts against config

from typing import Optional, Tuple, List


_CANON_ORDER = ["alt", "control", "shift"]  # fixed order


def normalize_shortcut(spec: str) -> str:
    """
    Normalize "Alt+Shift+F1" -> "alt+shift+f1" with canonical modifier order.
    Empty/None -> ""
    """
    if not spec:
        return ""
    parts = [p.strip().lower() for p in spec.split("+") if p.strip()]
    if not parts:
        return ""
    key = parts[-1]
    mods = [p for p in parts[:-1] if p in _CANON_ORDER]
    ordered = [m for m in _CANON_ORDER if m in mods]
    return "+".join(ordered + [key])


class ShortcutHandler:
    """
    Holds normalized shortcuts from config and matches incoming combos.
    Returns:
      - ("action", action_name) for app actions
      - ("window", idx) for window index shortcuts
      - None if no match
    """

    def __init__(self, config: dict):
        self._cfg = config
        self._rebuild()

    def set_config(self, config: dict):
        self._cfg = config
        self._rebuild()

    def all_shortcut_combos(self) -> List[str]:
        """All known combos (normalized)."""
        combos = list(self._action_map.keys())
        combos += [c for c, _ in self._window_indices]
        return combos

    def match(self, combo_now: str) -> Optional[Tuple[str, object]]:
        """
        combo_now is already normalized via normalize_shortcut.
        """
        if not combo_now:
            return None

        # Exact action match?
        action = self._action_map.get(combo_now)
        if action:
            return ("action", action)

        # Window index?
        for c, idx in self._window_indices:
            if combo_now == c:
                return ("window", idx)

        return None

    # -------- internal --------

    def _rebuild(self):
        sc = self._cfg.get("shortcuts", {}) or {}

        # Map normalized combo -> action name
        self._action_map = {}
        for action_key in ("prev", "next", "minimize_all", "close_all",
                           "toggle_broadcast", "toggle_overlay"):
            combo = normalize_shortcut(sc.get(action_key, ""))
            if combo:
                self._action_map[combo] = action_key

        # Window index shortcuts (list)
        window_keys = self._cfg.get("shortcuts", {}).get("window_keys", []) or []
        self._window_indices = []
        for idx, combo in enumerate(window_keys):
            norm = normalize_shortcut(combo)
            if norm:
                self._window_indices.append((norm, idx))
