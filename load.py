__version__ = "1.2.3"

"""
Displays commodities required, provided and needed when you land at a construction site,
market or fleet carrier and tracks cargo in your fleet carrier and starship.

Author: CMDR kfpopeye and ChatGPT
Date: 2025-04-08
Git: https://github.com/kfpopeye/EliteDangerous
License: GNU GENERAL PUBLIC LICENSE Version 2
"""

import json
import os
import logging
from logging.handlers import TimedRotatingFileHandler
import tkinter as tk
from tkinter import ttk
import tkinter.font as tkFont
import platform
from contextlib import suppress
from companion import CAPIData
import binascii
from theme import theme
from typing import Optional
import myNotebook as nb
from config import appname, config
from enum import Enum
import traceback
import semantic_version
from config import appversion
import webbrowser

import math
from typing import Union

# Global vars
EDMC_ROOT = None
FCAPI_PAUSED = False
ARCHITECT_TRACKER_VER = __version__
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

CURRENT_LOCATION = None
SITE_LOCATION = None

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
MARKET_LIB_PATH = os.path.join(USER_DIR, "market_library.json")
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
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(lineno)d - %(message)s')
file_handler.setFormatter(formatter)
if not logger.hasHandlers():
    logger.addHandler(file_handler)

# --- Settings persistence ---
def load_gui_settings():
    try:
        vis = {}
        cols = list(DEFAULT_COLUMNS.keys())
        for c in cols:
            key = "ArchTrack_" + c.replace(" ", "_")
            if config.get(key) is None:
                vis[c] = True
                logger.info(f"Key: %s not found using default setting.", key)
            else:
                vis[c] = config.get_bool(key)
        vis["Material"] = True

        if config.get('ArchTrack_hide_Provided') is None:
            hid = False
            logger.info(f"Hid not found using default settings.")
        else:
            hid = config.get_bool('ArchTrack_hide_Provided')

        if config.get('ArchTrack_theme') is None:
            theme = "Dark Mode"
            logger.info(f"Theme not found using default settings.")
        else:
            theme = config.get_str('ArchTrack_theme')

        if config.get('ArchTrack_cols') is None:
            col_display = cols
            logger.info(f"Column names not found using default settings.")
        else:
            col_display = config.get_list('ArchTrack_cols')

        if config.get('ArchTrack_tbg') is None:
            trans_bg = False
            logger.info(f"trans_bg not found using default settings.")
        else:
            trans_bg = config.get_bool('ArchTrack_tbg')

        if config.get('ArchTrack_wintop') is None:
            win_top = False
            logger.info(f"win_top not found using default settings.")
        else:
            win_top = config.get_bool('ArchTrack_wintop')

        if config.get('ArchTrack_opcamt') is None:
            opac_amt = 100
            logger.info(f"opac_amt not found using default settings.")
        else:
            opac_amt = config.get_int('ArchTrack_opcamt')

        return vis, hid, theme, col_display, trans_bg, win_top, opac_amt
    except Exception as e:
        logger.error(f"Error loading GUI settings: {e}")
        return DEFAULT_COLUMNS, False, "Dark Mode", cols

def save_gui_settings():
    logger.info(f"Saving settings.")
    if not ARCHITECT_GUI or not ARCHITECT_GUI.winfo_exists():
        return
    try:
        for col, vis in ARCHITECT_GUI.column_visibility.items():
            c = "ArchTrack_" + col.replace(" ", "_")
            config.set(c, vis)
        config.set('ArchTrack_hide_Provided', bool(ARCHITECT_GUI.hide_provided))
        config.set('ArchTrack_theme', str(ARCHITECT_GUI.theme))
        config.set('ArchTrack_showUI', bool(SHOW_UI_AT_START))
        config.set('ArchTrack_cols', list(ARCHITECT_GUI.column_names))
        config.set('ArchTrack_tbg', bool(ARCHITECT_GUI.trans_bg))
        config.set('ArchTrack_wintop', bool(ARCHITECT_GUI.win_top))
        config.set('ArchTrack_opcamt', int(ARCHITECT_GUI.opac_amount))
    except Exception as e:
        logger.error(f"Error saving GUI settings: {e}")

# --- Helpers ---
def calculate_distance(x1: Union[int, float], y1: Union[int, float], z1: Union[int, float], x2: Union[int, float], y2: Union[int, float], z2: Union[int, float]):
        return math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2 + (z1 - z2) ** 2)

def decode_vanity_name(hex_string):
    try:
        return binascii.unhexlify(hex_string).decode('utf-8')
    except Exception as e:
        logger.error(f"Failed to decode vanity name: {e}")
        return hex_string

def get_next_entry(dictionary, key):
    keys_iterator = iter(dictionary)
    for current_key in keys_iterator:
        if current_key == key:
            return next(keys_iterator, None)
    return None

# --- Fleet Carrier Cargo Tracker ---
class FleetCarrierCargoTracker:
    def __init__(self):
        self.commodities = {}
        self.carrier_name = ""
        self.callsign = ""
        self.load()

    # update from CAPI data
    def update(self, data):
        #store list of ALL cargo
        cargo_items = data.get('cargo', [])
        if not isinstance(cargo_items, list):
            logger.warning("Unexpected cargo data format.")
            return

        newcargo = {}
        for item in cargo_items:
            try:
                name = item.get("commodity")
                qty = item.get("qty", 0)
                if not name:
                    logger.warning("Missing commodity name in cargo item: %s. Skipping it.", item)
                    continue
                newcargo[name] = newcargo.get(name, 0) + qty #materials purchase at different prices have different slots
                logger.debug("Fleet carrier has %s tonnes of %s", qty, name)
            except Exception as e:
                logger.error("Error updating fleet carrier cargo from CAPI: %s", e)
                continue

        self.commodities.clear()
        self.commodities = newcargo

        carrier_info = data.get("name", {})
        hex_name = carrier_info.get("vanityName")
        self.carrier_name = decode_vanity_name(hex_name) if hex_name else "Unnamed Carrier"
        self.callsign = carrier_info.get("callsign", "")
        self.save()

    def apply_transfer_event(self, transfers):
        for transfer in transfers:
            name = transfer.get("Type").capitalize()
            qty = transfer.get("Count", 0)
            direction = transfer.get("Direction")
            if not name or qty <= 0 or direction not in ("tocarrier", "toship"):
                continue
            current = self.commodities.get(name, 0)
            if direction == "tocarrier":
                self.commodities[name] = current + qty
                logger.info("Transfered: %s x %s to carrier", name, qty)
            else:
                self.commodities[name] = max(0, current - qty)
                logger.info("Transfered: %s x %s to starship", name, qty)
        self.save()

    def apply_market_purchase(self, eventData):
        name = eventData.get("Type").capitalize()
        qty = eventData.get("Count", 0)
        current = self.commodities.get(name, 0)
        self.commodities[name] = max(0, current - qty)
        logger.info("Puchased: %s x %s from carrier", name, qty)
        self.save()

    def get_quantity(self, commodity_name):
        return self.commodities.get(commodity_name.capitalize(), 0)

    def save(self):
        try:
            with open(CARRIER_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "carrier_name": self.carrier_name,
                    "callsign": self.callsign,
                    "commodities": self.commodities
                }, f, indent=4)
        except Exception as e:
            logger.error("Error saving fleet carrier cargo: %s", e)

    def load(self):
        if not os.path.exists(CARRIER_FILE):
            return
        try:
            with open(CARRIER_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.carrier_name = data.get("carrier_name", "")
                self.callsign = data.get("callsign", "")
                self.commodities = data.get("commodities", {})
        except Exception as e:
            logger.error("Error loading fleet carrier cargo: %s", e)

CARRIER_TRACKER = FleetCarrierCargoTracker()

def is_station_complete(materials):
    return all(info["ProvidedAmount"] >= info["RequiredAmount"] for info in materials.values())

def save_facility_requirements(resources, station_name):
    materials = {r["Name"]: {"Name_Localised": r["Name_Localised"],
                                   "RequiredAmount": r["RequiredAmount"],
                                   "ProvidedAmount": r["ProvidedAmount"],
                                   "Price": r["Payment"]}
                     for r in resources}
    try:
        with open(SAVE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}

    if is_station_complete(materials) and station_name in data:
        logger.info("Facility %s is complete. Removing from list.", station_name)
        data.pop(station_name, None)
    else:
        data[station_name] = {"Location": CURRENT_LOCATION, "materials": materials}
        logger.info("Adding\\updating facility %s to list.", station_name)

    try:
        with open(SAVE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error("Error saving data: %s", e)

def load_facility_requirements():
    global SITE_LOCATION

    if not os.path.exists(SAVE_FILE):
        return {}
    try:
        with open(SAVE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.error("Error reading save file: %s", e)
        return {}
    cleaned = {s: info for s, info in data.items() if not is_station_complete(info.get("materials", {}))}
    if cleaned != data:
        try:
            with open(SAVE_FILE, "w", encoding="utf-8") as f:
                json.dump(cleaned, f, indent=4)
        except Exception as e:
            logger.error("Error writing cleaned data: %s", e)

    if not SITE_LOCATION and cleaned:
        first_site = next(iter(cleaned.values()))
        if first_site and first_site.get("Location"):
            SITE_LOCATION = first_site.get("Location")
            logger.info("Set site location to: %s", SITE_LOCATION)
        else:
            SITE_LOCATION = None

    return cleaned

def is_facility(station):
    # Load new data
    data = load_facility_requirements()
    # Prepare data for display
    cleaned = [
        (
          (full.split(':', 1)[-1].strip() if ':' in full else
           full.split(';', 1)[-1].strip() if ';' in full else full)
        )
        for full in data
    ]

    return station in cleaned

# load cargo for currently piloted ship
def load_starship_cargo_data():
    if not os.path.exists(CARGO_JSON):
        return []
    try:
        with open(CARGO_JSON, "r", encoding="utf-8") as f:
            cargo = json.load(f)
        return cargo.get("Inventory", [])
    except Exception as e:
        logger.error("Error loading cargo data: %s", e)
        return []

# is the item a construction commodity
COMMODITIES = None
def isItemConstructionCommodity(item) -> bool:
    global COMMODITIES

    if not os.path.exists(COMMODITY_FILE):
        logger.error("Commodity data file does not exist: %s", COMMODITY_FILE)
        return False

    if COMMODITIES is None:
        with open(COMMODITY_FILE, "r") as f:
            lines = [line.strip() for line in f]
        COMMODITIES = [f"${line}_name;" for line in lines]
        
    item_name = item.get("Name")
    if item_name in COMMODITIES:
        logger.debug("Item: %s is a construction commodity.", item_name)
        return True
    else:
        logger.debug("Item: %s is NOT a construction commodity.", item_name)
        return False

#a list of the cheapest and closest markets that are selling an item
def update_market_library() -> None:
    if not os.path.exists(MARKET_JSON):
        logger.warning("Market data file does not exist: %s", MARKET_JSON)
        return

    try:
        # Load existing persistent dictionary if available
        if os.path.exists(MARKET_LIB_PATH):
            with open(MARKET_LIB_PATH, "r", encoding="utf-8") as f:
                market_lib = json.load(f)
        else:
            market_lib = {}

        # Load market data from EDMC
        with open(MARKET_JSON, "r", encoding="utf-8") as f:
            market = json.load(f)

        station_name = market.get("StationName")
        items = market.get("Items", [])

        for item in items:
            if item.get("Stock", 0) > 0:  # Item is for sale
                item_name = item.get("Name")
                m_price = item.get("SellPrice")

                if item_name and isItemConstructionCommodity(item):
                    existing = market_lib.get(item_name, {})
                    cheap_entry = existing.get("CheapMarket")
                    
                    if not cheap_entry or m_price < cheap_entry["Price"]: # Update CheapMarket if cheaper or no entry
                        logger.debug("Updating CheapMarket for: %s", item_name)
                        existing["CheapMarket"] = {
                            "Price": m_price,
                            "StationName": station_name,
                            "Location": CURRENT_LOCATION
                        }
                    elif station_name == cheap_entry.get("StationName"): #update price if station is already cheapest entry
                        logger.debug("Updating price for: %s", item_name)
                        existing["CheapMarket"]["Price"] = m_price

                    # Update ClosestMarket if closer or no entry
                    close_entry = existing.get("ClosestMarket")
                    if close_entry:
                        existing_distance = calculate_distance(*close_entry["Location"], *SITE_LOCATION)
                    else:
                        existing_distance = float("inf")
                    if CURRENT_LOCATION and SITE_LOCATION:
                        new_distance = calculate_distance(*CURRENT_LOCATION, *SITE_LOCATION)
                    else:
                        new_distance = float("inf")
                    if new_distance < existing_distance:
                        logger.debug("Updating ClosestMarket for: %s", item_name)
                        existing["ClosestMarket"] = {
                            "Price": m_price,
                            "StationName": station_name,
                            "Location": CURRENT_LOCATION
                        }

                    market_lib[item_name] = existing

        # Save updated dictionary
        with open(MARKET_LIB_PATH, "w", encoding="utf-8") as f:
            json.dump(market_lib, f, indent=2)

    except json.JSONDecodeError as e:
        logger.error("JSON decode error: %s", e)
    except Exception as e:
        logger.error("Unexpected error: %s", e)
        logger.error("Traceback:\n%s", traceback.format_exc())

def get_prefMarket_name(material):
    try:
        # Load existing persistent dictionary if available
        if os.path.exists(MARKET_LIB_PATH):
            with open(MARKET_LIB_PATH, "r", encoding="utf-8") as f:
                market_lib = json.load(f)
        else:
            return ""

        resource = market_lib.get(material)
        if not resource:
            return ""
        pref_cheap_market = config.get_bool('ArchTrack_prefCheap')

        if pref_cheap_market:
            market = resource.get("CheapMarket")
            return market.get("StationName", "")
        else:
            market = resource.get("ClosestMarket")
            return market.get("StationName", "")

    except json.JSONDecodeError as e:
        logger.error("JSON decode error: %s", e)
    except Exception as e:
        logger.error("Unexpected error: %s", e)
        logger.error("Traceback:\n%s", traceback.format_exc())

def is_market_selling(material) -> bool:
    # Load market data from EDMC
    with open(MARKET_JSON, "r", encoding="utf-8") as f:
        market = json.load(f)

    # Load market info
    station_name = market.get("StationName")
    items = market.get("Items", [])

    for item in items:
        if material == item.get("Name"):
            if item and item.get("Stock", 0) > 0: #if item is for sale
                return True
    return False

class Tooltip:
    def __init__(self, widget, text, delay=400, follow_mouse=False):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.follow_mouse = follow_mouse

        self.tooltip = None
        self.after_id = None

        self.widget.bind("<Enter>", self._on_enter, add="+")
        self.widget.bind("<Leave>", self._on_leave, add="+")
        self.widget.bind("<ButtonPress>", self._on_leave, add="+")

        if follow_mouse:
            self.widget.bind("<Motion>", self._on_motion, add="+")

    # --------------------

    def _on_enter(self, event=None):
        self._schedule()

    def _on_leave(self, event=None):
        self._unschedule()
        self._hide()

    def _on_motion(self, event):
        if self.tooltip:
            self._position(event)

    # --------------------

    def _schedule(self):
        self._unschedule()
        self.after_id = self.widget.after(self.delay, self._show)

    def _unschedule(self):
        if self.after_id:
            self.widget.after_cancel(self.after_id)
            self.after_id = None

    # --------------------

    def _show(self):
        if self.tooltip:
            return

        root = self.widget.winfo_toplevel()

        self.tooltip = tk.Frame(
            root,
            bg="#FFFFEA",
            highlightbackground="black",
            highlightthickness=1,
            bd=0
        )

        label = tk.Label(
            self.tooltip,
            text=self.text,
            bg="#FFFFEA",
            justify="left",
            wraplength=250
        )
        label.pack(ipadx=6, ipady=4)

        self._position()

        # Force above everything in this window
        self.tooltip.lift()

    def _position(self, event=None):
        root = self.widget.winfo_toplevel()

        if event:
            x = event.x_root + 15
            y = event.y_root + 15
        else:
            x, y = self.widget.winfo_pointerxy()
            x += 15
            y += 15

        # Convert screen coords to root coords
        rx = root.winfo_rootx()
        ry = root.winfo_rooty()

        x -= rx
        y -= ry

        self.tooltip.place(x=x, y=y)

    def _hide(self):
        if self.tooltip:
            self.tooltip.destroy()
            self.tooltip = None

# --- GUI Definition ---
class ArchitectTrackerGUI(tk.Toplevel):
    edBlue = "#1fbeff"
    edOrange = "#ff8500"
    bgBlack = "#1a1a1a"
    column_visibility = {}
    canvas_tooltip = None

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Architect Tracker")
        self.geometry("800x600")
        self.configure(bg=self.bgBlack)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.column_visibility, self.hide_provided, self.theme, self.column_names, self.trans_bg, self.win_top, self.opac_amount = load_gui_settings()

        self.setAlpha(self.opac_amount)
        self.setStayOnTop(self.win_top)
        self.setTransparentBg(self.trans_bg)
        self.setStyle()
        load_facility_requirements()
        if not SITE_LOCATION:
            self._build_info_widgets()
        else:
            self._build_widgets()
            self.refresh()

    def setStayOnTop(self, val):
        self.win_top = val
        if platform.system() == "Darwin":
            self.wm_attributes("-topmost", self.win_top)
        elif platform.system() == "Windows":
            self.wm_attributes("-topmost", self.win_top)
        else:
            self.attributes('-topmost', self.win_top)

    def setAlpha(self, percentage):
        self.opac_amount = percentage
        if platform.system() == "Darwin":
            self.attributes("-alpha", self.opac_amount / 100)
        elif platform.system() == "Windows":
            self.attributes("-alpha", self.opac_amount / 100)
        else:
            self.wm_attributes("-alpha", self.opac_amount / 100)

    def setTransparentBg(self, val):
        self.trans_bg = val
        if self.theme == "Dark Mode":
            if self.trans_bg:
                if platform.system() == "Darwin":
                    self.wm_attributes("-transparent", self.trans_bg)
                    self.config(bg='systemTransparent')
                elif platform.system() == "Windows":
                    self.attributes('-transparentcolor', ArchitectTrackerGUI.bgBlack)
                else:
                    self.wm_attributes("-transparent", self.trans_bg)
            else:
                if platform.system() == "Darwin":
                    self.wm_attributes("-transparent", self.trans_bg)
                    self.config(bg='white')
                elif platform.system() == "Windows":
                    self.attributes('-transparentcolor', "red")
                else:
                    self.wm_attributes("-transparent", "red")
        elif self.theme == "Light Mode":
            if self.trans_bg:
                if platform.system() == "Darwin":
                    self.wm_attributes("-transparent", self.trans_bg)
                    self.config(bg='systemTransparent')
                elif platform.system() == "Windows":
                    self.attributes('-transparentcolor', '#d9d9d9')
                else:
                    self.wm_attributes("-transparent", '#d9d9d9')
            else:
                if platform.system() == "Darwin":
                    self.wm_attributes("-transparent", self.trans_bg)
                    self.config(bg='white')
                elif platform.system() == "Windows":
                    self.attributes('-transparentcolor', "red")
                else:
                    self.wm_attributes("-transparent", "red")

    def auto_size_tree(self):
        """Adjust column widths to fit content."""
        style_font = self.style.lookup("ArchTrack.Treeview", "font")
        font = tkFont.Font(font=style_font)

        for col in self.tree["columns"]:
            max_width = 0
            if col != "#0":  # Exclude the tree column
                for item in self.tree.get_children():
                    text = self.tree.set(item, col)
                    width = font.measure(text) + 10
                    max_width = max(max_width, width)
                text = self.tree.heading(col, "text")
                width = font.measure(text) + 10
                max_width = max(max_width, width)
                # Add some padding
                self.tree.column(col, width=max_width)

        self.update_idletasks()

        """Adjust height to fit content."""
        num_items = 0
        if self.tree.get_children():
            num_items = len(self.tree.get_children())
        self.tree.configure(height=num_items)
        self.update_idletasks()

    def setStyle(self):
        logger.info("setStyle theme is: %s", self.theme)

        self.style = ttk.Style()
        if self.theme == "Dark Mode":
            self.style.theme_use("clam")
            self.style.configure("ArchTrack.Treeview.Heading",
                                    background=ArchitectTrackerGUI.bgBlack,
                                    foreground=ArchitectTrackerGUI.edOrange)
            self.style.configure("ArchTrack.TButton",
                                    background=ArchitectTrackerGUI.bgBlack,
                                    foreground=ArchitectTrackerGUI.edOrange,
                                    padding=(6, 2))
            self.style.configure("ArchTrack.Vertical.TScrollbar",
                                    gripcount=0,
                                    background=ArchitectTrackerGUI.bgBlack,  # Dark background for the scrollbar
                                    troughcolor=ArchitectTrackerGUI.bgBlack,  # Match trough to background
                                    lightcolor=ArchitectTrackerGUI.edOrange,
                                    darkcolor=ArchitectTrackerGUI.edOrange,
                                    sliderlength=20,  # Length of the slider
                                    sliderrelief="flat",
                                    thickness=12,  # Scrollbar thickness
                                    arrowcolor=ArchitectTrackerGUI.edOrange)  # Color for the arrows
            self.style.configure("ArchTrack.Treeview",
                                    background=ArchitectTrackerGUI.bgBlack,
                                    foreground=ArchitectTrackerGUI.edOrange,
                                    rowheight=24,
                                    selectbackground=ArchitectTrackerGUI.bgBlack)
            self.style.configure("ArchTrack.TCombobox",
                                    background=ArchitectTrackerGUI.bgBlack,
                                    foreground=ArchitectTrackerGUI.edOrange,
                                    selectbackground=ArchitectTrackerGUI.bgBlack,
                                    arrowcolor=ArchitectTrackerGUI.edOrange)
            self.style.configure("ArchTrack.TFrame",
                                    background=ArchitectTrackerGUI.bgBlack)
            self.style.configure("ArchTrack.TLabel",
                                    background=ArchitectTrackerGUI.bgBlack,
                                    foreground=ArchitectTrackerGUI.edOrange)
            self.style.map("ArchTrack.TButton",
               foreground=[("disabled", ArchitectTrackerGUI.bgBlack)],  # Color for disabled text
               background=[("disabled", "#7d7d7d")])  # Color for disabled background
            self.style.map("ArchTrack.Treeview", foreground=[("selected", ArchitectTrackerGUI.edBlue)])
            self.style.map("ArchTrack.TCombobox",
                                fieldbackground=[('readonly', ArchitectTrackerGUI.bgBlack)], # Background color of the entry field
                                background=[('readonly', ArchitectTrackerGUI.bgBlack)]) # Background color of the dropdown list
        elif self.theme == "Light Mode":
            self.style.theme_use("default")  # Use default theme
            self.style.configure("Treeview", rowheight=24)

    def _build_info_widgets(self):
        frame = ttk.Frame(self, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text="Construction site data not found!",
                  background=self.bgBlack,
                  foreground=self.edOrange).grid(row=0, column=0, sticky="w", padx=10)
        ttk.Label(frame,
                  text="Visit a construction site and the required commodities will automatically be displayed.",
                  background=self.bgBlack,
                  foreground=self.edOrange).grid(row=1, column=0, sticky="w", padx=10)
        self.update_idletasks()
        self.geometry(f"{self.winfo_reqwidth()}x{self.winfo_reqheight()}")

    def _build_widgets(self):
        frame = ttk.Frame(self, padding=8, style="ArchTrack.TFrame")
        frame.pack(fill=tk.BOTH, expand=True)

        # Top controls (row 0)
        dropframe = ttk.Frame(frame, padding=8, style="ArchTrack.TFrame")
        dropframe.grid(row=0, column=0, sticky="nsew", padx=(0, 2))

        self.deleteStation = ttk.Button(dropframe, text="X", style="ArchTrack.TButton", width=1, command=self.on_delete_station)
        self.deleteStation.grid(row=0, column=0, sticky="w")
        Tooltip(self.deleteStation, "Delete the site currently shown.")

        self.station_var = tk.StringVar()
        self.station_var.trace_add("write", self._on_change_station_var)
        self.dropdown = ttk.Combobox(dropframe, textvariable=self.station_var, state="readonly", style="ArchTrack.TCombobox")
        self.dropdown.grid(row=0, column=1, sticky="w", padx=(0, 2))
        self.dropdown.bind("<<ComboboxSelected>>", lambda e: self.refresh())

        self.changeToPrevStation = ttk.Button(dropframe, text="<", style="ArchTrack.TButton", width=1, command=self.on_prev_station)
        self.changeToPrevStation.grid(row=0, column=2, sticky="w")
        Tooltip(self.changeToPrevStation, "Change to the previous site.")

        self.changeStation = ttk.Button(dropframe, text=">", style="ArchTrack.TButton", width=1, command=self.on_next_station)
        self.changeStation.grid(row=0, column=3, sticky="w")
        Tooltip(self.changeStation, "Change to the next site.")

        marketframe = ttk.Frame(frame, padding=8, style="ArchTrack.TFrame")
        marketframe.grid(row=0, column=3, sticky="nsew", padx=(0, 2))

        self.togglePrefStation = ttk.Button(marketframe, text="$\\Ly", style="ArchTrack.TButton", width=4, command=self.on_toggle_prefMarket)
        self.togglePrefStation.grid(row=0, column=0, sticky="w")
        Tooltip(self.togglePrefStation, "Switch between closest and cheapest market.")

        ttk.Label(marketframe, text="Preferred Market:", style="ArchTrack.TLabel").grid(row=0, column=1, sticky="e", padx=(0, 5))
        self.market_name_label = ttk.Label(marketframe, text="", style="ArchTrack.TLabel")
        self.market_name_label.grid(row=0, column=2, sticky="w")
        cheap = config.get_bool('ArchTrack_prefCheap')
        if cheap:
            self.market_name_label['text'] = 'cheapest ($)'
        else:
            self.market_name_label['text'] = 'closest (Ly)'

        carrierframe = ttk.Frame(frame, padding=8, style="ArchTrack.TFrame")
        carrierframe.grid(row=0, column=5, sticky="nsew", padx=(0, 2))

        self.canvas = tk.Canvas(carrierframe, width=25, height=25)
        self.canvas.grid(row=0, column=0, sticky="w")
        self.draw_canvas()

        ttk.Label(carrierframe, text="Carrier:", style="ArchTrack.TLabel").grid(row=0, column=1, sticky="e", padx=(0, 5))
        self.carrier_label = ttk.Label(carrierframe, text="", style="ArchTrack.TLabel")
        self.carrier_label.grid(row=0, column=2, sticky="w")

        # Treeview setup (row 1)
        cols = list(DEFAULT_COLUMNS.keys())
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", style="ArchTrack.Treeview")
        for idx, c in enumerate(cols):
            self.tree.heading(c, text=self.column_names[idx])
            self.tree.column(c, anchor='w' if c == "Material" else 'center')

        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview, style="ArchTrack.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.grid(row=1, column=0, columnspan=7, sticky="nsew")
        scrollbar.grid(row=1, column=7, sticky="ns")

        # Make row 1 expandable
        frame.rowconfigure(1, weight=1)
        for i in range(8):
            frame.columnconfigure(i, weight=1 if i < 7 else 0)

        self.refresh_columns()  # Ensure columns initial visibility

    def draw_canvas(self):
        if self.theme == "Dark Mode":
            bg = self.style.lookup("ArchTrack.TButton", "background")
            fg = self.style.lookup("ArchTrack.TButton", "foreground")
            active_bg = self.style.lookup("ArchTrack.TButton", "background", state=("active",))
        else:
            bg = self.style.lookup("TButton", "background")
            fg = self.style.lookup("TButton", "foreground")
            active_bg = self.style.lookup("TButton", "background", state=("active",))

        # Clear canvas first
        self.canvas.delete("all")

        # Draw main rectangle
        self.rect_id = self.canvas.create_rectangle(
            0, 0, 25, 25,
            fill=bg,
            outline="black",
            tags="canvas_button"
        )

        # Draw play/pause symbol
        if FCAPI_PAUSED:
            self.canvas.create_rectangle(7, 5, 12, 20, fill=fg, outline="black", tags="canvas_button")
            self.canvas.create_rectangle(15, 5, 20, 20, fill=fg, outline="black", tags="canvas_button")
            tooltip_text = "Press to UNpause\ncarrier updates."
        else:
            self.canvas.create_polygon(7, 5, 7, 20, 20, 13, fill=fg, outline="black", tags="canvas_button")
            tooltip_text = "Press to pause\ncarrier updates."

        # Attach tooltip to the canvas itself (not individual items)
        if hasattr(self, "canvas_tooltip") and self.canvas_tooltip:
            self.canvas_tooltip._hide()
        self.canvas_tooltip = Tooltip(self.canvas, tooltip_text, follow_mouse=True)

        # Bind hover for rectangle color
        self.canvas.tag_bind("canvas_button", "<Enter>", lambda e: self.canvas.itemconfig(self.rect_id, fill=active_bg))
        self.canvas.tag_bind("canvas_button", "<Leave>", lambda e: self.canvas.itemconfig(self.rect_id, fill=bg))

        # Bind click for canvas (anywhere)
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        
    def _on_change_station_var(self, *args):
        if self.station_var.get() == '-All-':
            self.deleteStation.config(state="disabled")
        else:
            self.deleteStation.config(state="enabled")

    def _on_canvas_hover(self, event, color):
        self.canvas.itemconfig("canvas_button", fill=color)

    def refresh(self):
        # Remember the currently selected station name
        current_selection = self.station_var.get()

        # Load new data
        data = load_facility_requirements()
        self.data = data

        # Prepare data for display
        display = [
            (
              (full.split(':', 1)[-1].strip() if ':' in full else
               full.split(';', 1)[-1].strip() if ';' in full else full),
              full
            )
            for full in data
        ]
        self.station_map = {name: full for name, full in display}
        self.station_map['-All-'] = None

        # Update dropdown
        values = [name for name, _ in display]
        values.insert(0, '-All-')
        self.dropdown['values'] = values

        # Restore selection or default to first station
        if values:
            if current_selection in values:
                self.station_var.set(current_selection)
            else:
                self.station_var.set(values[0])

            # Refresh data for selected station
            self.display_station()
        else:
            # No data - clear tree
            self.tree.delete(*self.tree.get_children())

        # Set the carrier label
        self.carrier_label['text'] = CARRIER_TRACKER.carrier_name or 'N/A'

        self.draw_canvas() #resets pause button

        self.update_idletasks()
        self.auto_size_tree()
        width = self.winfo_reqwidth()
        height = self.winfo_reqheight()
        '''
        #is this needed for VR?
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        if height > screen_height:
            height = screen_height
        '''
        self.geometry(f"{width}x{height}")

    def display_station(self):
        self.tree.delete(*self.tree.get_children())
        sel = self.station_var.get()

        if sel == '-All-':
            materials = {}
            for site in self.data.values():
                for material_key, info in site['materials'].items():
                    if material_key not in materials:
                        materials[material_key] = {
                            'Name_Localised': info['Name_Localised'],
                            'RequiredAmount': 0,
                            'ProvidedAmount': 0
                        }
                    materials[material_key]['RequiredAmount'] += info['RequiredAmount']
                    materials[material_key]['ProvidedAmount'] += info['ProvidedAmount']
        else:
            full = self.station_map.get(sel)
            if not full:
                return
            materials = self.data[full]['materials']

        cargo_items = load_starship_cargo_data()
        # Create lookup for cargo items
        cargo_lookup = {i.get('Name'): i for i in cargo_items}

        # Set the alternating row and highlight colours
        if self.theme == "Dark Mode":
            if self.trans_bg:
                self.tree.tag_configure('evenrow', background=self.bgBlack)
            else:
                self.tree.tag_configure('evenrow', background='#2a2a2a')
            self.tree.tag_configure('oddrow', background=self.bgBlack)
            self.tree.tag_configure('highlightedrow', foreground=self.edBlue)
        else:
            if self.trans_bg:
                self.tree.tag_configure('oddrow', background='#d9d9d9')
            else:
                self.tree.tag_configure('oddrow', background='#ffffff')
            self.tree.tag_configure('evenrow', background='#d9d9d9')
            self.tree.tag_configure('highlightedrow', foreground='#ff6347')
        
        self.tree.tag_configure('totalsrow', font=('TkDefaultFont', 10, 'bold'))
            
        req_total = 0
        prov_total = 0
        need_total = 0
        fc_total = 0
        ship_total = 0
        short_total = 0
        rows_index = 0

        # Insert the materials into the tree
        for idx, (mat, vals) in enumerate(sorted(materials.items())):
            req = vals['RequiredAmount']
            prov = vals['ProvidedAmount']
            if self.hide_provided and prov >= req:
                continue
            safeMat = mat.replace("$", "").replace("_name;", "")
            locName = vals['Name_Localised']
            need = req - prov

            pref_market = get_prefMarket_name(mat)

            # Get fleet carrier and ship cargo quantities
            #TODO: change these to use $_name (can't till EDMC updates cargo and fc)
            fc_qty = CARRIER_TRACKER.get_quantity(safeMat)
            ship_qty = cargo_lookup.get(safeMat, {}).get('Count', 0)

            # Calculate shortage
            short = max(0, need - (fc_qty + ship_qty))

            # Determine row color based on even or odd index
            row_tag = 'evenrow' if idx % 2 == 0 else 'oddrow'
            tags = [row_tag]

            if SHIP_STATE == SHIP_MODE.DockedAtMarket:
                for_sale = is_market_selling(mat)
                if for_sale and short > 0:
                    tags.append('highlightedrow')
            elif SHIP_STATE == SHIP_MODE.DockedAtFC:
                if need > 0 and fc_qty > 0:
                    tags.append('highlightedrow')
            elif SHIP_STATE == SHIP_MODE.DockedAtSite:
                if need > 0 and ship_qty > 0:
                    tags.append('highlightedrow')

            # Insert row into the tree view
            self.tree.insert("", "end", values=(locName, req, prov, need, pref_market,
                                               fc_qty, ship_qty, short), tags=tuple(tags))
                                               
            rows_index += 1
            req_total = req_total + req
            prov_total = prov_total + prov
            need_total = need_total + need
            fc_total = fc_total + fc_qty
            ship_total = ship_total + ship_qty
            short_total = short_total + short
            
        total_row_tag = 'evenrow' if rows_index % 2 == 0 else 'oddrow'
        tags = (total_row_tag, 'totalsrow')
        self.tree.insert("", "end", values=("Totals", req_total, prov_total, need_total, "",
                                               fc_total, ship_total, short_total), tags=tuple(tags))

    def on_close(self):
        AT_BUTTON.set("Show Architect Tracker (tracking disabled)")
        self.destroy()  # Close the window

    def on_canvas_click(self, event):
        global FCAPI_PAUSED
        FCAPI_PAUSED = not FCAPI_PAUSED
        if FCAPI_PAUSED:
            logger.info(f'Fleet carrier API paused.')
        else:
            logger.info(f'Fleet carrier API UNpaused.')
        self.draw_canvas()

    def on_next_station(self):
        values = self.dropdown['values']
        if not values:
            logger.info("No stations to switch to.")
            return

        next_ndx = self.dropdown.current() + 1
        if next_ndx >= len(values):
            next_ndx = 0

        self.dropdown.current(next_ndx)
        logger.info("Changing to station: %s", self.dropdown.get())
        self.refresh()

    def on_prev_station(self):
        values = self.dropdown['values']
        if not values:
            logger.info("No stations to switch to.")
            return

        prev_ndx = self.dropdown.current() - 1
        if prev_ndx <= -1:
            prev_ndx = len(values) - 1

        self.dropdown.current(prev_ndx)
        logger.info("Changing to station: %s", self.dropdown.get())
        self.refresh()

    def change_station(self, station):
        short_name = (station.split(':', 1)[-1].strip() if ':' in station else
                        station.split(';', 1)[-1].strip() if ';' in station
                        else station)

        values = self.dropdown['values']
        if not values:
            logger.info("No stations to switch to.")
            return

        if short_name in values:
            self.station_var.set(short_name)
            return
        else:
            self.refresh()
            
        values = self.dropdown['values']
        if short_name in values:
            self.station_var.set(short_name)
            return
        else:
            logger.info("Could not change to station: %s", short_name)

    def on_delete_station(self):
        sel = self.station_var.get()
        station_name = self.station_map.get(sel)
        if self.data.pop(station_name, None):
            logger.info("Deleted station: %s", station_name)
        else:
            logger.info("Could not delete station: %s", station_name)

        try:
            with open(SAVE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=4)
        except Exception as e:
            logger.error("Error saving data: %s", e)

        self.refresh()

    def reset_Style(self, new_theme):
        self.theme = new_theme
        logger.info("reset_Style theme is: %s", self.theme)
        self.setStyle()
        self.refresh()

    def toggle_column(self, column, is_visible: bool):
        self.column_visibility[column] = is_visible
        self.refresh_columns()

    def toggle_hide_provided(self, val):
        self.hide_provided = val
        self.refresh()

    def refresh_columns(self):
        visible_columns = [col for col, vis in self.column_visibility.items() if vis]
        self.tree["displaycolumns"] = visible_columns
        """for col in visible_columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=100)"""

    def on_toggle_prefMarket(self):
        old = config.get_bool('ArchTrack_prefCheap')
        config.set('ArchTrack_prefCheap', bool(not old))
        if not old:
            self.market_name_label['text'] = 'cheapest ($)'
        else:
            self.market_name_label['text'] = 'closest (Ly)'
        self.refresh()

    def rename_column(self, c, v):
        self.tree.heading(c, text=v)
        cols = self.tree["columns"]
        col_index = cols.index(c)
        self.column_names[col_index] = v

# --- Plugin Hooks ---
def show_gui():
    global ARCHITECT_GUI
    global AT_BUTTON

    if not ARCHITECT_GUI or not ARCHITECT_GUI.winfo_exists():
        ARCHITECT_GUI = ArchitectTrackerGUI(EDMC_ROOT)
    else:
        ARCHITECT_GUI.lift()
        ARCHITECT_GUI.refresh()
    AT_BUTTON.set("Hide Architect Tracker (tracking)")

def toggle_gui():
    global ARCHITECT_GUI
    global AT_BUTTON

    if not ARCHITECT_GUI or not ARCHITECT_GUI.winfo_exists():
        AT_BUTTON.set("Hide Architect Tracker (tracking)")
        ARCHITECT_GUI = ArchitectTrackerGUI(EDMC_ROOT)
    else:
        AT_BUTTON.set("Show Architect Tracker (tracking disabled)")
        ARCHITECT_GUI.destroy()

def plugin_start3(plugin_dir):
    global SHOW_UI_AT_START
    global FCAPI_PAUSED
    global COMMODITY_FILE

    logger.info("Starting Architect Tracker plugin (%s)", ARCHITECT_TRACKER_VER)

    # Up until 5.0.0-beta1 config.appversion is a string
    if isinstance(appversion, str):
        core_version = semantic_version.Version(appversion)
    elif callable(appversion):
        # From 5.0.0-beta1 it's a function, returning semantic_version.Version
        core_version = appversion()
    # Yes, just blow up if config.appverison is neither str nor callable
    logger.info(f'Core EDMarketConnector version: {core_version}')

    COMMODITY_FILE = os.path.join(plugin_dir, COMMODITY_FILE)

    if config.get('ArchTrack_fcapimode') is None:
        fcapi_mode = "First then pause"
        config.set('ArchTrack_fcapimode', fcapi_mode)
        logger.info(f"fcapi_mode not found using default settings.")
    else:
        fcapi_mode = config.get_str('ArchTrack_fcapimode')

    if fcapi_mode == "Only when unpaused":
        FCAPI_PAUSED = True
        logger.info(f'Fleet carrier API paused.')

    SHOW_UI_AT_START = config.get_bool('ArchTrack_showUI')
    if SHOW_UI_AT_START:
        show_gui()
    return "ArchitectTracker"

def on_key_press(event):
    if event.char == 't':
       toggle_gui()
       return
       
    if not ARCHITECT_GUI or not ARCHITECT_GUI.winfo_exists() or not SITE_LOCATION:
        return
        
    if event.char == '>':
        ARCHITECT_GUI.on_next_station()
    elif event.char == '<':
        ARCHITECT_GUI.on_prev_station()
    elif event.char == 'p':
        ARCHITECT_GUI.on_toggle_prefMarket()
    elif event.char == 'u':
        ARCHITECT_GUI.on_canvas_click(event)

def plugin_app(parent: tk.Frame) -> tk.Frame:
    global EDMCframe
    global AT_BUTTON
    global EDMC_ROOT

    EDMC_ROOT = parent.winfo_toplevel()

    parent.bind_all('<KeyPress>', on_key_press)

    EDMCframe = tk.Frame(parent)
    tk.Button(EDMCframe, textvariable=AT_BUTTON, command=toggle_gui).pack(fill=tk.X, padx=5, pady=5)

    theme.update(EDMCframe)
    return EDMCframe

def plugin_stop():
    if ARCHITECT_GUI and ARCHITECT_GUI.winfo_exists():
        AT_BUTTON.set("Show Architect Tracker (tracking disabled)")
        ARCHITECT_GUI.destroy()
    logger.info("Shutting down.")
    logger.info("***************************************")

# --- Data Hooks ---
def journal_entry(cmdr, is_beta, system, station, entry, state):
    global CURRENT_LOCATION
    global SITE_LOCATION
    global SHIP_STATE
    
    if "StarPos" in entry:
        CURRENT_LOCATION = tuple(entry["StarPos"])
        logger.info("Set current location to: %s", CURRENT_LOCATION)
    
    if not ARCHITECT_GUI and not ARCHITECT_GUI.winfo_exists():
        return
        
    if (SHIP_STATE == SHIP_MODE.Unknown):
        if state.get("IsDocked") is True:
            if CARRIER_TRACKER and station == CARRIER_TRACKER.callsign:
                SHIP_STATE = SHIP_MODE.DockedAtFC
                logger.info("Ship state: Docked at FC")
            elif is_facility(station):
                SHIP_STATE = SHIP_MODE.DockedAtSite
                logger.info("Ship state: Docked at site")
            else:
                SHIP_STATE = SHIP_MODE.DockedAtMarket
                logger.info("Ship state: Docked at market")
        else:
            SHIP_STATE = SHIP_MODE.Undocked
            logger.info("Ship state: Undocked")

    event = entry.get("event")

    if event == "ColonisationConstructionDepot":
        SHIP_STATE = SHIP_MODE.DockedAtSite
        logger.info("Ship state: Docked at site: %s", station)
        resources = entry.get("ResourcesRequired", [])
        save_facility_requirements(resources, station)
        if not SITE_LOCATION: #reinitialize if no construction sites existed
            if ARCHITECT_GUI and ARCHITECT_GUI.winfo_exists():
                ARCHITECT_GUI.destroy()
            SITE_LOCATION = CURRENT_LOCATION
            logger.info("Set site location to current location: %s", SITE_LOCATION)
            show_gui()
        elif ARCHITECT_GUI and ARCHITECT_GUI.winfo_exists():
            ARCHITECT_GUI.change_station(station)

    elif event == "Market":
        # do not register my fleet carrier as a market
        if CARRIER_TRACKER and station == CARRIER_TRACKER.callsign:
            return;
        SHIP_STATE = SHIP_MODE.DockedAtMarket
        logger.info("Ship state: Docked at market: %s", station)
        update_market_library()

    elif event == "MarketBuy":
        if CARRIER_TRACKER and station == CARRIER_TRACKER.callsign:
            CARRIER_TRACKER.apply_market_purchase(entry)

    elif event == "CargoTransfer":
        transfers = entry.get("Transfers", [])
        if CARRIER_TRACKER:
            CARRIER_TRACKER.apply_transfer_event(transfers)

    elif event == "Docked":
        if CARRIER_TRACKER and station == CARRIER_TRACKER.callsign:
            SHIP_STATE = SHIP_MODE.DockedAtFC
            logger.info("Ship state: Docked at FC")

    elif event == "Undocked":
        SHIP_STATE = SHIP_MODE.Undocked
        logger.info("Ship state: Undocked")

    if ARCHITECT_GUI and ARCHITECT_GUI.winfo_exists() and SITE_LOCATION: #only refresh if we have construction sites to show
        ARCHITECT_GUI.refresh()

def capi_fleetcarrier(data: CAPIData):
    global FCAPI_PAUSED

    if FCAPI_PAUSED:
        logger.info("Ignored fleet carrier API data")
        return

    if config.get('ArchTrack_fcapimode') is None:
        fcapi_mode = "First then pause"
        config.set('ArchTrack_fcapimode', fcapi_mode)
        logger.info(f"fcapi_mode not found using default settings.")
    else:
        fcapi_mode = config.get_str('ArchTrack_fcapimode')

    if ARCHITECT_GUI and ARCHITECT_GUI.winfo_exists():
        logger.info("Received fleet carrier CAPI data") #only OUR carrier, others are treated as markets
        CARRIER_TRACKER.update(data)
        if fcapi_mode == "First then pause":
            FCAPI_PAUSED = True
            logger.info(f'Fleet carrier API paused.')
        if SITE_LOCATION: #only refresh if we have construction sites to show
            ARCHITECT_GUI.refresh()

# --- Settings Hooks ---
def plugin_prefs(parent: nb.Notebook, cmdr: str, is_beta: bool) -> nb.Frame | None:
    global SHOW_UI_AT_START
    global ARCHITECT_TRACKER_VER
    column_display_vars = {}

    column_visibility, hide_provided, theme, column_display, trans_bg, win_top, opac_amount = load_gui_settings() #SHOW_UI_AT_START is set in plugin_start3()

    if config.get('ArchTrack_fcapimode') is None:
        fcapi_mode = "First then pause"
        logger.info(f"fcapi_mode not found using default settings.")
    else:
        fcapi_mode = config.get_str('ArchTrack_fcapimode')

    column_description = {}
    column_description["Material"] = "The commodities the construction site requires."
    column_description["Required"] = "The total amount required by the construction site."
    column_description["Provided"] = "The total amount delivered to the construction site."
    column_description["Needed"] = "Required minus Provided"
    column_description["Pref Market"] = "The closest or cheapest market that has the commodity."
    column_description["Carrier Qty"] = "The total amount you fleet carrier has."
    column_description["Ship Qty"] = "The total amount your starship has."
    column_description["Shortfall"] = "Needed minus Carrier Qty minus Ship Qty (or 0 if negative)"

    # PREFS FRAME ************************************************
    pref_frame = nb.Frame(parent)
    title_frame = nb.Frame(pref_frame, border=0)
    title_frame.grid(row=0, column=1, columnspan=2)
    nb.Label(title_frame, text="Architect Tracker (" + ARCHITECT_TRACKER_VER + ") plugin by CMDR kfpopeye.").grid(row=0, column=1, sticky="nsew")
    nb.Button(title_frame, text="Open website", command=open_url).grid(row=0, column=2, sticky="w")

    upper_row = nb.Frame(pref_frame, border=0)
    upper_row.grid(row=1, column=1, columnspan=2)

    # COLUMNS FRAME ************************************************
    col_frame = nb.Frame(upper_row, border=2, relief="groove")
    col_frame.grid(row=1, column=0)

    #configure column headers
    g_row = 0
    nb.Label(col_frame, text="Change columns to display or rename:").grid(row=g_row, column=0, columnspan=2, sticky="nsew")
    g_row = g_row +1
    for idx, (col, visible) in enumerate(column_visibility.items()):
        var = tk.BooleanVar(value=visible)
        if idx == 0:
            chk = nb.Checkbutton(
                col_frame,
                text=col,
                variable=var,
                state="disabled"
            )
            var.set(True)
        else:
            chk = nb.Checkbutton(
                col_frame,
                text=col,
                variable=var,
                command=lambda c=col, v=var: toggle_column(c, v.get())
            )
        chk.grid(row=g_row, column=0, sticky="nsew")

        display_var = tk.StringVar(value=column_display[idx])
        column_display_vars[col] = display_var
        c_name = tk.Entry(col_frame, textvariable=display_var)
        c_name.bind("<KeyRelease>", lambda e, c=col, v=display_var: on_column_rename(c, v.get()))
        c_name.grid(row=g_row, column=1, sticky="nsew")

        nb.Label(col_frame, text=column_description[col]).grid(row=g_row, column=2, sticky="w", padx=5)
        g_row = g_row + 1

    # CAPI FRAME ************************************************
    capi_frame = nb.Frame(upper_row, border=2, relief="groove")
    capi_frame.grid(row=1, column=1, sticky="nsew")
    g_row = 0

    #select FCAPI mode
    nb.Label(capi_frame, text="Select fleet capi mode:").grid(row=g_row, sticky="nw")
    g_row = g_row +1
    fcapi_var = tk.StringVar(value=fcapi_mode)
    capi_opt = ttk.Combobox(capi_frame, textvariable=fcapi_var, state="readonly")
    capi_opt['values'] = ("First then pause", "Only when unpaused")
    capi_opt.grid(row=g_row, sticky="nw", padx=5, pady=5)
    g_row = g_row +1
    capi_opt.bind("<<ComboboxSelected>>", lambda event: change_fcapi_mode(fcapi_var.get()))

    #display fcapi notes
    text2_widget = tk.Text(capi_frame, height=8, width=40, wrap='word', font=('Verdana', 9), border=0)
    text2_widget.tag_configure('big', font=('Verdana', 9, 'bold'))
    text2_widget.tag_configure('underline', font=('Verdana', 9, 'underline'))

    text2_widget.insert(tk.END, "Fleet Carrier API Options\n\n", 'underline')
    text2_widget.insert(tk.END, "First then pause\n", 'big')
    text2_widget.insert(tk.END, "Accepts the first update then automatically pauses.\n")
    text2_widget.insert(tk.END, "Only when UNpaused\n", 'big')
    text2_widget.insert(tk.END, "Only accepts updates when NOT paused.\n")

    text2_widget.config(state='disabled')
    text2_widget.grid(row=g_row, sticky="nsew", padx=5, pady=5)

    # BUTTONS FRAME ************************************************
    but_frame = nb.Frame(pref_frame, border=2, relief="groove")
    but_frame.grid(row=2, column=1, sticky="nw")
    g_row = 0

    #remove fully provided materials
    hide_var = tk.BooleanVar(value=hide_provided)
    chk_hide = nb.Checkbutton(
        but_frame,
        text="Remove delivered from lists",
        variable=hide_var,
        command=lambda val=hide_var: toggle_hide_provided(val.get())
    ).grid(row=g_row, sticky="nw", padx=5, pady=5)
    g_row = g_row +1

    #select UI colours
    nb.Label(but_frame, text="Select colours to use:").grid(row=g_row, sticky="nw")
    g_row = g_row +1
    theme_var = tk.StringVar(value=theme)
    color_opt = ttk.Combobox(but_frame, textvariable=theme_var, state="readonly")
    color_opt['values'] = ("Light Mode", "Dark Mode")
    color_opt.grid(row=g_row, sticky="nw", padx=5, pady=5)
    g_row = g_row +1
    color_opt.bind("<<ComboboxSelected>>", lambda event: reset_Style(theme_var.get()))

    # Opacity Settings
    trans_var = tk.BooleanVar(value=trans_bg)
    nb.Checkbutton(
        but_frame,
        text="Use Transparent Background",
        variable=trans_var,
        command=lambda val=trans_var: toggle_trans_bg(val.get())
    ).grid(row=g_row, sticky="nw", padx=5, pady=5)
    g_row = g_row +1
    wintop_var = tk.BooleanVar(value=win_top)
    nb.Checkbutton(
        but_frame,
        text="Keep window on top",
        variable=wintop_var,
        command=lambda val=wintop_var: toggle_win_top(val.get())
    ).grid(row=g_row, sticky="nw", padx=5, pady=5)
    g_row = g_row +1
    s = "Window Opacity - " + str(opac_amount) + "%"
    sldr_label = nb.Label(but_frame, text=s)
    sldr_label.grid(row=g_row, sticky="nw")
    g_row = g_row +1
    onum_var = tk.IntVar(value=opac_amount)
    ttk.Scale(
        but_frame,
        from_=10, to=100, variable=onum_var,
        command=lambda val: slider_changed(sldr_label, val)
    ).grid(row=g_row, sticky="news")
    g_row = g_row +1

    #delete market data
    nb.Button(but_frame, text="Delete Market Data", command=on_delete_markets).grid(row=g_row, sticky="nsew", padx=5, pady=5)
    g_row = g_row +1
    italic_font = tkFont.Font(family="Helvetica", size=8, slant="italic")
    nb.Label(but_frame, text="Delete cannot be undone.", font=italic_font).grid(row=g_row, sticky="nw", padx=10, pady=1)
    g_row = g_row +1

    #show at startup
    show_var = tk.BooleanVar(value=SHOW_UI_AT_START)
    chk_hide = nb.Checkbutton(
        but_frame,
        text="Show UI at EDMC startup",
        variable=show_var,
        command=lambda v=show_var: toggle_showUIatStart(v.get())
    ).grid(row=g_row, sticky="nw", padx=5, pady=5)
    g_row = g_row +1

    #Open Log Directory
    nb.Button(but_frame, text="Open Log Directory", command=on_log_open).grid(row=g_row, sticky="nsew", padx=5, pady=5)
    g_row = g_row +1

    # NOTES FRAME ************************************************
    note_frame = nb.Frame(pref_frame, border=2, relief="groove")
    note_frame.grid(row=2, column=2, columnspan=2, sticky="nsew")

    #display button and highlighting notes
    text_widget = tk.Text(note_frame, height=19, width=85, wrap='word', font=('Verdana', 9), border=0)
    text_widget.tag_configure('big', font=('Verdana', 9, 'bold'))
    text_widget.tag_configure('underline', font=('Verdana', 9, 'underline'))

    """Button Descriptions
    X - deletes the current construction site. Handy if someone else completes it.
    < and > - shows the previous or next site in the list. (Bound the '<' and '>' keys for Voice Attack users.)
    $\\Ly - toggles between cheapest and closest market. Prices and distances are tracked whenever you open a commodity market. Prices are only considered if they are lower than the buy prices of all construction sites. (This is bound the the 'p' key for Voice Attack users.)
    Pause\\Unpause - pauses and unpause updating fleet carrier cargo from Fdev servers, which can become out of sync with game data. (Bound to 'u' key)

    Row highlighting
    Depending on where you are docked, rows are highlighted to indicate:
    Markets - market is selling the item and you have shortfall.
    Fleeet Carrier - site needs it and fleet carrier has some.
    Construction site - site needs it and starship has some.

    Other
    Selecting -All- in the station dropdown list will display materials from all construction sites in a single view.
    """

    text_widget.insert(tk.END, "Button Descriptions\n", 'underline')
    text_widget.insert(tk.END, "X", 'big')
    text_widget.insert(tk.END, " - deletes the current construction site. Handy if someone else completes it.\n")
    text_widget.insert(tk.END, "< and >", 'big')
    text_widget.insert(tk.END, " - shows the previous or next site in the list. (Bound the '<' and '>' keys for Voice Attack users.)\n")
    text_widget.insert(tk.END, "$\\Ly", 'big')
    text_widget.insert(tk.END, " - toggles between cheapest and closest market. Prices and distances are tracked whenever you open a commodity market. Prices are only considered if they are lower than the buy prices of all construction sites. (Bound the the 'p' key for Voice Attack users.)\n")
    text_widget.insert(tk.END, "Pause\\Unpause", 'big')
    text_widget.insert(tk.END, " - pauses and unpause updating fleet carrier cargo from Fdev servers, which can become out of sync with game data. (Bound to 'u' key)\n\n")
    text_widget.insert(tk.END, "Row highlighting\n", 'underline')
    text_widget.insert(tk.END, "Depending on where you are docked, rows are highlighted to indicate:\n")
    text_widget.insert(tk.END, "Markets", 'big')
    text_widget.insert(tk.END, " - market is selling the item and you have shortfall.\n")
    text_widget.insert(tk.END, "Fleeet Carrier", 'big')
    text_widget.insert(tk.END, " - site needs it and fleet carrier has some.\n")
    text_widget.insert(tk.END, "Construction site", 'big')
    text_widget.insert(tk.END, " - site needs it and starship has some.\n")
    text_widget.insert(tk.END, "Undocked", 'big')
    text_widget.insert(tk.END, " - no highlighting is done.\n\n")
    text_widget.insert(tk.END, "Other\n", 'underline')
    text_widget.insert(tk.END, "Selecting -All- in the station dropdown list will display materials from all construction sites in a single view.\n")

    text_widget.config(state='disabled')
    text_widget.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

    pref_frame.grid_columnconfigure(0, minsize=5)
    return pref_frame

def open_url():
    webbrowser.open_new("https://github.com/kfpopeye/EliteDangerous")

def slider_changed(lbl, val):
    val = int(float(val))
    s = "Window Opacity = " + str(val) + "%"
    lbl.config(text=s)
    config.set('ArchTrack_opcamt', val)
    if ARCHITECT_GUI and ARCHITECT_GUI.winfo_exists():
        ARCHITECT_GUI.setAlpha(val)

def toggle_win_top(val):
    config.set('ArchTrack_wintop', bool(val))
    if ARCHITECT_GUI and ARCHITECT_GUI.winfo_exists():
        ARCHITECT_GUI.setStayOnTop(bool(val))

def toggle_trans_bg(val):
    config.set('ArchTrack_tbg', bool(val))
    if ARCHITECT_GUI and ARCHITECT_GUI.winfo_exists():
        ARCHITECT_GUI.setTransparentBg(bool(val))
        ARCHITECT_GUI.setStyle()
        ARCHITECT_GUI.refresh()

def on_log_open():
    import subprocess
    import sys

    if sys.platform == 'darwin':
        subprocess.check_call(['open', '--', USER_DIR])
    elif sys.platform == 'linux2':
        subprocess.check_call(['xdg-open', '--', USER_DIR])
    elif sys.platform == 'win32':
        subprocess.check_call(['explorer', USER_DIR])

def on_column_rename(c, v):
    if ARCHITECT_GUI and ARCHITECT_GUI.winfo_exists():
        ARCHITECT_GUI.rename_column(c, v)

def prefs_changed(cmdr: str, is_beta: bool) -> None:
    save_gui_settings()

def toggle_column(col, val):
    c = "ArchTrack_" + col.replace(" ", "_")
    config.set(c, val)

    if ARCHITECT_GUI and ARCHITECT_GUI.winfo_exists():
        ARCHITECT_GUI.toggle_column(col, val)

def toggle_hide_provided(val):
    config.set('ArchTrack_hide_Provided', bool(val))
    if ARCHITECT_GUI and ARCHITECT_GUI.winfo_exists():
        ARCHITECT_GUI.toggle_hide_provided(val)

def reset_Style(style):
    config.set('ArchTrack_theme', str(style))
    if ARCHITECT_GUI and ARCHITECT_GUI.winfo_exists():
        ARCHITECT_GUI.reset_Style(style)

def on_delete_markets():
    try:
        if os.path.exists(MARKET_LIB_PATH):
            os.remove(MARKET_LIB_PATH)
            if ARCHITECT_GUI and ARCHITECT_GUI.winfo_exists():
                ARCHITECT_GUI.refresh()

    except Exception as e:
        logger.error("Delete market Data error: %s", e)

def toggle_showUIatStart(b):
    global SHOW_UI_AT_START
    SHOW_UI_AT_START = b

def change_fcapi_mode(mode):
    config.set('ArchTrack_fcapimode', mode)
