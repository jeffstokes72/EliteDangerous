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
        raise AssertionError("plugin must stick to send_message; "
                             "send_raw differs between overlay versions")

    @classmethod
    def reset(cls):
        cls.messages = []
