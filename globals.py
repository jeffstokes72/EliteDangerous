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
SITE_LOCATION = None
class STATION_TYPE(Enum):
    Unknown = 0
    Orbital = 1
    Surface = 2
DOCKED_STATION_TYPE = STATION_TYPE.Unknown

# Configure user directories for different OS's
if platform.system() == "Windows":
    USER_DIR = os.path.join(os.getenv("LOCALAPPDATA", os.path.expanduser("~\\AppData\\Local")), "ArchitectTracker")
elif platform.system() == "Darwin":
    USER_DIR = os.path.join(os.path.expanduser("~/Library/Application Support"), "ArchitectTracker")
else:
    USER_DIR = os.path.join(os.path.expanduser("~/.config"), "ArchitectTracker")

os.makedirs(USER_DIR, exist_ok=True)

SAVE_FILE = os.path.join(USER_DIR, "construction_requirements.json")
LOG_FILE = os.path.join(USER_DIR, "EDMC_Architect_Log.txt")
CARRIER_FILE = os.path.join(USER_DIR, "fleet_carrier_cargo.json")
MARKET_LIB_PATH = os.path.join(USER_DIR, "market_library_v2.json")
COMMODITY_FILE = "commodity_list.txt"

#files created by EDMC
MARKET_JSON = os.path.join(os.getenv('USERPROFILE', os.path.expanduser('~')), 'Saved Games', 'Frontier Developments', 'Elite Dangerous', 'Market.json')
CARGO_JSON = os.path.join(os.getenv('USERPROFILE', os.path.expanduser('~')), 'Saved Games', 'Frontier Developments', 'Elite Dangerous', 'Cargo.json')

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
if not logger.hasHandlers():
    logger.addHandler(file_handler)
    
import fleetcarriercargotracker
CARRIER_TRACKER = fleetcarriercargotracker.FleetCarrierCargoTracker()
