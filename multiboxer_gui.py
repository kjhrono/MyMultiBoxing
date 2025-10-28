#!/usr/bin/env python3
# multiboxer_gui.py
# Main application file for the Multiboxer Control Center.
#
# Works on X11 only. Dependencies: python3-gi, gir1.2-gtk-3.0, python3-xlib, xdotool, wmctrl
#
# Usage: python3 multiboxer_gui.py

import os
import sys
import threading
import time
import logging

# GTK imports
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib

# X11
from Xlib import X, XK, display

# --- Project Imports ---
import config
import x11_utils
from overlay import Overlay
# -------------------------

# Logging
logging.basicConfig(filename=config.LOG_FILE, level=logging.DEBUG,
                    format='%(asctime)s [%(levelname)s] %(message)s')
logging.info("Starting Multiboxer GUI")


# ------------------------- MAIN APP -------------------------
class MultiboxerApp(Gtk.Window):
    def __init__(self):
        super().__init__(title="Multiboxer Control Center")
        self.set_default_size(700, 480)
        self.connect("destroy", self.on_destroy)

        # load config
        self.config = config.load_config()
        self.wins = []  # list of window ids (decimal str)
        self.overlays = {}  # winid -> Overlay
        self.active_window = x11_utils.get_active_window() # Initialize once
        self.display = display.Display()
        self.root = self.display.screen().root

        # --- Dynamic-only Grab Logic ---
        self._grabbed_keycodes = [] 
        self._keys_to_grab = [] 
        
        self.poll_thread = None
        self.running = True

        # build UI
        self.build_ui()

        # initial rescan
        self.refresh_windows()

        # --- Startup Order ---
        # 1. Configure the master list of keys
        self.update_keys_to_grab() 
        
        # 2. Start the poller (manages all grabs)
        self.poll_thread = threading.Thread(target=self.active_window_poller_and_grab_manager, daemon=True)
        self.poll_thread.start()

    # ---------- UI ----------
    def build_ui(self):
        grid = Gtk.Grid(column_spacing=8, row_spacing=8, margin=8)
        self.add(grid)

        # pattern + rescan
        grid.attach(Gtk.Label(label="Pattern finestra:"), 0,0,1,1)
        self.pattern_entry = Gtk.Entry(); self.pattern_entry.set_text(self.config.get("pattern","World of Warcraft"))
        grid.attach(self.pattern_entry, 1,0,2,1)
        btn_rescan = Gtk.Button(label="Scansiona")
        btn_rescan.connect("clicked", lambda b: self.refresh_windows())
        grid.attach(btn_rescan, 3,0,1,1)

        # broadcast + overlay toggles + color
        self.broadcast_check = Gtk.CheckButton(label="Broadcast abilitato")
        self.broadcast_check.set_active(self.config.get("broadcast_enabled", True))
        self.broadcast_check.connect("toggled", lambda b: self.on_toggle_broadcast())
        grid.attach(self.broadcast_check, 0,1,1,1)

        self.overlay_check = Gtk.CheckButton(label="Overlay abilitato")
        self.overlay_check.set_active(self.config.get("overlay_enabled", True))
        self.overlay_check.connect("toggled", lambda b: self.on_toggle_overlay())
        grid.attach(self.overlay_check, 1,1,1,1)

        grid.attach(Gtk.Label(label="Colore overlay:"), 2,1,1,1)
        self.color_btn = Gtk.ColorButton()
        rgba = Gdk.RGBA()
        color_str = self.config.get("overlay_color","#00FF00")
        if not rgba.parse(color_str):
            logging.warning(f"Could not parse color '{color_str}', using default.")
            rgba.parse("#00FF00") # Fallback
        self.color_btn.set_rgba(rgba)
        self.color_btn.connect("color-set", lambda cb: self.on_color_change())
        grid.attach(self.color_btn, 3,1,1,1)

        # inhibit keys
        grid.attach(Gtk.Label(label="Tasti da escludere (comma):"), 0,2,2,1)
        self.inhibit_entry = Gtk.Entry(); self.inhibit_entry.set_text(",".join(self.config.get("inhibit_keys",[])))
        grid.attach(self.inhibit_entry, 2,2,2,1)
        # Helper text for special keys
        key_list = "Speciali: Escape, Page_Down, Page_Up, Home, End, Insert, Delete, Up, Down, Left, Right, Tab, space, Return, BackSpace, minus, plus, F1, F2, F3, F4, F5, F6, F7, F8, F9, F10, F11, F12"
        help_label = Gtk.Label(label=key_list)
        help_label.set_line_wrap(True)
        help_label.set_selectable(True) # Allows copy-pasting
        help_label.set_xalign(0) # Align left
        grid.attach(help_label, 0, 3, 4, 1) # Span all 4 columns

        # windows list
        grid.attach(Gtk.Label(label="Finestre catturate:"), 0,4,1,1)
        self.win_store = Gtk.ListStore(str, str)
        self.win_view = Gtk.TreeView(self.win_store)
        renderer = Gtk.CellRendererText()
        col1 = Gtk.TreeViewColumn("#", renderer, text=0)
        col2 = Gtk.TreeViewColumn("Title (id)", renderer, text=1)
        self.win_view.append_column(col1); self.win_view.append_column(col2)
        scrolled = Gtk.ScrolledWindow(); scrolled.set_min_content_height(160); scrolled.add(self.win_view)
        grid.attach(scrolled, 0,5,4,1)

        # Layout controls
        grid.attach(Gtk.Label(label="Layout:"), 0,6,1,1)
        self.layout_combo = Gtk.ComboBoxText()
        self.layout_combo.append_text("Nessuno")
        self.layout_combo.append_text("Massimizza tutte")
        self.layout_combo.append_text("Allinea orizzontalmente")
        self.layout_combo.append_text("Main left + affiancate right")
        self.layout_combo.set_active(0)
        grid.attach(self.layout_combo, 1,6,1,1)
        btn_layout = Gtk.Button(label="Applica")
        btn_layout.connect("clicked", lambda b: self.apply_layout())
        grid.attach(btn_layout, 2,6,1,1)

        # custom size
        grid.attach(Gtk.Label(label="W x H:"), 0,7,1,1)
        self.size_w = Gtk.Entry(); self.size_w.set_text(str(self.config.get("window_size",[1280,720])[0]))
        self.size_h = Gtk.Entry(); self.size_h.set_text(str(self.config.get("window_size",[1280,720])[1]))
        grid.attach(self.size_w, 1,7,1,1); grid.attach(self.size_h, 2,7,1,1)

        # shortcuts
        grid.attach(Gtk.Label(label="Shortcuts (es. Alt+a):"), 0,8,2,1)
        self.short_prev = Gtk.Entry(); self.short_prev.set_text(self.config["shortcuts"].get("prev","Alt+a"))
        self.short_next = Gtk.Entry(); self.short_next.set_text(self.config["shortcuts"].get("next","Alt+d"))
        self.short_min = Gtk.Entry(); self.short_min.set_text(self.config["shortcuts"].get("minimize_all","Alt+m"))
        grid.attach(Gtk.Label(label="Prev:"), 0,9,1,1); grid.attach(self.short_prev, 1,9,1,1)
        grid.attach(Gtk.Label(label="Next:"), 2,9,1,1); grid.attach(self.short_next, 3,9,1,1)

        # Row 10: Minimize All | Close All
        grid.attach(Gtk.Label(label="Minimize All:"), 0,10,1,1) # Row 10
        self.short_min = Gtk.Entry(); self.short_min.set_text(self.config["shortcuts"].get("minimize_all","Alt+m"))
        grid.attach(self.short_min, 1,10,1,1)

        grid.attach(Gtk.Label(label="Close All:"), 2,10,1,1) # NEW
        self.short_close_all = Gtk.Entry(); self.short_close_all.set_text(self.config["shortcuts"].get("close_all","Alt+q")) # NEW
        grid.attach(self.short_close_all, 3,10,1,1) # NEW
        
        # Row 11: Toggle Overlay | Toggle Broadcast
        grid.attach(Gtk.Label(label="Toggle Overlay:"), 0,11,1,1) # Row 11
        self.short_toggle_overlay = Gtk.Entry(); self.short_toggle_overlay.set_text(self.config["shortcuts"].get("toggle_overlay","Alt+o"))
        grid.attach(self.short_toggle_overlay, 1,11,1,1) 

        grid.attach(Gtk.Label(label="Toggle Broadcast:"), 2,11,1,1) # MOVED to Row 11
        self.short_toggle_broadcast = Gtk.Entry(); self.short_toggle_broadcast.set_text(self.config["shortcuts"].get("toggle_broadcast","Alt+b"))
        grid.attach(self.short_toggle_broadcast, 3,11,1,1) # MOVED to Row 11

        # Row 12: Save / generate bindings / minimize / quit
        btn_save = Gtk.Button(label="Salva config")
        btn_save.connect("clicked", lambda b: self.on_save_config())
        grid.attach(btn_save, 0,12,1,1) 
        btn_min_all = Gtk.Button(label="Minimizza tutte")
        btn_min_all.connect("clicked", lambda b: self.minimize_all())
        grid.attach(btn_min_all, 1,12,1,1)
        btn_quit = Gtk.Button(label="Quit")
        btn_quit.connect("clicked", lambda b: self.destroy()) # self.destroy() triggers on_destroy
        grid.attach(btn_quit, 3, 12, 1, 1)

        # status
        self.status_label = Gtk.Label(label="")
        grid.attach(self.status_label, 0,13,4,1)

    # ---------- windows / overlays ----------
    def refresh_windows(self):
        pattern = self.pattern_entry.get_text().strip()
        # Use utility function
        self.wins = x11_utils.rescan_windows(pattern)
        self.wins = [w for w in self.wins if w] # Filter out any empty strings

        # Sort the window IDs to get a stable order for numbering
        self.wins.sort()

        def _update_gui_threadsafe():
            """
            This function will run ONCE on the main GTK thread
            to perform all UI updates atomically.
            """
            self.win_store.clear()
            wmap = x11_utils.wmctrl_list()
            
            for i,w in enumerate(self.wins):
                title_tuple = wmap.get(str(w), ("", "", "", "", "", "", ""))
                title = title_tuple[-1] if title_tuple else ""
                self.win_store.append([str(i+1), f"{title} ({w})"])
                
            self.sync_overlays()
            return False
        
        GLib.idle_add(_update_gui_threadsafe)

    def sync_overlays(self):
        current = set(self.overlays.keys())
        wins_set = set(self.wins)
        for w in list(current - wins_set):
            try:
                self.overlays[w].destroy()
            except:
                pass
            self.overlays.pop(w, None)

        for idx, w in enumerate(self.wins):
            if w not in self.overlays:
                # Create Overlay from imported class
                ov = Overlay(w, idx, color=self.config.get("overlay_color","#00FF00"),
                             show_broadcast=self.config.get("broadcast_enabled", True))
                self.overlays[w] = ov
            else:
                self.overlays[w].update(index=idx,
                                        color=self.config.get("overlay_color","#00FF00"),
                                        show_broadcast=self.config.get("broadcast_enabled", True))
        for w,ov in self.overlays.items():
            ov.place_on_window()

    def update_overlay_visibility(self):
        # This function is called by the poller.
        active = self.active_window
        
        if not self.config.get("overlay_enabled", True):
            for ov in self.overlays.values():
                ov.hide()
            return
            
        if not active or active not in self.wins:
            for ov in self.overlays.values():
                ov.hide()
        else:
            is_broadcasting = self.config.get("broadcast_enabled", True)
            for ov in self.overlays.values():
                ov.show()
                # Tell the overlay if it's the active one
                ov.update(
                    show_broadcast=is_broadcasting,
                    is_active=(ov.winid == active)
                )

    # ---------- layout ----------
    def apply_layout(self):
        if not self.wins:
            self.status_label.set_text("Nessuna finestra catturata")
            return
        mode = self.layout_combo.get_active_text()
        scr_w = Gdk.Screen.get_default().get_width()
        scr_h = Gdk.Screen.get_default().get_height()
        if mode == "Massimizza tutte":
            for w in self.wins:
                x11_utils.maximize_window(w)
        elif mode == "Allinea orizzontalmente":
            n = len(self.wins)
            if n == 0: return
            h = max(10, scr_h // n)
            y = 0
            for w in self.wins:
                x11_utils.move_resize_window(w, 0, y, scr_w, h)
                y += h
        elif mode == "Main left + affiancate right":
            if not self.wins: return
            main = self.wins[0]
            others = self.wins[1:]
            main_w = scr_w // 2; main_h = scr_h
            x11_utils.move_resize_window(main, 0, 0, main_w, main_h)
            if others:
                right_w = scr_w - main_w
                h = max(10, scr_h // len(others))
                y = 0
                for w in others:
                    x11_utils.move_resize_window(w, main_w, y, right_w, h)
                    y += h
        else: # "Nessuno" - apply custom size
            try:
                w = int(self.size_w.get_text()); h = int(self.size_h.get_text())
                if w <= 0 or h <= 0:
                    self.status_label.set_text("Dimensione invalida")
                    return
                per_row = max(1, scr_w // w)
                x = y = 0; cur = 0
                for win in self.wins:
                    x11_utils.move_resize_window(win, x, y, w, h)
                    cur += 1
                    x += w
                    if cur >= per_row and x < scr_w:
                        cur = 0; x = 0; y += h
            except Exception:
                self.status_label.set_text("Dimensione invalida")
        self.status_label.set_text("Layout applicato")
        GLib.timeout_add(500, self.sync_overlays)

    def minimize_all(self):
        for w in self.wins:
            x11_utils.minimize_window(w)
        self.status_label.set_text("Minimizzate tutte le finestre")
    
    def close_all_windows(self):
        for w in self.wins:
            x11_utils.close_window(w)
        self.status_label.set_text("Segnale di chiusura inviato")
        # We should probably rescan after a moment
        GLib.timeout_add(1000, self.refresh_windows)

    # ---------- config/save ----------
    def on_save_config(self):
        self.config["pattern"] = self.pattern_entry.get_text().strip()
        self.config["broadcast_enabled"] = bool(self.broadcast_check.get_active())
        self.config["overlay_enabled"] = bool(self.overlay_check.get_active())
        rgba = self.color_btn.get_rgba()
        hex_color = "#{:02x}{:02x}{:02x}".format(
            int(rgba.red * 255),
            int(rgba.green * 255),
            int(rgba.blue * 255)
        )
        self.config["overlay_color"] = hex_color

        self.config["inhibit_keys"] = [s.strip() for s in self.inhibit_entry.get_text().split(",") if s.strip()]

        try:
            self.config["window_size"] = [int(self.size_w.get_text()), int(self.size_h.get_text())]
        except:
            pass
        
        self.config["shortcuts"]["prev"] = self.short_prev.get_text().strip()
        self.config["shortcuts"]["next"] = self.short_next.get_text().strip()
        self.config["shortcuts"]["minimize_all"] = self.short_min.get_text().strip()
        self.config["shortcuts"]["close_all"] = self.short_close_all.get_text().strip()
        self.config["shortcuts"]["toggle_broadcast"] = self.short_toggle_broadcast.get_text().strip()
        self.config["shortcuts"]["toggle_overlay"] = self.short_toggle_overlay.get_text().strip()
        
        config.save_config(self.config)
        self.status_label.set_text("Configurazione salvata")
        
        # Update the master list of keys
        self.update_keys_to_grab()
        
        self.sync_overlays()

    def on_toggle_broadcast(self):
        self.config["broadcast_enabled"] = bool(self.broadcast_check.get_active())
        config.save_config(self.config)
        self.update_overlay_visibility()
        logging.info("Broadcast toggled: %s", self.config["broadcast_enabled"])

    def on_toggle_overlay(self):
        self.config["overlay_enabled"] = bool(self.overlay_check.get_active())
        config.save_config(self.config)
        self.update_overlay_visibility()
        logging.info("Overlay toggled: %s", self.config["overlay_enabled"])

    def on_color_change(self):
        # Convert Gdk.RGBA to a hex string (#RRGGBB) which Pango understands
        rgba = self.color_btn.get_rgba()
        hex_color = "#{:02x}{:02x}{:02x}".format(
            int(rgba.red * 255),
            int(rgba.green * 255),
            int(rgba.blue * 255)
        )
        self.config["overlay_color"] = hex_color
        
        config.save_config(self.config)
        self.sync_overlays()

    # ---------- poller AND event manager ----------
    def active_window_poller_and_grab_manager(self):
        """
        This single thread polls for the active window,
        manages key grabs, and processes all key events.
        """
        logging.info("Poller/Event Manager thread started.")
        while self.running:
            try:
                # --- 1. Poll Active Window ---
                new_active = x11_utils.get_active_window()
                
                if new_active != self.active_window:
                    logging.debug("Active changed: %s -> %s", self.active_window, new_active)
                    self.active_window = new_active
                    self.update_overlay_visibility()
                
                # --- 2. Manage Grabs ---
                is_in_game = (self.active_window in self.wins)
                
                if is_in_game and not self._grabbed_keycodes:
                    try:
                        # We just focused a game window. GRAB KEYS.
                        self._grabbed_keycodes = x11_utils.grab_keys_for_list(self.display, self.root, self._keys_to_grab)
                    except Exception as e:
                        logging.exception(f"Failed to GRAB keys: {e}")
                        
                elif (not is_in_game) and self._grabbed_keycodes:
                    try:
                        # We just left a game window. UNGRAB KEYS.
                        x11_utils.ungrab_keys_for_list(self.display, self.root, self._grabbed_keycodes)
                    except Exception as e:
                        logging.exception(f"Failed to UNGRAB keys: {e}")
                    finally:
                        self._grabbed_keycodes = []

                # --- 3. Process Key Events (Non-Blocking) ---
                # Check how many events are waiting
                while self.display.pending_events() > 0:
                    event = self.display.next_event()
                    self.process_key_press(event)

                # --- 4. Update Overlays ---
                if self.config.get("overlay_enabled", True):
                    for ov in list(self.overlays.values()):
                        ov.place_on_window()
                        
            except Exception:
                logging.exception("Poller error")
            
            # Sleep for a very short time for high responsiveness
            time.sleep(0.02) # 20ms

    # ---------- key listener logic ----------
    def update_keys_to_grab(self):
        """
        Updates the self._keys_to_grab MASTER list.
        Cleans shortcut keys to prevent "Unknown keysym" errors.
        """
        base_keys = []
        for c in range(ord('a'), ord('z')+1):
            base_keys.append(chr(c))
        for n in range(0,10):
            base_keys.append(str(n))
        for i in range(1,13):
            base_keys.append(f"F{i}")
        others = ["space","Tab","Return","Up","Down","Left","Right","minus","plus","BackSpace","Escape",
                  "Page_Up", "Page_Down", "Home", "End", "Insert", "Delete"]
        base_keys += others

        # Get shortcut keys to ADD them to the list
        shortcut_keys = set()
        shortcuts_dict = self.config.get("shortcuts", {})
        for key, value in shortcuts_dict.items():
            if not isinstance(value, (str, list)):
                continue
                
            key_list = value if isinstance(value, list) else [value]
            for sk in key_list:
                if not isinstance(sk, str):
                    continue
                # Clean the key part of the shortcut
                # "Alt + d " -> "d"
                # "<Alt>m" -> "m" (handles junk in config)
                key_part = sk.split('+')[-1].strip()
                if key_part:
                    shortcut_keys.add(key_part)
        
        self._keys_to_grab = list(set(base_keys + list(shortcut_keys)))
        logging.info(f"Master key list updated. Will grab {len(self._keys_to_grab)} keys on focus.")

    def process_key_press(self, event):
        """
        [FIX] Processes a single KeyPress event using a "guard clause"
        pattern for clarity and robustness.
        """
        try:
            if event.type != X.KeyPress:
                return # Not a key press, ignore.

            keysym = self.display.keycode_to_keysym(event.detail, 0)
            if not keysym: return
            keyname = XK.keysym_to_string(keysym)
            if not keyname: return
            
            kn = keyname
            if kn == 'ISO_Left_Tab': kn = 'Tab'
            
            state = event.state
            alt_pressed = bool(state & X.Mod1Mask)
            ctrl_pressed = bool(state & X.ControlMask)
            shift_pressed = bool(state & X.ShiftMask)
            
            logging.debug(f"Processing key: {kn} (Alt: {alt_pressed}, Ctrl: {ctrl_pressed})")

            # --- Guard Clause 1: Handle Shortcuts ---
            if self.handle_shortcuts(kn, alt_pressed, ctrl_pressed, shift_pressed):
                logging.debug(f"Key {kn} was a shortcut. Handled.")
                return

            # --- Guard Clause 2: Check Active Window ---
            active = self.active_window
            if not active:
                logging.warning(f"Key {kn} pressed, but no active window detected. Key swallowed.")
                return

            # --- Guard Clause 3: Check for Broadcast OFF ---
            if not self.config.get("broadcast_enabled", True):
                logging.debug("Broadcast OFF. Forwarding to active window only.")
                x11_utils.send_key_to_window(active, kn)
                return

            # --- Guard Clause 4: Check for Inhibited Key ---
            inhibited_keys = set([k.strip().lower() for k in self.config.get("inhibit_keys",[]) if k.strip()])
            if kn.lower() in inhibited_keys:
                logging.debug(f"Key {kn} is inhibited. Forwarding to active window only.")
                x11_utils.send_key_to_window(active, kn)
                return

            # --- Main Logic: Broadcast ---
            # If we are here: it's not a shortcut, broadcast is ON, and key is NOT inhibited.
            logging.debug(f"Broadcasting key {kn} to {len(self.wins)} windows.")
            for w in self.wins:
                try:
                    x11_utils.send_key_to_window(w, kn)
                except Exception:
                    logging.exception(f"Error broadcasting key {kn} to {w}")

        except Exception:
            if self.running:
                logging.exception("Critical error in process_key_press")

    # ---------- shortcut handling ----------
    def handle_shortcuts(self, keyname, alt, ctrl, shift):
        """
        [FIX] Returns True if shortcut handled.
        Normalizes both pressed key and config string for reliable matching.
        """
        # 1. Normalize the *current* key press
        parts = []
        if alt: parts.append("alt")
        if ctrl: parts.append("control")
        if shift: parts.append("shift")
        parts.append(keyname.lower())
        
        # Creates a clean string like "alt+d"
        combo_now = "+".join(parts)
        logging.debug(f"Shortcut check: combo_now = '{combo_now}'")

        def compare_shortcut(config_key):
            # 2. Get the shortcut string from config, e.g., "Alt + d"
            shortcut_str = self.config["shortcuts"].get(config_key, "")
            
            # 3. Normalize the *config* string
            shortcut_str = shortcut_str.lower()
            shortcut_parts = shortcut_str.split('+')
            cleaned_parts = [part.strip() for part in shortcut_parts if part.strip()]
            combo_config = "+".join(cleaned_parts)
            
            if not combo_config:
                return False
                
            return combo_now == combo_config

        if compare_shortcut("prev"):
            self.switch_prev()
            return True
        if compare_shortcut("next"):
            self.switch_next()
            return True
        if compare_shortcut("minimize_all"):
            self.minimize_all()
            return True
        if compare_shortcut("close_all"):
            self.close_all_windows()
            return True
        if compare_shortcut("toggle_broadcast"):
            self.toggle_broadcast_from_shortcut()
            return True
        if compare_shortcut("toggle_overlay"):
            self.toggle_overlay_from_shortcut()
            return True
            
        for idx, sk in enumerate(self.config["shortcuts"].get("window_keys", [])):
            # 4. Normalize window_keys config string
            shortcut_str = sk.lower()
            shortcut_parts = shortcut_str.split('+')
            cleaned_parts = [part.strip() for part in shortcut_parts if part.strip()]
            combo_config = "+".join(cleaned_parts)
            
            if combo_now == combo_config:
                self.focus_index(idx)
                return True
        return False

    def toggle_broadcast_from_shortcut(self):
        """Thread-safe toggle for broadcast."""
        def do_toggle():
            new_state = not self.broadcast_check.get_active()
            self.broadcast_check.set_active(new_state)
            return False
        GLib.idle_add(do_toggle)

    def toggle_overlay_from_shortcut(self):
        """Thread-safe toggle for overlay."""
        def do_toggle():
            new_state = not self.overlay_check.get_active()
            self.overlay_check.set_active(new_state)
            return False
        GLib.idle_add(do_toggle)

    # ---------- window switching ----------
    def switch_next(self):
        if not self.wins:
            return
        try:
            active = x11_utils.get_active_window()
            if active in self.wins:
                i = self.wins.index(active)
                i = (i + 1) % len(self.wins)
            else:
                i = 0
            
            target = self.wins[i]
            x11_utils.activate_window(target)
            logging.info("Switched next to %s", target)
        except Exception:
            logging.exception("switch_next error")

    def switch_prev(self):
        if not self.wins:
            return
        try:
            active = x11_utils.get_active_window()
            if active in self.wins:
                i = self.wins.index(active)
                i = (i - 1) % len(self.wins)
            else:
                i = 0
            
            target = self.wins[i]
            x11_utils.activate_window(target)
            logging.info("Switched prev to %s", target)
        except Exception:
            logging.exception("switch_prev error")

    def focus_index(self, idx):
        if idx < 0 or idx >= len(self.wins):
            return
        try:
            target = self.wins[idx]
            x11_utils.activate_window(target)
            logging.info("Focused window index %d -> %s", idx, target)
        except Exception:
            logging.exception("focus_index error")

    # ---------- cleanup ----------
    def on_destroy(self, *args):
        self.running = False
        logging.info("Shutting down")
        
        for ov in list(self.overlays.values()):
            try:
                ov.destroy()
            except: pass
        self.overlays.clear()

        try:
            if getattr(self, "_grabbed_keycodes", []):
                logging.debug("Ungrabbing all keys on exit...")
                x11_utils.ungrab_keys_for_list(self.display, self.root, self._grabbed_keycodes)
            
            self.display.flush()
            self.display.close() # <-- This is fine
        except Exception:
            logging.exception("Error during X11 cleanup")            

        Gtk.main_quit()

# ---------------------- main ----------------------
def main():
    # check X11
    if os.environ.get("XDG_SESSION_TYPE") == "wayland":
        print("Wayland detected - this tool requires X11.")
        dialog = Gtk.MessageDialog(
            transient_for=None,
            flags=0,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text="Wayland Not Supported"
        )
        dialog.format_secondary_text("This application requires X11 to function and will not work on a Wayland session.")
        dialog.run()
        dialog.destroy()
        sys.exit(1)
        
    app = MultiboxerApp()
    app.show_all()
    Gtk.main()

if __name__ == "__main__":
    main()
