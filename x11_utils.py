#!/usr/bin/env python3
# x11_utils.py
# All utility functions for interacting with X11, wmctrl, and xdotool.

import os
import subprocess
import logging
from Xlib import X, XK, display

from pynput import keyboard
import subprocess
import shlex

# Import path from config
from config import TMP_WINS_FILE

# ------------------------- UTILITIES -------------------------
def run_cmd(args):
    """Helper to run a command and return output"""
    try:
        return subprocess.check_output(args, stderr=subprocess.DEVNULL).decode().strip()
    except subprocess.CalledProcessError:
        return ""

def rescan_windows(pattern):
    """
    Returns list of window ids (decimal strings) matching pattern via xdotool.
    Saves to /tmp/multiboxer_windows
    Uses --onlyvisible and filters out this script's PID.
    """
    wins = []
    try:
        out = subprocess.check_output(['xdotool','search','--onlyvisible','--name', pattern]).decode().strip()
        ids = [l.strip() for l in out.splitlines() if l.strip()]
    except subprocess.CalledProcessError:
        ids = []

    # remove duplicati
    seen = set()
    ids_uniq = []
    for wid in ids:
        if wid not in seen:
            seen.add(wid)
            ids_uniq.append(wid)

    # filtra finestre del processo corrente
    pid_self = str(os.getpid())
    filtered = []
    for wid in ids_uniq:
        try:
            pid = subprocess.check_output(['xdotool','getwindowpid', wid]).decode().strip()
            if pid == pid_self:
                logging.debug(f"Filtered out own window {wid} with PID {pid}")
                continue
        except subprocess.CalledProcessError:
            pass # Window might have closed
        filtered.append(wid)

    # save
    try:
        with open(TMP_WINS_FILE, "w") as f:
            f.write("\n".join(filtered))
    except Exception as e:
        logging.exception("Error writing tmp windows file: %s", e)
        
    logging.info("Rescanned windows: %s", filtered)
    return filtered

def set_window_title(winid, title):
    """
    Tenta di impostare il titolo di una finestra usando xdotool.
    """
    logging.debug(f"Tentativo di rinominare {winid} in '{title}'")
    try:
        cmd = ['xdotool', 'set_window', '--name', title, str(winid)]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        logging.exception(f"Errore in set_window_title per {winid}: {e}")

def get_window_name(win_id):
    """Prende il nome della finestra dall'ID"""
    try:
        name = subprocess.check_output(
            ["xdotool", "getwindowname", str(win_id)], stderr=subprocess.DEVNULL
        ).decode().strip()
        return name
    except subprocess.CalledProcessError:
        return ""

def wmctrl_list():
    """
    returns dict winid -> (pid, desktop, x,y,w,h,title)
    winid is decimal string
    Uses 'wmctrl -lpG'
    """
    out = run_cmd(['wmctrl','-lpG'])
    d = {}
    for line in out.splitlines():
        parts = line.split(None, 7)
        if len(parts) < 8: continue
        wid_hex, desktop, pid, x, y, w, h, title = parts
        try:
            winid = str(int(wid_hex, 16))
            d[winid] = (pid, desktop, int(x), int(y), int(w), int(h), title)
        except Exception:
            logging.warning(f"Could not parse wmctrl line: {line}")
    return d

def get_window_geometry(winid):
    """Gets window geometry (x, y, w, h) from wmctrl_list or fallback."""
    m = wmctrl_list().get(str(winid))
    if m:
        # m is (pid, desktop, x, y, w, h, title)
        return m[2], m[3], m[4], m[5]
    # fallback
    try:
        out = run_cmd(['xwininfo','-id', str(winid)])
        x=y=w=h=0
        for l in out.splitlines():
            if "Absolute upper-left X" in l:
                x = int(l.split(":")[1])
            if "Absolute upper-left Y" in l:
                y = int(l.split(":")[1])
            if "Width" in l:
                w = int(l.split(":")[1])
            if "Height" in l:
                h = int(l.split(":")[1])
        return x,y,w,h
    except:
        return 0,0,100,40

def move_resize_window(winid, x, y, w, h):
    geom = f"0,{x},{y},{w},{h}"
    subprocess.call(['wmctrl','-ir', str(winid), '-e', geom])

def maximize_window(winid):
    subprocess.call(['wmctrl','-ir', str(winid), '-b', 'add,maximized_vert,maximized_horz'])

def minimize_window(winid):
    subprocess.call(['wmctrl','-ir', str(winid), '-b', 'add,hidden'])

def get_active_window():
    """Restituisce l'ID della finestra attiva (come stringa) o una stringa vuota."""
    try:
        # Usiamo check_output per catturare l'output
        out = subprocess.check_output(
            ["xdotool", "getactivewindow"], stderr=subprocess.DEVNULL
        ).decode().strip()
        return out if out else ""
    except subprocess.CalledProcessError:
        return ""

def activate_window(winid):
    """Focuses/activates a window using xdotool."""
    try:
        subprocess.call(['xdotool','windowactivate','--sync', str(winid)])
    except Exception as e:
        logging.exception("activate_window error for win %s: %s", winid, e)

def close_window(winid):
    """Sends a close signal to the window."""
    try:
        cmd = ['xdotool','windowclose', str(winid)]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        logging.exception("close_window Popen error for win %s: %s", winid, e)

# ------------------------- KEY GRABBING -------------------------
def grab_key(window, keyname, modifier_mask=X.AnyModifier):
    """Grab a key on the specified window with optional modifier mask."""
    try:
        # Use the global display instance
        from Xlib import display as xdisplay
        d = xdisplay.Display()
        
        keysym = XK.string_to_keysym(keyname)
        if keysym == 0:
            # Try with "Key_" prefix for special keys
            keysym = XK.string_to_keysym("Key_" + keyname)
        if keysym == 0:
            logging.warning(f"Could not find keysym for key: {keyname}")
            return None
            
        keycode = d.keysym_to_keycode(keysym)
        if keycode == 0:
            logging.warning(f"Could not find keycode for keysym: {keysym} ({keyname})")
            return None
            
        window.grab_key(keycode, modifier_mask, True,
                       X.GrabModeAsync, X.GrabModeAsync)
        logging.debug(f"Successfully grabbed key: {keyname} (keycode: {keycode}, modifiers: {modifier_mask})")
        return keycode
    except Exception as e:
        logging.exception(f"Error grabbing key {keyname}")
        return None

def ungrab_key(window, keycode, modifier_mask=X.AnyModifier):
    """Ungrab a key on the specified window."""
    try:
        window.ungrab_key(keycode, modifier_mask)
        logging.debug(f"Successfully ungrabbed keycode: {keycode}")
    except Exception as e:
        logging.warning(f"Error ungrabbing keycode {keycode}: {e}")

def send_key_to_window(winid, key_sequence):
    """
    Send a key sequence to a specific window using xdotool.
    key_sequence: can be single key "a" or modified "alt+a"
    """
    try:
        # Convert key sequence to xdotool format
        if '+' in key_sequence:
            # It's a modified key like "alt+a"
            parts = key_sequence.split('+')
            modifiers = parts[:-1]
            key = parts[-1]
            
            # Build xdotool command
            cmd = ['xdotool', 'key', '--window', str(winid)]
            for mod in modifiers:
                cmd.append(f'{mod.lower()}+')
            cmd.append(key.lower())
            
            # Flatten the command
            flat_cmd = []
            for item in cmd:
                if item.endswith('+'):
                    flat_cmd.append(item[:-1])  # Remove trailing +
                    flat_cmd.append('+')
                else:
                    flat_cmd.append(item)
            # Remove any trailing +
            if flat_cmd and flat_cmd[-1] == '+':
                flat_cmd.pop()
                
            subprocess.Popen(flat_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            # Simple key
            cmd = ['xdotool', 'key', '--window', str(winid), key_sequence.lower()]
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
        logging.debug(f"Sent key '{key_sequence}' to window {winid}")
        return True
        
    except Exception as e:
        logging.error(f"Error sending key to window {winid}: {e}")
        return False

def broadcast_key_to_windows(key_sequence, target_windows, exclude_window=None):
    """
    Broadcast a key sequence to all target windows except the exclude_window.
    """
    success_count = 0
    for winid in target_windows:
        if winid != exclude_window:
            if send_key_to_window(winid, key_sequence):
                success_count += 1
    logging.debug(f"Broadcast '{key_sequence}' to {success_count} windows (excluded: {exclude_window})")
    return success_count