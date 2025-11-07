#!/usr/bin/env python3
# multiboxer_gui.py
# Main application file for the Multiboxer Control Center.

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

        self.config = config.load_config()
        self.wins = []
        self.overlays = {}
        self.original_titles = {} # Set original title of window for a roll-back when exiting
        
        self.active_window = x11_utils.get_active_window()
        self.display = display.Display()
        self.root = self.display.screen().root

        self._grabbed_keycodes = [] 
        self._keys_to_grab = [] 
        
        self.poll_thread = None
        self.running = True

        self.build_ui()
        self.refresh_windows()

        self.update_keys_to_grab() 
        
        self.poll_thread = threading.Thread(target=self.active_window_poller_and_grab_manager, daemon=True)
        self.poll_thread.start()

    # ---------- UI ----------
    def build_ui(self):
        grid = Gtk.Grid(column_spacing=8, row_spacing=8, margin=8)
        self.add(grid)
        row_index = 0 

        # --- 1. Gestione Finestre ---
        grid.attach(Gtk.Label(label="Pattern finestra:"), 0, row_index, 1, 1)
        self.pattern_entry = Gtk.Entry(); self.pattern_entry.set_text(self.config.get("pattern","World of Warcraft"))
        grid.attach(self.pattern_entry, 1, row_index, 2, 1)
        btn_rescan = Gtk.Button(label="Scansiona")
        btn_rescan.connect("clicked", lambda b: self.refresh_windows())
        grid.attach(btn_rescan, 3, row_index, 1, 1)
        row_index += 1

        grid.attach(Gtk.Label(label="Finestre catturate:"), 0, row_index, 4, 1)
        row_index += 1
        self.win_store = Gtk.ListStore(str, str)
        self.win_view = Gtk.TreeView(self.win_store)
        renderer = Gtk.CellRendererText()
        col1 = Gtk.TreeViewColumn("#", renderer, text=0)
        col2 = Gtk.TreeViewColumn("Title (id)", renderer, text=1)
        self.win_view.append_column(col1); self.win_view.append_column(col2)
        scrolled = Gtk.ScrolledWindow(); scrolled.set_min_content_height(160); scrolled.add(self.win_view)
        grid.attach(scrolled, 0, row_index, 4, 1)
        row_index += 1

        grid.attach(Gtk.Label(label="Layout:"), 0, row_index, 1, 1)
        self.layout_combo = Gtk.ComboBoxText()
        self.layout_combo.append_text("Nessuno")
        self.layout_combo.append_text("Massimizza tutte")
        self.layout_combo.append_text("Allinea orizzontalmente")
        self.layout_combo.append_text("Main left + affiancate right")
        self.layout_combo.set_active(0)
        grid.attach(self.layout_combo, 1, row_index, 2, 1) 
        btn_layout = Gtk.Button(label="Applica")
        btn_layout.connect("clicked", lambda b: self.apply_layout())
        grid.attach(btn_layout, 3, row_index, 1, 1)
        row_index += 1

        grid.attach(Gtk.Label(label="Dimensione (W x H):"), 0, row_index, 1, 1)
        self.size_w = Gtk.Entry(); self.size_w.set_text(str(self.config.get("window_size",[1280,720])[0]))
        self.size_h = Gtk.Entry(); self.size_h.set_text(str(self.config.get("window_size",[1280,720])[1]))
        size_box = Gtk.Box(spacing=6)
        size_box.pack_start(self.size_w, True, True, 0)
        size_box.pack_start(Gtk.Label(label="x"), False, False, 0)
        size_box.pack_start(self.size_h, True, True, 0)
        grid.attach(size_box, 1, row_index, 2, 1)
        btn_min_all = Gtk.Button(label="Minimizza tutte")
        btn_min_all.connect("clicked", lambda b: self.minimize_all())
        grid.attach(btn_min_all, 3, row_index, 1, 1)
        row_index += 1

        grid.attach(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), 0, row_index, 4, 1)
        row_index += 1

        # --- 2. Overlay (Semplificato) ---
        self.overlay_check = Gtk.CheckButton(label="Overlay abilitato")
        self.overlay_check.set_active(self.config.get("overlay_enabled", True))
        self.overlay_check.connect("toggled", lambda b: self.on_toggle_overlay())
        grid.attach(self.overlay_check, 0, row_index, 1, 1)

        grid.attach(Gtk.Label(label="Colore Testo:"), 1, row_index, 1, 1)
        self.color_btn = Gtk.ColorButton()
        rgba_fg = Gdk.RGBA()
        color_str_fg = self.config.get("overlay_color","#00FF00")
        if not rgba_fg.parse(color_str_fg): rgba_fg.parse("#00FF00")
        self.color_btn.set_rgba(rgba_fg)
        self.color_btn.connect("color-set", lambda cb: self.on_color_change()) # Rinominato
        grid.attach(self.color_btn, 2, row_index, 1, 1)
        
        grid.attach(Gtk.Label(label="Dimensione Font:"), 3, row_index, 1, 1)
        row_index += 1
        
        # Rimosso il selettore colore sfondo
        
        font_size_val = self.config.get("overlay_font_size", 36000)
        adjustment = Gtk.Adjustment(value=font_size_val, lower=10000, upper=80000, step_increment=1000, page_increment=5000)
        self.font_size_spin = Gtk.SpinButton(adjustment=adjustment)
        grid.attach(self.font_size_spin, 3, row_index, 1, 1) # Allineato col titolo
        row_index += 1 

        # --- Separatore ---
        grid.attach(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), 0, row_index, 4, 1)
        row_index += 1

        # --- 3. Broadcasting ---
        # ... (Invariato, con il checkbox cliccabile) ...
        self.broadcast_check = Gtk.CheckButton(label="Broadcast abilitato")
        self.broadcast_check.set_active(self.config.get("broadcast_enabled", False))
        self.broadcast_check.connect("toggled", lambda b: self.on_toggle_broadcast())
        grid.attach(self.broadcast_check, 0, row_index, 1, 1)
        broadcast_warning = Gtk.Label(label="(Nota: il broadcast non funziona correttamente)")
        broadcast_warning.set_xalign(0)
        grid.attach(broadcast_warning, 1, row_index, 3, 1)
        row_index += 1
        label_inhibit = Gtk.Label(label="Tasti da escludere (comma):")
        label_inhibit.set_xalign(0) 
        grid.attach(label_inhibit, 0, row_index, 1, 1) 
        self.inhibit_entry = Gtk.Entry(); self.inhibit_entry.set_text(",".join(self.config.get("inhibit_keys",[])))
        grid.attach(self.inhibit_entry, 1, row_index, 3, 1) 
        row_index += 1
        key_list = "Speciali: Escape, Page_Down, Page_Up, Home, End, Insert, Delete, Up, Down, Left, Right, Tab, space, Return, BackSpace, minus, plus, F1..F12"
        help_label = Gtk.Label(label=key_list)
        help_label.set_line_wrap(True)
        help_label.set_selectable(True)
        help_label.set_xalign(0)
        grid.attach(help_label, 0, row_index, 4, 1)
        row_index += 1
        grid.attach(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), 0, row_index, 4, 1)
        row_index += 1

        # --- 4. Shortcuts ---
        # ... (Invariato) ...
        label_shortcuts = Gtk.Label(label="Shortcuts (es: Alt+a, Control+s, Shift+F1, Alt+Control+Delete):")
        label_shortcuts.set_xalign(0)
        grid.attach(label_shortcuts, 0, row_index, 4, 1)
        row_index += 1
        grid.attach(Gtk.Label(label="Prev:"), 0,row_index,1,1);
        self.short_prev = Gtk.Entry(); self.short_prev.set_text(self.config["shortcuts"].get("prev","Alt+a"))
        grid.attach(self.short_prev, 1,row_index,1,1)
        grid.attach(Gtk.Label(label="Next:"), 2,row_index,1,1);
        self.short_next = Gtk.Entry(); self.short_next.set_text(self.config["shortcuts"].get("next","Alt+d"))
        grid.attach(self.short_next, 3,row_index,1,1)
        row_index += 1
        grid.attach(Gtk.Label(label="Minimize All:"), 0,row_index,1,1);
        self.short_min = Gtk.Entry(); self.short_min.set_text(self.config["shortcuts"].get("minimize_all","Alt+m"))
        grid.attach(self.short_min, 1,row_index,1,1)
        grid.attach(Gtk.Label(label="Close All:"), 2,row_index,1,1);
        self.short_close_all = Gtk.Entry(); self.short_close_all.set_text(self.config["shortcuts"].get("close_all","Alt+q"))
        grid.attach(self.short_close_all, 3,row_index,1,1)
        row_index += 1
        grid.attach(Gtk.Label(label="Toggle Overlay:"), 0,row_index,1,1);
        self.short_toggle_overlay = Gtk.Entry(); self.short_toggle_overlay.set_text(self.config["shortcuts"].get("toggle_overlay","Alt+o"))
        grid.attach(self.short_toggle_overlay, 1,row_index,1,1)
        grid.attach(Gtk.Label(label="Toggle Broadcast:"), 2,row_index,1,1);
        self.short_toggle_broadcast = Gtk.Entry(); self.short_toggle_broadcast.set_text(self.config["shortcuts"].get("toggle_broadcast","Alt+b"))
        grid.attach(self.short_toggle_broadcast, 3,row_index,1,1)
        row_index += 1
        grid.attach(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), 0, row_index, 4, 1)
        row_index += 1

        # --- 5. Azioni ---
        # ... (Invariato) ...
        btn_save = Gtk.Button(label="Salva config")
        btn_save.connect("clicked", lambda b: self.on_save_config())
        grid.attach(btn_save, 0, row_index, 1, 1)
        btn_quit = Gtk.Button(label="Quit")
        btn_quit.connect("clicked", lambda b: self.destroy())
        grid.attach(btn_quit, 3, row_index, 1, 1)
        row_index += 1
        self.status_label = Gtk.Label(label="")
        grid.attach(self.status_label, 0, row_index, 4, 1)

    # ---------- windows / overlays ----------
    def refresh_windows(self):
        pattern_base = self.pattern_entry.get_text().strip()
        pattern_custom_prefix = "WoW Finestra" # Il prefisso che usiamo
        
        logging.debug(f"Scansione per pattern base: '{pattern_base}'")
        wins1 = x11_utils.rescan_windows(pattern_base)
        
        logging.debug(f"Scansione per pattern custom: '{pattern_custom_prefix}'")
        wins2 = x11_utils.rescan_windows(pattern_custom_prefix)
        
        all_wins = list(set(wins1 + wins2))
        self.wins = [w for w in all_wins if w] 

        self.wins.sort()
        logging.debug(f"Finestre totali trovate e ordinate: {self.wins}")

        def _update_gui_threadsafe():
            self.win_store.clear()
            wmap = x11_utils.wmctrl_list()
            
            for i, w in enumerate(self.wins):
                # --- MODIFICA Punto 1 ---
                # 1. Salva il titolo originale VERO (se non già salvato)
                if w not in self.original_titles:
                    title_tuple = wmap.get(str(w), ("", "", "", "", "", "", ""))
                    original_title = title_tuple[-1] if title_tuple else ""
                    if original_title:
                        logging.debug(f"Salvo titolo originale per {w}: '{original_title}'")
                        self.original_titles[w] = original_title
                
                # 2. Crea il nuovo titolo usando il prefisso custom
                nuovo_titolo = f"{pattern_custom_prefix} {i + 1}"
                # --- FINE MODIFICA ---

                x11_utils.set_window_title(w, nuovo_titolo)
                self.win_store.append([str(i+1), f"{nuovo_titolo} ({w})"])
                
            self.sync_overlays()
            return False
        
        GLib.idle_add(_update_gui_threadsafe)

    # --- Passa il font_size ---
    def sync_overlays(self):
        logging.debug(f"Syncing overlays. Current wins: {self.wins}")
        current_ov_ids = set(self.overlays.keys())
        target_win_ids = set(self.wins)

        to_remove = current_ov_ids - target_win_ids
        if to_remove:
            logging.debug(f"Removing overlays for closed windows: {to_remove}")
            for w in list(to_remove):
                try: self.overlays[w].destroy()
                except Exception: pass
                self.overlays.pop(w, None)

        font_size = self.config.get("overlay_font_size", 36000)
        fg_color = self.config.get("overlay_color","#00FF00")
        
        for idx, w in enumerate(self.wins):
            if w not in self.overlays:
                logging.debug(f"Creating new overlay for win {w} at index {idx}")
                ov = Overlay(w, idx, 
                             color=fg_color,
                             font_size=font_size,
                             show_broadcast=self.config.get("broadcast_enabled", True))
                self.overlays[w] = ov
            else:
                logging.debug(f"Updating existing overlay for win {w} to index {idx}")
                self.overlays[w].update(index=idx,
                                        color=fg_color,
                                        font_size=font_size,
                                        show_broadcast=self.config.get("broadcast_enabled", True))
        
        logging.debug("Placing all overlays on windows.")
        for w,ov in self.overlays.items():
            ov.place_on_window()

    # --- Forza il riposizionamento ---
    def update_overlay_visibility(self):
        active = self.active_window
        
        if not self.config.get("overlay_enabled", True):
            for ov in self.overlays.values(): ov.hide()
            return
            
        if not active or active not in self.wins:
            # Siamo su una finestra non gestita, nascondi tutto
            for ov in self.overlays.values():
                ov.hide()
        else:
            # Siamo su una finestra gestita
            is_broadcasting = self.config.get("broadcast_enabled", False)
            font_size = self.config.get("overlay_font_size", 36000)
            fg_color = self.config.get("overlay_color","#00FF00")
            
            logging.debug(f"Updating visibility. Active Win ID: {active}")
            
            for win_id, ov in self.overlays.items():
                is_active = (win_id == active)
                
                # --- QUESTA E' LA LOGICA CORRETTA ---
                if is_active:
                    # È la finestra attiva: aggiorna e MOSTRA
                    logging.debug(f"  -> Showing Active Overlay for {win_id} (Index {ov.index})")
                    ov.update(
                        show_broadcast=is_broadcasting,
                        is_active=True,
                        font_size=font_size,
                        color=fg_color 
                    )
                    ov.show()
                    ov.place_on_window()
                else:
                    # NON è la finestra attiva: NASCONDI
                    logging.debug(f"  -> Hiding Inactive Overlay for {win_id} (Index {ov.index})")
                    ov.hide()
                # --- FINE LOGICA ---

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
        GLib.timeout_add(1000, self.refresh_windows)

    # ---------- config/save ----------
    def on_save_config(self):
        self.config["pattern"] = self.pattern_entry.get_text().strip()
        self.config["broadcast_enabled"] = bool(self.broadcast_check.get_active())
        self.config["overlay_enabled"] = bool(self.overlay_check.get_active())
        
        rgba_fg = self.color_btn.get_rgba()
        hex_color_fg = "#{:02x}{:02x}{:02x}".format(
            int(rgba_fg.red * 255), int(rgba_fg.green * 255), int(rgba_fg.blue * 255))
        self.config["overlay_color"] = hex_color_fg
        
        # Rimosso salvataggio bgcolor
        
        self.config["overlay_font_size"] = self.font_size_spin.get_value_as_int()
        self.config["inhibit_keys"] = [s.strip() for s in self.inhibit_entry.get_text().split(",") if s.strip()]

        try:
            self.config["window_size"] = [int(self.size_w.get_text()), int(self.size_h.get_text())]
        except: pass
        
        # ... (salvataggio shortcuts invariato) ...
        self.config["shortcuts"]["prev"] = self.short_prev.get_text().strip()
        self.config["shortcuts"]["next"] = self.short_next.get_text().strip()
        self.config["shortcuts"]["minimize_all"] = self.short_min.get_text().strip()
        self.config["shortcuts"]["close_all"] = self.short_close_all.get_text().strip()
        self.config["shortcuts"]["toggle_broadcast"] = self.short_toggle_broadcast.get_text().strip()
        self.config["shortcuts"]["toggle_overlay"] = self.short_toggle_overlay.get_text().strip()
        
        config.save_config(self.config)
        self.status_label.set_text("Configurazione salvata")
        
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

    def on_color_change(self): # Rinominata
        rgba = self.color_btn.get_rgba()
        hex_color = "#{:02x}{:02x}{:02x}".format(
            int(rgba.red * 255), int(rgba.green * 255), int(rgba.blue * 255))
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
                        self._grabbed_keycodes = x11_utils.grab_keys_for_list(self.display, self.root, self._keys_to_grab)
                    except Exception as e:
                        logging.exception(f"Failed to GRAB keys: {e}")
                        
                elif (not is_in_game) and self._grabbed_keycodes:
                    try:
                        x11_utils.ungrab_keys_for_list(self.display, self.root, self._grabbed_keycodes)
                    except Exception as e:
                        logging.exception(f"Failed to UNGRAB keys: {e}")
                    finally:
                        self._grabbed_keycodes = []

                # --- 3. Process Key Events (Non-Blocking) ---
                while self.display.pending_events() > 0:
                    event = self.display.next_event()
                    self.process_key_press(event)

                # --- 4. Update Overlays ---
                if self.config.get("overlay_enabled", True):
                    for ov in list(self.overlays.values()):
                        ov.place_on_window()
                        
            except Exception:
                logging.exception("Poller error")
            
            time.sleep(0.02) # 20ms

    # ---------- key listener logic ----------
    def update_keys_to_grab(self):
        base_keys = []
        for c in range(ord('a'), ord('z')+1): base_keys.append(chr(c))
        for n in range(0,10): base_keys.append(str(n))
        for i in range(1,13): base_keys.append(f"F{i}")
        others = ["space","Tab","Return","Up","Down","Left","Right","minus","plus","BackSpace","Escape",
                  "Page_Up", "Page_Down", "Home", "End", "Insert", "Delete"]
        base_keys += others

        shortcut_keys = set()
        shortcuts_dict = self.config.get("shortcuts", {})
        for key, value in shortcuts_dict.items():
            if not isinstance(value, (str, list)): continue
            key_list = value if isinstance(value, list) else [value]
            for sk in key_list:
                if not isinstance(sk, str): continue
                key_part = sk.split('+')[-1].strip()
                if key_part:
                    shortcut_keys.add(key_part)
        
        self._keys_to_grab = list(set(base_keys + list(shortcut_keys)))
        logging.info(f"Master key list updated. Will grab {len(self._keys_to_grab)} keys on focus.")

    def process_key_press(self, event):
        """
        [FIX] Implementa la logica del Punto 3:
        1. Inghiottiamo il tasto (owner_events=False)
        2. Controlliamo le scorciatoie
        3. Se non è scorciatoia, invia SEMPRE all'attiva
        4. Se broadcast è ON, invia anche alle altre
        """
        try:
            if event.send_event: return
            if event.type != X.KeyPress: return

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

            logging.debug(f"Processing REAL key: {kn} (Alt: {alt_pressed})")

            # --- Punto 2: Controllo Scorciatoie ---
            if self.handle_shortcuts(kn, alt_pressed, ctrl_pressed, shift_pressed):
                logging.debug(f"Key {kn} was a shortcut. Handled.")
                return # Non invia nessun tasto

            # --- Punto 3: Non è scorciatoia, invia ad attiva ---
            active = self.active_window
            if not active:
                logging.warning(f"Key {kn} pressed, but no active window. Key swallowed.")
                return
            
            logging.debug(f"Forwarding key '{kn}' to active window {active}")
            x11_utils.send_key_to_window(active, kn) # Invia

            # --- Punto 4: Controllo Broadcast ---
            if not self.config.get("broadcast_enabled", False):
                return # Broadcast disabilitato, abbiamo finito.
            
            inhibited_keys = set([k.strip().lower() for k in self.config.get("inhibit_keys",[]) if k.strip()])
            if kn.lower() in inhibited_keys:
                logging.debug(f"Key {kn} is inhibited. Not broadcasting.")
                return

            # Broadcast è ON e tasto non inibito: invia alle altre
            target_wins = [w for w in self.wins if w != active]
            logging.debug(f"Attempting broadcast of '{kn}' to {len(target_wins)} OTHER windows.")
            for w in target_wins:
                try:
                    x11_utils.send_key_to_window(w, kn)
                except Exception:
                    logging.exception(f"Error attempting broadcast of {kn} to {w}")

        except Exception:
            if self.running:
                logging.exception("Critical error in process_key_press")

    # ---------- shortcut handling ----------
    def handle_shortcuts(self, keyname, alt, ctrl, shift):
        parts = []
        if alt: parts.append("alt")
        if ctrl: parts.append("control")
        if shift: parts.append("shift")
        parts.append(keyname.lower())
        combo_now = "+".join(parts)
        logging.debug(f"Shortcut check: combo_now = '{combo_now}'")

        def compare_shortcut(config_key):
            shortcut_str = self.config["shortcuts"].get(config_key, "")
            shortcut_str = shortcut_str.lower()
            shortcut_parts = shortcut_str.split('+')
            cleaned_parts = [part.strip() for part in shortcut_parts if part.strip()]
            combo_config = "+".join(cleaned_parts)
            if not combo_config: return False
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
            # Leggi lo stato attuale del config, non del checkbox
            current_state = self.config.get("broadcast_enabled", False)
            new_state = not current_state
            # Imposta il config *e* il checkbox
            self.config["broadcast_enabled"] = new_state
            self.broadcast_check.set_active(new_state)
            logging.info(f"Broadcast toggled via shortcut to: {new_state}")
            # Non è necessario salvare qui, on_toggle_broadcast lo farà
            return False
        GLib.idle_add(do_toggle)

    def toggle_overlay_from_shortcut(self):
        """Thread-safe toggle for overlay."""
        def do_toggle():
            current_state = self.config.get("overlay_enabled", True)
            new_state = not current_state
            self.config["overlay_enabled"] = new_state
            self.overlay_check.set_active(new_state)
            logging.info(f"Overlay toggled via shortcut to: {new_state}")
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
        
        # --- AGGIUNTA: Ripristina titoli originali ---
        logging.debug("Ripristino titoli originali...")
        for winid, original_title in self.original_titles.items():
            if original_title: # Assicurati che non sia una stringa vuota
                try:
                    x11_utils.set_window_title(winid, original_title)
                except Exception:
                    logging.warning(f"Impossibile ripristinare titolo per {winid}")
        # --- FINE AGGIUNTA ---
        
        for ov in list(self.overlays.values()):
            try: ov.destroy()
            except: pass
        self.overlays.clear()

        try:
            if getattr(self, "_grabbed_keycodes", []):
                logging.debug("Ungrabbing all keys on exit...")
                x11_utils.ungrab_keys_for_list(self.display, self.root, self._grabbed_keycodes)
            self.display.flush()
            self.display.close() 
        except Exception:
            logging.exception("Error during X11 cleanup")        

        Gtk.main_quit()

# ---------------------- main ----------------------
def main():
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