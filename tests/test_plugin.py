"""Regression tests for the Architect Tracker plugin.

Run them with:

    python3 tests/test_plugin.py

They need Tkinter and a display. On a headless machine use `xvfb-run -a python3
tests/test_plugin.py`. EDMC itself is not needed; tests/stubs stands in for it.
"""

import json
import os
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.dirname(TESTS_DIR)

# A throwaway home so the tests never touch a real ArchitectTracker install.
_SANDBOX = tempfile.mkdtemp(prefix="architecttracker-tests-")
os.environ["HOME"] = _SANDBOX
os.environ.pop("XDG_CONFIG_HOME", None)

sys.path.insert(0, os.path.join(TESTS_DIR, "stubs"))
sys.path.insert(0, PLUGIN_DIR)

try:
    import tkinter as tk
    from tkinter import ttk
    ROOT = tk.Tk()
    ROOT.withdraw()
except Exception as exc:  # pragma: no cover - depends on the machine
    print(f"Tkinter is unavailable ({exc}); try: xvfb-run -a python3 tests/test_plugin.py")
    raise SystemExit(77)

import globals as g
import helpers
import load
import marketimport
import preferences
import myNotebook as nb
from commodities import commodity_key
from config import config
from fleetcarriercargotracker import FleetCarrierCargoTracker, cargo_key
from tooltip import Tooltip


class FakeGUI:
    """Stands in for the tracker window in tests that only care about the guard."""

    def __init__(self, exists=True):
        self._exists = exists

    def winfo_exists(self):
        if self._exists == "torn-down":
            raise tk.TclError("application has been destroyed")
        return 1 if self._exists else 0


class PluginTestCase(unittest.TestCase):
    """Gives every test a clean user directory, config and journal directory."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(dir=_SANDBOX)
        self.journal_dir = os.path.join(self.tmp, "journals")
        os.makedirs(self.journal_dir)

        g.USER_DIR = self.tmp
        g.SAVE_FILE = os.path.join(self.tmp, "construction_requirements.json")
        g.MARKET_LIB_PATH = os.path.join(self.tmp, "market_library_v2.json")
        g.CARRIER_FILE = os.path.join(self.tmp, "fleet_carrier_cargo.json")
        g.COMMODITY_FILE = os.path.join(PLUGIN_DIR, "commodity_list.txt")
        g.set_journal_dir(self.journal_dir)

        g.ARCHITECT_GUI = None
        g.CURRENT_LOCATION = None
        g.SITE_LOCATION = None
        g.SHIP_STATE = g.SHIP_MODE.Unknown
        g.DOCKED_STATION_TYPE = g.STATION_TYPE.Orbital
        g.CARRIER_TRACKER = FleetCarrierCargoTracker()
        g.FCAPI_PAUSED = False
        config.settings.clear()
        # Overlay module caches its import and painted ids across tests.
        import overlay as overlay_mod
        import edmcoverlay as edmcoverlay_stub
        overlay_mod._edmcoverlay_mod = edmcoverlay_stub
        overlay_mod._overlay_client = None
        overlay_mod._import_attempted = True
        overlay_mod._warned_unavailable = False
        overlay_mod._warned_send = False
        overlay_mod._logged_missing = False
        overlay_mod._logged_skip_disabled = False
        overlay_mod._logged_skip_unavailable = False
        overlay_mod._group_registered = False
        overlay_mod._active_row_count = 0
        overlay_mod._last_payload = None
        overlay_mod._last_heartbeat = 0.0
        edmcoverlay_stub.Overlay.reset()
        if hasattr(edmcoverlay_stub, "MODERN_OVERLAY_IDENTITY"):
            delattr(edmcoverlay_stub, "MODERN_OVERLAY_IDENTITY")

    def tearDown(self):
        if g.ARCHITECT_GUI is not None:
            try:
                g.ARCHITECT_GUI.destroy()
            except Exception:
                pass
            g.ARCHITECT_GUI = None

    def write_json(self, path, obj):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f)

    def open_tracker_window(self):
        """Build the tracker against this test's temp dirs."""
        if g.ARCHITECT_GUI is not None:
            try:
                g.ARCHITECT_GUI.destroy()
            except Exception:
                pass
        from architecttrackergui import ArchitectTrackerGUI
        g.ARCHITECT_GUI = ArchitectTrackerGUI(ROOT)
        ROOT.update()
        return g.ARCHITECT_GUI

    def errors_logged(self, fn, *args, **kwargs):
        """Run fn and return the ERROR-level messages the plugin logged."""
        import logging

        captured = []

        class Capture(logging.Handler):
            def emit(self, record):
                if record.levelno >= logging.ERROR:
                    captured.append(record.getMessage())

        handler = Capture()
        g.logger.addHandler(handler)
        try:
            fn(*args, **kwargs)
        finally:
            g.logger.removeHandler(handler)
        return captured


class TestWindowGuard(PluginTestCase):
    """The window may be closed, never opened, or already torn down."""

    def test_gui_exists_reports_each_state(self):
        g.ARCHITECT_GUI = None
        self.assertFalse(helpers.gui_exists())
        g.ARCHITECT_GUI = FakeGUI(exists=False)
        self.assertFalse(helpers.gui_exists())
        g.ARCHITECT_GUI = FakeGUI(exists=True)
        self.assertTrue(helpers.gui_exists())
        g.ARCHITECT_GUI = FakeGUI(exists="torn-down")
        self.assertFalse(helpers.gui_exists())

    def test_journal_entry_without_a_window_does_not_raise(self):
        entry = {"event": "FSDJump", "StarPos": [1.0, 2.0, 3.0]}
        errors = self.errors_logged(
            load.journal_entry, "Cmdr", False, "Sol", None, entry, {"IsDocked": False})
        self.assertEqual(errors, [])
        self.assertEqual(g.CURRENT_LOCATION, (1.0, 2.0, 3.0))
        # closing the window stops tracking, as documented in the README
        self.assertEqual(g.SHIP_STATE, g.SHIP_MODE.Unknown)

    def test_journal_entry_with_a_window_tracks_ship_state(self):
        g.ARCHITECT_GUI = FakeGUI(exists=True)
        load.journal_entry("Cmdr", False, "Sol", None,
                           {"event": "FSDJump", "StarPos": [1.0, 2.0, 3.0]},
                           {"IsDocked": False})
        self.assertEqual(g.SHIP_STATE, g.SHIP_MODE.Undocked)

    def test_plugin_stop_without_a_window(self):
        g.ARCHITECT_GUI = None
        load.plugin_stop()


class TestJournalDirectory(PluginTestCase):
    """Finding Elite's journals, which is where most Linux installs come unstuck."""

    def test_prefers_the_directory_edmc_is_watching(self):
        config.set("journaldir", self.journal_dir)
        self.assertEqual(g.find_ed_journal_dir(), self.journal_dir)

    def test_ignores_a_journaldir_that_no_longer_exists(self):
        config.set("journaldir", os.path.join(self.tmp, "gone"))
        self.assertIsNone(g.find_ed_journal_dir())

    def test_no_journal_directory_anywhere_is_not_a_crash(self):
        g.set_journal_dir(None)
        self.assertIsNone(g.MARKET_JSON)
        self.assertIsNone(g.CARGO_JSON)
        # every consumer has to cope with the paths being unset
        self.assertEqual(helpers.load_starship_cargo_data(), [])
        self.assertEqual(helpers.load_market_stock(), set())
        self.assertIsNone(helpers.get_current_location_from_journal())
        self.assertEqual(self.errors_logged(helpers.update_market_library), [])

    def test_setting_the_directory_updates_the_derived_paths(self):
        g.set_journal_dir(self.journal_dir)
        self.assertEqual(g.MARKET_JSON, os.path.join(self.journal_dir, "Market.json"))
        self.assertEqual(g.CARGO_JSON, os.path.join(self.journal_dir, "Cargo.json"))

    def test_a_saved_choice_wins_and_is_validated(self):
        chosen = os.path.join(self.tmp, "chosen")
        os.makedirs(chosen)
        config.set("ArchTrack_EDSaveDir", chosen)
        self.assertEqual(helpers.resolve_journal_dir(), chosen)
        self.assertEqual(g.CARGO_JSON, os.path.join(chosen, "Cargo.json"))

        # a stale choice falls back to what we detected rather than breaking
        config.set("ArchTrack_EDSaveDir", os.path.join(self.tmp, "deleted"))
        g.set_journal_dir(self.journal_dir)
        self.assertEqual(helpers.resolve_journal_dir(), self.journal_dir)

    def test_location_is_read_from_the_newest_journal(self):
        with open(os.path.join(self.journal_dir, "Journal.2026-01-01T000000.01.log"),
                  "w", encoding="utf-8") as f:
            f.write('{"event":"Location","StarPos":[1.0,2.0,3.0]}\n')
            f.write('not json at all\n')
            f.write('{"event":"FSDJump","StarPos":[4.5,-6.0,7.25],"StarSystem":"Bl\\u00e9riot"}\n')
        self.assertEqual(helpers.get_current_location_from_journal(), (4.5, -6.0, 7.25))

    def test_a_journal_with_non_ascii_names_is_readable(self):
        path = os.path.join(self.journal_dir, "Journal.2026-01-02T000000.01.log")
        with open(path, "wb") as f:
            f.write('{"event":"FSDJump","StarPos":[1.0,1.0,1.0],"Cmdr":"Ãœberpilot"}\n'.encode("utf-8"))
        self.assertEqual(helpers.get_current_location_from_journal(), (1.0, 1.0, 1.0))


class TestMarketLibrary(PluginTestCase):
    STEEL = "$steel_name;"

    def market(self, price=4000):
        # a station always pays less than it charges, hence the spread
        return {"StationName": "Jameson Memorial", "MarketID": 128666762,
                "Items": [{"Name": self.STEEL, "Stock": 500,
                           "BuyPrice": price, "SellPrice": price - 100}]}

    def site(self, location, price=9000):
        return {"Site Alpha": {"Location": location, "ID": 3700001,
                               "materials": {self.STEEL: {"Name_Localised": "Steel",
                                                          "RequiredAmount": 1000,
                                                          "ProvidedAmount": 0,
                                                          "Price": price}}}}

    def test_missing_sections_are_repaired(self):
        self.write_json(g.MARKET_LIB_PATH, {"Markets": []})
        lib = helpers.get_market_library()
        self.assertEqual(lib["Commodities"], {})
        self.assertEqual(lib["Markets"], [])

    def test_a_corrupt_library_is_replaced_rather_than_fatal(self):
        with open(g.MARKET_LIB_PATH, "w", encoding="utf-8") as f:
            f.write("{not json")
        lib = helpers.get_market_library()
        self.assertEqual(lib, {"Commodities": {}, "Markets": []})

    def test_updates_when_the_site_location_is_unknown(self):
        """A site saved before the first StarPos leaves SITE_LOCATION unset."""
        self.write_json(g.SAVE_FILE, self.site(location=None))
        self.write_json(g.MARKET_JSON, self.market(price=2000))
        self.write_json(g.MARKET_LIB_PATH, {
            "Commodities": {self.STEEL: {
                "CheapMarkets": {"Orbital": {"Price": 3000, "StationID": 111}},
                "ClosestMarkets": {"Orbital": {"Price": 3000, "StationID": 111}}}},
            "Markets": [{"StationName": "Old Station", "Location": [1.0, 2.0, 3.0],
                         "StationID": 111, "Type": "Orbital"}]})
        helpers.load_facility_requirements()
        g.CURRENT_LOCATION = (10.0, 20.0, 30.0)
        self.assertIsNone(g.SITE_LOCATION)

        self.assertEqual(self.errors_logged(helpers.update_market_library), [])
        lib = helpers.get_market_library()
        self.assertEqual(lib["Commodities"][self.STEEL]["CheapMarkets"]["Orbital"]["StationID"],
                         128666762)

    def test_a_market_missing_from_the_markets_list(self):
        self.write_json(g.MARKET_LIB_PATH, {
            "Commodities": {self.STEEL: {
                "CheapMarkets": {"Orbital": {"Price": 3000, "StationID": 999}},
                "ClosestMarkets": {"Orbital": {"Price": 3000, "StationID": 999}}}},
            "Markets": []})
        self.assertEqual(helpers.get_prefMarket_name(self.STEEL), "")

    def test_a_market_location_is_filled_in_once_it_is_known(self):
        lib = {"Commodities": {}, "Markets": []}
        g.CURRENT_LOCATION = None
        helpers.ensure_market_exists(lib, "Somewhere", 222)
        self.assertIsNone(lib["Markets"][0]["Location"])
        self.assertEqual(helpers.distance_to_site(lib, 222), float("inf"))

        g.CURRENT_LOCATION = (1.0, 2.0, 3.0)
        helpers.ensure_market_exists(lib, "Somewhere", 222)
        self.assertEqual(lib["Markets"][0]["Location"], (1.0, 2.0, 3.0))

    def test_preferred_market_falls_back_to_the_other_station_type(self):
        self.write_json(g.MARKET_LIB_PATH, {
            "Commodities": {self.STEEL: {
                "CheapMarkets": {"Surface": {"Price": 3000, "StationID": 111}}}},
            "Markets": [{"StationName": "Dirt Farm", "Location": [1.0, 2.0, 3.0],
                         "StationID": 111, "Type": "Surface"}]})
        config.set("ArchTrack_prefType", g.STATION_TYPE.Orbital.value)
        self.assertEqual(helpers.get_prefMarket_name(self.STEEL), "*Dirt Farm")
        config.set("ArchTrack_prefType", g.STATION_TYPE.Surface.value)
        self.assertEqual(helpers.get_prefMarket_name(self.STEEL), "Dirt Farm")

    def test_market_stock_without_a_market_file(self):
        self.assertEqual(helpers.load_market_stock(), set())
        self.assertFalse(helpers.is_market_selling(self.STEEL))

    def test_market_stock_only_lists_what_is_in_stock(self):
        self.write_json(g.MARKET_JSON, {"StationName": "X", "MarketID": 1, "Items": [
            {"Name": self.STEEL, "Stock": 10, "BuyPrice": 1},
            {"Name": "$gold_name;", "Stock": 0, "BuyPrice": 1}]})
        stock = helpers.load_market_stock()
        self.assertTrue(helpers.is_market_selling(self.STEEL, stock))
        self.assertFalse(helpers.is_market_selling("$gold_name;", stock))

    def test_the_price_recorded_is_what_the_commander_pays(self):
        """BuyPrice, not SellPrice, which is what the station would pay us."""
        self.write_json(g.SAVE_FILE, self.site(location=[1.0, 2.0, 3.0]))
        self.write_json(g.MARKET_JSON, self.market(price=4000))
        helpers.load_facility_requirements()
        g.CURRENT_LOCATION = (10.0, 20.0, 30.0)
        helpers.update_market_library()
        entry = helpers.get_market_library()["Commodities"][self.STEEL]["CheapMarkets"]["Orbital"]
        self.assertEqual(entry["Price"], 4000)

    def test_docking_records_the_system_name(self):
        self.write_json(g.SAVE_FILE, self.site(location=[1.0, 2.0, 3.0]))
        self.write_json(g.MARKET_JSON, self.market(price=4000))
        helpers.load_facility_requirements()
        g.CURRENT_LOCATION = (10.0, 20.0, 30.0)
        g.CURRENT_SYSTEM = "Sol"
        helpers.update_market_library()
        station = helpers.get_market_by_station_id(
            helpers.get_market_library(), 128666762)
        self.assertEqual(station["System"], "Sol")
        self.assertEqual(helpers.get_prefMarket_system(self.STEEL), "Sol")

    def test_preferred_market_distance_is_in_ly(self):
        self.write_json(g.MARKET_LIB_PATH, {
            "Commodities": {self.STEEL: {
                "ClosestMarkets": {"Orbital": {"Price": 2000, "StationID": 42}}}},
            "Markets": [{"StationName": "Jameson Memorial", "System": "Shinrarta Dezhra",
                         "Location": [11.0, 2.0, 3.0], "StationID": 42, "Type": "Orbital"}]})
        config.set("ArchTrack_prefMarket", g.MARKET_MODE.Closest.value)
        g.SITE_LOCATION = [1.0, 2.0, 3.0]
        self.assertEqual(helpers.get_prefMarket_distance(self.STEEL), "10.0")
        self.assertEqual(helpers.get_prefMarket_distance(self.STEEL, from_location=[1.0, 2.0, 3.0]),
                         "10.0")
        self.assertEqual(helpers.get_prefMarket_distance("$aluminium_name;"), "")

    def test_null_site_location_is_backfilled_on_update(self):
        self.write_json(g.SAVE_FILE, self.site(location=None))
        g.CURRENT_LOCATION = (4.0, 5.0, 6.0)
        helpers.save_facility_requirements(
            [{"Name": self.STEEL, "Name_Localised": "Steel", "RequiredAmount": 1000,
              "ProvidedAmount": 1, "Payment": 9000}],
            "Site Alpha", 3700001, "SysA")
        with open(g.SAVE_FILE, encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(list(saved["Site Alpha"]["Location"]), [4.0, 5.0, 6.0])

    def test_is_facility_matches_full_journal_names(self):
        self.write_json(g.SAVE_FILE, {
            "Orbital Construction Site: Vulcan Gate": {
                "Location": [1.0, 2.0, 3.0], "ID": 1,
                "materials": {self.STEEL: {"Name_Localised": "Steel", "RequiredAmount": 10,
                                           "ProvidedAmount": 0, "Price": 9000}}}})
        self.assertTrue(helpers.is_facility("Orbital Construction Site: Vulcan Gate"))
        self.assertTrue(helpers.is_facility("Vulcan Gate"))
        self.assertFalse(helpers.is_facility("Somewhere Else"))

    def test_price_above_site_cost_demotes_cheap_and_closest(self):
        g.SITE_LOCATION = [0.0, 0.0, 0.0]
        lib = {"Commodities": {}, "Markets": []}
        site_prices = {self.STEEL: [9000]}
        helpers.record_market_price(
            lib, self.STEEL, 1000, "Jameson", 42, g.STATION_TYPE.Orbital,
            [1.0, 0.0, 0.0], site_prices, "Sol")
        self.assertEqual(lib["Commodities"][self.STEEL]["CheapMarkets"]["Orbital"]["Price"], 1000)
        helpers.record_market_price(
            lib, self.STEEL, 9500, "Jameson", 42, g.STATION_TYPE.Orbital,
            [1.0, 0.0, 0.0], site_prices, "Sol")
        self.assertNotIn("Orbital", lib["Commodities"][self.STEEL].get("CheapMarkets", {}))
        self.assertNotIn("Orbital", lib["Commodities"][self.STEEL].get("ClosestMarkets", {}))
        self.assertEqual(
            lib["Commodities"][self.STEEL]["AlternateMarkets"]["Orbital"]["StationID"], 42)

    def test_closest_price_updates_for_the_same_station(self):
        g.SITE_LOCATION = [0.0, 0.0, 0.0]
        lib = {"Commodities": {}, "Markets": []}
        site_prices = {self.STEEL: [9000]}
        helpers.record_market_price(
            lib, self.STEEL, 2000, "Jameson", 42, g.STATION_TYPE.Orbital,
            [1.0, 0.0, 0.0], site_prices, "Sol")
        helpers.record_market_price(
            lib, self.STEEL, 1800, "Jameson", 42, g.STATION_TYPE.Orbital,
            [1.0, 0.0, 0.0], site_prices, "Sol")
        self.assertEqual(lib["Commodities"][self.STEEL]["ClosestMarkets"]["Orbital"]["Price"], 1800)

    def test_legacy_purge_tolerates_null_location(self):
        old = os.path.join(g.USER_DIR, "market_library.json")
        self.write_json(old, {
            self.STEEL: {"CheapMarket": {"StationName": "Jameson", "Location": None}}})
        g.CURRENT_LOCATION = (1.0, 2.0, 3.0)
        self.assertEqual(self.errors_logged(helpers.remove_from_old_market_library, "Jameson"), [])


class TestSettings(PluginTestCase):
    def test_defaults_when_nothing_has_been_saved(self):
        vis, hid, theme, cols, trans, top, opac = helpers.load_gui_settings()
        self.assertEqual(list(vis), list(g.DEFAULT_COLUMNS))
        self.assertFalse(hid)
        self.assertEqual(theme, "Dark Mode")
        self.assertEqual(cols, list(g.DEFAULT_COLUMNS))
        self.assertEqual(opac, 100)

    def test_the_failure_path_still_returns_every_value(self):
        broken = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("config is broken"))
        original, config.get = config.get, broken
        try:
            settings = helpers.load_gui_settings()
        finally:
            config.get = original
        self.assertEqual(len(settings), 7)
        # and it is still usable by the window
        vis, hid, theme, cols, trans, top, opac = settings
        self.assertEqual(len(cols), len(g.DEFAULT_COLUMNS))

    def test_column_names_survive_a_saved_list_of_the_wrong_length(self):
        config.set("ArchTrack_cols", ["Material", "Required"])
        names = helpers.load_column_names()
        self.assertEqual(len(names), len(g.DEFAULT_COLUMNS))
        self.assertEqual(names[:2], ["Material", "Required"])
        self.assertEqual(names[2], list(g.DEFAULT_COLUMNS)[2])

    def test_pre_system_column_renames_are_kept(self):
        # Eight names from before System (and Distance) were inserted after Pref Market.
        config.set("ArchTrack_cols", [
            "Material", "Required", "Provided", "Left", "Pref Market",
            "FC", "Ship", "Still to buy"])
        names = helpers.load_column_names()
        self.assertEqual(len(names), len(g.DEFAULT_COLUMNS))
        self.assertEqual(names[3], "Left")
        self.assertEqual(names[5], "System")
        self.assertEqual(names[6], "Distance")
        self.assertEqual(names[7], "FC")
        self.assertEqual(names[8], "Ship")
        self.assertEqual(names[9], "Still to buy")

    def test_pre_distance_column_renames_are_kept(self):
        # Nine names from after System but before Distance.
        config.set("ArchTrack_cols", [
            "Material", "Required", "Provided", "Left", "Pref Market",
            "System", "FC", "Ship", "Still to buy"])
        names = helpers.load_column_names()
        self.assertEqual(len(names), len(g.DEFAULT_COLUMNS))
        self.assertEqual(names[3], "Left")
        self.assertEqual(names[5], "System")
        self.assertEqual(names[6], "Distance")
        self.assertEqual(names[7], "FC")
        self.assertEqual(names[9], "Still to buy")

    def test_show_ui_at_start_defaults_to_true(self):
        self.assertTrue(helpers.show_ui_at_start())
        config.set("ArchTrack_showUI", False)
        self.assertFalse(helpers.show_ui_at_start())

    def test_show_ui_at_start_is_saved_with_the_window_closed(self):
        config.set("ArchTrack_showUI", True)
        g.ARCHITECT_GUI = None
        preferences.toggle_showUIatStart(False)
        self.assertIs(config.get("ArchTrack_showUI"), False)
        helpers.save_gui_settings()
        self.assertIs(config.get("ArchTrack_showUI"), False)

    def test_carrier_sync_defaults_to_always_on(self):
        self.assertEqual(helpers.fcapi_mode(), "always")
        self.assertFalse(g.FCAPI_PAUSED)

    def test_old_carrier_sync_labels_map_to_always_or_paused(self):
        config.set("ArchTrack_fcapimode", "First then pause")
        self.assertEqual(helpers.fcapi_mode(), "always")
        config.set("ArchTrack_fcapimode", "Only when unpaused")
        self.assertEqual(helpers.fcapi_mode(), "paused")

    def test_carrier_sync_dropdown_pauses_and_resumes_capi(self):
        payload = {"cargo": [{"commodity": "Steel", "qty": 10}],
                   "name": {"callsign": "ABC-123"}}
        preferences.change_fcapi_mode("Always on")
        self.assertFalse(g.FCAPI_PAUSED)
        load.capi_fleetcarrier(payload)
        self.assertEqual(g.CARRIER_TRACKER.get_quantity("steel"), 10)
        load.capi_fleetcarrier({"cargo": [{"commodity": "Steel", "qty": 40}],
                                "name": {"callsign": "ABC-123"}})
        self.assertEqual(g.CARRIER_TRACKER.get_quantity("steel"), 40)
        self.assertFalse(g.FCAPI_PAUSED)

        preferences.change_fcapi_mode("Paused")
        self.assertTrue(g.FCAPI_PAUSED)
        load.capi_fleetcarrier({"cargo": [{"commodity": "Steel", "qty": 99}],
                                "name": {"callsign": "ABC-123"}})
        self.assertEqual(g.CARRIER_TRACKER.get_quantity("steel"), 40)

        helpers.set_fcapi_paused(False)
        self.assertEqual(helpers.fcapi_mode(), "always")
        self.assertFalse(g.FCAPI_PAUSED)

    def test_renaming_a_column_is_saved_with_the_window_closed(self):
        g.ARCHITECT_GUI = None
        preferences.on_column_rename("Needed", "Left")
        self.assertEqual(helpers.load_column_names()[3], "Left")

    def test_settings_tab_builds_without_mixing_pack_and_grid(self):
        # EDMC's nb.Frame grids a spacer on create; packing into it raises TclError
        # and EDMC then omits the whole ArchitectTracker settings tab.
        notebook = nb.Notebook(ROOT)
        frame = preferences.pluginprefs(notebook, "TestCMDR", False)
        self.assertIsNotNone(frame)
        self.assertTrue(frame.winfo_exists())
        frame.destroy()
        notebook.destroy()


class TestHotkeys(PluginTestCase):
    def test_typing_in_a_text_field_is_not_a_hotkey(self):
        for widget in (tk.Entry(ROOT), tk.Text(ROOT), ttk.Entry(ROOT), ttk.Combobox(ROOT)):
            self.assertTrue(helpers.is_typing_widget(widget),
                            f"{widget.winfo_class()} should be treated as a text field")
            widget.destroy()

    def test_other_widgets_still_get_hotkeys(self):
        for widget in (tk.Frame(ROOT), tk.Button(ROOT), tk.Canvas(ROOT)):
            self.assertFalse(helpers.is_typing_widget(widget))
            widget.destroy()

    def test_a_keypress_in_an_entry_does_not_toggle_the_window(self):
        entry = tk.Entry(ROOT)
        event = type("Event", (), {"widget": entry, "char": "t", "keysym": "t"})()
        g.ARCHITECT_GUI = None
        helpers.on_key_press(event)
        self.assertIsNone(g.ARCHITECT_GUI)
        entry.destroy()


class TestFleetCarrierCargo(PluginTestCase):
    def test_names_from_every_source_reach_the_same_key(self):
        self.assertEqual(cargo_key("$cmmcomposite_name;"), "cmmcomposite")
        self.assertEqual(cargo_key("CMM Composite"), "cmmcomposite")
        self.assertEqual(cargo_key("cmmcomposite"), "cmmcomposite")
        self.assertEqual(cargo_key("Aluminium"), "aluminium")
        self.assertEqual(cargo_key(None), "")

    def test_capi_then_transfer_then_buy_and_sell(self):
        tracker = g.CARRIER_TRACKER
        tracker.update({"cargo": [{"commodity": "CMM Composite", "qty": 100},
                                  {"commodity": "CMM Composite", "qty": 50}],
                        "name": {"callsign": "ABC-123"}})
        self.assertEqual(tracker.get_quantity("$cmmcomposite_name;"), 150)

        tracker.apply_transfer_event([{"Type": "cmmcomposite", "Count": 10,
                                       "Direction": "tocarrier"}])
        self.assertEqual(tracker.get_quantity("cmmcomposite"), 160)

        tracker.apply_transfer_event([{"Type": "cmmcomposite", "Count": 60,
                                       "Direction": "toship"}])
        self.assertEqual(tracker.get_quantity("cmmcomposite"), 100)

        tracker.apply_market_purchase({"Type": "cmmcomposite", "Count": 40})
        self.assertEqual(tracker.get_quantity("cmmcomposite"), 60)

        tracker.apply_market_sale({"Type": "cmmcomposite", "Count": 25})
        self.assertEqual(tracker.get_quantity("cmmcomposite"), 85)

    def test_events_without_a_commodity_are_ignored(self):
        tracker = g.CARRIER_TRACKER
        tracker.apply_transfer_event([{"Count": 5, "Direction": "tocarrier"}])
        tracker.apply_market_purchase({"Count": 5})
        tracker.apply_market_sale({"Count": 5})
        self.assertEqual(tracker.commodities, {})

    def test_cargo_saved_by_an_older_version_is_re_keyed(self):
        self.write_json(g.CARRIER_FILE, {"carrier_name": "Hauler", "callsign": "ABC-123",
                                         "commodities": {"Cmmcomposite": 10,
                                                         "CMM Composite": 5}})
        tracker = FleetCarrierCargoTracker()
        self.assertEqual(tracker.get_quantity("$cmmcomposite_name;"), 15)

    def test_a_vanity_name_that_is_not_hex(self):
        tracker = g.CARRIER_TRACKER
        tracker.update({"cargo": [], "name": {"vanityName": "not hex", "callsign": "ABC-123"}})
        self.assertEqual(tracker.carrier_name, "not hex")

    def test_stale_capi_does_not_undo_a_transfer_to_ship(self):
        tracker = g.CARRIER_TRACKER
        tracker.update({"cargo": [{"commodity": "Steel", "qty": 1000}],
                        "name": {"callsign": "ABC-123"},
                        "market": {"id": 3700000099},
                        "timestamp": "2026-01-01T12:00:00Z"})
        tracker.apply_transfer_event(
            [{"Type": "steel", "Count": 400, "Direction": "toship"}],
            timestamp="2026-01-01T12:05:00Z")
        self.assertEqual(tracker.get_quantity("steel"), 600)

        # Frontier CAPI often still has the pre-transfer snapshot.
        tracker.update({"cargo": [{"commodity": "Steel", "qty": 1000}],
                        "name": {"callsign": "ABC-123"},
                        "timestamp": "2026-01-01T12:00:00Z"})
        self.assertEqual(tracker.get_quantity("steel"), 600)

        # A later snapshot that already includes the transfer is left alone.
        tracker.update({"cargo": [{"commodity": "Steel", "qty": 600}],
                        "name": {"callsign": "ABC-123"},
                        "timestamp": "2026-01-01T12:06:00Z"})
        self.assertEqual(tracker.get_quantity("steel"), 600)

    def test_toship_accepts_localised_names_and_odd_direction_case(self):
        tracker = g.CARRIER_TRACKER
        tracker.update({"cargo": [{"commodity": "Steel", "qty": 50}],
                        "name": {"callsign": "ABC-123"}})
        tracker.apply_transfer_event([
            {"Type": "", "Type_Localised": "Steel", "Count": "20", "Direction": "ToShip"}])
        self.assertEqual(tracker.get_quantity("$steel_name;"), 30)

    def test_own_carrier_matches_market_id_when_the_station_name_differs(self):
        tracker = g.CARRIER_TRACKER
        tracker.update({"cargo": [{"commodity": "Steel", "qty": 80}],
                        "name": {"callsign": "ABC-123"},
                        "market": {"id": 3700000099}})
        self.assertTrue(tracker.is_own_carrier("Homerus", 3700000099))
        self.assertTrue(tracker.is_own_carrier("abc-123"))
        self.assertFalse(tracker.is_own_carrier("Jameson Memorial", 128666762))

        tracker.apply_market_purchase({"Type": "steel", "Count": 15, "MarketID": 3700000099})
        self.assertEqual(tracker.get_quantity("steel"), 65)

    def test_transfer_to_ship_is_tracked_with_the_window_closed(self):
        g.ARCHITECT_GUI = None
        tracker = g.CARRIER_TRACKER
        tracker.update({"cargo": [{"commodity": "Steel", "qty": 100}],
                        "name": {"callsign": "ABC-123"}})
        load.journal_entry("Cmdr", False, "Vulcan", "ABC-123", {
            "event": "CargoTransfer", "timestamp": "2026-01-01T12:05:00Z",
            "Transfers": [{"Type": "steel", "Count": 40, "Direction": "toship"}]},
            {"IsDocked": True})
        self.assertEqual(tracker.get_quantity("steel"), 60)


class TestTooltip(PluginTestCase):
    def test_updating_the_text_does_not_add_bindings(self):
        canvas = tk.Canvas(ROOT, width=25, height=25)
        tooltip = Tooltip(canvas, "first", follow_mouse=True)

        def handlers(sequence):
            return len([l for l in canvas.bind(sequence).strip().split("\n") if l.strip()])

        before = (handlers("<Enter>"), handlers("<Leave>"), handlers("<Motion>"))
        for i in range(25):
            tooltip.set_text(f"text {i}")
        self.assertEqual((handlers("<Enter>"), handlers("<Leave>"), handlers("<Motion>")), before)
        self.assertEqual(tooltip.text, "text 24")
        canvas.destroy()


class TestTrackerWindow(PluginTestCase):
    """The window has two shapes: the 'no sites yet' message and the table."""

    def open_window(self):
        from architecttrackergui import ArchitectTrackerGUI
        g.EDMC_ROOT = ROOT
        g.ARCHITECT_GUI = ArchitectTrackerGUI(ROOT)
        ROOT.update()
        return g.ARCHITECT_GUI

    def save_a_site(self):
        self.write_json(g.SAVE_FILE, {"Orbital Construction Site: Vulcan Gate": {
            "Location": [1.0, 2.0, 3.0], "ID": 3700001,
            "materials": {"$steel_name;": {"Name_Localised": "Steel", "RequiredAmount": 100,
                                           "ProvidedAmount": 10, "Price": 9000}}}})

    def test_opens_with_no_data(self):
        window = self.open_window()
        self.assertFalse(window.has_table)

    def test_settings_controls_work_with_no_data(self):
        self.open_window()
        preferences.toggle_column("Needed", False)
        preferences.on_column_rename("Needed", "Left")
        preferences.toggle_hide_provided(True)
        preferences.reset_Style("Light Mode")
        preferences.toggle_win_top(True)
        preferences.on_delete_markets()
        ROOT.update()

    def test_the_table_appears_once_a_site_is_visited(self):
        window = self.open_window()
        self.assertFalse(window.has_table)

        self.save_a_site()
        g.SITE_LOCATION = [1.0, 2.0, 3.0]
        window.refresh()
        ROOT.update()

        self.assertTrue(window.has_table)
        self.assertEqual(window.dropdown["values"], ("Vulcan Gate",))
        rows = window.tree.get_children()
        self.assertEqual(len(rows), 2)  # one commodity plus the totals row
        self.assertEqual(window.tree.item(rows[0])["values"][:4], ["Steel", 100, 10, 90])

    def test_ctrl_click_copies_the_system_name(self):
        self.save_a_site()
        self.write_json(g.MARKET_LIB_PATH, {
            "Commodities": {"$steel_name;": {
                "CheapMarkets": {"Orbital": {"Price": 2000, "StationID": 42}}}},
            "Markets": [{"StationName": "Jameson Memorial", "System": "Shinrarta Dezhra",
                         "Location": [11.0, 2.0, 3.0], "StationID": 42, "Type": "Orbital"}]})
        g.SITE_LOCATION = [1.0, 2.0, 3.0]
        window = self.open_window()
        ROOT.update()
        row = window.tree.get_children()[0]
        self.assertEqual(window.tree.set(row, "System"), "Shinrarta Dezhra")
        self.assertEqual(window.tree.set(row, "Distance"), "10.0")
        bbox = window.tree.bbox(row)
        self.assertTrue(bbox)
        event = type("E", (), {"y": bbox[1] + bbox[3] // 2})()
        result = window.on_copy_system_click(event)
        self.assertEqual(result, "break")
        self.assertEqual(window.clipboard_get(), "Shinrarta Dezhra")
        self.assertIn("Copied: Shinrarta Dezhra", window.market_name_label.cget("text"))

    def test_shortfall_header_sorts_the_list(self):
        self.write_json(g.SAVE_FILE, {"Orbital Construction Site: Vulcan Gate": {
            "Location": [1.0, 2.0, 3.0], "ID": 3700001,
            "materials": {
                "$steel_name;": {"Name_Localised": "Steel", "RequiredAmount": 100,
                                 "ProvidedAmount": 10, "Price": 9000},
                "$aluminium_name;": {"Name_Localised": "Aluminium", "RequiredAmount": 50,
                                     "ProvidedAmount": 40, "Price": 9000},
                "$titanium_name;": {"Name_Localised": "Titanium", "RequiredAmount": 200,
                                    "ProvidedAmount": 0, "Price": 9000},
            }}})
        g.SITE_LOCATION = [1.0, 2.0, 3.0]
        window = self.open_window()
        ROOT.update()
        names = [window.tree.set(r, "Material") for r in window.tree.get_children()[:-1]]
        self.assertEqual(names, ["Aluminium", "Steel", "Titanium"])  # Material A→Z default

        window.on_sort_column("Shortfall")
        ROOT.update()
        names = [window.tree.set(r, "Material") for r in window.tree.get_children()[:-1]]
        shorts = [int(window.tree.set(r, "Shortfall")) for r in window.tree.get_children()[:-1]]
        self.assertEqual(window.tree.set(window.tree.get_children()[-1], "Material"), "Totals")
        self.assertEqual(shorts, [200, 90, 10])  # high shortfall first
        self.assertEqual(names, ["Titanium", "Steel", "Aluminium"])
        self.assertIn("▼", window.tree.heading("Shortfall")["text"])

        window.on_sort_column("Shortfall")
        ROOT.update()
        shorts = [int(window.tree.set(r, "Shortfall")) for r in window.tree.get_children()[:-1]]
        self.assertEqual(shorts, [10, 90, 200])
        self.assertIn("▲", window.tree.heading("Shortfall")["text"])

    def test_distance_is_blank_without_a_preferred_market(self):
        self.save_a_site()
        g.SITE_LOCATION = [1.0, 2.0, 3.0]
        window = self.open_window()
        ROOT.update()
        row = window.tree.get_children()[0]
        self.assertEqual(window.tree.set(row, "Distance"), "")
        self.assertIn("Distance", window.tree["columns"])

    def test_copy_ignores_empty_system_cells(self):
        self.save_a_site()
        g.SITE_LOCATION = [1.0, 2.0, 3.0]
        window = self.open_window()
        ROOT.update()
        row = window.tree.get_children()[0]  # no preferred market yet
        self.assertEqual(window.tree.set(row, "System"), "")
        bbox = window.tree.bbox(row)
        event = type("E", (), {"y": bbox[1] + bbox[3] // 2})()
        window.clipboard_clear()
        window.clipboard_append("keep-me")
        self.assertEqual(window.on_copy_system_click(event), "break")
        self.assertEqual(window.clipboard_get(), "keep-me")

    def test_a_column_renamed_before_the_table_existed_is_used_when_it_is_built(self):
        window = self.open_window()
        self.assertFalse(window.has_table)
        preferences.on_column_rename("Shortfall", "Still to buy")

        self.save_a_site()
        g.SITE_LOCATION = [1.0, 2.0, 3.0]
        window.refresh()
        ROOT.update()
        self.assertEqual(window.tree.heading("Shortfall")["text"], "Still to buy")
        self.assertEqual(helpers.load_column_names()[-1], "Still to buy")

    def test_the_pause_tooltip_follows_the_rebuilt_canvas(self):
        self.save_a_site()
        g.SITE_LOCATION = [1.0, 2.0, 3.0]
        window = self.open_window()
        first_canvas = window.canvas
        self.assertIs(window.canvas_tooltip.widget, first_canvas)

        # losing the last site and getting a new one rebuilds every widget
        self.write_json(g.SAVE_FILE, {})
        window.refresh()
        self.save_a_site()
        g.SITE_LOCATION = [1.0, 2.0, 3.0]
        window.refresh()
        ROOT.update()

        self.assertIsNot(window.canvas, first_canvas)
        self.assertIs(window.canvas_tooltip.widget, window.canvas)

    def test_the_table_reverts_to_the_message_when_the_last_site_goes(self):
        self.save_a_site()
        g.SITE_LOCATION = [1.0, 2.0, 3.0]
        window = self.open_window()
        self.assertTrue(window.has_table)

        self.write_json(g.SAVE_FILE, {})
        window.refresh()
        ROOT.update()
        self.assertFalse(window.has_table)

    def test_sites_with_the_same_short_name_stay_separate(self):
        self.write_json(g.SAVE_FILE, {
            "Orbital Construction Site: Vulcan Gate": {
                "Location": [1.0, 2.0, 3.0], "ID": 1,
                "materials": {"$steel_name;": {"Name_Localised": "Steel", "RequiredAmount": 100,
                                               "ProvidedAmount": 0, "Price": 9000}}},
            "Planetary Construction Site: Vulcan Gate": {
                "Location": [1.0, 2.0, 3.0], "ID": 2,
                "materials": {"$steel_name;": {"Name_Localised": "Steel", "RequiredAmount": 200,
                                               "ProvidedAmount": 0, "Price": 9000}}}})
        g.SITE_LOCATION = [1.0, 2.0, 3.0]
        window = self.open_window()
        self.assertEqual(len(set(window.dropdown["values"])), 3)  # both sites plus -All-
        self.assertEqual(len(window.station_map), 3)  # both sites plus -All-

    def test_change_station_picks_the_matching_full_name(self):
        self.write_json(g.SAVE_FILE, {
            "Orbital Construction Site: Vulcan Gate": {
                "Location": [1.0, 2.0, 3.0], "ID": 1,
                "materials": {"$steel_name;": {"Name_Localised": "Steel", "RequiredAmount": 100,
                                               "ProvidedAmount": 0, "Price": 9000}}},
            "Planetary Construction Site: Vulcan Gate": {
                "Location": [10.0, 20.0, 30.0], "ID": 2,
                "materials": {"$steel_name;": {"Name_Localised": "Steel", "RequiredAmount": 200,
                                               "ProvidedAmount": 0, "Price": 9000}}}})
        g.SITE_LOCATION = [1.0, 2.0, 3.0]
        window = self.open_window()
        window.change_station("Planetary Construction Site: Vulcan Gate")
        ROOT.update()
        self.assertEqual(window.shown_station, "Planetary Construction Site: Vulcan Gate")
        self.assertEqual(list(g.SITE_LOCATION), [10.0, 20.0, 30.0])

    def test_table_opens_when_site_location_is_unknown(self):
        self.write_json(g.SAVE_FILE, {"Orbital Construction Site: Vulcan Gate": {
            "Location": None, "ID": 3700001,
            "materials": {"$steel_name;": {"Name_Localised": "Steel", "RequiredAmount": 100,
                                           "ProvidedAmount": 10, "Price": 9000}}}})
        g.SITE_LOCATION = None
        window = self.open_window()
        ROOT.update()
        self.assertTrue(window.has_table)
        self.assertEqual(window.tree.set(window.tree.get_children()[0], "Distance"), "")

    def test_all_view_leaves_distance_blank(self):
        self.write_json(g.SAVE_FILE, {
            "Orbital Construction Site: A": {
                "Location": [1.0, 2.0, 3.0], "ID": 1,
                "materials": {"$steel_name;": {"Name_Localised": "Steel", "RequiredAmount": 100,
                                               "ProvidedAmount": 0, "Price": 9000}}},
            "Orbital Construction Site: B": {
                "Location": [100.0, 200.0, 300.0], "ID": 2,
                "materials": {"$steel_name;": {"Name_Localised": "Steel", "RequiredAmount": 50,
                                               "ProvidedAmount": 0, "Price": 9000}}}})
        self.write_json(g.MARKET_LIB_PATH, {
            "Commodities": {"$steel_name;": {
                "CheapMarkets": {"Orbital": {"Price": 2000, "StationID": 42}}}},
            "Markets": [{"StationName": "Jameson Memorial", "System": "Shinrarta Dezhra",
                         "Location": [11.0, 2.0, 3.0], "StationID": 42, "Type": "Orbital"}]})
        g.SITE_LOCATION = [1.0, 2.0, 3.0]
        window = self.open_window()
        window.station_var.set("-All-")
        window.display_station()
        ROOT.update()
        row = window.tree.get_children()[0]
        self.assertEqual(window.tree.set(row, "Material"), "Steel")
        self.assertEqual(window.tree.set(row, "Distance"), "")

    def test_split_cargo_stacks_are_summed(self):
        self.save_a_site()
        self.write_json(g.CARGO_JSON, {"Inventory": [
            {"Name": "steel", "Count": 10, "Stolen": 0},
            {"Name": "steel", "Count": 5, "Stolen": 1}]})
        g.SITE_LOCATION = [1.0, 2.0, 3.0]
        window = self.open_window()
        ROOT.update()
        row = window.tree.get_children()[0]
        self.assertEqual(int(window.tree.set(row, "Ship Qty")), 15)
        self.assertEqual(int(window.tree.set(row, "Shortfall")), 75)

    def test_ship_and_carrier_qty_share_one_commodity_spelling(self):
        self.write_json(g.SAVE_FILE, {"Orbital Construction Site: Vulcan Gate": {
            "Location": [1.0, 2.0, 3.0], "ID": 3700001,
            "materials": {"$hazardousenvironmentsuits_name;": {
                "Name_Localised": "H.E. Suits", "RequiredAmount": 100,
                "ProvidedAmount": 0, "Price": 9000}}}})
        self.write_json(g.CARGO_JSON, {"Inventory": [
            {"Name": "$hesuits_name;", "Count": 12}]})
        g.CARRIER_TRACKER.update({"cargo": [{"commodity": "H.E. Suits", "qty": 30}],
                                  "name": {"callsign": "ABC-123"}})
        g.SITE_LOCATION = [1.0, 2.0, 3.0]
        window = self.open_window()
        ROOT.update()
        row = window.tree.get_children()[0]
        self.assertEqual(int(window.tree.set(row, "Carrier Qty")), 30)
        self.assertEqual(int(window.tree.set(row, "Ship Qty")), 12)
        self.assertEqual(int(window.tree.set(row, "Shortfall")), 58)

    def test_transfer_to_ship_updates_the_carrier_column(self):
        self.save_a_site()
        g.CARRIER_TRACKER.update({"cargo": [{"commodity": "Steel", "qty": 100}],
                                  "name": {"callsign": "ABC-123"},
                                  "timestamp": "2026-01-01T12:00:00Z"})
        g.SITE_LOCATION = [1.0, 2.0, 3.0]
        window = self.open_window()
        ROOT.update()
        load.journal_entry("Cmdr", False, "Vulcan", "ABC-123", {
            "event": "CargoTransfer", "timestamp": "2026-01-01T12:05:00Z",
            "Transfers": [{"Type": "steel", "Count": 40, "Direction": "toship"}]},
            {"IsDocked": True})
        ROOT.update()
        row = window.tree.get_children()[0]
        self.assertEqual(int(window.tree.set(row, "Carrier Qty")), 60)

    def test_edmc_keeps_its_own_ttk_theme(self):
        before = ttk.Style().theme_use()
        window = self.open_window()
        window.reset_Style("Light Mode")
        ROOT.update()
        self.assertEqual(ttk.Style().theme_use(), before)

        window.reset_Style("Dark Mode")
        ROOT.update()
        window.destroy()
        g.ARCHITECT_GUI = None
        self.assertEqual(ttk.Style().theme_use(), before)

    def test_the_dark_theme_does_not_restyle_other_widgets(self):
        self.open_window()
        style = ttk.Style()
        self.assertNotEqual(style.lookup("ArchTrack.TLabel", "background"),
                            style.lookup("TLabel", "background"))


class TestOverlay(PluginTestCase):
    def open_window(self):
        return self.open_tracker_window()

    def test_overlay_defaults_to_off(self):
        self.assertFalse(helpers.overlay_enabled())

    def test_paint_is_a_noop_when_disabled(self):
        import overlay as overlay_mod
        import edmcoverlay as stub
        stub.Overlay.reset()
        overlay_mod.paint("Vulcan Gate", [{"name": "Steel", "shortfall": 90}])
        self.assertEqual(stub.Overlay.messages, [])

    def test_paint_lists_shortfall_from_mid_left(self):
        import overlay as overlay_mod
        import edmcoverlay as stub
        helpers.set_overlay_enabled(True)
        stub.Overlay.reset()
        overlay_mod.paint("Vulcan Gate", [
            {"name": "Aluminium", "shortfall": 0},
            {"name": "Steel", "shortfall": 90},
            {"name": "Titanium", "shortfall": 200},
        ])
        by_id = {m["id"]: m for m in stub.Overlay.messages if m["text"]}
        self.assertEqual(by_id["archtrack-title"]["text"], "Vulcan Gate")
        self.assertEqual(by_id["archtrack-title"]["x"], 24)
        self.assertEqual(by_id["archtrack-title"]["y"], 480)
        self.assertEqual(by_id["archtrack-hdr-name"]["text"], "Commodity")
        self.assertEqual(by_id["archtrack-hdr-qty"]["text"], "Needed")
        self.assertEqual(by_id["archtrack-name-0"]["text"], "Steel")
        self.assertEqual(by_id["archtrack-qty-0"]["text"], "90")
        self.assertEqual(by_id["archtrack-name-1"]["text"], "Titanium")
        self.assertEqual(by_id["archtrack-qty-1"]["text"], "200")
        self.assertNotIn("archtrack-name-2", by_id)  # zero shortfall skipped
        # Quantity column sits to the right of the name column.
        self.assertGreater(by_id["archtrack-qty-0"]["x"], by_id["archtrack-name-0"]["x"])
        # Rows are spaced downward for legibility.
        self.assertGreater(by_id["archtrack-name-1"]["y"], by_id["archtrack-name-0"]["y"])
        self.assertGreaterEqual(
            by_id["archtrack-name-1"]["y"] - by_id["archtrack-name-0"]["y"], 20)

    def test_overlay_position_dropdown_moves_the_anchor(self):
        import overlay as overlay_mod
        import edmcoverlay as stub
        helpers.set_overlay_enabled(True)
        rows = [{"name": "Steel", "shortfall": 90}]

        helpers.set_overlay_position("top")
        stub.Overlay.reset()
        overlay_mod.paint("Vulcan Gate", rows)
        by_id = {m["id"]: m for m in stub.Overlay.messages if m["text"]}
        self.assertEqual(by_id["archtrack-title"]["y"], overlay_mod.OVERLAY_Y_BY_POS["top"])
        self.assertEqual(by_id["archtrack-title"]["x"], 24)

        helpers.set_overlay_position("bottom")
        stub.Overlay.reset()
        overlay_mod.paint("Vulcan Gate", rows)
        by_id = {m["id"]: m for m in stub.Overlay.messages if m["text"]}
        self.assertEqual(by_id["archtrack-title"]["y"], overlay_mod.OVERLAY_Y_BY_POS["bottom"])
        self.assertGreater(by_id["archtrack-title"]["y"], overlay_mod.OVERLAY_Y_BY_POS["mid"])

    def test_overlay_position_defaults_to_mid_left(self):
        self.assertEqual(helpers.overlay_position(), "mid")
        preferences.change_overlay_position("Top left")
        self.assertEqual(helpers.overlay_position(), "top")
        preferences.change_overlay_position("Bottomish left")
        self.assertEqual(helpers.overlay_position(), "bottom")

    def test_tracker_paints_when_overlay_enabled(self):
        import edmcoverlay as stub
        self.write_json(g.SAVE_FILE, {"Orbital Construction Site: Vulcan Gate": {
            "Location": [1.0, 2.0, 3.0], "ID": 3700001,
            "materials": {"$steel_name;": {"Name_Localised": "Steel", "RequiredAmount": 100,
                                           "ProvidedAmount": 10, "Price": 9000}}}})
        g.SITE_LOCATION = [1.0, 2.0, 3.0]
        helpers.set_overlay_enabled(True)
        stub.Overlay.reset()
        window = self.open_window()
        ROOT.update()
        by_id = {m["id"]: m for m in stub.Overlay.messages if m["text"]}
        self.assertEqual(by_id["archtrack-name-0"]["text"], "Steel")
        self.assertEqual(by_id["archtrack-qty-0"]["text"], "90")
        window.on_close()
        # Closing clears the overlay slots (empty strings / short ttl).
        self.assertTrue(any(m["text"] == "" for m in stub.Overlay.messages))

    def test_overlay_import_is_retried_after_a_failed_first_look(self):
        import overlay as overlay_mod
        overlay_mod._edmcoverlay_mod = None
        overlay_mod._import_attempted = True
        overlay_mod._logged_missing = True
        self.assertTrue(overlay_mod.overlay_available())
        self.assertIsNotNone(overlay_mod._edmcoverlay_mod)

    def test_heartbeat_repaints_the_last_frame(self):
        import overlay as overlay_mod
        import edmcoverlay as stub
        helpers.set_overlay_enabled(True)
        stub.Overlay.reset()
        overlay_mod.paint("Vulcan Gate", [{"name": "Steel", "shortfall": 90}])
        stub.Overlay.reset()
        overlay_mod._last_heartbeat = 0.0
        overlay_mod.heartbeat()
        by_id = {m["id"]: m for m in stub.Overlay.messages if m["text"]}
        self.assertEqual(by_id["archtrack-title"]["text"], "Vulcan Gate")
        self.assertEqual(by_id["archtrack-name-0"]["text"], "Steel")

    def test_first_paint_does_not_blank_twenty_unused_rows(self):
        import overlay as overlay_mod
        import edmcoverlay as stub
        helpers.set_overlay_enabled(True)
        stub.Overlay.reset()
        overlay_mod._active_row_count = 0
        overlay_mod.paint("Vulcan Gate", [{"name": "Steel", "shortfall": 90}])
        blanks = [m for m in stub.Overlay.messages if m["text"] == ""]
        self.assertLess(len(blanks), 10)

    def test_dashboard_entry_keeps_the_overlay_alive(self):
        import overlay as overlay_mod
        import edmcoverlay as stub
        helpers.set_overlay_enabled(True)
        g.ARCHITECT_GUI = FakeGUI(True)
        overlay_mod.paint("Vulcan Gate", [{"name": "Steel", "shortfall": 90}])
        stub.Overlay.reset()
        overlay_mod._last_heartbeat = 0.0
        load.dashboard_entry("CMDR", False, {"event": "Status"})
        by_id = {m["id"]: m for m in stub.Overlay.messages if m["text"]}
        self.assertEqual(by_id["archtrack-name-0"]["text"], "Steel")
        g.ARCHITECT_GUI = None

    def test_modern_overlay_still_gets_plain_send_message(self):
        # send_raw normalisation differs between Modern Overlay versions, so
        # even when the stub advertises itself as Modern Overlay the plugin
        # must stay on send_message (the stub's send_raw raises).
        import overlay as overlay_mod
        import edmcoverlay as stub
        stub.MODERN_OVERLAY_IDENTITY = {"plugin": "EDMCModernOverlay"}
        overlay_mod._edmcoverlay_mod = stub
        overlay_mod._overlay_client = None
        helpers.set_overlay_enabled(True)
        stub.Overlay.reset()
        overlay_mod.paint("Vulcan Gate", [{"name": "Steel", "shortfall": 90}])
        by_id = {m["id"]: m for m in stub.Overlay.messages if m["text"]}
        self.assertEqual(by_id["archtrack-title"]["text"], "Vulcan Gate")
        self.assertEqual(by_id["archtrack-name-0"]["text"], "Steel")
        del stub.MODERN_OVERLAY_IDENTITY


class TestCommodityNames(unittest.TestCase):
    def test_every_spelling_reaches_one_key(self):
        for spelling in ("$cmmcomposite_name;", "cmmcomposite", "CMM Composite",
                         "  CMM  Composite ".replace("  ", " ").strip()):
            self.assertEqual(commodity_key(spelling), "cmmcomposite", spelling)

    def test_commodities_whose_display_name_cannot_be_derived(self):
        # these four genuinely differ between the journal and everyone else
        self.assertEqual(commodity_key("$agriculturalmedicines_name;"),
                         commodity_key("Agri-Medicines"))
        self.assertEqual(commodity_key("$heliostaticfurnaces_name;"),
                         commodity_key("Microbial Furnaces"))
        self.assertEqual(commodity_key("$hazardousenvironmentsuits_name;"),
                         commodity_key("H.E. Suits"))
        self.assertEqual(commodity_key("$mutomimager_name;"), commodity_key("Muon Imager"))

    def test_every_construction_commodity_has_a_key(self):
        with open(os.path.join(PLUGIN_DIR, "commodity_list.txt"), encoding="utf-8") as f:
            names = [line.strip() for line in f if line.strip()]
        self.assertTrue(all(commodity_key(n) for n in names))

    def test_nothing_and_junk(self):
        self.assertEqual(commodity_key(None), "")
        self.assertEqual(commodity_key(""), "")


class FakeSpansh:
    """Serves the recorded Spansh response instead of going to the network."""

    def __init__(self, pages, error=None):
        self.pages = pages
        self.error = error
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append({"url": request.full_url,
                              "headers": dict(request.header_items()),
                              "body": json.loads(request.data.decode())})
        if self.error:
            raise self.error
        page = self.requests[-1]["body"]["page"]
        payload = self.pages[page] if page < len(self.pages) else {"count": 0, "results": []}
        return FakeResponse(json.dumps(payload).encode())


class FakeResponse:
    def __init__(self, raw):
        self.raw = raw

    def read(self):
        return self.raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestMarketImport(PluginTestCase):
    """Pulling in markets the commander has never docked at."""

    SITE = "Orbital Construction Site: Vulcan Gate"
    # the recorded response was captured on this day, so pin "now" to it and the
    # tests keep meaning the same thing as real time moves on
    NOW = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)

    def setUp(self):
        super().setUp()
        with open(os.path.join(TESTS_DIR, "spansh_sample.json"), encoding="utf-8") as f:
            self.sample = json.load(f)
        marketimport._last_import_at = 0.0
        self._real_urlopen = marketimport.urllib.request.urlopen

    def tearDown(self):
        marketimport.urllib.request.urlopen = self._real_urlopen
        super().tearDown()

    def serve(self, pages=None, error=None):
        fake = FakeSpansh(pages if pages is not None else [self.sample], error)
        marketimport.urllib.request.urlopen = fake
        return fake

    def save_site(self, needs=("$computercomponents_name;", "$biowaste_name;"),
                  system="Vulcan", price=9000, provided=0):
        self.write_json(g.SAVE_FILE, {self.SITE: {
            "Location": [1.0, 2.0, 3.0], "System": system, "ID": 3700001,
            "materials": {n: {"Name_Localised": n, "RequiredAmount": 1000,
                              "ProvidedAmount": provided, "Price": price} for n in needs}}})
        helpers.load_facility_requirements()

    # --- what gets sent ---

    def test_the_request_asks_for_what_we_want(self):
        self.save_site()
        fake = self.serve()
        marketimport.import_markets("Vulcan", 30, True, True, now=self.NOW)

        body = fake.requests[0]["body"]
        self.assertEqual(body["reference_system"], "Vulcan")
        self.assertEqual(body["filters"]["distance"], {"min": "0", "max": "30"})
        self.assertEqual(body["sort"], [{"distance": {"direction": "asc"}}])
        self.assertIs(body["filters"]["has_market"]["value"], True)
        types = body["filters"]["type"]["value"]
        self.assertIn("Coriolis Starport", types)
        self.assertIn("Planetary Outpost", types)
        # fleet carriers move, and construction depots are the sites themselves
        self.assertNotIn("Drake-Class Carrier", types)
        self.assertNotIn("Space Construction Depot", types)
        self.assertIn("ArchitectTracker", fake.requests[0]["headers"].get("User-agent", ""))

    def test_the_orbital_and_surface_toggles(self):
        self.save_site()
        for orbital, surface, expect_orbital, expect_surface in (
                (True, False, True, False), (False, True, False, True), (True, True, True, True)):
            fake = self.serve()
            marketimport._last_import_at = 0.0
            marketimport.import_markets("Vulcan", 25, orbital, surface, now=self.NOW)
            types = fake.requests[0]["body"]["filters"]["type"]["value"]
            self.assertEqual("Coriolis Starport" in types, expect_orbital)
            self.assertEqual("Planetary Outpost" in types, expect_surface)

    def test_pad_filter_helpers(self):
        large = {"has_large_pad": True, "large_pads": 4, "medium_pads": 8}
        medium = {"has_large_pad": False, "large_pads": 0, "medium_pads": 1}
        small = {"has_large_pad": False, "large_pads": 0, "medium_pads": 0, "small_pads": 2}
        unknown = {"name": "Old Dump"}
        self.assertTrue(marketimport.fits_pad_filter(large, marketimport.PAD_LARGE))
        self.assertFalse(marketimport.fits_pad_filter(medium, marketimport.PAD_LARGE))
        self.assertTrue(marketimport.fits_pad_filter(large, marketimport.PAD_LARGE_MEDIUM))
        self.assertTrue(marketimport.fits_pad_filter(medium, marketimport.PAD_LARGE_MEDIUM))
        self.assertFalse(marketimport.fits_pad_filter(small, marketimport.PAD_LARGE_MEDIUM))
        self.assertTrue(marketimport.fits_pad_filter(unknown, marketimport.PAD_LARGE_MEDIUM))

    def test_import_pad_size_setting(self):
        self.assertEqual(helpers.import_pad_size(), marketimport.PAD_LARGE_MEDIUM)
        config.set("ArchTrack_importPadSize", marketimport.PAD_LARGE)
        self.assertEqual(helpers.import_pad_size(), marketimport.PAD_LARGE)
        config.set("ArchTrack_importPadSize", "nonsense")
        self.assertEqual(helpers.import_pad_size(), marketimport.PAD_LARGE_MEDIUM)

    def test_the_radius_is_clamped(self):
        self.save_site()
        for asked, sent in ((1, "5"), (25, "25"), (50, "50"), (5000, "50")):
            fake = self.serve()
            marketimport._last_import_at = 0.0
            marketimport.import_markets("Vulcan", asked, True, True, now=self.NOW)
            self.assertEqual(fake.requests[0]["body"]["filters"]["distance"]["max"], sent)

    # --- what comes back ---

    def test_prices_land_in_the_market_library(self):
        self.save_site()
        self.serve()
        summary = marketimport.import_markets("Vulcan", 25, True, True, now=self.NOW)

        self.assertGreater(summary.markets_used, 0)
        self.assertGreater(summary.prices, 0)
        lib = helpers.get_market_library()
        cheap = lib["Commodities"]["$computercomponents_name;"]["CheapMarkets"]
        # Powell High is the cheapest orbital supplier of that in the sample
        station = helpers.get_market_by_station_id(lib, cheap["Orbital"]["StationID"])
        self.assertEqual(station["StationName"], "Powell High")
        self.assertEqual(cheap["Orbital"]["Price"], 607)

        source = next(s for s in self.sample["results"] if s["name"] == "Powell High")
        self.assertEqual(station["Location"],
                         [source["system_x"], source["system_y"], source["system_z"]])
        self.assertEqual(station["Type"], "Orbital")
        self.assertEqual(station["StationID"], source["market_id"])
        self.assertEqual(station["System"], source["system_name"])

    def test_the_pad_filter_asks_spansh_for_large_only(self):
        self.save_site()
        fake = self.serve()
        marketimport.import_markets("Vulcan", 25, True, True, now=self.NOW,
                                    pad_size=marketimport.PAD_LARGE)
        self.assertEqual(fake.requests[0]["body"]["filters"]["has_large_pad"],
                         {"value": True})

    def test_large_and_medium_does_not_send_the_large_pad_filter(self):
        self.save_site()
        fake = self.serve()
        marketimport.import_markets("Vulcan", 25, True, True, now=self.NOW,
                                    pad_size=marketimport.PAD_LARGE_MEDIUM)
        self.assertNotIn("has_large_pad", fake.requests[0]["body"]["filters"])

    def test_large_and_medium_skips_small_only_pads(self):
        self.save_site()
        page = json.loads(json.dumps(self.sample))
        # Force a known supplier down to small pads only; L/M must drop it.
        powell = next(s for s in page["results"] if s["name"] == "Powell High")
        powell.update(has_large_pad=False, large_pads=0, medium_pads=0, small_pads=4)
        self.serve([page])
        marketimport.import_markets("Vulcan", 25, True, True, now=self.NOW,
                                    pad_size=marketimport.PAD_LARGE_MEDIUM)
        names = {m["StationName"] for m in helpers.get_market_library()["Markets"]}
        self.assertNotIn("Powell High", names)

    def test_the_system_column_can_then_answer(self):
        self.save_site()
        self.serve()
        marketimport.import_markets("Vulcan", 25, True, True, now=self.NOW)
        system = helpers.get_prefMarket_system("$computercomponents_name;")
        self.assertEqual(system, "Wolf 359")

    def test_only_commodities_a_site_still_needs_are_imported(self):
        self.save_site(needs=("$computercomponents_name;",))
        self.serve()
        marketimport.import_markets("Vulcan", 25, True, True, now=self.NOW)
        self.assertEqual(list(helpers.get_market_library()["Commodities"]),
                         ["$computercomponents_name;"])

    def test_commodities_already_delivered_are_skipped(self):
        self.save_site(needs=("$computercomponents_name;",), provided=1000)
        self.serve()
        with self.assertRaises(marketimport.ImportError_):
            marketimport.import_markets("Vulcan", 25, True, True, now=self.NOW)

    def test_the_pref_market_column_can_then_answer(self):
        self.save_site()
        self.serve()
        marketimport.import_markets("Vulcan", 25, True, True, now=self.NOW)
        g.SITE_LOCATION = [1.0, 2.0, 3.0]
        name = helpers.get_prefMarket_name("$computercomponents_name;")
        self.assertIn(name.lstrip("*"), {s["name"] for s in self.sample["results"]})

    def test_the_summary_says_how_old_the_data_is(self):
        self.save_site(needs=("$computercomponents_name;",))
        page = json.loads(json.dumps(self.sample))
        for station in page["results"]:
            station["market_updated_at"] = "2026-02-01 00:00:00+00"  # ~six months old
        self.serve([page])
        summary = marketimport.import_markets("Vulcan", 25, True, True, now=self.NOW)
        self.assertGreater(summary.oldest_days, 180)
        self.assertIn("Oldest reported", str(summary))

    def test_markets_that_stock_nothing_we_need(self):
        self.save_site(needs=("$steel_name;",))  # the sample has no steel in supply
        page = json.loads(json.dumps(self.sample))
        for station in page["results"]:
            station["market"] = [row for row in (station.get("market") or [])
                                 if commodity_key(row["commodity"]) != "steel"]
        self.serve([page])
        summary = marketimport.import_markets("Vulcan", 25, True, True, now=self.NOW)
        self.assertEqual(summary.prices, 0)
        self.assertIn("none stocking", str(summary))

    def test_stale_markets_are_left_out(self):
        self.save_site(needs=("$basicmedicines_name;",))
        self.serve()
        summary = marketimport.import_markets("Vulcan", 25, True, True, now=self.NOW)
        self.assertGreater(summary.markets_stale, 0)
        stale = [s for s in self.sample["results"]
                 if marketimport.is_stale(s, self.NOW)]
        lib = helpers.get_market_library()
        for station in stale:
            self.assertIsNone(helpers.get_market_by_station_id(lib, station["market_id"]))

    def test_a_commodity_with_no_supply_is_not_a_price(self):
        self.save_site(needs=("$computercomponents_name;",))
        page = json.loads(json.dumps(self.sample))
        for station in page["results"]:
            for row in station.get("market") or []:
                row["supply"] = 0
        self.serve([page])
        summary = marketimport.import_markets("Vulcan", 25, True, True, now=self.NOW)
        self.assertEqual(summary.prices, 0)
        self.assertEqual(helpers.get_market_library()["Commodities"], {})

    def test_imported_and_visited_markets_compete_on_the_same_terms(self):
        """A visited market that is cheaper must win over an imported one."""
        self.save_site(needs=("$computercomponents_name;",))
        self.serve()
        marketimport.import_markets("Vulcan", 25, True, True, now=self.NOW)

        g.CURRENT_LOCATION = (1.0, 2.0, 3.0)
        g.DOCKED_STATION_TYPE = g.STATION_TYPE.Orbital
        self.write_json(g.MARKET_JSON, {
            "StationName": "Bargain Basement", "MarketID": 42,
            "Items": [{"Name": "$computercomponents_name;", "Stock": 500,
                       "BuyPrice": 100, "SellPrice": 90}]})
        helpers.update_market_library()

        lib = helpers.get_market_library()
        cheap = lib["Commodities"]["$computercomponents_name;"]["CheapMarkets"]["Orbital"]
        self.assertEqual(cheap["Price"], 100)
        self.assertEqual(helpers.get_market_by_station_id(lib, cheap["StationID"])["StationName"],
                         "Bargain Basement")

    # --- paging and limits ---

    def test_it_stops_when_a_page_is_short(self):
        self.save_site()
        fake = self.serve([self.sample])
        marketimport.import_markets("Vulcan", 25, True, True, now=self.NOW)
        self.assertEqual(len(fake.requests), 1)

    def test_it_stops_at_the_page_ceiling(self):
        self.save_site()
        full = {"count": 9999,
                "results": self.sample["results"] * (marketimport.PAGE_SIZE // 8 + 1)}
        full["results"] = full["results"][:marketimport.PAGE_SIZE]
        fake = self.serve([full] * (marketimport.MAX_PAGES + 3))
        summary = marketimport.import_markets("Vulcan", 25, True, True, now=self.NOW)
        self.assertEqual(len(fake.requests), marketimport.MAX_PAGES)
        self.assertTrue(summary.truncated)
        self.assertIn("Nearest", str(summary))

    def test_it_will_not_hammer_spansh(self):
        self.save_site()
        self.serve()
        marketimport.import_markets("Vulcan", 25, True, True, now=self.NOW)
        self.assertGreater(marketimport.seconds_until_allowed(), 0)

    # --- being told what went wrong ---

    def test_no_system_known(self):
        self.save_site()
        with self.assertRaises(marketimport.ImportError_) as caught:
            marketimport.import_markets(None, 25, True, True)
        self.assertIn("system", str(caught.exception).lower())

    def test_neither_market_type_chosen(self):
        self.save_site()
        with self.assertRaises(marketimport.ImportError_):
            marketimport.import_markets("Vulcan", 25, False, False)

    def test_no_construction_sites(self):
        self.write_json(g.SAVE_FILE, {})
        with self.assertRaises(marketimport.ImportError_):
            marketimport.import_markets("Vulcan", 25, True, True, now=self.NOW)

    def test_a_system_spansh_does_not_know(self):
        self.save_site()
        self.serve(error=urllib.error.HTTPError("u", 502, "Bad Gateway", {}, None))
        with self.assertRaises(marketimport.ImportError_) as caught:
            marketimport.import_markets("Nowhere", 25, True, True)
        self.assertIn("Nowhere", str(caught.exception))

    def test_the_network_being_down(self):
        self.save_site()
        self.serve(error=urllib.error.URLError("no route to host"))
        with self.assertRaises(marketimport.ImportError_) as caught:
            marketimport.import_markets("Vulcan", 25, True, True, now=self.NOW)
        self.assertIn("Spansh", str(caught.exception))

    def test_nothing_is_written_when_the_search_fails(self):
        self.save_site()
        self.serve(error=urllib.error.URLError("down"))
        with self.assertRaises(marketimport.ImportError_):
            marketimport.import_markets("Vulcan", 25, True, True, now=self.NOW)
        self.assertFalse(os.path.exists(g.MARKET_LIB_PATH))

    # --- where to search from ---

    def test_the_site_system_is_remembered(self):
        g.CURRENT_SYSTEM = "Vulcan"
        helpers.save_facility_requirements(
            [{"Name": "$steel_name;", "Name_Localised": "Steel", "RequiredAmount": 10,
              "ProvidedAmount": 0, "Payment": 900}], self.SITE, 3700001, "Vulcan")
        self.assertEqual(helpers.site_system(), "Vulcan")

    def test_falls_back_to_where_the_commander_is(self):
        self.write_json(g.SAVE_FILE, {})
        g.CURRENT_SYSTEM = "Somewhere Else"
        self.assertEqual(helpers.site_system(), "Somewhere Else")

    def test_a_site_saved_before_1_7_has_no_system(self):
        self.write_json(g.SAVE_FILE, {self.SITE: {
            "Location": [1.0, 2.0, 3.0], "ID": 3700001, "materials": {}}})
        g.CURRENT_SYSTEM = None
        self.assertIsNone(helpers.site_system())


class TestStaleness(unittest.TestCase):
    NOW = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)

    def test_recent_and_ancient(self):
        self.assertFalse(marketimport.is_stale({"market_updated_at": "2026-08-05 21:42:43+00"},
                                               self.NOW))
        self.assertTrue(marketimport.is_stale({"market_updated_at": "2025-03-06 10:00:00+00"},
                                              self.NOW))

    def test_right_on_the_boundary(self):
        cutoff = self.NOW - timedelta(days=marketimport.STALE_AFTER_DAYS)
        just_inside = (cutoff + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S+00")
        just_outside = (cutoff - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S+00")
        self.assertFalse(marketimport.is_stale({"market_updated_at": just_inside}, self.NOW))
        self.assertTrue(marketimport.is_stale({"market_updated_at": just_outside}, self.NOW))

    def test_a_timestamp_we_cannot_read(self):
        self.assertFalse(marketimport.is_stale({"market_updated_at": "last tuesday"}, self.NOW))
        self.assertFalse(marketimport.is_stale({}, self.NOW))

    def test_frontier_data_is_kept(self):
        """Out where people colonise, the median market was last reported months
        ago. Dropping those would empty the column exactly where it is needed."""
        for months in (3, 6, 9, 11):
            when = self.NOW - timedelta(days=30 * months)
            station = {"market_updated_at": when.strftime("%Y-%m-%d %H:%M:%S+00")}
            self.assertFalse(marketimport.is_stale(station, self.NOW),
                             f"{months} month old data should still be used")


class TestAWholeSession(PluginTestCase):
    """Drive the plugin through a realistic sequence of journal events."""

    CALLSIGN = "K7Q-B2Z"
    MATERIALS = [("$steel_name;", "Steel", 8000),
                 ("$cmmcomposite_name;", "CMM Composite", 6400),
                 ("$aluminium_name;", "Aluminium", 4200)]
    SITE = "Orbital Construction Site: Vulcan Gate"

    def depot(self, provided):
        return {"event": "ColonisationConstructionDepot", "MarketID": 3700001,
                "ResourcesRequired": [{"Name": n, "Name_Localised": loc,
                                       "RequiredAmount": req, "ProvidedAmount": provided,
                                       "Payment": 9000}
                                      for n, loc, req in self.MATERIALS]}

    def write_market(self, station, market_id, price):
        self.write_json(g.MARKET_JSON, {
            "StationName": station, "MarketID": market_id,
            "Items": [{"Name": n, "Stock": 900, "BuyPrice": price, "SellPrice": price - 100}
                      for n, _, _ in self.MATERIALS]})

    def play(self, station, entry, docked=True):
        load.journal_entry("Cmdr", False, "Vulcan", station, entry, {"IsDocked": docked})
        ROOT.update()

    def test_a_full_run_logs_nothing_untoward(self):
        import logging

        problems = []

        class Capture(logging.Handler):
            def emit(self, record):
                if record.levelno >= logging.WARNING \
                        and "not found in commodity list" not in record.getMessage():
                    problems.append(f"{record.levelname}: {record.getMessage()}")

        handler = Capture()
        g.logger.addHandler(handler)
        g.EDMC_ROOT = ROOT
        try:
            config.set("ArchTrack_showUI", True)
            load.plugin_start3(PLUGIN_DIR)
            ROOT.update()

            self.play(None, {"event": "FSDJump", "StarPos": [372.5, -131.4, -288.1]}, False)
            self.play(self.SITE, self.depot(0))
            load.capi_fleetcarrier({"cargo": [{"commodity": "CMM Composite", "qty": 2400},
                                              {"commodity": "Steel", "qty": 900}],
                                    "name": {"callsign": self.CALLSIGN,
                                             "vanityName": "486f6d65727573"}})
            self.play(None, {"event": "Undocked"}, False)
            self.play(None, {"event": "SupercruiseDestinationDrop"}, False)

            self.write_market("Jameson Memorial", 128666762, 4000)
            self.play("Jameson Memorial", {"event": "Market"})
            self.write_json(g.CARGO_JSON, {"Vessel": "Ship", "Count": 700,
                                           "Inventory": [{"Name": "steel", "Count": 700}]})
            self.play("Jameson Memorial", {"event": "MarketBuy", "Type": "steel", "Count": 700})

            self.play(self.CALLSIGN, {"event": "Docked"})
            self.play(self.CALLSIGN, {"event": "CargoTransfer",
                                      "Transfers": [{"Type": "steel", "Count": 700,
                                                     "Direction": "tocarrier"}]})
            self.play(self.CALLSIGN, {"event": "MarketSell", "Type": "aluminium", "Count": 120})

            self.play(None, {"event": "ApproachSettlement"}, False)
            self.write_market("Dirt Farm", 3200001, 2500)
            self.play("Dirt Farm", {"event": "Market"})

            self.play(self.SITE, self.depot(4000))
            helpers.toggle_gui()  # close it, tracking stops
            self.play(None, {"event": "FSDJump", "StarPos": [1.0, 2.0, 3.0]}, False)
            helpers.toggle_gui()  # and open it again
            self.play(self.SITE, self.depot(8000))  # site finished
            load.plugin_stop()
        finally:
            g.logger.removeHandler(handler)

        self.assertEqual(problems, [])
        self.assertEqual(g.CARRIER_TRACKER.commodities,
                         {"cmmcomposite": 2400, "steel": 1600, "aluminium": 120})
        self.assertEqual(g.CARRIER_TRACKER.carrier_name, "Homerus")
        self.assertEqual(helpers.load_facility_requirements(), {})  # completed, so removed
        self.assertEqual(sorted(m["StationName"] for m in helpers.get_market_library()["Markets"]),
                         ["Dirt Farm", "Jameson Memorial"])
        self.assertEqual(helpers.get_prefMarket_name("$steel_name;"), "Jameson Memorial")


if __name__ == "__main__":
    unittest.main(verbosity=2)
