__version__ = "2.0"

"""
Displays commodities required, provided and needed when you land at a construction site,
market or fleet carrier and tracks cargo in your fleet carrier and starship.

Author: CMDR kfpopeye and ChatGPT
Date: 2025-04-08
Git: https://github.com/jeffstokes72/EliteDangerous
License: GNU GENERAL PUBLIC LICENSE Version 2
"""

import os
import platform
import tkinter as tk
from theme import theme
import traceback
import semantic_version

from companion import CAPIData
from config import appversion, config
import myNotebook as nb

import globals
from globals import logger
import preferences
import helpers

globals.ARCHITECT_TRACKER_VER = __version__

def plugin_start3(plugin_dir):
    try:
        logger.info("Starting Architect Tracker plugin (%s)", globals.ARCHITECT_TRACKER_VER)

        # Up until 5.0.0-beta1 config.appversion is a string
        if isinstance(appversion, str):
            core_version = semantic_version.Version(appversion)
        elif callable(appversion):
            # From 5.0.0-beta1 it's a function, returning semantic_version.Version
            core_version = appversion()
        # Yes, just blow up if config.appverison is neither str nor callable
        logger.info('Core EDMarketConnector version: %s', core_version)
        logger.info('OS: %s', platform.system())
        if platform.system() == "Linux":
            logger.info('Flatpak: %s', helpers.is_flatpak())

        globals.COMMODITY_FILE = os.path.join(plugin_dir, globals.COMMODITY_FILE)

        if not helpers.resolve_journal_dir():
            return "ArchitectTracker"

        globals.CURRENT_LOCATION = helpers.get_current_location_from_journal()
            
        if not os.path.exists(globals.USER_DIR):
            logger.error('Could not find the user directory: %s', globals.USER_DIR)
        else:
            logger.info('Found the user directory: %s', globals.USER_DIR)

        if config.get('ArchTrack_fcapimode') is None:
            fcapi_mode = "First then pause"
            config.set('ArchTrack_fcapimode', fcapi_mode)
            logger.info("fcapi_mode not found using default settings.")
        else:
            fcapi_mode = config.get_str('ArchTrack_fcapimode')

        if fcapi_mode == "Only when unpaused":
            globals.FCAPI_PAUSED = True
            logger.info('Fleet carrier API paused.')
            
        globals.SHOW_UI_AT_START = helpers.show_ui_at_start()
        if globals.SHOW_UI_AT_START:
            helpers.show_gui()
        return "ArchitectTracker"
    except Exception as e:
        logger.error("Unexpected error: %s", e)
        logger.error("Traceback:\n%s", traceback.format_exc())
        logger.error("***************************************")
        return "ArchitectTracker"

def plugin_app(parent: tk.Frame) -> tk.Frame:
    globals.EDMC_ROOT = parent.winfo_toplevel()

    parent.bind_all('<KeyPress>', helpers.on_key_press)

    globals.EDMCframe = tk.Frame(parent)
    tk.Button(globals.EDMCframe, textvariable=globals.AT_BUTTON, command=helpers.toggle_gui).pack(fill=tk.X, padx=5, pady=5)

    theme.update(globals.EDMCframe)
    return globals.EDMCframe

def plugin_stop():
    helpers.save_gui_settings()
    if helpers.gui_exists():
        globals.AT_BUTTON.set("Show Architect Tracker (tracking disabled)")
        globals.ARCHITECT_GUI.destroy()
    logger.info("Shutting down.")
    logger.info("***************************************")

# --- Data Hooks ---
def journal_entry(cmdr, is_beta, system, station, entry, state):
    try:
        if system:
            globals.CURRENT_SYSTEM = system

        if "StarPos" in entry:
            globals.CURRENT_LOCATION = tuple(entry["StarPos"])
            logger.info("Set current location to: %s", globals.CURRENT_LOCATION)

        if not helpers.gui_exists():
            return

        if globals.SHIP_STATE == globals.SHIP_MODE.Unknown:
            if state.get("IsDocked") is True:
                if globals.CARRIER_TRACKER and station == globals.CARRIER_TRACKER.callsign:
                    globals.SHIP_STATE = globals.SHIP_MODE.DockedAtFC
                    logger.info("Ship state: Docked at FC")
                elif helpers.is_facility(station):
                    globals.SHIP_STATE = globals.SHIP_MODE.DockedAtSite
                    logger.info("Ship state: Docked at site")
                else:
                    globals.SHIP_STATE = globals.SHIP_MODE.DockedAtMarket
                    logger.info("Ship state: Docked at market")
            else:
                globals.SHIP_STATE = globals.SHIP_MODE.Undocked
                logger.info("Ship state: Undocked")

        event = entry.get("event")

        if event == "ColonisationConstructionDepot":
            if station == None:
                return
            globals.SHIP_STATE = globals.SHIP_MODE.DockedAtSite
            logger.info("Ship state: Docked at site: %s", station)
            resources = entry.get("ResourcesRequired", [])
            mid = entry.get("MarketID")
            helpers.save_facility_requirements(resources, station, mid, system)
            if not globals.SITE_LOCATION: #reinitialize if no construction sites existed
                if helpers.gui_exists():
                    globals.ARCHITECT_GUI.destroy()
                globals.SITE_LOCATION = globals.CURRENT_LOCATION
                logger.info("Set site location to current location: %s", globals.SITE_LOCATION)
                helpers.show_gui()
            elif helpers.gui_exists():
                globals.ARCHITECT_GUI.change_station(station)

        elif event == "Market":
            if station == None:
                return
            # do not register my fleet carrier as a market
            if not (globals.CARRIER_TRACKER and station == globals.CARRIER_TRACKER.callsign):
                globals.SHIP_STATE = globals.SHIP_MODE.DockedAtMarket
                logger.info("Ship state: Docked at market: %s", station)
                helpers.update_market_library()

        elif event == "MarketBuy":
            if globals.CARRIER_TRACKER and station == globals.CARRIER_TRACKER.callsign:
                globals.CARRIER_TRACKER.apply_market_purchase(entry)

        elif event == "MarketSell":
            if globals.CARRIER_TRACKER and station == globals.CARRIER_TRACKER.callsign:
                globals.CARRIER_TRACKER.apply_market_sale(entry)

        elif event == "CargoTransfer":
            transfers = entry.get("Transfers", [])
            if globals.CARRIER_TRACKER:
                globals.CARRIER_TRACKER.apply_transfer_event(transfers)

        elif event == "Docked":
            if globals.CARRIER_TRACKER and station == globals.CARRIER_TRACKER.callsign:
                globals.SHIP_STATE = globals.SHIP_MODE.DockedAtFC
                logger.info("Ship state: Docked at FC")

        elif event == "Undocked":
            globals.SHIP_STATE = globals.SHIP_MODE.Undocked
            logger.info("Ship state: Undocked")

        elif event == "ApproachSettlement":
            globals.DOCKED_STATION_TYPE = globals.STATION_TYPE.Surface
            logger.info("Station type set to: %s", globals.DOCKED_STATION_TYPE.name)

        elif event == "SupercruiseDestinationDrop":
            globals.DOCKED_STATION_TYPE = globals.STATION_TYPE.Orbital
            logger.info("Station type set to: %s", globals.DOCKED_STATION_TYPE.name)

        elif event == "SupercruiseEntry":
            globals.DOCKED_STATION_TYPE = globals.STATION_TYPE.Unknown
            logger.info("Station type set to: %s", globals.DOCKED_STATION_TYPE.name)

        if helpers.gui_exists() and globals.SITE_LOCATION: #only refresh if we have construction sites to show
            globals.ARCHITECT_GUI.refresh()

    except Exception as e:
        logger.error("Unexpected error: %s", e)
        logger.error("Traceback:\n%s", traceback.format_exc())

def capi_fleetcarrier(data: CAPIData):
    if globals.FCAPI_PAUSED:
        logger.info("Ignored fleet carrier API data")
        return

    if config.get('ArchTrack_fcapimode') is None:
        fcapi_mode = "First then pause"
        config.set('ArchTrack_fcapimode', fcapi_mode)
        logger.info("fcapi_mode not found using default settings.")
    else:
        fcapi_mode = config.get_str('ArchTrack_fcapimode')

    if helpers.gui_exists():
        logger.info("Received fleet carrier CAPI data") #only OUR carrier, others are treated as markets
        globals.CARRIER_TRACKER.update(data)
        if fcapi_mode == "First then pause":
            globals.FCAPI_PAUSED = True
            logger.info('Fleet carrier API paused.')
        if globals.SITE_LOCATION: #only refresh if we have construction sites to show
            globals.ARCHITECT_GUI.refresh()
            
def plugin_prefs(parent: nb.Notebook, cmdr: str, is_beta: bool) -> nb.Frame | None:
    try:
        return preferences.pluginprefs(parent, cmdr, is_beta)
    except Exception as e:
        # EDMC drops the whole settings tab if this raises; keep a stub so the
        # tab still appears and the log explains what went wrong.
        logger.error("Architect Tracker settings tab failed to build: %s", e)
        logger.error("Traceback:\n%s", traceback.format_exc())
        frame = nb.Frame(parent)
        nb.Label(
            frame,
            text=("Architect Tracker settings failed to load. "
                  "Open the log viewer from the plugin folder or "
                  "~/.config/ArchitectTracker/EDMC_Architect_Log.txt"),
            wraplength=400,
            justify="left",
        ).grid(row=1, column=0, sticky="nw", padx=5, pady=5)
        return frame

def prefs_changed(cmdr: str, is_beta: bool) -> None:
    helpers.save_gui_settings()
