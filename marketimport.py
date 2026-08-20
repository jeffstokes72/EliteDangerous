"""Import market data for markets the commander has not visited.

Everything the plugin knows about prices normally comes from docking somewhere
and reading Market.json. This asks Spansh (https://spansh.co.uk), which
aggregates the same data from EDDN, for the markets around a construction site
so the Pref Market column has something to say before you have flown there.

There is no Spansh endpoint that returns just the commodity rows, so this pulls
whole station records nearest-first and reads their markets. That is a few MB,
so it only ever runs when the commander asks for it.
"""

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import globals
from globals import logger
from commodities import commodity_key

SEARCH_URL = "https://spansh.co.uk/api/stations/search"
USER_AGENT = None  # built lazily, needs the plugin version

PAGE_SIZE = 100
# Each station record is ~50KB because Spansh has no way to ask for just the
# market, so this ceiling is really a download budget. Colonisation regions hold
# a handful to ~100 markets within 25 ly, so two pages covers them; next door to
# Sol it stops at the 200 nearest, which is further than anyone would fly anyway.
MAX_PAGES = 2
PAGE_PAUSE = 0.5       # seconds between pages, to be a good guest
TIMEOUT = 45
MIN_SECONDS_BETWEEN_IMPORTS = 60
# Deliberately generous. In the bubble almost every market was reported today, so
# any cutoff would do; out where people actually colonise the median market was
# last reported nine months ago, and a nine month old price beats a blank column.
# This only drops records nobody has touched in over a year.
STALE_AFTER_DAYS = 365

MIN_RADIUS = 5
MAX_RADIUS = 50
DEFAULT_RADIUS = 25

# Landing pad filter. Large ships need L; medium ships can use L or M.
# Small-only pads are never useful for colonisation hauling.
PAD_LARGE = "L"
PAD_MEDIUM = "M"
PAD_SMALL = "S"
PAD_LARGE_MEDIUM = "L/M"
DEFAULT_PAD_SIZE = PAD_LARGE_MEDIUM
PAD_SIZE_LABELS = {
    PAD_LARGE: "Large pads only",
    PAD_LARGE_MEDIUM: "Large and Medium",
}
PAD_SIZE_SHORT = {
    PAD_LARGE: "L",
    PAD_LARGE_MEDIUM: "L/M",
}

# Journal StationType / Spansh type names used when pad counts are missing.
LARGE_STATION_TYPES = {
    "Coriolis", "Orbis", "Ocellus", "AsteroidBase", "MegaShip", "StationMegaShip",
    "Coriolis Starport", "Orbis Starport", "Ocellus Starport", "Dodec Starport",
    "Asteroid base", "Planetary Port", "Dockable Planet Station",
}
MEDIUM_STATION_TYPES = {"Outpost"}

# Station types with a commodity market you can dock at and buy from. Fleet
# carriers and megaships are deliberately absent because they relocate, and the
# plugin tracks your own carrier separately. So are construction depots, which
# are the sites themselves.
ORBITAL_TYPES = ["Coriolis Starport", "Orbis Starport", "Ocellus Starport",
                 "Dodec Starport", "Asteroid base", "Outpost"]
SURFACE_TYPES = ["Planetary Outpost", "Planetary Port", "Dockable Planet Station"]

_last_import_at = 0.0


class ImportError_(Exception):
    """Something went wrong that the commander needs to be told about."""


def user_agent():
    global USER_AGENT
    if USER_AGENT is None:
        USER_AGENT = (f"ArchitectTracker_enhanced/{globals.ARCHITECT_TRACKER_VER} "
                      "(EDMC plugin; +https://github.com/jeffstokes72/EliteDangerous)")
    return USER_AGENT


def seconds_until_allowed():
    """How long the commander has to wait before importing again."""
    remaining = MIN_SECONDS_BETWEEN_IMPORTS - (time.monotonic() - _last_import_at)
    return max(0, int(remaining)) if _last_import_at else 0


def station_types(include_orbital, include_surface):
    types = []
    if include_orbital:
        types.extend(ORBITAL_TYPES)
    if include_surface:
        types.extend(SURFACE_TYPES)
    return types


def max_pad_from_counts(large=0, medium=0, small=0, has_large_pad=None):
    """Largest pad class present: L, M, S, or None if nothing is known."""
    if has_large_pad is True or (large or 0) > 0:
        return PAD_LARGE
    if (medium or 0) > 0:
        return PAD_MEDIUM
    if (small or 0) > 0:
        return PAD_SMALL
    return None


def max_pad_from_landing_pads(pads):
    """Journal Docked.LandingPads -> L / M / S / None."""
    if not isinstance(pads, dict):
        return None
    return max_pad_from_counts(
        large=pads.get("Large"), medium=pads.get("Medium"), small=pads.get("Small"))


def max_pad_from_station_type(station_type):
    """Guess pad class from a journal StationType or Spansh type name."""
    if not station_type:
        return None
    name = str(station_type).strip()
    if name in LARGE_STATION_TYPES:
        return PAD_LARGE
    if name in MEDIUM_STATION_TYPES:
        return PAD_MEDIUM
    return None


def max_pad_of_station(station):
    """Largest pad on a Spansh station record, falling back to its type name."""
    if any(key in station for key in
           ("has_large_pad", "large_pads", "medium_pads", "small_pads")):
        return max_pad_from_counts(
            large=station.get("large_pads"),
            medium=station.get("medium_pads"),
            small=station.get("small_pads"),
            has_large_pad=station.get("has_large_pad") if "has_large_pad" in station else None)
    return max_pad_from_station_type(station.get("type"))


def fits_pad_filter(station, pad_size):
    """Whether a Spansh station record matches the commander's pad filter.

    Large-only is enforced in the Spansh query via has_large_pad. L/M still
    drops small-only pads client-side when pad counts are present; missing pad
    fields (older dumps) are kept rather than discarding useful prices.
    """
    max_pad = max_pad_of_station(station)
    if pad_size == PAD_LARGE:
        return max_pad == PAD_LARGE
    if max_pad is None:
        return True
    return max_pad in (PAD_LARGE, PAD_MEDIUM)


def search_page(system, radius, types, page, pad_size=DEFAULT_PAD_SIZE):
    """One page of stations around `system`, nearest first."""
    filters = {
        "distance": {"min": "0", "max": str(radius)},
        "type": {"value": types},
        "has_market": {"value": True},
    }
    # Spansh's has_large_pad filter is the reliable way to ask for L pads.
    # There is no equivalent "has medium or large" filter, so L/M is filtered
    # after the reply arrives.
    if pad_size == PAD_LARGE:
        filters["has_large_pad"] = {"value": True}
    payload = {
        "filters": filters,
        "sort": [{"distance": {"direction": "asc"}}],
        "size": PAGE_SIZE,
        "page": page,
        "reference_system": system,
    }
    request = urllib.request.Request(
        SEARCH_URL, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": user_agent()})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read()
    except urllib.error.HTTPError as e:
        # Spansh answers 502 for a reference system it has never heard of
        if e.code in (500, 502, 503, 504):
            raise ImportError_(f"Spansh could not search around '{system}'. "
                               "If the system was only just discovered it may not "
                               "be in their data yet.") from e
        raise ImportError_(f"Spansh returned HTTP {e.code}.") from e
    except urllib.error.URLError as e:
        raise ImportError_(f"Could not reach Spansh: {e.reason}") from e
    except OSError as e:
        raise ImportError_(f"Could not reach Spansh: {e}") from e

    try:
        return json.loads(raw), len(raw)
    except json.JSONDecodeError as e:
        raise ImportError_("Spansh sent a reply that could not be read.") from e


def reported_at(station):
    """When EDDN last heard about this market, or None if we cannot tell."""
    updated = station.get("market_updated_at")
    if not updated:
        return None
    try:
        # e.g. "2026-08-05 21:42:43+00"
        text = updated.strip().replace(" ", "T")
        if text.endswith("+00"):
            text += ":00"
        when = datetime.fromisoformat(text)
    except ValueError:
        logger.debug("Unparseable market timestamp: %s", updated)
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)

def is_stale(station, now=None):
    when = reported_at(station)
    if when is None:
        # In practice only stations with no market data at all lack a timestamp,
        # and those are dropped before we get here. Keep anything else: a price
        # of unknown age still beats the blank column it would otherwise leave.
        return False
    return (now or datetime.now(timezone.utc)) - when > timedelta(days=STALE_AFTER_DAYS)


def station_type_of(station):
    return (globals.STATION_TYPE.Surface if station.get("is_planetary")
            else globals.STATION_TYPE.Orbital)


class Summary:
    """What an import did, in terms worth showing the commander."""

    def __init__(self):
        self.markets_seen = 0
        self.markets_used = 0
        self.markets_stale = 0
        self.prices = 0
        self.pages = 0
        self.bytes = 0
        self.truncated = False
        self.total_available = 0
        self.oldest_days = 0

    def __str__(self):
        if not self.markets_seen:
            return "No markets found in range."
        if not self.markets_used:
            return f"Found {self.markets_seen} markets, none stocking what your sites need."
        text = f"{self.markets_used} markets, {self.prices} prices."
        if self.truncated:
            text += f" Nearest {self.markets_seen} of {self.total_available}."
        if self.oldest_days > 60:
            text += f" Oldest reported {self.oldest_days} days ago."
        if self.markets_stale:
            text += f" Skipped {self.markets_stale} over a year old."
        return text


def wanted_commodities():
    """Commodity key -> the internal name the sites use, for everything still needed."""
    import helpers

    wanted = {}
    for site in helpers.load_facility_requirements().values():
        for name, info in site.get("materials", {}).items():
            if info.get("RequiredAmount", 0) > info.get("ProvidedAmount", 0):
                wanted[commodity_key(name)] = name
    return wanted


def import_markets(system, radius, include_orbital, include_surface,
                   progress=None, now=None, pad_size=DEFAULT_PAD_SIZE):
    """Pull nearby markets into the market library. Runs off the main thread."""
    global _last_import_at
    import helpers

    if not system:
        raise ImportError_("The construction site's system is not known yet. Dock at "
                           "the site once, or jump into its system, and try again.")
    types = station_types(include_orbital, include_surface)
    if not types:
        raise ImportError_("Choose orbital markets, surface markets, or both.")
    if pad_size not in (PAD_LARGE, PAD_LARGE_MEDIUM):
        pad_size = DEFAULT_PAD_SIZE
    radius = max(MIN_RADIUS, min(MAX_RADIUS, int(radius)))

    wanted = wanted_commodities()
    if not wanted:
        raise ImportError_("No construction sites are waiting on anything, so there "
                           "is nothing to look up.")

    def report(text):
        logger.info(text)
        if progress:
            progress(text)

    pad_label = PAD_SIZE_LABELS.get(pad_size, pad_size)
    report(f"Looking for {pad_label.lower()} markets within {radius} ly of {system}...")

    summary = Summary()
    market_lib = helpers.get_market_library()
    site_prices = helpers.load_site_prices()
    now = now or datetime.now(timezone.utc)

    for page in range(MAX_PAGES):
        if page:
            time.sleep(PAGE_PAUSE)
        data, nbytes = search_page(system, radius, types, page, pad_size=pad_size)
        summary.pages += 1
        summary.bytes += nbytes
        summary.total_available = data.get("count") or 0
        results = data.get("results") or []
        if not results:
            break

        for station in results:
            market = station.get("market")
            if not market:
                continue
            if not fits_pad_filter(station, pad_size):
                continue
            summary.markets_seen += 1
            if is_stale(station, now):
                summary.markets_stale += 1
                continue

            location = [station.get("system_x"), station.get("system_y"),
                        station.get("system_z")]
            if None in location:
                continue
            station_type = station_type_of(station)
            system_name = station.get("system_name")
            used = False
            for row in market:
                if row.get("supply", 0) <= 0:
                    continue
                internal = wanted.get(commodity_key(row.get("commodity")))
                if not internal:
                    continue
                price = row.get("buy_price")
                if not price or price <= 0:
                    continue
                helpers.record_market_price(
                    market_lib, internal, price, station.get("name"),
                    station.get("market_id"), station_type, location,
                    site_prices=site_prices, system=system_name,
                    max_pad=max_pad_of_station(station))
                summary.prices += 1
                used = True
            if used:
                summary.markets_used += 1
                when = reported_at(station)
                if when:
                    summary.oldest_days = max(summary.oldest_days, (now - when).days)

        report(f"Read {summary.markets_seen} markets so far...")
        if len(results) < PAGE_SIZE:
            break
    else:
        summary.truncated = summary.total_available > summary.markets_seen

    helpers.save_market_library(market_lib)
    _last_import_at = time.monotonic()
    logger.info("Market import finished: %s (%d pages, %.1f MB)",
                summary, summary.pages, summary.bytes / 1024 / 1024)
    return summary
