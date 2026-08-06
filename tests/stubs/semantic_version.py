"""Stand-in for the semantic_version package."""


class Version:
    def __init__(self, text):
        self.text = text

    def __str__(self):
        return self.text
