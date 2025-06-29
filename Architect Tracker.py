import json
import os
import logging
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

import math
from typing import Union

# Global vars
ARCHITECT_TRACKER_VER = "1.0"
ARCHITECT_GUI = None
EDMCframe: Optional[tk.Frame] = None
AT_BUTTON: Optional[tk.StringVar] = tk.StringVar(value="Show Architect Tracker (tracking disabled)")
DEFAULT_COLUMNS = {"Material": True, "Required": True, "Provided": True, "Needed": True,
                    "Pref Market": True, "Carrier Qty": True, "Ship Qty": True, "Shortfall": True
                    }
SHOW_UI_AT_START = True
class SHIP_MODE(Enum):
    DockedAtMarket = 1
    DockedAtSite = 2
    DockedAtFC = 3
    Undocked = 4
SHIP_STATE = SHIP_MODE.Undocked

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

#files created by EDMC
MARKET_JSON = os.path.join(os.getenv('USERPROFILE', os.path.expanduser('~')), 'Saved Games', 'Frontier Developments', 'Elite Dangerous', 'Market.json')
CARGO_JSON = os.path.join(os.getenv('USERPROFILE', os.path.expanduser('~')), 'Saved Games', 'Frontier Developments', 'Elite Dangerous', 'Cargo.json')

# Reset log
with suppress(Exception):
    os.remove(LOG_FILE)

logger = logging.getLogger("ArchitectTracker")
logger.setLevel(logging.DEBUG)
file_handler = logging.FileHandler(LOG_FILE)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
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
            val = config.get_bool(key)
            if val is not None:
                vis[c] = val
            else:
                vis[c] = True
                logger.info(f"Key: %s not found using default setting.", key)
            
        hid = config.get_bool('ArchTrack_hide_Provided')
        if hid == None:
            hid = False
            logger.info(f"Hid not found using default settings.")
            
        theme = config.get_str('ArchTrack_theme')
        if not theme:
            theme = "Dark Mode"
            logger.info(f"Theme not found using default settings.")
            
        col_display = config.get_list('ArchTrack_cols')
        if not col_display:
            col_display = cols
            logger.info(f"Column names not found using default settings.")
            
        trans_bg = config.get_bool('ArchTrack_tbg')
        if trans_bg == None:
            trans_bg = False
            logger.info(f"trans_bg not found using default settings.")
            
        win_top = config.get_bool('ArchTrack_wintop')
        if win_top == None:
            win_top = False
            logger.info(f"win_top not found using default settings.")
            
        opac_amt = config.get_int('ArchTrack_opcamt')
        if opac_amt == None:
            opac_amt = 100
            logger.info(f"opac_amt not found using default settings.")
            
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

    def update(self, data):
        cargo_items = data.get('cargo', [])
        if not isinstance(cargo_items, list):
            logger.warning("Unexpected cargo data format.")
            return
        self.commodities.clear()
        for item in cargo_items:
            name = item.get("commodity")
            qty = item.get("qty", 0)
            if not name:
                logger.warning("Missing commodity name in cargo item: %s", item)
                continue
            self.commodities[name] = self.commodities.get(name, 0) + qty

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
            else:
                self.commodities[name] = max(0, current - qty)
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

    if is_station_complete(materials):
        data.pop(station_name, None)
    else:
        data[station_name] = {"Location": CURRENT_LOCATION, "materials": materials}

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
        if first_site:
            SITE_LOCATION = first_site.get("Location")            
            logger.debug("Set site location to: %s)", SITE_LOCATION)
        else:
            SITE_LOCATION = None
        
    return cleaned

def load_cargo_data():
    if not os.path.exists(CARGO_JSON):
        return []
    try:
        with open(CARGO_JSON, "r", encoding="utf-8") as f:
            cargo = json.load(f)
        return cargo.get("Inventory", [])
    except Exception as e:
        logger.error("Error loading cargo data: %s", e)
        return []

# do any construction sites require the item AND is the item buy price cheaper than the sell price
def isItemInDemand(item) -> bool:
    item_name = item.get("Name")
    item_price = item.get("SellPrice")
    prices = []

    site_data = load_facility_requirements()
    for site in site_data.values():  # iterate over site dicts directly
        materials = site.get("materials", {})
        for mat, vals in materials.items():
            if mat == item_name:
                price = vals.get("Price")
                if price is not None:
                    prices.append(price)

    if not prices:
        logger.debug("Item '%s' is not needed by any site", item_name)
        return False

    in_demand = all(item_price < price for price in prices)
    if in_demand:
        logger.info("Item '%s' is in demand (price: %s < all site prices: %s)", item_name, item_price, prices)
    else:
        logger.debug("Item '%s' is NOT in demand (price: %s vs site prices: %s)", item_name, item_price, prices)
    return in_demand

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
                
                if item_name and isItemInDemand(item):
                    existing = market_lib.get(item_name, {})

                    # Update CheapMarket if cheaper
                    cheap_entry = existing.get("CheapMarket")
                    if not cheap_entry or m_price < cheap_entry["Price"]:
                        logger.debug("Updating CheapMarket for: %s", item_name)
                        existing["CheapMarket"] = {
                            "Price": m_price,
                            "StationName": station_name,
                            "Location": CURRENT_LOCATION
                        }

                    # Update ClosestMarket if closer
                    close_entry = existing.get("ClosestMarket")
                    existing_distance = (
                        calculate_distance(*close_entry["Location"], *SITE_LOCATION)
                        if close_entry else float("inf")
                    )
                    new_distance = calculate_distance(*CURRENT_LOCATION, *SITE_LOCATION)
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
            logger.debug(f"Returning cheap market")
            market = resource.get("CheapMarket")
            return market.get("StationName", "")
        else:
            logger.debug(f"Returning closest market")
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

# --- GUI Definition ---
class ArchitectTrackerGUI(tk.Toplevel):
    edBlue = "#1fbeff"
    edOrange = "#ff8500"
    bgBlack = "#1a1a1a"
    column_visibility = {}

    def __init__(self, parent):
        global ARCHITECT_TRACKER_VER
        super().__init__(parent)
        self.title("Architect Tracker - " + ARCHITECT_TRACKER_VER)
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
        
        self.station_var = tk.StringVar()
        self.dropdown = ttk.Combobox(dropframe, textvariable=self.station_var, state="readonly", style="ArchTrack.TCombobox")
        self.dropdown.grid(row=0, column=1, sticky="w", padx=(0, 2))
        self.dropdown.bind("<<ComboboxSelected>>", lambda e: self.display_station())
        
        self.changeStation = ttk.Button(dropframe, text=">", style="ArchTrack.TButton", width=1, command=self.on_next_station)
        self.changeStation.grid(row=0, column=2, sticky="w")
        
        marketframe = ttk.Frame(frame, padding=8, style="ArchTrack.TFrame")
        marketframe.grid(row=0, column=3, sticky="nsew", padx=(0, 2))
        
        self.togglePrefStation = ttk.Button(marketframe, text="$\\Ly", style="ArchTrack.TButton", width=4, command=self.on_toggle_prefMarket)
        self.togglePrefStation.grid(row=0, column=0, sticky="w")

        ttk.Label(marketframe, text="Preferred Market:", style="ArchTrack.TLabel").grid(row=0, column=1, sticky="e", padx=(0, 5))
        self.market_name_label = ttk.Label(marketframe, text="", style="ArchTrack.TLabel")
        self.market_name_label.grid(row=0, column=2, sticky="w")        
        cheap = config.get_bool('ArchTrack_prefCheap')
        if cheap:
            self.market_name_label['text'] = 'cheapest ($)'
        else:
            self.market_name_label['text'] = 'closest (Ly)'

        ttk.Label(frame, text="Carrier:", style="ArchTrack.TLabel").grid(row=0, column=5, sticky="e", padx=(10, 5))
        self.carrier_label = ttk.Label(frame, text="", style="ArchTrack.TLabel")
        self.carrier_label.grid(row=0, column=6, sticky="w")

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
        display.sort(key=lambda x: x[0])  # Sort alphabetically
        self.station_map = {name: full for name, full in display}

        # Update dropdown
        values = [name for name, _ in display]
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
            
        # Set the market and carrier labels
        self.carrier_label['text'] = CARRIER_TRACKER.carrier_name or 'N/A'
            
        self.update_idletasks()
        self.auto_size_tree()
        width = self.winfo_reqwidth()
        height = self.winfo_reqheight()
        self.geometry(f"{width}x{height}") 

    def display_station(self):
        self.tree.delete(*self.tree.get_children())
        sel = self.station_var.get()
        full = self.station_map.get(sel)
        if not full:
            return
        materials = self.data[full]['materials']
        
        cargo_items = load_cargo_data()
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

        # Insert the materials into the tree
        for idx, (mat, vals) in enumerate(materials.items()):
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
                                               fc_qty, ship_qty, short), tags=(tags))

    def on_close(self):
        AT_BUTTON.set("Show Architect Tracker (tracking disabled)")
        self.destroy()  # Close the window
        
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
        ARCHITECT_GUI = ArchitectTrackerGUI(None)
    else:
        ARCHITECT_GUI.lift()
        ARCHITECT_GUI.refresh()
    AT_BUTTON.set("Hide Architect Tracker (tracking)")
        
def toggle_gui():
    global ARCHITECT_GUI
    global AT_BUTTON
    
    if not ARCHITECT_GUI or not ARCHITECT_GUI.winfo_exists():
        AT_BUTTON.set("Hide Architect Tracker (tracking)")
        ARCHITECT_GUI = ArchitectTrackerGUI(None)
    else:
        AT_BUTTON.set("Show Architect Tracker (tracking disabled)")
        ARCHITECT_GUI.destroy()

def plugin_start3(plugin_dir):
    global SHOW_UI_AT_START
    
    logger.info("Starting Architect Tracker plugin")
    SHOW_UI_AT_START = config.get_bool('ArchTrack_showUI')
    if SHOW_UI_AT_START:
        show_gui()
    return "ArchitectTracker"
    
def on_key_press(event):
    if event.char == '>':
        ARCHITECT_GUI.on_next_station()
    elif event.char == 'p':
        ARCHITECT_GUI.on_toggle_prefMarket()
    elif event.char == 't':
       toggle_gui()

def plugin_app(parent: tk.Frame) -> tk.Frame:
    global EDMCframe
    global AT_BUTTON

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

# --- Data Hooks ---
def journal_entry(cmdr, is_beta, system, station, entry, state):
    global CURRENT_LOCATION
    global SITE_LOCATION
    global SHIP_STATE
    
    if not ARCHITECT_GUI and not ARCHITECT_GUI.winfo_exists():
        return
    
    event = entry.get("event")

    if event == "ColonisationConstructionDepot":
        SHIP_STATE = SHIP_MODE.DockedAtSite
        logger.debug("Ship state: Docked at site")
        resources = entry.get("ResourcesRequired", [])
        save_facility_requirements(resources, station)
        if not SITE_LOCATION: #reinitialize if no construction sites existed
            if ARCHITECT_GUI and ARCHITECT_GUI.winfo_exists():
                ARCHITECT_GUI.destroy()
            SITE_LOCATION = CURRENT_LOCATION
            logger.debug("Set site location to current location: %s)", SITE_LOCATION)
            show_gui()
        elif ARCHITECT_GUI and ARCHITECT_GUI.winfo_exists():
            ARCHITECT_GUI.change_station(station)
            ARCHITECT_GUI.refresh()

    elif event in ("Cargo", "CargoDepot"):
        if ARCHITECT_GUI and ARCHITECT_GUI.winfo_exists():
            ARCHITECT_GUI.refresh()

    elif event in ("Market"):
        SHIP_STATE = SHIP_MODE.DockedAtMarket        
        logger.debug("Ship state: Docked at market")
        update_market_library()
        if ARCHITECT_GUI and ARCHITECT_GUI.winfo_exists():
            ARCHITECT_GUI.refresh()

    elif event == "CargoTransfer":
        transfers = entry.get("Transfers", [])
        if CARRIER_TRACKER:
            CARRIER_TRACKER.apply_transfer_event(transfers)
        if ARCHITECT_GUI and ARCHITECT_GUI.winfo_exists():
            ARCHITECT_GUI.refresh()
            
    elif event == "Docked":
        if CARRIER_TRACKER and station == CARRIER_TRACKER.callsign:
            SHIP_STATE = SHIP_MODE.DockedAtFC
            logger.debug("Ship state: Docked at FC")
            if ARCHITECT_GUI and ARCHITECT_GUI.winfo_exists():
                ARCHITECT_GUI.refresh()
                
    elif event == "Undocked":
        SHIP_STATE = SHIP_MODE.Undocked
        logger.debug("Ship state: Undocked")
        if ARCHITECT_GUI and ARCHITECT_GUI.winfo_exists():
            ARCHITECT_GUI.refresh()
            
    elif event == "StartUp":
        if "StarPos" in entry:
            CURRENT_LOCATION = tuple(entry["StarPos"])
            logger.debug("Set current location to: %s)", CURRENT_LOCATION)
        if CARRIER_TRACKER and station == CARRIER_TRACKER.callsign:
            logger.debug("Carrier: %s Station: %s", CARRIER_TRACKER.callsign, station)
            SHIP_STATE = SHIP_MODE.DockedAtFC
            logger.debug("Ship state: Docked at FC")
            if ARCHITECT_GUI and ARCHITECT_GUI.winfo_exists():
                ARCHITECT_GUI.refresh()
                
    elif event in ["FSDJump", "Location"]: #location happened after loadgame
        if "StarPos" in entry:
            CURRENT_LOCATION = tuple(entry["StarPos"])
            logger.debug("Set current location to: %s)", CURRENT_LOCATION)

def capi_fleetcarrier(data: CAPIData):
    logger.info("Received fleet carrier CAPI data")
    CARRIER_TRACKER.update(data)
    if ARCHITECT_GUI and ARCHITECT_GUI.winfo_exists():
        ARCHITECT_GUI.refresh()
        
def cmdr_data(data: CAPIData, is_beta):
    logger.debug("cmdr_data: %s", data.get('lastStarport'))

# --- Settings Hooks ---
def plugin_prefs(parent: nb.Notebook, cmdr: str, is_beta: bool) -> nb.Frame | None:
    global SHOW_UI_AT_START
    global ARCHITECT_TRACKER_VER
    column_display_vars = {}
    
    column_visibility, hide_provided, theme, column_display, trans_bg, win_top, opac_amount = load_gui_settings() #SHOW_UI_AT_START is set in plugin_start3()
    
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
    nb.Label(pref_frame, text="Architect Tracker (" + ARCHITECT_TRACKER_VER + ") plugin by kfpopeye. Found here: https://github.com/kfpopeye/EliteDangerous").grid(row=0, column=1, columnspan=2, sticky="nsew")
    
    # COLUMNS FRAME ************************************************
    col_frame = nb.Frame(pref_frame, border=2, relief="groove")
    col_frame.grid(row=1, column=1, columnspan=2)
    
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
        g_row = g_row +1

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
    text_widget = tk.Text(note_frame, height=15, width=70, wrap='word', font=('Verdana', 9), border=0)
    text_widget.tag_configure('big', font=('Verdana', 9, 'bold'))
    text_widget.tag_configure('underline', font=('Verdana', 9, 'underline'))
    
    """Button Descriptions
    X - deletes the current construction site. Handy if someone else completes it.
    > - shows the next site in the list. (This is bound the the '>' key for Voice Attack users.)
    $\Ly - toggles between cheapest and closest market. Prices and distances are tracked whenever you open a commodity market. Prices are only considered if they are lower than the buy prices of all construction sites. (This is bound the the 'p' key for Voice Attack users.)
    
    Row highlighting
    Depending on where you are docked, rows are highlighted to indicate:
    Markets - market is selling the item and you have shortfall.
    Fleeet Carrier - site needs it and fleet carrier has some.
    Construction site - site needs it and starship has some.
    """
    
    text_widget.insert(tk.END, "Button Descriptions\n", 'underline')
    text_widget.insert(tk.END, "X", 'big')
    text_widget.insert(tk.END, " - deletes the current construction site. Handy if someone else completes it.\n")
    text_widget.insert(tk.END, ">", 'big')
    text_widget.insert(tk.END, " - shows the next site in the list. (Bound the the '>' key for Voice Attack users.)\n")
    text_widget.insert(tk.END, "$\\Ly", 'big')
    text_widget.insert(tk.END, " - toggles between cheapest and closest market. Prices and distances are tracked whenever you open a commodity market. Prices are only considered if they are lower than the buy prices of all construction sites. (Bound the the 'p' key for Voice Attack users.)\n\n")
    text_widget.insert(tk.END, "Row highlighting\n", 'underline')
    text_widget.insert(tk.END, "Depending on where you are docked, rows are highlighted to indicate:\n")
    text_widget.insert(tk.END, "Markets", 'big')
    text_widget.insert(tk.END, " - market is selling the item and you have shortfall.\n")
    text_widget.insert(tk.END, "Fleeet Carrier", 'big')
    text_widget.insert(tk.END, " - site needs it and fleet carrier has some.\n")
    text_widget.insert(tk.END, "Construction site", 'big')
    text_widget.insert(tk.END, " - site needs it and starship has some.\n")
    text_widget.insert(tk.END, "Undocked", 'big')
    text_widget.insert(tk.END, " - no highlighting is done.\n")
    
    text_widget.config(state='disabled')
    text_widget.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
    
    pref_frame.grid_columnconfigure(0, minsize=5)
    return pref_frame
    
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
