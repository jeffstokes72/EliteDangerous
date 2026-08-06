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
import preferences
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
        config.settings.clear()

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
        return {"StationName": "Jameson Memorial", "MarketID": 128666762,
                "Items": [{"Name": self.STEEL, "Stock": 500, "SellPrice": price}]}

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
            {"Name": self.STEEL, "Stock": 10, "SellPrice": 1},
            {"Name": "$gold_name;", "Stock": 0, "SellPrice": 1}]})
        stock = helpers.load_market_stock()
        self.assertTrue(helpers.is_market_selling(self.STEEL, stock))
        self.assertFalse(helpers.is_market_selling("$gold_name;", stock))


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

    def test_renaming_a_column_is_saved_with_the_window_closed(self):
        g.ARCHITECT_GUI = None
        preferences.on_column_rename("Needed", "Left")
        self.assertEqual(helpers.load_column_names()[3], "Left")


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
            "Items": [{"Name": n, "Stock": 900, "SellPrice": price}
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
