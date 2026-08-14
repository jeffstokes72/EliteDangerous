import os
import json
import binascii
from datetime import datetime, timezone

import globals
from globals import logger
from commodities import commodity_key as cargo_key

_MAX_JOURNAL_DELTAS = 200


def _parse_ts(value):
    """Journal/CAPI timestamp to epoch seconds, or None if unknown."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        pass
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw).timestamp()
    except ValueError:
        return None


def _qty(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _market_id_from_capi(data):
    market = data.get("market") if isinstance(data.get("market"), dict) else {}
    for candidate in (market.get("id"), market.get("MarketID"),
                      data.get("marketId"), data.get("MarketID")):
        if candidate is None or candidate == "":
            continue
        try:
            return int(candidate)
        except (TypeError, ValueError):
            return candidate
    return None


def _coerce_market_id(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# --- Fleet Carrier Cargo Tracker ---
class FleetCarrierCargoTracker:
    def __init__(self):
        self.commodities = {}
        self.carrier_name = ""
        self.callsign = ""
        self.market_id = None
        # Journal cargo changes newer than the last CAPI snapshot. Replayed when a
        # stale CAPI payload would otherwise undo a transfer/buy/sell.
        self._journal_deltas = []
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
                name = cargo_key(item.get("commodity"))
                qty = _qty(item.get("qty", 0))
                if not name:
                    logger.warning("Missing commodity name in cargo item: %s. Skipping it.", item)
                    continue
                newcargo[name] = newcargo.get(name, 0) + qty #materials purchase at different prices have different slots
                logger.debug("Fleet carrier has %s tonnes of %s", qty, name)
            except Exception as e:
                logger.error("Error updating fleet carrier cargo from CAPI: %s", e)
                continue

        capi_ts = _parse_ts(data.get("timestamp"))
        replayed = 0
        kept = []
        for ts, name, delta in self._journal_deltas:
            if capi_ts is None or ts is None or ts > capi_ts:
                newcargo[name] = max(0, newcargo.get(name, 0) + delta)
                kept.append((ts, name, delta))
                replayed += 1
        if replayed:
            logger.info("Replayed %s journal cargo change(s) on top of CAPI snapshot", replayed)
        self._journal_deltas = kept[-_MAX_JOURNAL_DELTAS:]
        self.commodities = newcargo

        carrier_info = data.get("name", {}) if isinstance(data.get("name"), dict) else {}
        hex_name = carrier_info.get("vanityName")
        self.carrier_name = self.decode_vanity_name(hex_name) if hex_name else "Unnamed Carrier"
        self.callsign = carrier_info.get("callsign", "") or self.callsign
        mid = _market_id_from_capi(data)
        if mid is not None:
            self.market_id = mid
        self.save()

    def is_own_carrier(self, station=None, market_id=None) -> bool:
        """True when `station` or `market_id` is the commander's tracked carrier."""
        own_mid = _coerce_market_id(self.market_id)
        other_mid = _coerce_market_id(market_id)
        if own_mid is not None and other_mid is not None and own_mid == other_mid:
            return True
        if station and self.callsign:
            return str(station).strip().upper() == str(self.callsign).strip().upper()
        return False

    def _record_delta(self, name, delta, timestamp=None):
        ts = _parse_ts(timestamp)
        if ts is None:
            ts = datetime.now(timezone.utc).timestamp()
        self._journal_deltas.append((ts, name, delta))
        if len(self._journal_deltas) > _MAX_JOURNAL_DELTAS:
            self._journal_deltas = self._journal_deltas[-_MAX_JOURNAL_DELTAS:]

    def apply_transfer_event(self, transfers, timestamp=None):
        if not isinstance(transfers, list):
            return
        for transfer in transfers:
            if not isinstance(transfer, dict):
                continue
            name = cargo_key(transfer.get("Type") or transfer.get("Type_Localised"))
            qty = _qty(transfer.get("Count", 0))
            direction = str(transfer.get("Direction") or "").lower()
            if not name or qty <= 0 or direction not in ("tocarrier", "toship"):
                continue
            current = self.commodities.get(name, 0)
            if direction == "tocarrier":
                self.commodities[name] = current + qty
                self._record_delta(name, qty, timestamp)
                logger.info("Transferred: %s x %s to carrier", name, qty)
            else:
                self.commodities[name] = max(0, current - qty)
                self._record_delta(name, -qty, timestamp)
                logger.info("Transferred: %s x %s to starship", name, qty)
        self.save()

    def apply_market_purchase(self, eventData, timestamp=None):
        name = cargo_key(eventData.get("Type") or eventData.get("Type_Localised"))
        qty = _qty(eventData.get("Count", 0))
        if not name or qty <= 0:
            return
        current = self.commodities.get(name, 0)
        self.commodities[name] = max(0, current - qty)
        self._record_delta(name, -qty, timestamp or eventData.get("timestamp"))
        logger.info("Purchased: %s x %s from carrier", name, qty)
        self.save()

    def apply_market_sale(self, eventData, timestamp=None):
        name = cargo_key(eventData.get("Type") or eventData.get("Type_Localised"))
        qty = _qty(eventData.get("Count", 0))
        if not name or qty <= 0:
            return
        self.commodities[name] = self.commodities.get(name, 0) + qty
        self._record_delta(name, qty, timestamp or eventData.get("timestamp"))
        logger.info("Sold: %s x %s to carrier", name, qty)
        self.save()

    def get_quantity(self, commodity_name):
        return self.commodities.get(cargo_key(commodity_name), 0)

    def save(self):
        try:
            with open(globals.CARRIER_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "carrier_name": self.carrier_name,
                    "callsign": self.callsign,
                    "market_id": self.market_id,
                    "commodities": self.commodities
                }, f, indent=4)
        except Exception as e:
            logger.error("Error saving fleet carrier cargo: %s", e)

    def load(self):
        if not os.path.exists(globals.CARRIER_FILE):
            return
        try:
            with open(globals.CARRIER_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.carrier_name = data.get("carrier_name", "")
                self.callsign = data.get("callsign", "")
                self.market_id = _coerce_market_id(data.get("market_id"))
                #re-key anything written before the names were normalised
                stored = data.get("commodities", {}) or {}
                self.commodities = {}
                for name, qty in stored.items():
                    key = cargo_key(name)
                    if key:
                        self.commodities[key] = self.commodities.get(key, 0) + _qty(qty)
        except Exception as e:
            logger.error("Error loading fleet carrier cargo: %s", e)

    def decode_vanity_name(self, hex_string):
        try:
            return binascii.unhexlify(hex_string).decode('utf-8')
        except Exception as e:
            logger.error(f"Failed to decode vanity name: {e}")
            return hex_string
