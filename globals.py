import os
from enum import Enum
import platform
import logging
from logging.handlers import TimedRotatingFileHandler
from typing import Optional
import tkinter as tk

# Global vars
EDMC_ROOT = None
FCAPI_PAUSED = False
ARCHITECT_TRACKER_VER = "error"
ARCHITECT_GUI = None
EDMCframe: Optional[tk.Frame] = None
AT_BUTTON: Optional[tk.StringVar] = tk.StringVar(value="Show Architect Tracker (tracking disabled)")
DEFAULT_COLUMNS = {"Material": True, "Required": True, "Provided": True, "Needed": True,
                   "Pref Market": True, "Carrier Qty": True, "Ship Qty": True, "Shortfall": True
                  }
SHOW_UI_AT_START = True
class SHIP_MODE(Enum):
    Unknown = 0
    DockedAtMarket = 1
    DockedAtSite = 2
    DockedAtFC = 3
    Undocked = 4
SHIP_STATE = SHIP_MODE.Unknown
class MARKET_MODE(Enum):
    Cheapest = 0
    Closest = 1
    Alternate = 2
CURRENT_LOCATION = None
CURRENT_SYSTEM = None
SITE_LOCATION = None
class STATION_TYPE(Enum):
    Unknown = 0
    Orbital = 1
    Surface = 2
DOCKED_STATION_TYPE = STATION_TYPE.Unknown

# Where Steam/Proton keeps the Windows "Saved Games" folder for Elite Dangerous.
# Snap and Flatpak Steam relocate the whole steamapps tree, hence the several roots.
def find_proton_saved_games():
    home = os.path.expanduser("~")
    steam_roots = [
        os.path.join(home, ".steam", "steam"),
        os.path.join(home, ".steam", "root"),
        os.path.join(home, ".local", "share", "Steam"),
        os.path.join(home, ".var", "app", "com.valvesoftware.Steam", ".local", "share", "Steam"),
        os.path.join(home, "snap", "steam", "common", ".local", "share", "Steam"),
    ]
    suffix = os.path.join("steamapps", "compatdata", "359320", "pfx", "drive_c", "users",
                          "steamuser", "Saved Games", "Frontier Developments", "Elite Dangerous")
    paths = [os.path.join(root, suffix) for root in steam_roots]

    # Elite can also live on a secondary library disk, which Steam records here.
    for root in steam_roots:
        vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
        try:
            with open(vdf, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if '"path"' in line:
                        parts = line.split('"')
                        if len(parts) >= 4:
                            paths.append(os.path.join(parts[3], suffix))
        except OSError:
            continue

    for path in paths:
        if os.path.isdir(path):
            return path

    return None

# EDMC already resolves the journal directory for the platform it is running on,
# including a Windows "Saved Games" folder that has been redirected to OneDrive or
# moved to another drive, so always ask it before guessing.
def find_ed_journal_dir():
    candidates = []
    try:
        from config import config
        candidates.append(config.get_str('journaldir'))
        # On Linux this attribute is None, which str()s to "None"; isdir() rejects it.
        candidates.append(config.default_journal_dir)
    except Exception:
        pass

    if platform.system() == "Windows":
        candidates.append(os.path.join(os.getenv('USERPROFILE', os.path.expanduser('~')),
                                       'Saved Games', 'Frontier Developments', 'Elite Dangerous'))
    elif platform.system() == "Darwin":
        candidates.append(os.path.expanduser(
            "~/Library/Application Support/Frontier Developments/Elite Dangerous"))
    else:
        candidates.append(find_proton_saved_games())

    for path in candidates:
        if path:
            path = os.path.expanduser(path)
            if os.path.isdir(path):
                return path

    return None

# Configure user directories for different OS's
if platform.system() == "Windows":
    USER_DIR = os.path.join(os.getenv("LOCALAPPDATA", os.path.expanduser("~\\AppData\\Local")), "ArchitectTracker")
elif platform.system() == "Darwin":
    USER_DIR = os.path.join(os.path.expanduser("~/Library/Application Support"), "ArchitectTracker")
else:
    _legacy_user_dir = os.path.join(os.path.expanduser("~"), ".config", "ArchitectTracker")
    _xdg = os.environ.get("XDG_CONFIG_HOME")
    # Honour XDG_CONFIG_HOME, but never walk away from an existing install.
    if _xdg and not os.path.isdir(_legacy_user_dir):
        USER_DIR = os.path.join(os.path.expanduser(_xdg), "ArchitectTracker")
    else:
        USER_DIR = _legacy_user_dir

try:
    os.makedirs(USER_DIR, exist_ok=True)
except Exception as e:
    from tkinter import messagebox
    messagebox.showerror("Error", f"Could not create directory: {USER_DIR}\n\n{e}")
    
SAVE_FILE = os.path.join(USER_DIR, "construction_requirements.json")
LOG_FILE = os.path.join(USER_DIR, "EDMC_Architect_Log.txt")
CARRIER_FILE = os.path.join(USER_DIR, "fleet_carrier_cargo.json")
MARKET_LIB_PATH = os.path.join(USER_DIR, "market_library_v2.json")
COMMODITY_FILE = "commodity_list.txt"

#files created by EDMC. Always defined so nothing downstream has to guess.
ED_SAVE_PATH = None
MARKET_JSON = None
CARGO_JSON = None

def set_journal_dir(path):
    """Point the plugin at a journal directory, keeping the derived paths in step."""
    global ED_SAVE_PATH, MARKET_JSON, CARGO_JSON
    ED_SAVE_PATH = path
    MARKET_JSON = os.path.join(path, 'Market.json') if path else None
    CARGO_JSON = os.path.join(path, 'Cargo.json') if path else None
    return ED_SAVE_PATH

set_journal_dir(find_ed_journal_dir())

logger = logging.getLogger("ArchitectTracker")
logger.setLevel(logging.INFO)

file_handler = TimedRotatingFileHandler(
        LOG_FILE,
        when="midnight",    # rotate at midnight local time
        interval=1,         # every 1 day
        backupCount=7,      # <-- keep X days (set this to whatever you want)
        encoding="utf-8",
        utc=False           # EDMC uses local timestamps
    )
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s')
file_handler.setFormatter(formatter)
# hasHandlers() walks up to the root logger, so it goes True as soon as anything
# else configures logging and our own log file would never be written again.
if not logger.handlers:
    logger.addHandler(file_handler)
logger.propagate = False  # EDMC's log has its own copy of nothing useful from us
    
import fleetcarriercargotracker
CARRIER_TRACKER = fleetcarriercargotracker.FleetCarrierCargoTracker()
