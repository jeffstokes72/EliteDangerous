"""Stand-in for EDMarketConnector's myNotebook module.

EDMC's real Frame grids a spacer child in __init__, which means you cannot
then pack anything into that frame. The stub does the same so a pack/grid
mix fails here the way it fails inside EDMC.
"""

import tkinter as tk
from tkinter import ttk


class Notebook(ttk.Notebook):
    pass


class Frame(ttk.Frame):
    def __init__(self, master=None, **kw):
        # Drop border/relief kwargs that ttk.Frame does not accept the same way.
        kw.pop("border", None)
        kw.pop("relief", None)
        kw.pop("bd", None)
        super().__init__(master, **kw)
        ttk.Frame(self).grid(pady=5)  # Top spacer, same as EDMC's myNotebook.Frame
        self.configure(takefocus=1)


class Label(ttk.Label):
    def __init__(self, master=None, **kw):
        # tk Font objects and justify work on ttk.Label; drop plain-tk-only noise.
        super().__init__(master, **kw)


class Checkbutton(ttk.Checkbutton):
    pass


class Entry(ttk.Entry):
    pass


class Button(ttk.Button):
    pass


class OptionMenu(ttk.OptionMenu):
    pass
