#!/usr/bin/env python3
# config.py
# Holds all configuration constants and load/save functions.

import os
import json
import logging

# ------------------------- CONFIG / PATHS -------------------------
HOME = os.path.expanduser("~")
CONFIG_DIR = os.path.join(HOME, ".config", "multiboxer")
os.makedirs(CONFIG_DIR, exist_ok=True)
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
LOG_FILE = os.path.join(CONFIG_DIR, "debug.log")
TMP_WINS_FILE = "/tmp/multiboxer_windows"

# ------------------------- DEFAULT CONFIG -------------------------
# Default config
DEFAULT_CONFIG = {
  "pattern": "World of Warcraft",
  "broadcast_enabled": False,
  "overlay_enabled": True,
  "overlay_color": "#00FF00",
  "overlay_bgcolor": "#000000",
  "overlay_font_size": 36000,
  "inhibit_keys": ["Alt_L","Alt_R","Control_L","Control_R","Escape"],
  "window_size": [1280, 720],
  "maximize_windows": False,
  "shortcuts": {
    "prev": "Alt+a",
    "next": "Alt+d",
    "minimize_all": "Alt+m",
    "close_all": "Alt+CANC",
    "toggle_broadcast": "Alt+b",
    "toggle_overlay": "Alt+o",
    "window_keys": ["Alt+F1","Alt+F2","Alt+F3","Alt+F4","Alt+F5"]
  }
}

# ------------------------- LOAD/SAVE -------------------------

def load_config():
    """Loads config from file, or creates default."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except Exception:
            logging.exception("Failed to load config, falling back to default")
    
    # create default if load failed or file missing
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
    except Exception:
        logging.exception("Failed to create default config file")
        
    return DEFAULT_CONFIG.copy()

def save_config(config_data):
    """Saves the provided config data to the file."""
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config_data, f, indent=2)
        logging.info("Config saved")
    except Exception:
        logging.exception("Error saving config")