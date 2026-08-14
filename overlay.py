"""Optional in-game list via EDMC Overlay / Overlay2 / Modern Overlay.

Uses the shared edmcoverlay API. When no overlay plugin is installed, every
call is a no-op so Architect Tracker still runs normally.
"""

import time

from globals import logger

# Virtual canvas used by EDMCOverlay / Overlay2 (and Modern Overlay's compat layer).
WIDTH_OVERLAY = 1280
HEIGHT_OVERLAY = 960

# Stable name for Modern Overlay's Overlay Controller. Folder rename
# (ArchitectTracker → ArchitectTracker_enhanced) must not create a new group.
PLUGIN_OVERLAY_NAME = "ArchitectTracker"
PLUGIN_GROUP_NAME = "Architect Tracker"
PLUGIN_ID_PREFIX = "archtrack-"

# Left edge. Vertical start is chosen in settings (top / mid / bottomish).
OVERLAY_X = 24
OVERLAY_Y_BY_POS = {
    "top": 80,  # below the ship HUD; 36 sat under it
    "mid": HEIGHT_OVERLAY // 2,  # 480, original placement
    "bottom": 700,
}
OVERLAY_Y_START = OVERLAY_Y_BY_POS["mid"]
# Room between rows so names stay readable over game HUD noise.
LINE_HEIGHT = 22
MAX_ROWS = 20
# Status.json heartbeat refreshes this; keep it long enough to survive a quiet stretch.
TTL_SECONDS = 60
HEARTBEAT_SECONDS = 8

# Two-column table: commodity name | amount needed.
# Overlay fonts are roughly fixed-width; pad for a clear gap between columns.
NAME_WIDTH = 26
QTY_WIDTH = 8
NAME_COL_X = OVERLAY_X
# ~5 px per character at normal size on the virtual canvas.
QTY_COL_X = OVERLAY_X + (NAME_WIDTH * 5) + 24

TITLE_COLOR = "#1fbeff"  # Elite-ish cyan
HEADER_COLOR = "yellow"
NAME_COLOR = "yellow"
QTY_COLOR = "#ff8500"

TITLE_ID = "archtrack-title"
HEADER_NAME_ID = "archtrack-hdr-name"
HEADER_QTY_ID = "archtrack-hdr-qty"
NAME_ID_PREFIX = "archtrack-name-"
QTY_ID_PREFIX = "archtrack-qty-"

_edmcoverlay_mod = None
_overlay_client = None
_import_attempted = False
_logged_missing = False
_warned_unavailable = False
_warned_send = False
_logged_skip_disabled = False
_logged_skip_unavailable = False
_group_registered = False
_active_row_count = 0
_last_payload = None  # (title, rows) for heartbeat
_last_heartbeat = 0.0


def _module_has_overlay(mod):
    if mod is None:
        return None
    if getattr(mod, "Overlay", None) is not None:
        return mod
    inner = getattr(mod, "edmcoverlay", None)
    if inner is not None and getattr(inner, "Overlay", None) is not None:
        return inner
    return None


def _import_overlay_module():
    """Load whichever overlay package is installed (Overlay2 / EDMC / Modern).

    Overlay plugins are often still being added to sys.path when Architect
    Tracker opens its window at EDMC startup. A failed first import must not
    stick for the rest of the session.
    """
    global _edmcoverlay_mod, _import_attempted, _logged_missing
    if _edmcoverlay_mod is not None:
        return _edmcoverlay_mod

    tried = []
    try:
        import edmcoverlay as mod
        found = _module_has_overlay(mod)
        if found is not None:
            _edmcoverlay_mod = found
            logger.info("Overlay: loaded edmcoverlay module")
            return _edmcoverlay_mod
        tried.append("edmcoverlay (no Overlay class)")
    except ImportError:
        tried.append("edmcoverlay")

    try:
        from EDMCOverlay import edmcoverlay as mod
        found = _module_has_overlay(mod)
        if found is not None:
            _edmcoverlay_mod = found
            logger.info("Overlay: loaded EDMCOverlay.edmcoverlay module")
            return _edmcoverlay_mod
        tried.append("EDMCOverlay.edmcoverlay (no Overlay class)")
    except ImportError:
        tried.append("EDMCOverlay.edmcoverlay")

    try:
        import edmcoverlay2 as mod
        found = _module_has_overlay(mod)
        if found is not None:
            _edmcoverlay_mod = found
            logger.info("Overlay: loaded edmcoverlay2 module")
            return _edmcoverlay_mod
        tried.append("edmcoverlay2 (no Overlay class)")
    except ImportError:
        tried.append("edmcoverlay2")

    _import_attempted = True
    if not _logged_missing:
        logger.info("Overlay: no overlay plugin found yet (%s); will retry",
                    ", ".join(tried))
        _logged_missing = True
    return None


def overlay_available() -> bool:
    """True when an overlay Python API is importable."""
    return _import_overlay_module() is not None


def _is_modern_overlay(mod=None) -> bool:
    mod = mod if mod is not None else _edmcoverlay_mod
    if mod is None:
        return False
    if getattr(mod, "MODERN_OVERLAY_IDENTITY", None):
        return True
    return hasattr(mod, "normalise_legacy_payload")


def _register_modern_overlay_group():
    """Tell Modern Overlay to keep our lines in one left-anchored group."""
    global _group_registered
    if _group_registered or not _is_modern_overlay():
        return
    try:
        from overlay_plugin.overlay_api import define_plugin_group
    except ImportError:
        return
    try:
        define_plugin_group(
            plugin_name=PLUGIN_OVERLAY_NAME,
            plugin_matching_prefixes=[PLUGIN_ID_PREFIX],
            plugin_group_name=PLUGIN_GROUP_NAME,
            plugin_group_prefixes=[PLUGIN_ID_PREFIX],
            plugin_group_anchor="nw",
            payload_justification="left",
        )
        _group_registered = True
        logger.info("Overlay: registered Modern Overlay group %s", PLUGIN_GROUP_NAME)
    except Exception as e:
        logger.debug("Overlay: Modern Overlay group not registered yet: %s", e)


def _client():
    global _overlay_client, _warned_unavailable
    mod = _import_overlay_module()
    if mod is None:
        return None
    if _overlay_client is None:
        try:
            _overlay_client = mod.Overlay()
            _register_modern_overlay_group()
        except Exception as e:
            if not _warned_unavailable:
                logger.warning("Overlay: could not connect to overlay service: %s", e)
                _warned_unavailable = True
            return None
    return _overlay_client


def _send(msg_id, text, color, x, y, size="normal", ttl=TTL_SECONDS):
    global _overlay_client, _warned_send
    client = _client()
    if client is None:
        return False
    try:
        x, y = int(x), int(y)
        if _is_modern_overlay() and hasattr(client, "send_raw"):
            client.send_raw({
                "id": msg_id,
                "text": text,
                "color": color,
                "x": x,
                "y": y,
                "ttl": ttl,
                "size": size,
                "plugin": PLUGIN_OVERLAY_NAME,
            })
            return True
        client.send_message(msg_id, text, color, x, y, ttl=ttl, size=size)
        return True
    except TypeError:
        # Older clients may not take size=
        try:
            client.send_message(msg_id, text, color, int(x), int(y), ttl=ttl)
            return True
        except Exception as e:
            if not _warned_send:
                logger.warning("Overlay send failed: %s", e)
                _warned_send = True
            _overlay_client = None
            return False
    except Exception as e:
        if not _warned_send:
            logger.warning("Overlay send failed: %s", e)
            _warned_send = True
        _overlay_client = None
        return False


def _y_start():
    try:
        import helpers
        pos = helpers.overlay_position()
    except Exception:
        pos = "mid"
    return OVERLAY_Y_BY_POS.get(pos, OVERLAY_Y_BY_POS["mid"])


def _clear_slot_range(count, y=None):
    if y is None:
        y = _y_start()
    for i in range(max(0, int(count or 0))):
        _send(f"{NAME_ID_PREFIX}{i}", "", NAME_COLOR, NAME_COL_X, y, ttl=1)
        _send(f"{QTY_ID_PREFIX}{i}", "", QTY_COLOR, QTY_COL_X, y, ttl=1)


def clear():
    """Blank previously painted Architect Tracker lines."""
    global _active_row_count, _last_payload
    y = _y_start()
    _send(TITLE_ID, "", TITLE_COLOR, OVERLAY_X, y, size="large", ttl=1)
    _send(HEADER_NAME_ID, "", HEADER_COLOR, NAME_COL_X, y, ttl=1)
    _send(HEADER_QTY_ID, "", HEADER_COLOR, QTY_COL_X, y, ttl=1)
    _clear_slot_range(_active_row_count, y)
    _active_row_count = 0
    _last_payload = None


def _format_qty(value):
    """Thousand-separated amount for easier reading in-game."""
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def paint(title, rows):
    """Draw a two-column table: commodity | amount needed.

    `rows` is a list of dicts with keys: name, shortfall.
    Only items with shortfall > 0 are shown (what you still need to haul).
    """
    global _active_row_count, _last_payload
    global _logged_skip_disabled, _logged_skip_unavailable
    import helpers

    if not helpers.overlay_enabled():
        if not _logged_skip_disabled:
            logger.info("Overlay: not painting (disabled in settings)")
            _logged_skip_disabled = True
        return

    if not overlay_available():
        if not _logged_skip_unavailable:
            logger.info("Overlay: not painting (overlay plugin not importable yet)")
            _logged_skip_unavailable = True
        return
    _logged_skip_unavailable = False
    _register_modern_overlay_group()

    try:
        needed = [r for r in rows if int(r.get("shortfall") or 0) > 0]
    except (TypeError, ValueError):
        needed = []
    site = (title or "Architect Tracker").strip() or "Architect Tracker"
    _last_payload = (site, list(rows or []))

    y = _y_start()
    sent = _send(TITLE_ID, site[:48], TITLE_COLOR, OVERLAY_X, y, size="large", ttl=TTL_SECONDS)
    y += LINE_HEIGHT + 6

    _send(HEADER_NAME_ID, "Commodity", HEADER_COLOR, NAME_COL_X, y, ttl=TTL_SECONDS)
    _send(HEADER_QTY_ID, "Needed", HEADER_COLOR, QTY_COL_X, y, ttl=TTL_SECONDS)
    y += LINE_HEIGHT + 4

    if not needed:
        _send(f"{NAME_ID_PREFIX}0", "Nothing left to haul", NAME_COLOR, NAME_COL_X, y,
              ttl=TTL_SECONDS)
        # Empty qty deletes a leftover number from a previous paint (Overlay2
        # treats empty text as a per-id remove).
        _send(f"{QTY_ID_PREFIX}0", "", QTY_COLOR, QTY_COL_X, y, ttl=1)
        painted = 1
        y += LINE_HEIGHT
    else:
        painted = 0
        for r in needed[:MAX_ROWS]:
            name = str(r.get("name") or "")[:NAME_WIDTH]
            qty = _format_qty(r.get("shortfall") or 0)
            _send(f"{NAME_ID_PREFIX}{painted}", name, NAME_COLOR, NAME_COL_X, y,
                  ttl=TTL_SECONDS)
            _send(f"{QTY_ID_PREFIX}{painted}", qty, QTY_COLOR, QTY_COL_X, y,
                  ttl=TTL_SECONDS)
            painted += 1
            y += LINE_HEIGHT

    # Clear unused slots from a previous longer paint. Do not blast MAX_ROWS
    # empty messages on every frame — Overlay2 treats empty text as a delete,
    # and Modern Overlay grouping does not need the extra blanks.
    origin = _y_start()
    for i in range(painted, _active_row_count):
        _send(f"{NAME_ID_PREFIX}{i}", "", NAME_COLOR, NAME_COL_X, origin, ttl=1)
        _send(f"{QTY_ID_PREFIX}{i}", "", QTY_COLOR, QTY_COL_X, origin, ttl=1)
    _active_row_count = painted

    if sent:
        logger.debug("Overlay: painted %s (%s rows)", site, painted)


def heartbeat():
    """Re-send the last frame so the overlay does not expire between journal events."""
    global _last_heartbeat
    if _last_payload is None:
        return
    now = time.monotonic()
    if now - _last_heartbeat < HEARTBEAT_SECONDS:
        return
    _last_heartbeat = now
    title, rows = _last_payload
    paint(title, rows)
