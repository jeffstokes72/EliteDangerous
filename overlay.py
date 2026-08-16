"""Optional in-game list via EDMC Overlay / Overlay2 / Modern Overlay.

Uses the shared edmcoverlay API. When no overlay plugin is installed, every
call is a no-op so Architect Tracker still runs normally.
"""

import json
import os
import time

from globals import logger

# Virtual canvas used by EDMCOverlay / Overlay2 (and Modern Overlay's compat layer).
WIDTH_OVERLAY = 1280
HEIGHT_OVERLAY = 960

# Stable name reported to Modern Overlay so the payloads stay attributed to
# this plugin whatever the plugin folder is called.
PLUGIN_OVERLAY_NAME = "ArchitectTracker"
PLUGIN_GROUP_NAME = "Architect Tracker"  # group written by older builds; removed now
PLUGIN_ID_PREFIX = "archtrack-"

# Left edge. Vertical start is chosen in settings (top / mid / bottomish).
OVERLAY_X = 24
OVERLAY_Y_BY_POS = {
    "top": 80,  # below the ship HUD; 36 sat under it
    "mid": HEIGHT_OVERLAY // 2,  # 480, original placement
    "bottom": 700,
}
OVERLAY_Y_START = OVERLAY_Y_BY_POS["mid"]
# Space between rows on the 1280x960 virtual canvas, chosen in settings.
LINE_HEIGHT = 22
SPACING_PX = {
    "compact": 16,
    "normal": LINE_HEIGHT,
    "roomy": 30,
}
MAX_ROWS = 20
# Status.json heartbeat refreshes this; keep it long enough to survive a quiet stretch.
TTL_SECONDS = 60
HEARTBEAT_SECONDS = 8

# Two-column table: commodity name | Needed or Shortfall (chosen in the tracker).
# Names are truncated with ".." so they cannot run into the numbers. The
# overlay font is proportional; 8 px/char left a wide empty band between
# the name and the amount (about as wide as the longest label). 5 px/char
# plus a small gap is enough once names are capped.
NAME_MAX_CHARS = 22
NAME_PX_PER_CHAR = 5
COL_GAP_PX = 12
NAME_COL_X = OVERLAY_X
QTY_COL_X = OVERLAY_X + (NAME_MAX_CHARS * NAME_PX_PER_CHAR) + COL_GAP_PX  # 146

TITLE_COLOR = "#1fbeff"  # Elite-ish cyan
HEADER_COLOR = "yellow"
NAME_COLOR = "yellow"
QTY_COLOR = "#ff8500"
QTY_COLOR_WHITE = "white"

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
_last_qty_mode = None
_last_qty_color = None
_last_sent = {}  # msg_id -> (text, color, x, y, size)
_dirty = False
_last_emit_at = 0.0
# Modern Overlay warns at 200 payloads / 2s. A full table is ~43 messages, so
# more than one complete re-paint in a journal burst trips it. Tests set this
# to 0 so they can assert on the next call.
MIN_PAINT_INTERVAL = 1.0


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


def _groupings_dir():
    """Directory holding Modern Overlay's overlay_groupings.json, or None."""
    mod_file = getattr(_edmcoverlay_mod, "__file__", None)
    if not mod_file:
        return None
    root = os.path.dirname(os.path.abspath(mod_file))
    for _ in range(3):
        if os.path.exists(os.path.join(root, "overlay_groupings.json")):
            return root
        parent = os.path.dirname(root)
        if parent == root:
            break
        root = parent
    return None


def _remove_legacy_group():
    """Delete the idPrefixGroup an earlier build registered.

    A fill-mode group renders the whole block at 1:1 logical pixels around a
    single anchor, which squashed the rows together on large monitors. The
    grouping API cannot delete entries, so edit the same JSON files it writes.
    """
    root = _groupings_dir()
    if root is None:
        return
    for fname in ("overlay_groupings.json", "overlay_groupings.user.json"):
        path = os.path.join(root, fname)
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            block = data.get(PLUGIN_OVERLAY_NAME)
            if not isinstance(block, dict) or "idPrefixGroups" not in block:
                continue
            block.pop("idPrefixGroups")
            if not block:
                data.pop(PLUGIN_OVERLAY_NAME)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.write("\n")
            logger.info("Overlay: removed the old Architect Tracker group from %s", fname)
        except Exception as e:
            logger.debug("Overlay: could not tidy %s: %s", fname, e)


def _register_modern_overlay_group():
    """Attribute our payloads to ArchitectTracker without grouping them.

    Only the matching prefix is registered, so Modern Overlay knows whose
    lines these are while each line still scales with the game window like
    every other legacy payload (grouping collapsed the row spacing).
    """
    global _group_registered
    if _group_registered or not _is_modern_overlay():
        return
    _remove_legacy_group()
    try:
        from overlay_plugin.overlay_api import define_plugin_group
    except ImportError:
        return
    try:
        try:
            define_plugin_group(
                plugin_name=PLUGIN_OVERLAY_NAME,
                plugin_matching_prefixes=[PLUGIN_ID_PREFIX],
            )
        except TypeError:
            # Modern Overlay builds from before the argument rename.
            define_plugin_group(
                plugin_group=PLUGIN_OVERLAY_NAME,
                matching_prefixes=[PLUGIN_ID_PREFIX],
            )
        _group_registered = True
        logger.info("Overlay: payloads registered to %s (ungrouped)", PLUGIN_OVERLAY_NAME)
    except Exception as e:
        logger.debug("Overlay: Modern Overlay registration not done yet: %s", e)


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


def _visual_key(text, color, x, y, size):
    return (str(text), color, int(x), int(y), size)


def _remember_sent(msg_id, text, color, x, y, size):
    if text == "":
        _last_sent.pop(msg_id, None)
    else:
        _last_sent[msg_id] = _visual_key(text, color, x, y, size)


def _send(msg_id, text, color, x, y, size="normal", ttl=TTL_SECONDS, force=False):
    # Plain send_message only: it is the one call every overlay plugin
    # (EDMC Overlay, Overlay2, all Modern Overlay versions) implements the
    # same way. Modern Overlay routes our lines to the Architect Tracker
    # group by the archtrack- id prefix, so no extra payload fields needed.
    #
    # Unchanged lines are skipped unless force=True (TTL heartbeat). Journal
    # bursts used to re-send the whole table and trip Modern Overlay's
    # 200-payloads-in-2-seconds warning.
    global _overlay_client, _warned_send
    key = _visual_key(text, color, x, y, size)
    if not force:
        if _last_sent.get(msg_id) == key:
            return True
        if text == "" and msg_id not in _last_sent:
            return True
    client = _client()
    if client is None:
        return False
    try:
        client.send_message(msg_id, text, color, int(x), int(y), ttl=ttl, size=size)
    except TypeError:
        # Older clients may not take size=
        try:
            client.send_message(msg_id, text, color, int(x), int(y), ttl=ttl)
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
    _remember_sent(msg_id, text, color, x, y, size)
    return True


def _y_start():
    try:
        import helpers
        pos = helpers.overlay_position()
    except Exception:
        pos = "mid"
    return OVERLAY_Y_BY_POS.get(pos, OVERLAY_Y_BY_POS["mid"])


def _line_height():
    try:
        import helpers
        spacing = helpers.overlay_spacing()
    except Exception:
        spacing = "normal"
    return SPACING_PX.get(spacing, LINE_HEIGHT)


def _clear_slot_range(count, y=None):
    if y is None:
        y = _y_start()
    for i in range(max(0, int(count or 0))):
        _send(f"{NAME_ID_PREFIX}{i}", "", NAME_COLOR, NAME_COL_X, y, ttl=1)
        _send(f"{QTY_ID_PREFIX}{i}", "", QTY_COLOR, QTY_COL_X, y, ttl=1)


def clear():
    """Blank previously painted Architect Tracker lines."""
    global _active_row_count, _last_payload, _dirty, _last_qty_mode, _last_qty_color
    y = _y_start()
    _send(TITLE_ID, "", TITLE_COLOR, OVERLAY_X, y, size="large", ttl=1)
    _send(HEADER_NAME_ID, "", HEADER_COLOR, NAME_COL_X, y, ttl=1)
    _send(HEADER_QTY_ID, "", HEADER_COLOR, QTY_COL_X, y, ttl=1)
    _clear_slot_range(_active_row_count, y)
    _active_row_count = 0
    _last_payload = None
    _dirty = False
    _last_qty_mode = None
    _last_qty_color = None
    _last_sent.clear()


def _format_qty(value):
    """Thousand-separated amount for easier reading in-game."""
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def _fit_name(name):
    """Trim a commodity name so it stays inside the name column."""
    name = str(name or "")
    if len(name) <= NAME_MAX_CHARS:
        return name
    return name[:NAME_MAX_CHARS - 2] + ".."


def _qty_mode():
    try:
        import helpers
        return helpers.overlay_qty_mode()
    except Exception:
        return "needed"


def _qty_header(mode=None):
    if mode is None:
        mode = _qty_mode()
    return "Shortfall" if mode == "shortfall" else "Needed"


def _qty_color():
    try:
        import helpers
        if helpers.overlay_white_numbers():
            return QTY_COLOR_WHITE
    except Exception:
        pass
    return QTY_COLOR


def _row_qty(row, mode=None):
    """Amount for the overlay's second column (Needed or Shortfall)."""
    if mode is None:
        mode = _qty_mode()
    if mode == "shortfall":
        value = row.get("shortfall")
        if value is None:
            value = row.get("needed")
    else:
        value = row.get("needed")
        if value is None:
            value = row.get("shortfall")
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def paint(title, rows, force=False):
    """Draw a two-column table: commodity | Needed or Shortfall.

    `rows` is a list of dicts with keys: name, needed, shortfall. Missing
    amounts fall back to the other. Only items with a positive value in the
    selected column are shown, sorted highest first. Unchanged lines are not
    re-sent. Rapid calls are coalesced to one emit per MIN_PAINT_INTERVAL
    (heartbeat still force-refreshes TTLs). Switching Needed/Shortfall emits
    immediately.
    """
    global _last_payload, _dirty
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

    site = (title or "Architect Tracker").strip() or "Architect Tracker"
    _last_payload = (site, list(rows or []))
    _dirty = True
    if helpers.overlay_qty_mode() != _last_qty_mode or _qty_color() != _last_qty_color:
        force = True
    _emit(force=force)


def _emit(force=False):
    """Send the stored frame, unless a paint just went out (unless force)."""
    global _last_emit_at, _dirty
    if _last_payload is None:
        return
    now = time.monotonic()
    if not force:
        if not _dirty:
            return
        if MIN_PAINT_INTERVAL > 0 and (now - _last_emit_at) < MIN_PAINT_INTERVAL:
            return
    site, rows = _last_payload
    _draw(site, rows, resend=force)
    _last_emit_at = now
    _dirty = False


def _draw(site, rows, resend=False):
    global _active_row_count, _last_qty_mode, _last_qty_color

    mode = _qty_mode()
    qty_color = _qty_color()
    visible = [r for r in (rows or []) if _row_qty(r, mode) > 0]
    visible.sort(key=lambda r: (-_row_qty(r, mode), str(r.get("name") or "").lower()))

    line_height = _line_height()
    y = _y_start()
    sent = _send(TITLE_ID, site[:48], TITLE_COLOR, OVERLAY_X, y, size="large",
                 ttl=TTL_SECONDS, force=resend)
    y += line_height + 6

    _send(HEADER_NAME_ID, "Commodity", HEADER_COLOR, NAME_COL_X, y,
          ttl=TTL_SECONDS, force=resend)
    _send(HEADER_QTY_ID, _qty_header(mode), HEADER_COLOR, QTY_COL_X, y,
          ttl=TTL_SECONDS, force=resend)
    y += line_height + 4

    if not visible:
        _send(f"{NAME_ID_PREFIX}0", "Nothing left to haul", NAME_COLOR, NAME_COL_X, y,
              ttl=TTL_SECONDS, force=resend)
        # Empty qty deletes a leftover number from a previous paint (Overlay2
        # treats empty text as a per-id remove).
        _send(f"{QTY_ID_PREFIX}0", "", qty_color, QTY_COL_X, y, ttl=1)
        painted = 1
        y += line_height
    else:
        painted = 0
        for r in visible[:MAX_ROWS]:
            name = _fit_name(r.get("name"))
            qty = _format_qty(_row_qty(r, mode))
            _send(f"{NAME_ID_PREFIX}{painted}", name, NAME_COLOR, NAME_COL_X, y,
                  ttl=TTL_SECONDS, force=resend)
            _send(f"{QTY_ID_PREFIX}{painted}", qty, qty_color, QTY_COL_X, y,
                  ttl=TTL_SECONDS, force=resend)
            painted += 1
            y += line_height

    # Clear unused slots from a previous longer paint. Do not blast MAX_ROWS
    # empty messages on every frame — Overlay2 treats empty text as a delete,
    # and Modern Overlay grouping does not need the extra blanks.
    origin = _y_start()
    for i in range(painted, _active_row_count):
        _send(f"{NAME_ID_PREFIX}{i}", "", NAME_COLOR, NAME_COL_X, origin, ttl=1)
        _send(f"{QTY_ID_PREFIX}{i}", "", qty_color, QTY_COL_X, origin, ttl=1)
    _active_row_count = painted
    _last_qty_mode = mode
    _last_qty_color = qty_color

    if sent:
        logger.debug("Overlay: painted %s (%s rows, %s)", site, painted, mode)


def heartbeat():
    """Re-send the last frame so the overlay does not expire between journal events.

    Also flushes a paint that was deferred to stay under Modern Overlay's rate limit.
    """
    global _last_heartbeat
    if _last_payload is None:
        return
    now = time.monotonic()
    if now - _last_heartbeat >= HEARTBEAT_SECONDS:
        _last_heartbeat = now
        _emit(force=True)
        return
    _emit(force=False)
