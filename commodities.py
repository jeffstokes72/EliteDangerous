"""One spelling for a commodity, whichever source it came from.

The plugin sees commodity names from four places and they disagree:

    construction sites   $cmmcomposite_name;   (journal internal name)
    cargo transfers      cmmcomposite          (journal, undecorated)
    carrier CAPI         CMM Composite         (display name)
    Spansh               CMM Composite         (display name)

commodity_key() folds all of them onto one key. A handful of commodities have
a display name that cannot be derived from the internal one at all, so those
are listed explicitly; the rest fall out of stripping the decoration.
"""

# internal name -> display name, for the ones that do not match after stripping.
# Taken from EDCD/FDevIDs commodity.csv, where symbol and name disagree.
ALIASES = {
    "agriculturalmedicines": "agrimedicines",
    "atmosphericextractors": "atmosphericprocessors",
    "basicnarcotics": "narcotics",
    "hazardousenvironmentsuits": "hesuits",
    "heliostaticfurnaces": "microbialfurnaces",
    "marinesupplies": "marineequipment",
    "mutomimager": "muonimager",
    "skimercomponents": "skimmercomponents",
    "terrainenrichmentsystems": "landenrichmentsystems",
    "unknownartifact": "thargoidsensor",
    "usscargoblackbox": "blackbox",
}

_STRIP = (" ", "-", "_", "'", ".", "&")


def commodity_key(name) -> str:
    """A comparable key for a commodity name in any of its spellings."""
    if not name:
        return ""
    key = str(name).strip().lower()
    if key.startswith("$"):
        key = key[1:]
    if key.endswith("_name;"):
        key = key[:-len("_name;")]
    for ch in _STRIP:
        key = key.replace(ch, "")
    return ALIASES.get(key, key)
