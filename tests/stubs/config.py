"""Stand-in for EDMarketConnector's config module so the plugin can be tested
without a full EDMC install. Mirrors the parts of the real API the plugin uses."""

appname = "EDMarketConnector"
appversion = "6.1.2"


class _Config:
    def __init__(self):
        self.settings = {}
        self.default_journal_dir = "None"  # what EDMC hands back on Linux

    def get(self, key, default=None):
        return self.settings.get(key.lower(), default)

    def get_str(self, key, default=""):
        val = self.get(key)
        return str(val) if val is not None else default

    def get_int(self, key, default=0):
        val = self.get(key)
        if isinstance(val, int):
            return val
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    def get_bool(self, key, default=False):
        val = self.get(key)
        if isinstance(val, bool):
            return val
        if isinstance(val, int):
            return val != 0
        if isinstance(val, str):
            return val.strip().lower() in ("1", "true", "yes", "on")
        return default

    def get_list(self, key, default=None):
        val = self.get(key)
        return val if isinstance(val, list) else (default if default is not None else [])

    def set(self, key, val):
        self.settings[key.lower()] = val

    def delete(self, key):
        self.settings.pop(key.lower(), None)


config = _Config()
