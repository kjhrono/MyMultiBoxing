#!/usr/bin/env python3
# x11_utils.py
# All utility functions for interacting with X11, wmctrl, and xdotool.

import os
import subprocess
import logging
from Xlib import X, XK

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

def get_active_window():
    """Gets active window ID, returns empty string on failure."""
    try:
        out = subprocess.check_output(["xdotool","getactivewindow"]).decode().strip()
        return out if out else ""
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

def activate_window(winid):
    """Focuses/activates a window using xdotool."""
    try:
        subprocess.call(['xdotool','windowactivate','--sync', str(winid)])
    except Exception as e:
        logging.exception("activate_window error for win %s: %s", winid, e)

def send_key_to_window(winid, keyname):
    """
    [FIX] Invia tasti in modo differenziato.
    Usa 'type' per il testo (che funziona) e 'key' per i tasti speciali
    e i modificatori (che funziona per le scorciatoie).
    """
    try:
        cmd = ['xdotool']
        
        # Se è un singolo carattere stampabile (testo o numeri)
        if len(keyname) == 1 and keyname.isalnum():
            logging.debug(f"Invio come 'type' a {winid}: {keyname}")
            # Usiamo 'type' che funziona per il testo
            cmd.extend(['type', '--clearmodifiers', '--window', str(winid), keyname])
        
        # Se è un tasto speciale (Space, Return, Escape, Alt_L, F1, ecc.)
        else:
            logging.debug(f"Invio come 'key' a {winid}: {keyname}")
            # Usiamo 'key'
            cmd.extend(['key', '--window', str(winid), keyname])
            
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
    except Exception as e:
        logging.exception(f"Errore Popen send_key a {winid} per {keyname}: {e}")

# ------------------------- KEY GRABBING -------------------------

def grab_keys_for_list(disp, root, keys_to_grab):
    """Grabs a specific list of keys."""
    grabbed = []
    for k in keys_to_grab:
        try:
            keysym = XK.string_to_keysym(k) if isinstance(k,str) else 0
            if keysym==0:
                keysym = XK.string_to_keysym(k.upper())
            if keysym==0:
                logging.debug("Unknown keysym: %s", k)
                continue
            keycode = disp.keysym_to_keycode(keysym)
            if not keycode:
                continue

            root.grab_key(keycode, X.AnyModifier, False, X.GrabModeAsync, X.GrabModeAsync)
            grabbed.append(keycode)

        except Exception:
            logging.exception("grab_keys error for %s", k)

    logging.info(f"Grabbing {len(grabbed)} keys.")
    return grabbed

def ungrab_keys_for_list(disp, root, grabbed_keycodes):
    """Ungrabs the provided list of keycodes."""
    logging.info(f"Ungrabbing {len(grabbed_keycodes)} keys.")
    for keycode in grabbed_keycodes:
        try:
            root.ungrab_key(keycode, X.AnyModifier)
        except Exception:
            pass
    disp.flush()

def close_window(winid):
    """Sends a close signal to the window."""
    try:
        cmd = ['xdotool','windowclose', str(winid)]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        logging.exception("close_window Popen error for win %s: %s", winid, e)