"""Stand-in for the edmcoverlay API used by Overlay2 / EDMC Overlay / Modern Overlay."""


class Overlay:
    messages = []

    def __init__(self):
        pass

    def send_message(self, msg_id, text, color, x, y, ttl=8, size="normal"):
        Overlay.messages.append({
            "id": msg_id, "text": text, "color": color,
            "x": x, "y": y, "ttl": ttl, "size": size,
        })

    def send_raw(self, msg):
        Overlay.messages.append({
            "id": msg.get("id"), "text": msg.get("text"), "color": msg.get("color"),
            "x": msg.get("x"), "y": msg.get("y"), "ttl": msg.get("ttl"),
            "size": msg.get("size"), "plugin": msg.get("plugin"),
        })

    @classmethod
    def reset(cls):
        cls.messages = []
