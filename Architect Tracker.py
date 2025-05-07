import json
import os
import logging
import tkinter as tk
from tkinter import ttk
import platform
from contextlib import suppress
from companion import CAPIData
import binascii
from theme import theme
from typing import Optional
import myNotebook as nb
from config import appname, config

# Global GUI instance
ARCHITECT_GUI = None
frame: Optional[tk.Frame] = None
DEFAULT_COLUMNS = {"Material": True, "Required": True, "Provided": True, "Needed": True,
                    "Last Market": True, "Carrier Qty": True, "Ship Qty": True, "Shortfall": True
                    } 

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
MARKET_JSON = os.path.join(os.getenv('USERPROFILE', os.path.expanduser('~')), 'Saved Games', 'Frontier Developments', 'Elite Dangerous', 'Market.json')
CARGO_JSON = os.path.join(os.getenv('USERPROFILE', os.path.expanduser('~')), 'Saved Games', 'Frontier Developments', 'Elite Dangerous', 'Cargo.json')
SETTINGS_FILE = os.path.join(USER_DIR, "settings.json")

# Reset log
with suppress(Exception):
    os.remove(LOG_FILE)

logger = logging.getLogger("ArchitectTracker")
logger.setLevel(logging.INFO)
file_handler = logging.FileHandler(LOG_FILE)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
if not logger.hasHandlers():
    logger.addHandler(file_handler)
    
# --- Settings persistence ---
def load_gui_settings():
    global DEFAULT_COLUMNS
    
    try:
        vis = {}
        cols = list(DEFAULT_COLUMNS.keys())
        for c in cols:
            key = "ArchTrack_" + c.replace(" ", "_")
            val = config.get_bool(key)
            vis[c] = val if val is not None else True
        hid = config.get_bool('ArchTrack_hide_Provided')
        theme = config.get_str('ArchTrack_theme')
        if vis:
            logger.info(f"Found settings.")
            return vis, hid, theme
        else:
            logger.info(f"Returning default settings.")
            return DEFAULT_COLUMNS, False, "Dark Mode"
    except Exception as e:
        logger.error(f"Error loading GUI settings: {e}")
        return DEFAULT_COLUMNS, False, "Dark Mode"

def save_gui_settings():
    logger.info(f"Saving settings.")
    try:
        for col, vis in ARCHITECT_GUI.column_visibility.items():
            c = "ArchTrack_" + col.replace(" ", "_")
            config.set(c, vis)
        config.set('ArchTrack_hide_Provided', bool(ARCHITECT_GUI.hide_provided))
        config.set('ArchTrack_theme', str(ARCHITECT_GUI.theme))
    except Exception as e:                                                  
        logger.error(f"Error saving GUI settings: {e}")

# --- Helpers ---
def decode_vanity_name(hex_string):
    try:
        return binascii.unhexlify(hex_string).decode('utf-8')
    except Exception as e:
        logger.error(f"Failed to decode vanity name: {e}")
        return hex_string

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

carrier_tracker = FleetCarrierCargoTracker()

# --- Requirement persistence ---
def is_station_complete(materials):
    return all(info["ProvidedAmount"] >= info["RequiredAmount"] for info in materials.values())


def save_facility_requirements(resources, station_name):
    global ARCHITECT_GUI
    materials = {r["Name"]: {"Name_Localised": r["Name_Localised"],
                                   "RequiredAmount": r["RequiredAmount"],
                                   "ProvidedAmount": r["ProvidedAmount"]}
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
        data[station_name] = {"materials": materials}

    try:
        with open(SAVE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error("Error saving data: %s", e)


def load_facility_requirements():
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
    return cleaned


def load_market_data():
    if not os.path.exists(MARKET_JSON):
        return [], None
    try:
        with open(MARKET_JSON, "r", encoding="utf-8") as f:
            market = json.load(f)
        return market.get("Items", []), market.get("StationName")
    except Exception as e:
        logger.error("Error loading market data: %s", e)
        return [], None


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

# --- GUI Definition ---
class ArchitectTrackerGUI(tk.Toplevel):
    global DEFAULT_COLUMNS
    
    edBlue = "#1fbeff"
    edOrange = "#ff8500"
    bgBlack = "#1a1a1a"
        
    column_visibility = {}

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Architect Tracker")
        self.geometry("800x600")
        self.configure(bg=self.bgBlack)
        self.column_visibility, self.hide_provided, self.theme = load_gui_settings()

        self.setStyle()

        if not os.path.exists(SAVE_FILE):
            self._build_info_widgets()
        else:
            self._build_widgets()
            self.refresh()
            
    def auto_size_tree(self):
        import tkinter.font as tkFont
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
        self.station_var = tk.StringVar()
        self.dropdown = ttk.Combobox(frame, textvariable=self.station_var, state="readonly", style="ArchTrack.TCombobox")
        self.dropdown.grid(row=0, column=0, sticky="w", padx=(0, 50))
        self.dropdown.bind("<<ComboboxSelected>>", lambda e: self.display_station())

        ttk.Label(frame, text="Last Market:", style="ArchTrack.TLabel").grid(row=0, column=1, sticky="e", padx=(0, 5))
        self.market_name_label = ttk.Label(frame, text="", style="ArchTrack.TLabel")
        self.market_name_label.grid(row=0, column=2, sticky="w")

        ttk.Label(frame, text="Carrier:", style="ArchTrack.TLabel").grid(row=0, column=3, sticky="e", padx=(10, 5))
        self.carrier_label = ttk.Label(frame, text="", style="ArchTrack.TLabel")
        self.carrier_label.grid(row=0, column=4, sticky="w")

        # Treeview setup (row 2)
        cols = list(DEFAULT_COLUMNS.keys())
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", style="ArchTrack.Treeview")
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, anchor='w' if c == "Material" else 'center')

        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview, style="ArchTrack.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.grid(row=1, column=0, columnspan=5, sticky="nsew")
        scrollbar.grid(row=1, column=5, sticky="ns")

        # Make row 1 expandable
        frame.rowconfigure(1, weight=1)
        for i in range(5):
            frame.columnconfigure(i, weight=1)
            
        self.refresh_columns()  # Ensure columns initial visibility
        
    def reset_Style(self, new_theme):
        self.theme = new_theme
        logger.info("reset_Style theme is: %s", self.theme)
        save_gui_settings()
        self.setStyle()
        self.refresh()

    def toggle_column(self, column, is_visible: bool):
        self.column_visibility[column] = is_visible
        self.refresh_columns()

    def toggle_hide_provided(self):
        self.hide_provided = self.hide_var.get()
        self.refresh()

    def refresh_columns(self):
        visible_columns = [col for col, vis in self.column_visibility.items() if vis]
        self.tree["displaycolumns"] = visible_columns
        for col in visible_columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=100)

    def refresh(self):
        # Zapamiętaj aktualnie wybraną nazwę stacji
        current_selection = self.station_var.get()

        # Wczytaj nowe dane
        data = load_facility_requirements()
        self.data = data

        # Przygotuj dane do wyświetlenia
        display = [
            (
              (full.split(':', 1)[-1].strip() if ':' in full else 
               full.split(';', 1)[-1].strip() if ';' in full else full),
              full
            )
            for full in data
        ]
        display.sort(key=lambda x: x[0])  # Sortuj alfabetycznie
        self.station_map = {name: full for name, full in display}

        # Zaktualizuj dropdown
        values = [name for name, _ in display]
        self.dropdown['values'] = values

        # Przywróć wybór lub wybierz domyślnie pierwszą stację
        if values:
            if current_selection in values:
                self.station_var.set(current_selection)
            else:
                self.station_var.set(values[0])

            # Odśwież dane dla wybranej stacji
            self.display_station()
        else:
            # Brak danych – wyczyść drzewo
            self.tree.delete(*self.tree.get_children())
            
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
        market_items, market_name = load_market_data()
        cargo_items = load_cargo_data()

        market_lookup = {i.get('Name'): i for i in market_items}
        cargo_lookup = {i.get('Name'): i for i in cargo_items}

        self.market_name_label['text'] = market_name or 'N/A'
        self.carrier_label['text'] = carrier_tracker.carrier_name or 'N/A'

        for idx, (mat, vals) in enumerate(materials.items()):
            req = vals['RequiredAmount']
            prov = vals['ProvidedAmount']
            if self.hide_provided and prov >= req:
                continue
            safeMat = mat.replace("$", "").replace("_name;", "")
            locName = vals['Name_Localised']
            need = req - prov
            for_sale = '✔' if market_lookup.get(mat, {}).get('Stock', 0) > 0 else ''
            fc_qty = carrier_tracker.get_quantity(safeMat)
            ship_qty = cargo_lookup.get(safeMat, {}).get('Count', 0)
            short = max(0, need - (fc_qty + ship_qty))
            tag = 'evenrow' if idx % 2 == 0 else 'oddrow'
            self.tree.insert("", "end", values=(locName, req, prov, need, for_sale,
                                                   fc_qty, ship_qty, short), tags=(tag,))

# --- Plugin Hooks ---
def show_gui():
    global ARCHITECT_GUI
    if not ARCHITECT_GUI or not ARCHITECT_GUI.winfo_exists():
        ARCHITECT_GUI = ArchitectTrackerGUI(None)
    else:
        ARCHITECT_GUI.lift()
        ARCHITECT_GUI.refresh()

def plugin_start3(plugin_dir):
    logger.info("Starting Architect Tracker plugin")
    show_gui()
    return "ArchitectTracker"


def plugin_app(parent: tk.Frame) -> tk.Frame:
    global frame
    frame = tk.Frame(parent)
    tk.Button(frame, text="Show Architect Tracker", command=show_gui).pack(fill=tk.X, padx=5, pady=5)
    theme.update(frame)
    return frame


def plugin_stop():
    global ARCHITECT_GUI
    if ARCHITECT_GUI and ARCHITECT_GUI.winfo_exists():
        ARCHITECT_GUI.destroy()


def journal_entry(cmdr, is_beta, system, station, entry, state):
    event = entry.get("event")
    logger.info("Event detected: %s", event)

    if event == "ColonisationConstructionDepot":
        resources = entry.get("ResourcesRequired", [])
        save_facility_requirements(resources, station)
        if ARCHITECT_GUI and ARCHITECT_GUI.winfo_exists():
            ARCHITECT_GUI.refresh()

    elif event in ("Market", "Cargo"):
        if ARCHITECT_GUI and ARCHITECT_GUI.winfo_exists():
            ARCHITECT_GUI.refresh()

    elif event == "CargoTransfer":
        transfers = entry.get("Transfers", [])
        carrier_tracker.apply_transfer_event(transfers)
        if ARCHITECT_GUI and ARCHITECT_GUI.winfo_exists():
            ARCHITECT_GUI.refresh()

    elif event == "CargoDepot":
        if ARCHITECT_GUI and ARCHITECT_GUI.winfo_exists():
            ARCHITECT_GUI.refresh()            

def capi_fleetcarrier(data: CAPIData):
    logger.info("Received fleet carrier CAPI data")
    carrier_tracker.update(data)
    if ARCHITECT_GUI and ARCHITECT_GUI.winfo_exists():
        ARCHITECT_GUI.refresh()
        
def plugin_prefs(parent: nb.Notebook, cmdr: str, is_beta: bool) -> nb.Frame | None:
    pref_frame = nb.Frame(parent)
    col_frame = nb.Frame(pref_frame, border=2, relief="groove")
    col_frame.grid(row=1, column=1)
    
    g_row = 0
    nb.Label(col_frame, text="Select columns to display:").grid(row=g_row, column=0, sticky="nsew")
    g_row = g_row +1
    for idx, (col, visible) in enumerate(ARCHITECT_GUI.column_visibility.items()):
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
                command=lambda c=col, v=var: ARCHITECT_GUI.toggle_column(c, v.get())
            )
        chk.grid(row=g_row, column=0, sticky="nsew")
        g_row = g_row +1

    but_frame = nb.Frame(pref_frame, border=2, relief="groove")
    but_frame.grid(row=1, column=3, sticky="nw")
    
    #remove fully provided materials
    ARCHITECT_GUI.hide_var = tk.BooleanVar(value=ARCHITECT_GUI.hide_provided)
    chk_hide = nb.Checkbutton(
        but_frame,
        text="Remove delivered from lists",
        variable=ARCHITECT_GUI.hide_var,
        command=ARCHITECT_GUI.toggle_hide_provided
    ).grid(row=0, sticky="nw", padx=5, pady=5)
    
    #select UI colours
    nb.Label(but_frame, text="Select colours to use:").grid(row=2, sticky="nw")
    ARCHITECT_GUI.theme_var = tk.StringVar(value=ARCHITECT_GUI.theme or "Dark Mode")
    color_opt = ttk.Combobox(but_frame, textvariable=ARCHITECT_GUI.theme_var, state="readonly")
    color_opt['values'] = ("Light Mode", "Dark Mode")
    color_opt.grid(row=3, sticky="nw", padx=5, pady=5)
    color_opt.bind("<<ComboboxSelected>>", lambda e: ARCHITECT_GUI.reset_Style(ARCHITECT_GUI.theme_var.get()))
    
    pref_frame.grid_columnconfigure(0, minsize=5)
    pref_frame.grid_columnconfigure(2, minsize=5)
    return pref_frame
    
def prefs_changed(cmdr: str, is_beta: bool) -> None:
    save_gui_settings()
