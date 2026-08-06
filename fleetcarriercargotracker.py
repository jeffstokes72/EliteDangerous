import os
import json
import binascii

import globals
from globals import logger
from commodities import commodity_key as cargo_key

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
                name = cargo_key(item.get("commodity"))
                qty = item.get("qty", 0)
                if not name:
                    logger.warning("Missing commodity name in cargo item: %s. Skipping it.", item)
                    continue
                newcargo[name] = newcargo.get(name, 0) + qty #materials purchase at different prices have different slots
                logger.debug("Fleet carrier has %s tonnes of %s", qty, name)
            except Exception as e:
                logger.error("Error updating fleet carrier cargo from CAPI: %s", e)
                continue

        self.commodities = newcargo

        carrier_info = data.get("name", {})
        hex_name = carrier_info.get("vanityName")
        self.carrier_name = self.decode_vanity_name(hex_name) if hex_name else "Unnamed Carrier"
        self.callsign = carrier_info.get("callsign", "")
        self.save()

    def apply_transfer_event(self, transfers):
        for transfer in transfers:
            name = cargo_key(transfer.get("Type"))
            qty = transfer.get("Count", 0)
            direction = transfer.get("Direction")
            if not name or qty <= 0 or direction not in ("tocarrier", "toship"):
                continue
            current = self.commodities.get(name, 0)
            if direction == "tocarrier":
                self.commodities[name] = current + qty
                logger.info("Transferred: %s x %s to carrier", name, qty)
            else:
                self.commodities[name] = max(0, current - qty)
                logger.info("Transferred: %s x %s to starship", name, qty)
        self.save()

    def apply_market_purchase(self, eventData):
        name = cargo_key(eventData.get("Type"))
        qty = eventData.get("Count", 0)
        if not name or qty <= 0:
            return
        current = self.commodities.get(name, 0)
        self.commodities[name] = max(0, current - qty)
        logger.info("Purchased: %s x %s from carrier", name, qty)
        self.save()

    def apply_market_sale(self, eventData):
        name = cargo_key(eventData.get("Type"))
        qty = eventData.get("Count", 0)
        if not name or qty <= 0:
            return
        self.commodities[name] = self.commodities.get(name, 0) + qty
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
                #re-key anything written before the names were normalised
                stored = data.get("commodities", {}) or {}
                self.commodities = {}
                for name, qty in stored.items():
                    key = cargo_key(name)
                    if key:
                        self.commodities[key] = self.commodities.get(key, 0) + qty
        except Exception as e:
            logger.error("Error loading fleet carrier cargo: %s", e)
            
    def decode_vanity_name(self, hex_string):
        try:
            return binascii.unhexlify(hex_string).decode('utf-8')
        except Exception as e:
            logger.error(f"Failed to decode vanity name: {e}")
            return hex_string
