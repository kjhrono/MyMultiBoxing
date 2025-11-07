#!/usr/bin/env python3
# overlay.py
# Contains the Gtk.Window subclass for the in-game overlay.

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Gdk

# Import utilities to get window position
import logging
import x11_utils

# ------------------------- OVERLAY -------------------------
class Overlay:
    def __init__(self, winid, index, color="#00FF00", font_size=36000, show_broadcast=True):
        self.winid = str(winid)
        self.index = index
        self.color = color
        self.font_size = font_size
        self.show_broadcast = show_broadcast
        # self.is_active = False # <-- RIMOSSO
        self.win = Gtk.Window(type=Gtk.WindowType.POPUP)

        # --- TRASPARENZA (Corretta) ---
        screen = self.win.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.win.set_visual(visual)
        self.win.set_app_paintable(True)
        css_provider = Gtk.CssProvider()
        css_data = b"""
            window { background-color: rgba(0, 0, 0, 0); }
            label { background-color: rgba(0, 0, 0, 0); }
        """
        css_provider.load_from_data(css_data)
        context = self.win.get_style_context()
        context.add_provider(css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        # --- FINE TRASPARENZA ---

        self.win.set_decorated(False)
        self.win.set_keep_above(True)
        self.win.set_accept_focus(False)
        self.win.set_focus_on_map(False)
        self.win.set_default_size(160, 60) 
        
        self.label = Gtk.Label()
        self.label.set_markup(self._markup())
        self.win.add(self.label)
        self.win.show_all()

    def _markup(self):
        dot = "🟢" if self.show_broadcast else "🔴"
        icon_size = int(self.font_size * 0.6) # Icona scalabile
        dot_span = f"<span size='{icon_size}'>{dot}</span>"
        
        # --- CORREZIONE COLORE ---
        # Rimuoviamo la logica 'is_active'. Il colore è sempre self.color.
        display_color = self.color 
        display_weight = "bold" # Sempre grassetto, più visibile
        # --- FINE CORREZIONE ---

        index_str = f"#{self.index + 1}" if self.index is not None else "#?"
            
        return f"<span size='{self.font_size}' weight='{display_weight}' foreground='{display_color}'>{index_str}</span>  {dot_span}"

    def update(self, index=None, color=None, font_size=None, show_broadcast=None, is_active=None):
        # 'is_active' viene ricevuto ma ignorato, non ci serve più qui
        if index is not None: self.index = index
        if color is not None: self.color = color
        if font_size is not None: self.font_size = font_size
        if show_broadcast is not None: self.show_broadcast = show_broadcast
        
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