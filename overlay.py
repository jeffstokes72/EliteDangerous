"""Optional in-game list via EDMC Overlay / Overlay2 / Modern Overlay.

Uses the shared edmcoverlay API. When no overlay plugin is installed, every
call is a no-op so Architect Tracker still runs normally.
"""

from globals import logger

# Virtual canvas used by EDMCOverlay / Overlay2 (and Modern Overlay's compat layer).
WIDTH_OVERLAY = 1280
HEIGHT_OVERLAY = 960

# Left edge, starting at mid-screen and listing downward.
OVERLAY_X = 24
OVERLAY_Y_START = HEIGHT_OVERLAY // 2  # 480
LINE_HEIGHT = 16
MAX_LINES = 28
TTL_SECONDS = 20
TITLE_COLOR = "#1fbeff"  # Elite-ish cyan
ROW_COLOR = "yellow"
SHORTFALL_COLOR = "#ff8500"
HEADER_ID = "archtrack-title"
ROW_ID_PREFIX = "archtrack-row-"

_edmcoverlay_mod = None
_overlay_client = None
_import_attempted = False
_warned_unavailable = False
_active_row_ids = []


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


def clear():
    """Blank previously painted Architect Tracker lines."""
    global _active_row_ids
    _send(HEADER_ID, "", TITLE_COLOR, OVERLAY_X, OVERLAY_Y_START, size="large", ttl=1)
    for msg_id in _active_row_ids:
        _send(msg_id, "", ROW_COLOR, OVERLAY_X, OVERLAY_Y_START, ttl=1)
    # Also clear the fixed slot range so leftover lines from a longer list vanish.
    for i in range(MAX_LINES):
        _send(f"{ROW_ID_PREFIX}{i}", "", ROW_COLOR, OVERLAY_X, OVERLAY_Y_START, ttl=1)
    _active_row_ids = []


def paint(title, rows):
    """Draw the commodity list on the left, from mid-height downward.

    `rows` is a list of dicts with keys: name, shortfall, distance (optional).
    Only items with shortfall > 0 are shown (what you still need to haul).
    """
    import helpers

    if not helpers.overlay_enabled():
        return

    if not overlay_available():
        return

    needed = [r for r in rows if int(r.get("shortfall") or 0) > 0]
    lines = []
    site = (title or "Architect Tracker").strip() or "Architect Tracker"
    lines.append(("title", site[:48]))

    if not needed:
        lines.append(("row", "Nothing left to haul"))
    else:
        for r in needed[: MAX_LINES - 1]:
            name = str(r.get("name") or "")[:22]
            short = int(r.get("shortfall") or 0)
            dist = r.get("distance") or ""
            if dist:
                text = f"{name:<22} {short:>6}  {dist}ly"
            else:
                text = f"{name:<22} {short:>6}"
            color = SHORTFALL_COLOR if short > 0 else ROW_COLOR
            lines.append(("row", text, color))

    y = OVERLAY_Y_START
    active = []
    for index, entry in enumerate(lines):
        kind = entry[0]
        text = entry[1]
        if kind == "title":
            msg_id = HEADER_ID
            color = TITLE_COLOR
            size = "large"
        else:
            msg_id = f"{ROW_ID_PREFIX}{index - 1}"
            color = entry[2] if len(entry) > 2 else ROW_COLOR
            size = "normal"
            active.append(msg_id)
        _send(msg_id, text, color, OVERLAY_X, y, size=size, ttl=TTL_SECONDS)
        y += LINE_HEIGHT + (4 if kind == "title" else 0)

    # Clear unused slots from a previous longer paint.
    global _active_row_ids
    for i in range(len(active), MAX_LINES):
        msg_id = f"{ROW_ID_PREFIX}{i}"
        _send(msg_id, "", ROW_COLOR, OVERLAY_X, OVERLAY_Y_START, ttl=1)
    _active_row_ids = active
