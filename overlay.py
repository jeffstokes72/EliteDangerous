"""Optional in-game list via EDMC Overlay / Overlay2 / Modern Overlay.

Uses the shared edmcoverlay API. When no overlay plugin is installed, every
call is a no-op so Architect Tracker still runs normally.
"""

from globals import logger

# Virtual canvas used by EDMCOverlay / Overlay2 (and Modern Overlay's compat layer).
WIDTH_OVERLAY = 1280
HEIGHT_OVERLAY = 960

# Left edge. Vertical start is chosen in settings (top / mid / bottomish).
OVERLAY_X = 24
OVERLAY_Y_BY_POS = {
    "top": 36,
    "mid": HEIGHT_OVERLAY // 2,  # 480, original placement
    "bottom": 700,
}
OVERLAY_Y_START = OVERLAY_Y_BY_POS["mid"]
# Room between rows so names stay readable over game HUD noise.
LINE_HEIGHT = 22
MAX_ROWS = 20
TTL_SECONDS = 20

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
_warned_unavailable = False
_active_row_count = 0


def _import_overlay_module():
    """Load whichever overlay package is installed (Overlay2 / EDMC / Modern)."""
    global _edmcoverlay_mod, _import_attempted
    if _import_attempted:
        return _edmcoverlay_mod
    _import_attempted = True
    try:
        import edmcoverlay as mod
        _edmcoverlay_mod = mod
        logger.info("Overlay: loaded edmcoverlay module")
        return _edmcoverlay_mod
    except ImportError:
        pass
    try:
        from EDMCOverlay import edmcoverlay as mod
        _edmcoverlay_mod = mod
        logger.info("Overlay: loaded EDMCOverlay.edmcoverlay module")
        return _edmcoverlay_mod
    except ImportError:
        pass
    logger.info("Overlay: no edmcoverlay plugin found (optional)")
    _edmcoverlay_mod = None
    return None


def overlay_available() -> bool:
    """True when an overlay Python API is importable."""
    return _import_overlay_module() is not None


def _client():
    global _overlay_client, _warned_unavailable
    mod = _import_overlay_module()
    if mod is None:
        return None
    if _overlay_client is None:
        try:
            _overlay_client = mod.Overlay()
        except Exception as e:
            if not _warned_unavailable:
                logger.warning("Overlay: could not connect to overlay service: %s", e)
                _warned_unavailable = True
            return None
    return _overlay_client


def _send(msg_id, text, color, x, y, size="normal", ttl=TTL_SECONDS):
    client = _client()
    if client is None:
        return False
    try:
        client.send_message(msg_id, text, color, int(x), int(y), ttl=ttl, size=size)
        return True
    except TypeError:
        # Older clients may not take size=
        try:
            client.send_message(msg_id, text, color, int(x), int(y), ttl=ttl)
            return True
        except Exception as e:
            logger.debug("Overlay send failed: %s", e)
            return False
    except Exception as e:
        logger.debug("Overlay send failed: %s", e)
        return False


def _y_start():
    import helpers
    return OVERLAY_Y_BY_POS.get(helpers.overlay_position(), OVERLAY_Y_BY_POS["mid"])


def _clear_slot_range(count, y=None):
    if y is None:
        y = _y_start()
    for i in range(count):
        _send(f"{NAME_ID_PREFIX}{i}", "", NAME_COLOR, NAME_COL_X, y, ttl=1)
        _send(f"{QTY_ID_PREFIX}{i}", "", QTY_COLOR, QTY_COL_X, y, ttl=1)


def clear():
    """Blank previously painted Architect Tracker lines."""
    global _active_row_count
    y = _y_start()
    _send(TITLE_ID, "", TITLE_COLOR, OVERLAY_X, y, size="large", ttl=1)
    _send(HEADER_NAME_ID, "", HEADER_COLOR, NAME_COL_X, y, ttl=1)
    _send(HEADER_QTY_ID, "", HEADER_COLOR, QTY_COL_X, y, ttl=1)
    _clear_slot_range(max(_active_row_count, MAX_ROWS), y)
    _active_row_count = 0


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
    import helpers

    if not helpers.overlay_enabled():
        return

    if not overlay_available():
        return

    needed = [r for r in rows if int(r.get("shortfall") or 0) > 0]
    site = (title or "Architect Tracker").strip() or "Architect Tracker"

    y = _y_start()
    _send(TITLE_ID, site[:48], TITLE_COLOR, OVERLAY_X, y, size="large", ttl=TTL_SECONDS)
    y += LINE_HEIGHT + 6

    _send(HEADER_NAME_ID, "Commodity", HEADER_COLOR, NAME_COL_X, y, ttl=TTL_SECONDS)
    _send(HEADER_QTY_ID, "Needed", HEADER_COLOR, QTY_COL_X, y, ttl=TTL_SECONDS)
    y += LINE_HEIGHT + 4

    if not needed:
        _send(f"{NAME_ID_PREFIX}0", "Nothing left to haul", NAME_COLOR, NAME_COL_X, y,
              ttl=TTL_SECONDS)
        _send(f"{QTY_ID_PREFIX}0", "", QTY_COLOR, QTY_COL_X, y, ttl=TTL_SECONDS)
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

    # Clear unused slots from a previous longer paint.
    global _active_row_count
    origin = _y_start()
    for i in range(painted, max(_active_row_count, MAX_ROWS)):
        _send(f"{NAME_ID_PREFIX}{i}", "", NAME_COLOR, NAME_COL_X, origin, ttl=1)
        _send(f"{QTY_ID_PREFIX}{i}", "", QTY_COLOR, QTY_COL_X, origin, ttl=1)
    _active_row_count = painted
