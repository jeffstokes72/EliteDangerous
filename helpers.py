import os
import json
import math
from typing import Union
import traceback
import tkinter as tk

from config import config

import globals
from globals import logger

# --- Journal directory ---
def resolve_journal_dir():
    """Settle on a journal directory, asking the user only if we cannot find one."""
    chosen = config.get_str('ArchTrack_EDSaveDir')
    if chosen and os.path.isdir(chosen):
        logger.info('Using the ED journal directory chosen in settings: %s', chosen)
        return globals.set_journal_dir(chosen)
    if chosen:
        logger.warning('The ED journal directory chosen in settings is gone: %s', chosen)

    if globals.ED_SAVE_PATH:
        logger.info('Found the ED journal directory: %s', globals.ED_SAVE_PATH)
        return globals.ED_SAVE_PATH

    logger.warning('Could not find the ED journal directory, asking the commander.')
    from tkinter import filedialog
    path = filedialog.askdirectory(title="Select Elite Dangerous Journal Folder")
    if path and os.path.isdir(path):
        config.set('ArchTrack_EDSaveDir', str(path))
        logger.info('Commander chose the ED journal directory: %s', path)
        return globals.set_journal_dir(path)

    logger.error('No ED journal directory available. Tracking is disabled.')
    from tkinter import messagebox
    messagebox.showerror(
        "Architect Tracker",
        "Cannot find the Elite Dangerous journal files.\n\n"
        "Set the journal folder in EDMC's File > Settings > Configuration tab, "
        "then restart EDMC."
    )
    return None

# is the tracker window currently open?
def gui_exists() -> bool:
    if not globals.ARCHITECT_GUI:
        return False
    try:
        return bool(globals.ARCHITECT_GUI.winfo_exists())
    except tk.TclError:  # interpreter already torn down
        return False

# for linux
def is_flatpak():
    return (
        os.path.exists("/.flatpak-info") or
        "FLATPAK_SANDBOX_DIR" in os.environ or
        os.environ.get("FLATPAK_ID") is not None
    )

# --- Settings persistence ---
def load_column_names():
    """Header text for every column, always one entry per column in DEFAULT_COLUMNS."""
    cols = list(globals.DEFAULT_COLUMNS.keys())
    if config.get('ArchTrack_cols') is None:
        logger.info("Column names not found using default settings.")
        return cols
    saved = config.get_list('ArchTrack_cols')
    # Pre-System builds stored eight names; insert the default System header so
    # Carrier Qty / Ship Qty / Shortfall keep the labels the commander chose.
    if len(saved) == len(cols) - 1 and "System" in cols:
        system_idx = cols.index("System")
        merged = list(saved)
        merged.insert(system_idx, cols[system_idx])
        saved = merged
    #a list saved by another version may not line up with the columns we have now
    return [str(saved[i]) if i < len(saved) and saved[i] else cols[i] for i in range(len(cols))]

def load_gui_settings():
    cols = list(globals.DEFAULT_COLUMNS.keys())
    try:
        vis = {}
        for c in cols:
            key = "ArchTrack_" + c.replace(" ", "_")
            if config.get(key) is None:
                vis[c] = True
                logger.info("Key: %s not found using default setting.", key)
            else:
                vis[c] = config.get_bool(key)
        vis["Material"] = True

        if config.get('ArchTrack_hide_Provided') is None:
            hid = False
            logger.info("Hid not found using default settings.")
        else:
            hid = config.get_bool('ArchTrack_hide_Provided')

        if config.get('ArchTrack_theme') is None:
            theme = "Dark Mode"
            logger.info("Theme not found using default settings.")
        else:
            theme = config.get_str('ArchTrack_theme')

        col_display = load_column_names()

        if config.get('ArchTrack_tbg') is None:
            trans_bg = False
            logger.info("trans_bg not found using default settings.")
        else:
            trans_bg = config.get_bool('ArchTrack_tbg')

        if config.get('ArchTrack_wintop') is None:
            win_top = False
            logger.info("win_top not found using default settings.")
        else:
            win_top = config.get_bool('ArchTrack_wintop')

        if config.get('ArchTrack_opcamt') is None:
            opac_amt = 100
            logger.info("opac_amt not found using default settings.")
        else:
            opac_amt = config.get_int('ArchTrack_opcamt')

        return vis, hid, theme, col_display, trans_bg, win_top, opac_amt
    except Exception as e:
        logger.error("Error loading GUI settings: %s", e)
        return dict(globals.DEFAULT_COLUMNS), False, "Dark Mode", cols, False, False, 100

def show_ui_at_start() -> bool:
    if config.get('ArchTrack_showUI') is None:
        logger.info("showUI not found using default settings.")
        return True
    return config.get_bool('ArchTrack_showUI')

# --- Market import settings ---
def import_radius() -> int:
    import marketimport
    if config.get('ArchTrack_importRadius') is None:
        return marketimport.DEFAULT_RADIUS
    return max(marketimport.MIN_RADIUS,
               min(marketimport.MAX_RADIUS, config.get_int('ArchTrack_importRadius')))

def import_orbital() -> bool:
    if config.get('ArchTrack_importOrbital') is None:
        return True
    return config.get_bool('ArchTrack_importOrbital')

def import_surface() -> bool:
    if config.get('ArchTrack_importSurface') is None:
        return True
    return config.get_bool('ArchTrack_importSurface')

def import_pad_size() -> str:
    """Landing pad filter for Spansh imports: large only, or large and medium."""
    import marketimport
    if config.get('ArchTrack_importPadSize') is None:
        return marketimport.PAD_LARGE_MEDIUM
    value = config.get_str('ArchTrack_importPadSize')
    if value not in (marketimport.PAD_LARGE, marketimport.PAD_LARGE_MEDIUM):
        return marketimport.PAD_LARGE_MEDIUM
    return value

def site_system() -> str:
    """The system to search around: the shown site's, or wherever we are now."""
    sites = load_facility_requirements()
    if globals.ARCHITECT_GUI is not None and gui_exists():
        shown = getattr(globals.ARCHITECT_GUI, "shown_station", None)
        if shown and sites.get(shown, {}).get("System"):
            return sites[shown]["System"]
    for site in sites.values():
        if site.get("System"):
            return site["System"]
    return globals.CURRENT_SYSTEM

def save_gui_settings():
    logger.info("Saving settings.")
    config.set('ArchTrack_showUI', bool(globals.SHOW_UI_AT_START))
    if not gui_exists():
        return
    try:
        for col, vis in globals.ARCHITECT_GUI.column_visibility.items():
            c = "ArchTrack_" + col.replace(" ", "_")
            config.set(c, vis)
        config.set('ArchTrack_hide_Provided', bool(globals.ARCHITECT_GUI.hide_provided))
        config.set('ArchTrack_theme', str(globals.ARCHITECT_GUI.theme))
        config.set('ArchTrack_showUI', bool(globals.SHOW_UI_AT_START))
        config.set('ArchTrack_cols', list(globals.ARCHITECT_GUI.column_names))
        config.set('ArchTrack_tbg', bool(globals.ARCHITECT_GUI.trans_bg))
        config.set('ArchTrack_wintop', bool(globals.ARCHITECT_GUI.win_top))
        config.set('ArchTrack_opcamt', int(globals.ARCHITECT_GUI.opac_amount))
    except Exception as e:
        logger.error(f"Error saving GUI settings: {e}")

def compare_material_to_list(materials):
    for name in materials:
        if name and not isItemConstructionCommodity(name):
            logger.warning("%s not found in commodity list, adding it.", name)
            if COMMODITIES is not None:
                COMMODITIES.append(name)
            try:
                # The list lives beside the plugin, which may be read only.
                with open(globals.COMMODITY_FILE, "a", encoding="utf-8") as f:
                    f.write(name + "\n")
            except OSError as e:
                logger.warning("Could not add %s to the commodity list: %s", name, e)

# --- Helpers ---
def calculate_distance(x1: Union[int, float], y1: Union[int, float], z1: Union[int, float], x2: Union[int, float], y2: Union[int, float], z2: Union[int, float]):
        return math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2 + (z1 - z2) ** 2)

def is_station_complete(materials):
    return all(info["ProvidedAmount"] >= info["RequiredAmount"] for info in materials.values())
    
def get_current_location_from_journal():
    if not globals.ED_SAVE_PATH or not os.path.isdir(globals.ED_SAVE_PATH):
        return None
    journal_dir = globals.ED_SAVE_PATH
    journal_files = [f for f in os.listdir(journal_dir) if f.startswith("Journal.") and f.endswith(".log")]
    if not journal_files:
        return None
    latest_journal = max(journal_files, key=lambda f: os.path.getmtime(os.path.join(journal_dir, f)))
    try:
        # Journals are UTF-8 whatever the system encoding happens to be
        with open(os.path.join(journal_dir, latest_journal), "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError as e:
        logger.error("Could not read journal %s: %s", latest_journal, e)
        return None
    for line in reversed(lines):
        if '"StarPos"' in line:
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "StarPos" in data:
                logger.info("Found current location in journal.")
                return tuple(data["StarPos"])
    return None

def save_facility_requirements(resources, station_name, mID, system=None):
    materials = {r["Name"]: {"Name_Localised": r["Name_Localised"],
                                   "RequiredAmount": r["RequiredAmount"],
                                   "ProvidedAmount": r["ProvidedAmount"],
                                   "Price": r["Payment"]}
                     for r in resources}
    try:
        with open(globals.SAVE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}

    compare_material_to_list(materials)

    if station_name in data and not data[station_name].get("ID"):   #because we only tracked ID's after 1.3
        data[station_name]["ID"] = mID
        logger.debug("Added ID to: %s", station_name)

    system = system or globals.CURRENT_SYSTEM

    if station_name in data and data[station_name]["ID"] == mID:
        if is_station_complete(materials):
            logger.info("Facility %s is complete. Removing from list.", station_name)
            data.pop(station_name, None)
        else:
            data[station_name]["materials"] = materials
            if system:  #the system is only recorded from 1.7 onwards
                data[station_name]["System"] = system
            logger.info("Updating facility %s.", station_name)
    else:
        for s, info in data.items():
            if mID == info.get("ID"): #check for renamed construction sites
                data.pop(s, None)
                logger.info("Removed facility %s because it is now %s.", s, station_name)
                break
        if not is_station_complete(materials):
            data[station_name] = {"Location": globals.CURRENT_LOCATION, "System": system,
                                  "ID": mID, "materials": materials}
            logger.info("Adding facility %s to list.", station_name)

    try:
        with open(globals.SAVE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error("Error saving data: %s", e)

def load_facility_requirements():
    if not os.path.exists(globals.SAVE_FILE):
        return {}
    try:
        with open(globals.SAVE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.error("Error reading save file: %s", e)
        return {}
    cleaned = {s: info for s, info in data.items() if not is_station_complete(info.get("materials", {}))}
    if cleaned != data:
        try:
            with open(globals.SAVE_FILE, "w", encoding="utf-8") as f:
                json.dump(cleaned, f, indent=4)
        except Exception as e:
            logger.error("Error writing cleaned data: %s", e)

    if not globals.SITE_LOCATION and cleaned:
        first_site = next(iter(cleaned.values()))
        if first_site and first_site.get("Location"):
            globals.SITE_LOCATION = first_site.get("Location")
            logger.info("Set site location to: %s", globals.SITE_LOCATION)
        else:
            globals.SITE_LOCATION = None

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
    if not globals.CARGO_JSON or not os.path.exists(globals.CARGO_JSON):
        return []
    try:
        with open(globals.CARGO_JSON, "r", encoding="utf-8") as f:
            cargo = json.load(f)
        return cargo.get("Inventory", [])
    except Exception as e:
        logger.error("Error loading cargo data: %s", e)
        return []

# is the item a construction commodity
COMMODITIES = None
def ensure_commodities_loaded() -> bool:
    global COMMODITIES

    if COMMODITIES is None:
        if not os.path.exists(globals.COMMODITY_FILE):
            logger.error("Commodity data file does not exist: %s", globals.COMMODITY_FILE)
            return False

        with open(globals.COMMODITY_FILE, "r") as f:
            COMMODITIES = list(dict.fromkeys(line.strip() for line in f if line.strip()))
    return True

def isItemConstructionCommodity(item_name) -> bool:
    if not ensure_commodities_loaded():
        return False

    if item_name in COMMODITIES:
        logger.debug("Item: %s is a construction commodity.", item_name)
        return True
    else:
        logger.debug("Item: %s is NOT a construction commodity.", item_name)
        return False

# what every construction site is paying for each commodity, read once
def load_site_prices() -> dict:
    prices = {}
    for site in load_facility_requirements().values():
        for mat, vals in site.get("materials", {}).items():
            price = vals.get("Price")
            if price is not None:
                prices.setdefault(mat, []).append(price)
    return prices

# does the item cost less than all buy prices at construction sites
def isItemBelowConstructionCost(item_name, item_price, site_prices=None) -> bool:
    if site_prices is None:
        site_prices = load_site_prices()
    prices = site_prices.get(item_name, [])

    if not prices:
        logger.debug("Item '%s' is not needed by any site", item_name)
        return False

    in_demand = all(item_price < price for price in prices)
    if in_demand:
        logger.debug("Item '%s' is in demand (price: %s < all site prices: %s)", item_name, item_price, prices)
    else:
        logger.debug("Item '%s' is NOT in demand (price: %s vs site prices: %s)", item_name, item_price, prices)
    return in_demand

def check_if_market_renamed(market_lib, market):
    station_name = market.get("StationName")
    station_id = market.get("MarketID")
    m = get_market_by_station_id(market_lib, station_id)
    if m and m["StationName"] != station_name:
        logger.info("Updating station name: '%s' [%s] to %s", m["StationName"], station_id, station_name)
        m["StationName"] = station_name

def get_market_by_station_id(data, station_id):
    for market in data["Markets"]:
        if market["StationID"] == station_id:
            return market
    return None

def ensure_market_exists(market_lib, station_name, station_id, location=None,
                         station_type=None, system=None):
    if location is None:
        location = globals.CURRENT_LOCATION
    if station_type is None:
        station_type = globals.DOCKED_STATION_TYPE
    if system is None:
        system = globals.CURRENT_SYSTEM
    market = get_market_by_station_id(market_lib, station_id)
    if market is None:
        market_lib["Markets"].append({
            "StationName": station_name,
            "System": system,
            "Location": location,
            "StationID": station_id,
            "Type": station_type.name
        })
        logger.debug("Adding new market: %s", station_name)
        return
    if not market.get("Location") and location:
        #recorded before we knew where we were, so fill it in now
        market["Location"] = location
        logger.debug("Filled in the location of market: %s", station_name)
    if system and not market.get("System"):
        market["System"] = system
        logger.debug("Filled in the system of market: %s", station_name)
    if station_name and market.get("StationName") != station_name:
        market["StationName"] = station_name

# One observation of "this market sells this commodity at this price", from
# wherever it came from: docking somewhere, or an import. Keeping both callers
# on the same rules is the point, so the two sources stay comparable.
def record_market_price(market_lib, item_name, price, station_name, station_id,
                        station_type, location, site_prices=None, system=None):
    if not item_name or not station_id or not price:
        return
    type_name = station_type.name
    commodity = market_lib["Commodities"].setdefault(item_name, {})

    def add_market():
        ensure_market_exists(market_lib, station_name, station_id, location,
                             station_type, system)

    def distance_from_site():
        if not location or not globals.SITE_LOCATION:
            return float("inf")
        return calculate_distance(*location, *globals.SITE_LOCATION)

    def closer_than(entry):
        if not entry:
            return True
        return distance_from_site() < distance_to_site(market_lib, entry["StationID"])

    if isItemBelowConstructionCost(item_name, price, site_prices):
        cheap_markets = commodity.setdefault("CheapMarkets", {})
        cheap_entry = cheap_markets.get(type_name)
        if not cheap_entry or price < cheap_entry["Price"]:  # cheaper, or nothing recorded
            add_market()
            logger.debug("Updating CheapMarket for: %s", item_name)
            cheap_markets[type_name] = {"Price": price, "StationID": station_id}
        elif station_id == cheap_entry.get("StationID"):  # same station, new price
            cheap_entry["Price"] = price

        close_markets = commodity.setdefault("ClosestMarkets", {})
        if closer_than(close_markets.get(type_name)):
            add_market()
            logger.debug("Updating ClosestMarket for: %s", item_name)
            close_markets[type_name] = {"Price": price, "StationID": station_id}
        return

    logger.debug("Item %s was expensive.", item_name)
    cheap_entry = commodity.setdefault("CheapMarkets", {}).get(type_name)
    close_entry = commodity.setdefault("ClosestMarkets", {}).get(type_name)
    #if this market is already listed as cheap or closest market for item, skip it
    if (cheap_entry and cheap_entry.get("StationID") == station_id) or \
            (close_entry and close_entry.get("StationID") == station_id):
        logger.debug("%s was already a cheap or closest entry.", station_name)
        return

    alt_markets = commodity.setdefault("AlternateMarkets", {})
    if closer_than(alt_markets.get(type_name)):
        add_market()
        logger.debug("Updating AlternateMarket for: %s", item_name)
        alt_markets[type_name] = {"Price": price, "StationID": station_id}
    else:
        logger.debug("%s has a closer AlternateMarket", item_name)

def save_market_library(market_lib):
    try:
        with open(globals.MARKET_LIB_PATH, "w", encoding="utf-8") as f:
            json.dump(market_lib, f, indent=2)
    except OSError as e:
        logger.error("Error saving the market library: %s", e)

def get_market_library():
    # Load existing persistent dictionary if available or create default
    market_lib = None
    if os.path.exists(globals.MARKET_LIB_PATH):
        try:
            with open(globals.MARKET_LIB_PATH, "r", encoding="utf-8") as f:
                market_lib = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.error("Market library is unreadable, starting a new one: %s", e)
    if not isinstance(market_lib, dict):
        market_lib = {}
    # An older or half written file may be missing either section.
    if not isinstance(market_lib.get("Commodities"), dict):
        market_lib["Commodities"] = {}
    if not isinstance(market_lib.get("Markets"), list):
        market_lib["Markets"] = []
    return market_lib

# distance from a market to the construction site, or infinity if either is unknown
def distance_to_site(market_lib, station_id):
    if not globals.SITE_LOCATION:
        return float("inf")
    market = get_market_by_station_id(market_lib, station_id)
    if not market or not market.get("Location"):
        return float("inf")
    return calculate_distance(*market["Location"], *globals.SITE_LOCATION)

#a list of the cheapest and closest markets that are selling an item
def update_market_library() -> None:
    if not globals.MARKET_JSON or not os.path.exists(globals.MARKET_JSON):
        logger.warning("Market data file does not exist: %s", globals.MARKET_JSON)
        return

    #do not update unless we know where we are landed at
    if globals.DOCKED_STATION_TYPE == globals.STATION_TYPE.Unknown:
        logger.warning("Station type unknown.")
        return

    try:
        market_lib = get_market_library()

        # Load market data from EDMC
        with open(globals.MARKET_JSON, "r", encoding="utf-8") as f:
            market = json.load(f)

        check_if_market_renamed(market_lib, market)

        station_name = market.get("StationName")
        items = market.get("Items", [])
        station_id = market.get("MarketID")

        if not station_name or not station_id:
            logger.warning("Invalid market data")
            return
            
        not_selling_list = None
        if ensure_commodities_loaded():
            not_selling_list = list(COMMODITIES)
        site_prices = load_site_prices()

        for item in items:
            if item.get("Stock", 0) > 0:  # Item is for sale
                item_name = item.get("Name")
                # BuyPrice is what the commander pays; SellPrice is what the
                # station would pay us for it, which is not the cost of hauling.
                m_price = item.get("BuyPrice")

                if item_name and isItemConstructionCommodity(item_name):
                    if item_name in not_selling_list:
                        not_selling_list.remove(item_name)
                    record_market_price(market_lib, item_name, m_price, station_name,
                                        station_id, globals.DOCKED_STATION_TYPE,
                                        globals.CURRENT_LOCATION, site_prices,
                                        system=globals.CURRENT_SYSTEM)

        if not_selling_list != None:
            purge_market_from_other_commodities(market_lib, not_selling_list, station_id, station_name) #removes station ID if no longer selling commodities
        save_market_library(market_lib)
        remove_from_old_market_library(station_name) #purge old v1.3 library

    except json.JSONDecodeError as e:
        logger.error("JSON decode error: %s", e)
    except Exception as e:
        logger.error("Unexpected error: %s", e)
        logger.error("Traceback:\n%s", traceback.format_exc())
        
#remove station ID if no longer selling commodities
def purge_market_from_other_commodities(market_lib, comm_list, station_id, station_name):
    for comm in comm_list:
        commodity = market_lib["Commodities"].get(comm)
        if not commodity:
            continue
        cheap_m_list = commodity.setdefault("CheapMarkets", {})
        cheap_entry = cheap_m_list.get(globals.DOCKED_STATION_TYPE.name)
        close_m_list = commodity.setdefault("ClosestMarkets", {})
        close_entry = close_m_list.get(globals.DOCKED_STATION_TYPE.name)
        alt_m_list = commodity.setdefault("AlternateMarkets", {})
        alt_entry = alt_m_list.get(globals.DOCKED_STATION_TYPE.name)

        if (cheap_entry and cheap_entry.get("StationID") == station_id):
            del cheap_m_list[globals.DOCKED_STATION_TYPE.name]
            logger.info("%s is no longer selling %s", station_name, comm)
        if (close_entry and close_entry.get("StationID") == station_id):
            del close_m_list[globals.DOCKED_STATION_TYPE.name]
            logger.info("%s is no longer selling %s", station_name, comm)
        if (alt_entry and alt_entry.get("StationID") == station_id):
            del alt_m_list[globals.DOCKED_STATION_TYPE.name]
            logger.info("%s is no longer selling %s", station_name, comm)

def getPreferedMarket()->globals.MARKET_MODE:
    if config.get('ArchTrack_prefCheap') is not None:   #setting not used since v1.3
        config.delete('ArchTrack_prefCheap')

    if config.get('ArchTrack_prefMarket') is None:
        mode = globals.MARKET_MODE.Cheapest
        config.set('ArchTrack_prefMarket', mode.value)
    else:
        value = config.get_int('ArchTrack_prefMarket')
        mode = globals.MARKET_MODE(value)
    return mode

def getPreferedType()->globals.STATION_TYPE:
    if config.get('ArchTrack_prefType') is None:
        type = globals.STATION_TYPE.Orbital
        config.set('ArchTrack_prefType', type.value)
    else:
        value = config.get_int('ArchTrack_prefType')
        type = globals.STATION_TYPE(value)
    return type
    
    #purge old v1.3 library until it is empty
def remove_from_old_market_library(station_name):
    # Load existing persistent dictionary if available
    old_library = os.path.join(globals.USER_DIR, "market_library.json")
    if os.path.exists(old_library):
        with open(old_library, "r", encoding="utf-8") as f:
            market_lib = json.load(f)
    else:
        return

    location = globals.CURRENT_LOCATION
    commodities_to_delete = []

    for commodity, markets in market_lib.items():
        markets_to_delete = []

        for market_type, market_data in markets.items():
            if (
                market_data["StationName"] == station_name and
                tuple(market_data["Location"]) == location
            ):
                markets_to_delete.append(market_type)

        # remove matching markets
        for market_type in markets_to_delete:
            del markets[market_type]

        # mark empty commodities
        if not markets:
            commodities_to_delete.append(commodity)

    # remove empty commodities
    for commodity in commodities_to_delete:
        del market_lib[commodity]

    # if no commodities remain, delete file
    if not market_lib:
        os.remove(old_library)
        logger.info(f"{old_library} deleted (no commodities left).")
        return

    # otherwise save cleaned data
    with open(old_library, "w", encoding="utf-8") as f:
        json.dump(market_lib, f, indent=2)

    logger.info("Matching stations removed and file updated.")
    
def get_legacy_market_library(): #the pre v1.3 library, kept until it has been drained
    old_library = os.path.join(globals.USER_DIR, "market_library.json")
    if not os.path.exists(old_library):
        return {}
    try:
        with open(old_library, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.error("Could not read the old market library: %s", e)
        return {}
    return data if isinstance(data, dict) else {}

def get_old_prefMarket_name(material, market_lib=None): #see if pre v1.3 market library has an entry
    try:
        if market_lib is None:
            market_lib = get_legacy_market_library()

        resource = market_lib.get(material)
        if not resource:
            return ""

        pref = getPreferedMarket()
        if pref == globals.MARKET_MODE.Cheapest:
            market = resource.get("CheapMarket")
        elif pref == globals.MARKET_MODE.Closest:
            market = resource.get("ClosestMarket")
        else:
            market = resource.get("AlternateMarket")
            
        if not market:
            return ""

        if market.get("StationName"):
            station_name = market.get("StationName")
            return "**" + station_name    

    except json.JSONDecodeError as e:
        logger.error("JSON decode error: %s", e)
    except Exception as e:
        logger.error("Unexpected error: %s", e)
        logger.error("Traceback:\n%s", traceback.format_exc())
    
    return "Old Err"

def get_prefMarket_entry(material, market_lib=None, legacy_lib=None):
    """Preferred market dict for `material`, or None. Shared by name/system lookups."""
    try:
        if market_lib is None:
            market_lib = get_market_library()
        resource = market_lib["Commodities"].get(material)
        if not resource:
            return None

        pref = getPreferedMarket()
        if pref == globals.MARKET_MODE.Cheapest:
            markets = resource.get("CheapMarkets")
        elif pref == globals.MARKET_MODE.Closest:
            markets = resource.get("ClosestMarkets")
        else:
            markets = resource.get("AlternateMarkets")

        if not markets:
            markets = resource.get("AlternateMarkets")
            if not markets:
                return None

        if getPreferedType() == globals.STATION_TYPE.Orbital:
            preferred, fallback = globals.STATION_TYPE.Orbital, globals.STATION_TYPE.Surface
        else:
            preferred, fallback = globals.STATION_TYPE.Surface, globals.STATION_TYPE.Orbital

        m = markets.get(preferred.name)
        prefix = ""
        if not m:
            m = markets.get(fallback.name)
            prefix = "*"  #mark the non-prefered type
        if not m:
            return None

        station = get_market_by_station_id(market_lib, m["StationID"])
        if not station or not station.get("StationName"):
            return None
        return {"prefix": prefix, "station": station}

    except Exception as e:
        logger.error("Unexpected error: %s", e)
        logger.error("Traceback:\n%s", traceback.format_exc())
        return None

def get_prefMarket_name(material, market_lib=None, legacy_lib=None):
    """Name of the market to buy `material` from. Callers rendering a whole table
    should load the libraries once and pass them in rather than paying for a
    re-read of both JSON files per row."""
    entry = get_prefMarket_entry(material, market_lib, legacy_lib)
    if entry:
        return entry["prefix"] + entry["station"]["StationName"]
    return get_old_prefMarket_name(material, legacy_lib)

def get_prefMarket_system(material, market_lib=None, legacy_lib=None):
    """System of the preferred market for `material`, or blank if unknown."""
    entry = get_prefMarket_entry(material, market_lib, legacy_lib)
    if not entry:
        return ""
    return entry["station"].get("System") or ""

def load_market_stock() -> set:
    """Names of everything the market we are docked at currently has in stock."""
    if not globals.MARKET_JSON or not os.path.exists(globals.MARKET_JSON):
        return set()
    try:
        with open(globals.MARKET_JSON, "r", encoding="utf-8") as f:
            market = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.error("Error loading market data: %s", e)
        return set()
    return {item.get("Name") for item in market.get("Items", []) if item.get("Stock", 0) > 0}

def is_market_selling(material, stock=None) -> bool:
    if stock is None:
        stock = load_market_stock()
    return material in stock

# --- Plugin Hooks ---
def show_gui():
    from architecttrackergui import ArchitectTrackerGUI
    if not gui_exists():
        globals.ARCHITECT_GUI = ArchitectTrackerGUI(globals.EDMC_ROOT)
    else:
        globals.ARCHITECT_GUI.lift()
        globals.ARCHITECT_GUI.refresh()
    globals.AT_BUTTON.set("Hide Architect Tracker (tracking)")

def toggle_gui():
    from architecttrackergui import ArchitectTrackerGUI
    if not gui_exists():
        globals.AT_BUTTON.set("Hide Architect Tracker (tracking)")
        globals.ARCHITECT_GUI = ArchitectTrackerGUI(globals.EDMC_ROOT)
    else:
        globals.AT_BUTTON.set("Show Architect Tracker (tracking disabled)")
        globals.ARCHITECT_GUI.destroy()

#widgets the commander types into, where a hotkey would eat the keystroke
TYPING_WIDGETS = ("Entry", "TEntry", "Text", "TCombobox", "Spinbox", "TSpinbox", "Listbox")

def is_typing_widget(widget) -> bool:
    try:
        return widget.winfo_class() in TYPING_WIDGETS
    except Exception:
        return False

def on_key_press(event):
    # These are bound with bind_all so Voice Attack can reach them, which means we
    # also see keystrokes meant for EDMC's own fields and for our settings tab.
    if is_typing_widget(getattr(event, "widget", None)):
        return

    if event.char == 't':
       toggle_gui()
       return

    if not gui_exists() or not globals.SITE_LOCATION:
        return

    if event.char == '>':
        globals.ARCHITECT_GUI.on_next_station()
    elif event.char == '<':
        globals.ARCHITECT_GUI.on_prev_station()
    elif event.char == 'p':
        globals.ARCHITECT_GUI.on_toggle_prefMarket()
    elif event.char == 'o':
        globals.ARCHITECT_GUI.on_toggle_prefType()
    elif event.char == 'u':
        globals.ARCHITECT_GUI.on_canvas_click(event)
