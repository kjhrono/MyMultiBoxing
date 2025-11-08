#!/usr/bin/env python3
# multiboxer_gui.py — thin GTK UI that delegates logic to CoreController

import os
import sys
import signal
import logging

# GTK
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib

# Project modules
import config
import x11_utils
from overlay import Overlay
from broadcaster import Broadcaster
from core import CoreController

# Logging
logging.basicConfig(
    filename=config.LOG_FILE,
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("MultiboxerGUI")


def handle_sigint(signum, frame):
    Gtk.main_quit()


signal.signal(signal.SIGINT, handle_sigint)


class MultiboxerApp(Gtk.Window):
    def __init__(self):
        super().__init__(title="Multiboxer Control Center")
        self.set_default_size(720, 520)
        self.connect("destroy", self.on_destroy)

        # Load config and build core
        self.cfg = config.load_config()
        self.broadcaster = Broadcaster(
            x11_utils,
            enabled=self.cfg.get("broadcast_enabled", False),
            mode=self.cfg.get("broadcast_mode", "focus_sweep")  # default to focus_sweep
        )
        self.core = CoreController(self.cfg, x11_utils, Overlay, self.broadcaster)

        # UI
        self._build_ui()

        # Initial state
        self._rescan()
        self.core.start()

    # ---------------- UI building ----------------

    def _build_ui(self):
        grid = Gtk.Grid(column_spacing=8, row_spacing=8, margin=8)
        self.add(grid)
        r = 0

        # Pattern
        grid.attach(Gtk.Label(label="Window title pattern:"), 0, r, 1, 1)
        self.pattern_entry = Gtk.Entry()
        self.pattern_entry.set_text(self.cfg.get("pattern", "World of Warcraft"))
        grid.attach(self.pattern_entry, 1, r, 2, 1)
        btn_rescan = Gtk.Button(label="Rescan")
        btn_rescan.connect("clicked", lambda *_: self._rescan())
        grid.attach(btn_rescan, 3, r, 1, 1)
        r += 1

        # Windows list
        grid.attach(Gtk.Label(label="Captured windows:"), 0, r, 4, 1)
        r += 1
        self.win_store = Gtk.ListStore(str, str)
        self.win_view = Gtk.TreeView(self.win_store)
        rend = Gtk.CellRendererText()
        self.win_view.append_column(Gtk.TreeViewColumn("#", rend, text=0))
        self.win_view.append_column(Gtk.TreeViewColumn("Title (id)", rend, text=1))
        scrolled = Gtk.ScrolledWindow(); scrolled.set_min_content_height(160); scrolled.add(self.win_view)
        grid.attach(scrolled, 0, r, 4, 1)
        r += 1

        # Layout
        grid.attach(Gtk.Label(label="Layout:"), 0, r, 1, 1)
        self.layout_combo = Gtk.ComboBoxText()
        self.layout_combo.append_text("None")
        self.layout_combo.append_text("Maximize all")
        self.layout_combo.append_text("Tile horizontally")
        self.layout_combo.append_text("Main left + stack right")
        self.layout_combo.set_active(0)
        grid.attach(self.layout_combo, 1, r, 2, 1)
        btn_layout = Gtk.Button(label="Apply")
        btn_layout.connect("clicked", lambda *_: self._apply_layout())
        grid.attach(btn_layout, 3, r, 1, 1)
        r += 1

        # Size
        grid.attach(Gtk.Label(label="Size (W x H):"), 0, r, 1, 1)
        self.size_w = Gtk.Entry(); self.size_w.set_text(str(self.cfg.get("window_size", [1280, 720])[0]))
        self.size_h = Gtk.Entry(); self.size_h.set_text(str(self.cfg.get("window_size", [1280, 720])[1]))
        hbox = Gtk.Box(spacing=6); hbox.pack_start(self.size_w, True, True, 0); hbox.pack_start(Gtk.Label(label="x"), False, False, 0); hbox.pack_start(self.size_h, True, True, 0)
        grid.attach(hbox, 1, r, 2, 1)
        btn_min_all = Gtk.Button(label="Minimize all")
        btn_min_all.connect("clicked", lambda *_: self._minimize_all())
        grid.attach(btn_min_all, 3, r, 1, 1)
        r += 1

        grid.attach(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), 0, r, 4, 1); r += 1

        # Overlay
        self.overlay_check = Gtk.CheckButton(label="Overlay enabled")
        self.overlay_check.set_active(self.cfg.get("overlay_enabled", True))
        self.overlay_check.connect("toggled", self._on_toggle_overlay)
        grid.attach(self.overlay_check, 0, r, 1, 1)

        grid.attach(Gtk.Label(label="Text color:"), 1, r, 1, 1)
        self.color_btn = Gtk.ColorButton()
        rgba = Gdk.RGBA(); rgba.parse(self.cfg.get("overlay_color", "#00FF00"))
        self.color_btn.set_rgba(rgba)
        self.color_btn.connect("color-set", self._on_color_change)
        grid.attach(self.color_btn, 2, r, 1, 1)

        grid.attach(Gtk.Label(label="Font size:"), 3, r, 1, 1)
        r += 1
        font_adj = Gtk.Adjustment(value=self.cfg.get("overlay_font_size", 36000), lower=10000, upper=80000, step_increment=1000, page_increment=5000)
        self.font_size_spin = Gtk.SpinButton(adjustment=font_adj)
        self.font_size_spin.connect("value-changed", self._on_font_change)
        grid.attach(self.font_size_spin, 3, r, 1, 1)
        r += 1

        grid.attach(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), 0, r, 4, 1); r += 1

        # Broadcast
        self.broadcast_check = Gtk.CheckButton(label="Broadcast enabled")
        self.broadcast_check.set_active(self.cfg.get("broadcast_enabled", False))
        self.broadcast_check.connect("toggled", self._on_toggle_broadcast)
        grid.attach(self.broadcast_check, 0, r, 1, 1)

        grid.attach(Gtk.Label(label="Exclude keys (comma-separated):"), 1, r, 1, 1)
        self.inhibit_entry = Gtk.Entry(); self.inhibit_entry.set_text(",".join(self.cfg.get("inhibit_keys", [])))
        self.inhibit_entry.connect("changed", self._on_inhibit_change)
        grid.attach(self.inhibit_entry, 2, r, 2, 1)
        r += 1

        help_label = Gtk.Label(label="Special: Escape, Page_Down, Page_Up, Home, End, Insert, Delete, Up, Down, Left, Right, Tab, space, Return, BackSpace, minus, plus, F1..F12")
        help_label.set_line_wrap(True); help_label.set_selectable(True); help_label.set_xalign(0)
        grid.attach(help_label, 0, r, 4, 1)
        r += 1

        grid.attach(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), 0, r, 4, 1); r += 1

        # Shortcuts
        grid.attach(Gtk.Label(label="Shortcuts (e.g., Alt+a, Control+s, Shift+F1, Alt+Control+Delete):"), 0, r, 4, 1); r += 1

        grid.attach(Gtk.Label(label="Prev:"), 0, r, 1, 1)
        self.short_prev = Gtk.Entry(); self.short_prev.set_text(self.cfg["shortcuts"].get("prev", "Alt+a"))
        self.short_prev.connect("changed", self._on_shortcuts_changed)
        grid.attach(self.short_prev, 1, r, 1, 1)

        grid.attach(Gtk.Label(label="Next:"), 2, r, 1, 1)
        self.short_next = Gtk.Entry(); self.short_next.set_text(self.cfg["shortcuts"].get("next", "Alt+d"))
        self.short_next.connect("changed", self._on_shortcuts_changed)
        grid.attach(self.short_next, 3, r, 1, 1)
        r += 1

        grid.attach(Gtk.Label(label="Minimize all:"), 0, r, 1, 1)
        self.short_min = Gtk.Entry(); self.short_min.set_text(self.cfg["shortcuts"].get("minimize_all", "Alt+m"))
        self.short_min.connect("changed", self._on_shortcuts_changed)
        grid.attach(self.short_min, 1, r, 1, 1)

        grid.attach(Gtk.Label(label="Close all:"), 2, r, 1, 1)
        self.short_close_all = Gtk.Entry(); self.short_close_all.set_text(self.cfg["shortcuts"].get("close_all", "Alt+Delete"))
        self.short_close_all.connect("changed", self._on_shortcuts_changed)
        grid.attach(self.short_close_all, 3, r, 1, 1)
        r += 1

        grid.attach(Gtk.Label(label="Toggle overlay:"), 0, r, 1, 1)
        self.short_toggle_overlay = Gtk.Entry(); self.short_toggle_overlay.set_text(self.cfg["shortcuts"].get("toggle_overlay", "Alt+o"))
        self.short_toggle_overlay.connect("changed", self._on_shortcuts_changed)
        grid.attach(self.short_toggle_overlay, 1, r, 1, 1)

        grid.attach(Gtk.Label(label="Toggle broadcast:"), 2, r, 1, 1)
        self.short_toggle_broadcast = Gtk.Entry(); self.short_toggle_broadcast.set_text(self.cfg["shortcuts"].get("toggle_broadcast", "Alt+b"))
        self.short_toggle_broadcast.connect("changed", self._on_shortcuts_changed)
        grid.attach(self.short_toggle_broadcast, 3, r, 1, 1)
        r += 1

        grid.attach(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), 0, r, 4, 1); r += 1

        # Actions + Logs menu
        btn_save = Gtk.Button(label="Save config")
        btn_save.connect("clicked", lambda *_: self._save_config())
        grid.attach(btn_save, 0, r, 1, 1)

        # Logs menu (Open / Clear)
        log_menu_btn = Gtk.MenuButton(label="Logs")
        log_menu = Gtk.Menu()
        view_log_item = Gtk.MenuItem(label="Open Logs")
        clear_log_item = Gtk.MenuItem(label="Clear Logs")
        view_log_item.connect("activate", self._open_log_viewer)
        clear_log_item.connect("activate", self._clear_log_file)
        log_menu.append(view_log_item)
        log_menu.append(clear_log_item)
        log_menu.show_all()
        log_menu_btn.set_popup(log_menu)
        grid.attach(log_menu_btn, 1, r, 1, 1)

        btn_quit = Gtk.Button(label="Quit")
        btn_quit.connect("clicked", lambda *_: self.destroy())
        grid.attach(btn_quit, 3, r, 1, 1)
        r += 1

        self.status_label = Gtk.Label(label="")
        grid.attach(self.status_label, 0, r, 4, 1)

    # ---------------- Event handlers ----------------

    def _rescan(self):
        pattern = self.pattern_entry.get_text().strip()
        wins = self.core.refresh_windows(pattern, custom_prefix="WoW Window")
        self._update_win_list(wins)

    def _update_win_list(self, wins):
        self.win_store.clear()
        for i, w in enumerate(wins):
            self.win_store.append([str(i+1), f"WoW Window {i+1} ({w})"])

    def _apply_layout(self):
        try:
            w = int(self.size_w.get_text()); h = int(self.size_h.get_text())
        except Exception:
            self._set_status("Invalid size")
            return
        scr = Gdk.Screen.get_default()
        msg = self.core.apply_layout(
            self.layout_combo.get_active_text(), w, h,
            scr.get_width(), scr.get_height()
        )
        self._set_status(msg)

    def _minimize_all(self):
        self.core.minimize_all()
        self._set_status("All windows minimized")

    def _on_toggle_broadcast(self, *_):
        val = bool(self.broadcast_check.get_active())
        self.core.set_broadcast_enabled(val)
        config.save_config(self.cfg)

    def _on_toggle_overlay(self, *_):
        val = bool(self.overlay_check.get_active())
        self.core.set_overlay_enabled(val)
        config.save_config(self.cfg)

    def _on_color_change(self, *_):
        rgba = self.color_btn.get_rgba()
        hex_color = "#{:02x}{:02x}{:02x}".format(
            int(rgba.red * 255), int(rgba.green * 255), int(rgba.blue * 255)
        )
        self.core.set_overlay_color(hex_color)
        config.save_config(self.cfg)

    def _on_font_change(self, *_):
        self.core.set_overlay_font_size(self.font_size_spin.get_value_as_int())
        config.save_config(self.cfg)

    def _on_inhibit_change(self, *_):
        keys = [s.strip() for s in self.inhibit_entry.get_text().split(",")]
        self.core.set_inhibit_keys(keys)
        config.save_config(self.cfg)

    def _on_shortcuts_changed(self, *_):
        self.cfg["shortcuts"]["prev"] = self.short_prev.get_text().strip()
        self.cfg["shortcuts"]["next"] = self.short_next.get_text().strip()
        self.cfg["shortcuts"]["minimize_all"] = self.short_min.get_text().strip()
        self.cfg["shortcuts"]["close_all"] = self.short_close_all.get_text().strip()
        self.cfg["shortcuts"]["toggle_overlay"] = self.short_toggle_overlay.get_text().strip()
        self.cfg["shortcuts"]["toggle_broadcast"] = self.short_toggle_broadcast.get_text().strip()
        self.core.reparse_shortcuts()
        config.save_config(self.cfg)

    def _save_config(self):
        self.cfg["pattern"] = self.pattern_entry.get_text().strip()
        try:
            self.cfg["window_size"] = [int(self.size_w.get_text()), int(self.size_h.get_text())]
        except Exception:
            pass
        config.save_config(self.cfg)
        self._set_status("Configuration saved")

    def _set_status(self, text):
        self.status_label.set_text(text)
        GLib.timeout_add_seconds(3, lambda: self.status_label.set_text("") or False)

    # ---------------- Logs ----------------

    def _open_log_viewer(self, *_):
        """Open a simple log viewer window with refresh and clear."""
        dialog = Gtk.Dialog(
            title="Log Viewer",
            transient_for=self,
            modal=False
        )
        dialog.set_default_size(800, 600)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)

        self.log_textview = Gtk.TextView()
        self.log_textview.set_editable(False)
        self.log_textview.set_monospace(True)
        self.log_textbuffer = self.log_textview.get_buffer()

        self._refresh_log_display()  # initial content
        scrolled.add(self.log_textview)

        # Buttons
        refresh_btn = Gtk.Button(label="Refresh")
        clear_btn = Gtk.Button(label="Clear Log")
        close_btn = Gtk.Button(label="Close")

        def on_refresh(_w):
            self._refresh_log_display()

        def on_clear(_w):
            self._clear_log_file()

        def on_close(_w):
            dialog.destroy()

        refresh_btn.connect("clicked", on_refresh)
        clear_btn.connect("clicked", on_clear)
        close_btn.connect("clicked", on_close)

        box = dialog.get_content_area()
        box.pack_start(scrolled, True, True, 0)

        button_box = Gtk.Box(spacing=6, margin=6)
        button_box.pack_start(refresh_btn, False, False, 0)
        button_box.pack_start(clear_btn, False, False, 0)
        button_box.pack_end(close_btn, False, False, 0)
        box.pack_start(button_box, False, False, 0)

        dialog.show_all()

    def _refresh_log_display(self):
        """Refresh the log display in the viewer."""
        try:
            if os.path.exists(config.LOG_FILE):
                with open(config.LOG_FILE, "r") as f:
                    log_content = f.read()
                self.log_textbuffer.set_text(log_content)

                # Scroll to end
                end_iter = self.log_textbuffer.get_end_iter()
                self.log_textbuffer.place_cursor(end_iter)
                self.log_textview.scroll_to_iter(end_iter, 0.0, False, 0.0, 0.0)
            else:
                self.log_textbuffer.set_text("Log file does not exist yet.")
        except Exception as e:
            self.log_textbuffer.set_text(f"Error reading log file: {e}")

    def _clear_log_file(self, *_):
        """Clear the log file after confirmation."""
        confirm = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Clear log file?"
        )
        confirm.format_secondary_text("This will permanently delete all log content.")
        resp = confirm.run()
        confirm.destroy()

        if resp != Gtk.ResponseType.YES:
            self._set_status("Log clear canceled")
            return

        try:
            with open(config.LOG_FILE, "w") as f:
                f.write("")
            logging.info("Log file cleared by user")
            self._set_status("Log file cleared")
            # If viewer is open, refresh it
            if hasattr(self, "log_textbuffer"):
                self._refresh_log_display()
        except Exception as e:
            logging.error(f"Error clearing log file: {e}")
            err = Gtk.MessageDialog(
                transient_for=self,
                modal=True,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text="Error clearing log file"
            )
            err.format_secondary_text(str(e))
            err.run()
            err.destroy()

    # ---------------- Lifecycle ----------------

    def on_destroy(self, *_):
        try:
            self.core.stop()
        finally:
            Gtk.main_quit()


def main():
    if os.environ.get("XDG_SESSION_TYPE") == "wayland":
        dialog = Gtk.MessageDialog(
            transient_for=None,
            flags=0,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text="Wayland not supported",
        )
        dialog.format_secondary_text("This application requires X11.")
        dialog.run()
        dialog.destroy()
        sys.exit(1)

    app = MultiboxerApp()
    app.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()