#!/usr/bin/env python3
# overlay.py
# Contains the Gtk.Window subclass for the in-game overlay.

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

# Import utilities to get window position
import x11_utils

# ------------------------- OVERLAY -------------------------
class Overlay:
    """
    Small popup window per game window, shows index and broadcast indicator.
    """
    def __init__(self, winid, index, color="#00FF00", show_broadcast=True):
        self.winid = str(winid)
        self.index = index
        self.color = color
        self.show_broadcast = show_broadcast
        self.is_active = False
        self.win = Gtk.Window(type=Gtk.WindowType.POPUP)
        self.win.set_decorated(False)
        self.win.set_keep_above(True)
        self.win.set_accept_focus(False)
        self.win.set_focus_on_map(False)
        self.win.set_default_size(120, 40)
        self.label = Gtk.Label()
        self.label.set_markup(self._markup())
        self.win.add(self.label)
        self.win.show_all()

    def _markup(self):
        dot = "🟢" if self.show_broadcast else "🔴"
        
        # If we are active, use a bright white. Otherwise, use the chosen color.
        display_color = "#FFFFFF" if self.is_active else self.color
        display_weight = "bold" if self.is_active else "normal"
        index_str = f"#{self.index + 1}" if self.index is not None else "#?"
            
        return f"<span size='12000' weight='{display_weight}' foreground='{display_color}'>{index_str}</span>  {dot}"

    def update(self, index=None, color=None, show_broadcast=None, is_active=None):
        if index is not None: self.index = index
        if color is not None: self.color = color
        if show_broadcast is not None: self.show_broadcast = show_broadcast
        
        if is_active is not None: self.is_active = is_active
        
        GLib.idle_add(self.label.set_markup, self._markup())

    def place_on_window(self):
        try:
            # Use the imported utility function
            x,y,w,h = x11_utils.get_window_geometry(self.winid)
            offx = 8; offy = 8
            GLib.idle_add(self.win.move, x+offx, y+offy)
            GLib.idle_add(self.win.resize, 120, 40)
        except Exception:
            pass

    def hide(self):
        GLib.idle_add(self.win.hide)

    def show(self):
        GLib.idle_add(self.win.show_all)

    def destroy(self):
        GLib.idle_add(self.win.destroy)
