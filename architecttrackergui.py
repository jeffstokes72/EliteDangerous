import json
import platform
import tkinter as tk
from tkinter import ttk
import tkinter.font as tkFont

from config import config

import globals
from globals import logger
import helpers
from tooltip import Tooltip

# --- GUI Definition ---
class ArchitectTrackerGUI(tk.Toplevel):
    edBlue = "#1fbeff"
    edOrange = "#ff8500"
    bgBlack = "#1a1a1a"
    column_visibility = {}
    canvas_tooltip = None

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Architect Tracker")
        self.geometry("800x600")
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.column_visibility, self.hide_provided, self.theme, self.column_names, self.trans_bg, self.win_top, self.opac_amount = helpers.load_gui_settings()
        self.has_table = False
        # Click a column header to sort; Shortfall defaults to high→low on first click.
        self.sort_column = "Material"
        self.sort_reverse = False

        self.setAlpha(self.opac_amount)
        self.setStayOnTop(self.win_top)
        self.setTransparentBg(self.trans_bg)
        self.setStyle()
        data = helpers.load_facility_requirements()
        # Build the table whenever sites exist, even if Location/SITE_LOCATION is
        # still unknown (distances stay blank until StarPos is recorded).
        if not data:
            self._build_info_widgets()
        else:
            self._build_widgets()
            self.refresh()

    def setStayOnTop(self, val):
        self.win_top = val
        if platform.system() == "Darwin":
            self.wm_attributes("-topmost", self.win_top)
        elif platform.system() == "Windows":
            self.wm_attributes("-topmost", self.win_top)
        else:
            self.attributes('-topmost', self.win_top)

    def setAlpha(self, percentage):
        self.opac_amount = percentage
        if platform.system() == "Darwin":
            self.attributes("-alpha", self.opac_amount / 100)
        elif platform.system() == "Windows":
            self.attributes("-alpha", self.opac_amount / 100)
        else:
            self.wm_attributes("-alpha", self.opac_amount / 100)

    def setTransparentBg(self, val):
        """Linux does not support this unless working under a native Win32 platform (ie. wine)"""
        try:
            self.trans_bg = val
            if self.theme == "Dark Mode":
                if self.trans_bg:
                    if platform.system() == "Darwin":
                        self.wm_attributes("-transparent", self.trans_bg)
                        self.config(bg='systemTransparent')
                    elif platform.system() == "Windows":
                        self.attributes('-transparentcolor', ArchitectTrackerGUI.bgBlack)
                    else:
                        ws = self.tk.call("tk", "windowingsystem")
                        if ws == "win32":
                            self.wm_attributes("-transparent", self.trans_bg)
                else:
                    if platform.system() == "Darwin":
                        self.wm_attributes("-transparent", self.trans_bg)
                        self.config(bg='white')
                    elif platform.system() == "Windows":
                        self.attributes('-transparentcolor', "red")
                    else:
                        ws = self.tk.call("tk", "windowingsystem")
                        if ws == "win32":
                            self.wm_attributes("-transparent", "red")
            elif self.theme == "Light Mode":
                if self.trans_bg:
                    if platform.system() == "Darwin":
                        self.wm_attributes("-transparent", self.trans_bg)
                        self.config(bg='systemTransparent')
                    elif platform.system() == "Windows":
                        self.attributes('-transparentcolor', '#d9d9d9')
                    else:
                        ws = self.tk.call("tk", "windowingsystem")
                        if ws == "win32":
                            self.wm_attributes("-transparent", '#d9d9d9')
                else:
                    if platform.system() == "Darwin":
                        self.wm_attributes("-transparent", self.trans_bg)
                        self.config(bg='white')
                    elif platform.system() == "Windows":
                        self.attributes('-transparentcolor', "red")
                    else:
                        ws = self.tk.call("tk", "windowingsystem")
                        if ws == "win32":
                            self.wm_attributes("-transparent", "red")
        except tk.TclError as e:
            logger.warning("Transparency not supported under this Linux version: %s", e)
    
    def auto_size_tree(self):
        """Adjust column widths to fit content."""
        style_font = self.style.lookup("ArchTrack.Treeview", "font")
        font = tkFont.Font(font=style_font)

        for col in self.tree["columns"]:
            max_width = 0
            if col != "#0":  # Exclude the tree column
                for item in self.tree.get_children():
                    text = self.tree.set(item, col)
                    width = font.measure(text) + 10
                    max_width = max(max_width, width)
                text = self.tree.heading(col, "text")
                width = font.measure(text) + 10
                max_width = max(max_width, width)
                # Add some padding
                self.tree.column(col, width=max_width)

        self.update_idletasks()

        """Adjust height to fit content."""
        num_items = 0
        if self.tree.get_children():
            num_items = len(self.tree.get_children())
        self.tree.configure(height=num_items)
        self.update_idletasks()

    # ttk themes are process wide, so switching to one for our own window also
    # restyles EDMC. Remember what EDMC was using and hand it back on the way out.
    edmc_theme = None

    def _use_theme(self, name):
        if ArchitectTrackerGUI.edmc_theme is None:
            ArchitectTrackerGUI.edmc_theme = self.style.theme_use()
        if name and self.style.theme_use() != name:
            self.style.theme_use(name)

    def _restore_edmc_theme(self):
        if not ArchitectTrackerGUI.edmc_theme:
            return
        try:
            style = ttk.Style()
            if style.theme_use() != ArchitectTrackerGUI.edmc_theme:
                style.theme_use(ArchitectTrackerGUI.edmc_theme)
        except tk.TclError as e:
            logger.warning("Could not restore the EDMC theme: %s", e)

    def palette(self):
        if self.theme == "Dark Mode":
            return {
                "bg": self.bgBlack, "fg": self.edOrange,
                "tree_bg": self.bgBlack, "tree_fg": self.edOrange,
                "sel_bg": self.bgBlack, "sel_fg": self.edBlue,
                "field": self.bgBlack,
            }
        #Light Mode borrows whatever the host theme uses so it looks native
        bg = self.style.lookup("TFrame", "background") or "#d9d9d9"
        fg = self.style.lookup("TLabel", "foreground") or "black"
        return {
            "bg": bg, "fg": fg,
            "tree_bg": self.style.lookup("Treeview", "background") or "#ffffff",
            "tree_fg": self.style.lookup("Treeview", "foreground") or fg,
            "sel_bg": self.style.lookup("Treeview", "background", ["selected"]) or "#4a6984",
            "sel_fg": self.style.lookup("Treeview", "foreground", ["selected"]) or "#ffffff",
            "field": self.style.lookup("TCombobox", "fieldbackground") or "#ffffff",
        }

    def setStyle(self):
        logger.info("setStyle theme is: %s", self.theme)

        self.style = ttk.Style(self)
        if self.theme == "Dark Mode":
            # The native Windows and macOS themes ignore background colours, so the
            # dark look needs clam. Light Mode puts EDMC's own theme back.
            self._use_theme("clam")
        else:
            self._restore_edmc_theme()

        c = self.palette()
        self.configure(bg=c["bg"])

        # Everything below is namespaced under ArchTrack so no other plugin, and
        # none of EDMC's own widgets, pick up these colours.
        self.style.configure("ArchTrack.TFrame", background=c["bg"])
        self.style.configure("ArchTrack.TLabel", background=c["bg"], foreground=c["fg"],
                             font=("TkDefaultFont", 11))
        self.style.configure("ArchTrack.TButton", background=c["bg"], foreground=c["fg"],
                             padding=(6, 2), font=("TkDefaultFont", 11))
        self.style.configure("ArchTrack.Treeview.Heading", background=c["bg"], foreground=c["fg"],
                             font=("TkDefaultFont", 11, "bold"))
        self.style.configure("ArchTrack.Treeview",
                             background=c["tree_bg"],
                             foreground=c["tree_fg"],
                             fieldbackground=c["tree_bg"],
                             font=("TkDefaultFont", 11),
                             rowheight=28,
                             selectbackground=c["sel_bg"])
        self.style.configure("ArchTrack.TCombobox",
                             background=c["bg"], foreground=c["fg"],
                             selectbackground=c["bg"], arrowcolor=c["fg"],
                             font=("TkDefaultFont", 11))
        self.style.map("ArchTrack.TButton",
                       foreground=[("disabled", c["bg"])],
                       background=[("disabled", "#7d7d7d")])
        self.style.map("ArchTrack.Treeview", foreground=[("selected", c["sel_fg"])])
        self.style.map("ArchTrack.TCombobox",
                       fieldbackground=[('readonly', c["field"])],
                       background=[('readonly', c["bg"])])

        if self.theme == "Dark Mode":
            #clam only, these options do not exist in the native themes
            self.style.configure("ArchTrack.Vertical.TScrollbar",
                                    gripcount=0,
                                    background=ArchitectTrackerGUI.bgBlack,  # Dark background for the scrollbar
                                    troughcolor=ArchitectTrackerGUI.bgBlack,  # Match trough to background
                                    lightcolor=ArchitectTrackerGUI.edOrange,
                                    darkcolor=ArchitectTrackerGUI.edOrange,
                                    sliderlength=20,  # Length of the slider
                                    sliderrelief="flat",
                                    thickness=12,  # Scrollbar thickness
                                    arrowcolor=ArchitectTrackerGUI.edOrange)  # Color for the arrows

    def destroy(self):
        self._restore_edmc_theme()
        super().destroy()

    def _build_info_widgets(self):
        self.has_table = False
        frame = ttk.Frame(self, padding=10, style="ArchTrack.TFrame")
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text="Construction site data not found!",
                  style="ArchTrack.TLabel").grid(row=0, column=0, sticky="nsew", padx=10)
        ttk.Label(frame,
                  text="Visit a construction site and the required commodities will automatically be displayed.",
                  style="ArchTrack.TLabel").grid(row=1, column=0, sticky="nsew", padx=10)
        self.update_idletasks()
        self.geometry(f"{self.winfo_reqwidth()}x{self.winfo_reqheight()}")

    def _build_widgets(self):
        self.has_table = True
        frame = ttk.Frame(self, padding=8, style="ArchTrack.TFrame")
        frame.pack(fill=tk.BOTH, expand=True)

        # Top controls (row 0)
        dropframe = ttk.Frame(frame, padding=8, style="ArchTrack.TFrame")
        dropframe.grid(row=0, column=0, sticky="nsew", padx=(0, 2))

        self.deleteStation = ttk.Button(dropframe, text="X", style="ArchTrack.TButton", width=1, command=self.on_delete_station)
        self.deleteStation.grid(row=0, column=0, sticky="w")
        Tooltip(self.deleteStation, "Delete the site currently shown.")

        self.station_var = tk.StringVar()
        self.station_var.trace_add("write", self._on_change_station_var)
        self.dropdown = ttk.Combobox(dropframe, textvariable=self.station_var, state="readonly", style="ArchTrack.TCombobox")
        self.dropdown.grid(row=0, column=1, sticky="w", padx=(0, 2))
        self.dropdown.bind("<<ComboboxSelected>>", lambda e: (self.refresh(), self.dropdown.after(1, self._clear_combo_selection)))

        self.changeToPrevStation = ttk.Button(dropframe, text="<", style="ArchTrack.TButton", width=1, command=self.on_prev_station)
        self.changeToPrevStation.grid(row=0, column=2, sticky="w")
        Tooltip(self.changeToPrevStation, "Change to the previous site.")

        self.changeStation = ttk.Button(dropframe, text=">", style="ArchTrack.TButton", width=1, command=self.on_next_station)
        self.changeStation.grid(row=0, column=3, sticky="w")
        Tooltip(self.changeStation, "Change to the next site.")

        marketframe = ttk.Frame(frame, padding=0, style="ArchTrack.TFrame")
        marketframe.grid(row=0, column=3, sticky="nsew", padx=(0, 2), pady=(0))

        self.togglePrefStation = ttk.Button(marketframe, text="$\\Ly\\Alt", style="ArchTrack.TButton", width=8, command=self.on_toggle_prefMarket)
        self.togglePrefStation.grid(row=0, column=0, sticky="w")
        Tooltip(self.togglePrefStation, "Switch between closest, cheapest\nand alternate markets.")

        self.toggleTypeStation = ttk.Button(marketframe, text="O\\S", style="ArchTrack.TButton", width=3, command=self.on_toggle_prefType)
        self.toggleTypeStation.grid(row=0, column=1, sticky="w")
        Tooltip(self.toggleTypeStation, "Prefer orbital or surface markets.")
        
        labelframe = ttk.Frame(marketframe)
        labelframe.grid(row=0, column=2, sticky="w")

        ttk.Label(labelframe, text="Preferred Market:", style="ArchTrack.TLabel", padding=0).pack(anchor="w", fill='x')
        self.market_name_label = ttk.Label(labelframe, text="", style="ArchTrack.TLabel", padding=0)
        self.market_name_label['text'] = "Holding text"
        self.market_name_label.pack(anchor="w", fill='x')

        carrierframe = ttk.Frame(frame, padding=8, style="ArchTrack.TFrame")
        carrierframe.grid(row=0, column=5, sticky="nsew", padx=(0, 2))

        self.canvas = tk.Canvas(carrierframe, width=25, height=25)
        self.canvas.grid(row=0, column=0, sticky="w")
        self.draw_canvas()

        ttk.Label(carrierframe, text="Carrier:", style="ArchTrack.TLabel").grid(row=0, column=1, sticky="e", padx=(0, 5))
        self.carrier_label = ttk.Label(carrierframe, text="", style="ArchTrack.TLabel")
        self.carrier_label.grid(row=0, column=2, sticky="w")

        # Treeview setup (row 1)
        cols = list(globals.DEFAULT_COLUMNS.keys())
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", style="ArchTrack.Treeview")
        for idx, c in enumerate(cols):
            self.tree.heading(c, text=self.column_names[idx],
                              command=lambda col=c: self.on_sort_column(col))
            self.tree.column(c, anchor='w' if c in ("Material", "Pref Market", "System") else 'center')
        self._refresh_sort_headings()

        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview, style="ArchTrack.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.grid(row=1, column=0, columnspan=7, sticky="nsew")
        scrollbar.grid(row=1, column=7, sticky="ns")

        # Ctrl/Shift+click a row to copy that preferred market's system name.
        self.tree.bind("<Control-Button-1>", self.on_copy_system_click)
        self.tree.bind("<Shift-Button-1>", self.on_copy_system_click)
        self._copy_feedback_after = None
        self._market_label_before_copy = None

        # Make row 1 expandable
        frame.rowconfigure(1, weight=1)
        for i in range(8):
            frame.columnconfigure(i, weight=1 if i < 7 else 0)

        self.refresh_columns()  # Ensure columns initial visibility

    def on_copy_system_click(self, event):
        """Ctrl+click or Shift+click copies the row's System value to the clipboard."""
        row = self.tree.identify_row(event.y)
        if not row:
            return
        system = self.tree.set(row, "System")
        if not system:
            return "break"
        try:
            self.clipboard_clear()
            self.clipboard_append(system)
            # Keep the selection available after the window loses focus (Tk quirk).
            self.update_idletasks()
        except tk.TclError as e:
            logger.error("Could not copy system name to the clipboard: %s", e)
            return "break"
        logger.info("Copied system name to clipboard: %s", system)
        self._flash_copied_system(system)
        return "break"

    def _flash_copied_system(self, system):
        """Briefly confirm the copy in the Preferred Market label."""
        if not getattr(self, "market_name_label", None):
            return
        try:
            if not self.market_name_label.winfo_exists():
                return
        except tk.TclError:
            return
        if self._copy_feedback_after is not None:
            try:
                self.after_cancel(self._copy_feedback_after)
            except (tk.TclError, ValueError):
                pass
            self._copy_feedback_after = None
        else:
            self._market_label_before_copy = self.market_name_label.cget("text")
        self.market_name_label.config(text=f"Copied: {system}")
        self._copy_feedback_after = self.after(2000, self._restore_market_label)

    def _restore_market_label(self):
        self._copy_feedback_after = None
        if self._market_label_before_copy is None:
            return
        try:
            if self.market_name_label.winfo_exists():
                self.market_name_label.config(text=self._market_label_before_copy)
        except tk.TclError:
            pass
        self._market_label_before_copy = None

    def draw_canvas(self):
        if self.theme == "Dark Mode":
            bg = self.style.lookup("ArchTrack.TButton", "background")
            fg = self.style.lookup("ArchTrack.TButton", "foreground")
            active_bg = self.style.lookup("ArchTrack.TButton", "background", state=("active",))
        else:
            bg = self.style.lookup("TButton", "background")
            fg = self.style.lookup("TButton", "foreground")
            active_bg = self.style.lookup("TButton", "background", state=("active",))

        # Clear canvas first
        self.canvas.delete("all")

        # Draw main rectangle
        self.rect_id = self.canvas.create_rectangle(
            0, 0, 25, 25,
            fill=bg,
            outline="black",
            tags="canvas_button"
        )

        # Draw play/pause symbol
        if globals.FCAPI_PAUSED:
            self.canvas.create_rectangle(7, 5, 12, 20, fill=fg, outline="black", tags="canvas_button")
            self.canvas.create_rectangle(15, 5, 20, 20, fill=fg, outline="black", tags="canvas_button")
            tooltip_text = "Press to UNpause\ncarrier updates."
        else:
            self.canvas.create_polygon(7, 5, 7, 20, 20, 13, fill=fg, outline="black", tags="canvas_button")
            tooltip_text = "Press to pause\ncarrier updates."

        # Attach tooltip to the canvas itself (not individual items). draw_canvas runs
        # on every refresh, so reuse it rather than binding another one each time.
        if self.canvas_tooltip:
            self.canvas_tooltip.set_text(tooltip_text)
        else:
            self.canvas_tooltip = Tooltip(self.canvas, tooltip_text, follow_mouse=True)

        # Bind hover for rectangle color
        self.canvas.tag_bind("canvas_button", "<Enter>", lambda e: self.canvas.itemconfig(self.rect_id, fill=active_bg))
        self.canvas.tag_bind("canvas_button", "<Leave>", lambda e: self.canvas.itemconfig(self.rect_id, fill=bg))

        # Bind click for canvas (anywhere)
        self.canvas.bind("<Button-1>", self.on_canvas_click)

    @property
    def shown_station(self):
        """Full name of the site on display, or None when showing -All-."""
        if not self.has_table:
            return None
        return self.station_map.get(self.station_var.get())

    def _on_change_station_var(self, *args):
        if self.station_var.get() == '-All-':
            self.deleteStation.config(state="disabled")
        else:
            self.deleteStation.config(state="enabled")

    def _on_canvas_hover(self, event, color):
        self.canvas.itemconfig("canvas_button", fill=color)
        
    def clear_frame(self):
        if getattr(self, "_copy_feedback_after", None) is not None:
            try:
                self.after_cancel(self._copy_feedback_after)
            except (tk.TclError, ValueError):
                pass
            self._copy_feedback_after = None
            self._market_label_before_copy = None
        for widget in self.winfo_children():
            widget.destroy()
        #the tooltip belongs to the canvas that just went with them
        self.canvas_tooltip = None

    def refresh(self):
        # Load new data
        data = helpers.load_facility_requirements()
        if data == {}:
            if self.has_table:
                self.clear_frame()
                self._build_info_widgets()
            globals.SITE_LOCATION = None
            return

        # The window is showing the "no sites yet" message and now has something to
        # show, so it needs the table building before anything can be put in it.
        if not self.has_table:
            self.clear_frame()
            self._build_widgets()

        # Remember the currently selected station name
        current_selection = self.station_var.get()
        self.data = data

        # Prepare data for display
        display = [
            (
              (full.split(':', 1)[-1].strip() if ':' in full else
               full.split(';', 1)[-1].strip() if ';' in full else full),
              full
            )
            for full in data
        ]
        #two sites can shorten to the same name, so keep the dropdown 1:1 with the data
        self.station_map = {}
        values = []
        for name, full in display:
            unique = name
            suffix = 2
            while unique in self.station_map:
                unique = f"{name} ({suffix})"
                suffix += 1
            self.station_map[unique] = full
            values.append(unique)
        self.station_map['-All-'] = None

        # Update dropdown
        if len(values) > 1:
            values.insert(0, '-All-')
        self.dropdown['values'] = values

        # Restore selection or default to first station
        if values:
            if current_selection in values:
                self.station_var.set(current_selection)
            else:
                self.station_var.set(values[0])

            # Refresh data for selected station
            self.display_station()
        else:
            # No data - clear tree
            self.tree.delete(*self.tree.get_children())

        #set preferred market label text
        mode = helpers.getPreferedMarket()
        if mode == globals.MARKET_MODE.Cheapest:
            t = 'cheapest ($)'
        elif mode == globals.MARKET_MODE.Closest:
            t = 'closest (Ly)'
        else:
            t = 'alternate (Alt)'
            
        t = t + " " + helpers.getPreferedType().name
        self.market_name_label['text'] = t
        
        # Set the carrier label
        self.carrier_label['text'] = globals.CARRIER_TRACKER.carrier_name or 'N/A'

        self.draw_canvas() #resets pause button

        self.update_idletasks()
        self.auto_size_tree()
        width = self.winfo_reqwidth()
        height = self.winfo_reqheight()
        '''
        #is this needed for VR?
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        if height > screen_height:
            height = screen_height
        '''
        self.geometry(f"{width}x{height}")

    def display_station(self):
        self.tree.delete(*self.tree.get_children())
        sel = self.station_var.get()

        if sel == '-All-':
            materials = {}
            for site in self.data.values():
                for material_key, info in site['materials'].items():
                    if material_key not in materials:
                        materials[material_key] = {
                            'Name_Localised': info['Name_Localised'],
                            'RequiredAmount': 0,
                            'ProvidedAmount': 0
                        }
                    materials[material_key]['RequiredAmount'] += info['RequiredAmount']
                    materials[material_key]['ProvidedAmount'] += info['ProvidedAmount']
        else:
            full = self.station_map.get(sel)
            if not full:
                return
            materials = self.data[full]['materials']

        cargo_counts = helpers.starship_cargo_counts()

        # Read these once for the whole table instead of once per row
        market_lib = helpers.get_market_library()
        legacy_lib = helpers.get_legacy_market_library()
        market_stock = (helpers.load_market_stock()
                        if globals.SHIP_STATE == globals.SHIP_MODE.DockedAtMarket else set())

        # Set the alternating row and highlight colours
        if self.theme == "Dark Mode":
            if self.trans_bg:
                self.tree.tag_configure('evenrow', background=self.bgBlack)
            else:
                self.tree.tag_configure('evenrow', background='#2a2a2a')
            self.tree.tag_configure('oddrow', background=self.bgBlack)
            self.tree.tag_configure('highlightedrow', foreground=self.edBlue)
        else:
            if self.trans_bg:
                self.tree.tag_configure('oddrow', background='#d9d9d9')
            else:
                self.tree.tag_configure('oddrow', background='#ffffff')
            self.tree.tag_configure('evenrow', background='#d9d9d9')
            self.tree.tag_configure('highlightedrow', foreground='#ff6347')

        self.tree.tag_configure('totalsrow', font=('TkDefaultFont', 11, 'bold'))

        req_total = 0
        prov_total = 0
        need_total = 0
        fc_total = 0
        ship_total = 0
        short_total = 0

        # Distance is from the site on screen only. -All- has no single origin, and
        # never fall back to another site's sticky SITE_LOCATION coords.
        if sel == '-All-':
            from_location = None
        else:
            from_location = self.data.get(full, {}).get("Location")
            if from_location:
                globals.SITE_LOCATION = from_location

        rows = []
        for mat, vals in materials.items():
            req = vals['RequiredAmount']
            prov = vals['ProvidedAmount']
            if self.hide_provided and prov >= req:
                continue
            safeMat = mat.replace("$", "").replace("_name;", "")
            locName = vals['Name_Localised']
            need = req - prov

            pref_market = helpers.get_prefMarket_name(mat, market_lib, legacy_lib)
            pref_system = helpers.get_prefMarket_system(mat, market_lib, legacy_lib)
            pref_distance = helpers.get_prefMarket_distance(
                mat, market_lib, legacy_lib, from_location=from_location)

            # Get fleet carrier and ship cargo quantities. Cargo.json still uses the
            # bare internal name, the carrier tracker normalises whatever it is given.
            fc_qty = globals.CARRIER_TRACKER.get_quantity(mat)
            ship_qty = cargo_counts.get(safeMat, 0)

            # Calculate shortage
            short = max(0, need - (fc_qty + ship_qty))

            tags = []
            if globals.SHIP_STATE == globals.SHIP_MODE.DockedAtMarket:
                for_sale = helpers.is_market_selling(mat, market_stock)
                if for_sale and short > 0:
                    tags.append('highlightedrow')
            elif globals.SHIP_STATE == globals.SHIP_MODE.DockedAtFC:
                if need > 0 and fc_qty > 0 and need > ship_qty:
                    tags.append('highlightedrow')
            elif globals.SHIP_STATE == globals.SHIP_MODE.DockedAtSite:
                if need > 0 and ship_qty > 0:
                    tags.append('highlightedrow')

            rows.append({
                "values": (locName, req, prov, need, pref_market, pref_system,
                           pref_distance, fc_qty, ship_qty, short),
                "tags": tags,
            })

            req_total = req_total + req
            prov_total = prov_total + prov
            need_total = need_total + need
            fc_total = fc_total + fc_qty
            ship_total = ship_total + ship_qty
            short_total = short_total + short

        rows = self._sorted_material_rows(rows)

        for idx, row in enumerate(rows):
            row_tag = 'evenrow' if idx % 2 == 0 else 'oddrow'
            tags = [row_tag] + list(row["tags"])
            self.tree.insert("", "end", values=row["values"], tags=tuple(tags))

        market_note = "* denotes orbital"
        if helpers.getPreferedType() == globals.STATION_TYPE.Orbital:
            market_note = "* denotes surface"

        total_row_tag = 'evenrow' if len(rows) % 2 == 0 else 'oddrow'
        tags = (total_row_tag, 'totalsrow')
        self.tree.insert("", "end", values=("Totals", req_total, prov_total, need_total,
                                               market_note, "", "",
                                               fc_total, ship_total, short_total), tags=tags)

    # Numeric columns sort as numbers; blank Distance sorts last either way.
    _NUMERIC_SORT_COLS = {
        "Required", "Provided", "Needed", "Distance",
        "Carrier Qty", "Ship Qty", "Shortfall",
    }

    def _sorted_material_rows(self, rows):
        col = getattr(self, "sort_column", "Material") or "Material"
        reverse = bool(getattr(self, "sort_reverse", False))
        cols = list(globals.DEFAULT_COLUMNS.keys())
        if col not in cols:
            col = "Material"
        col_idx = cols.index(col)

        def sort_key(row):
            value = row["values"][col_idx]
            if col in self._NUMERIC_SORT_COLS:
                if value in ("", None):
                    return float("inf") if not reverse else float("-inf")
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return float("inf") if not reverse else float("-inf")
            return str(value).lower()

        return sorted(rows, key=sort_key, reverse=reverse)

    def on_sort_column(self, col):
        """Toggle sort when a column header is clicked."""
        if not self.has_table:
            return
        if self.sort_column == col:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = col
            # First click on Shortfall (or other amounts) shows biggest first.
            self.sort_reverse = col in self._NUMERIC_SORT_COLS
        self._refresh_sort_headings()
        self.display_station()
        self.update_idletasks()
        self.auto_size_tree()

    def _refresh_sort_headings(self):
        if not self.has_table or not getattr(self, "tree", None):
            return
        cols = list(globals.DEFAULT_COLUMNS.keys())
        for idx, c in enumerate(cols):
            label = self.column_names[idx]
            if c == self.sort_column:
                label = f"{label} {'▼' if self.sort_reverse else '▲'}"
            self.tree.heading(c, text=label)

    def on_close(self):
        globals.AT_BUTTON.set("Show Architect Tracker (tracking disabled)")
        self.destroy()  # Close the window

    def on_canvas_click(self, event):
        globals.FCAPI_PAUSED = not globals.FCAPI_PAUSED
        if globals.FCAPI_PAUSED:
            logger.info('Fleet carrier API paused.')
        else:
            logger.info('Fleet carrier API UNpaused.')
        if self.has_table:
            self.draw_canvas()

    def on_next_station(self):
        if not self.has_table:
            return
        values = self.dropdown['values']
        if not values:
            logger.info("No stations to switch to.")
            return

        next_ndx = self.dropdown.current() + 1
        if next_ndx >= len(values):
            next_ndx = 0

        self.dropdown.current(next_ndx)
        self.dropdown.selection_clear()
        logger.info("Changing to station: %s", self.dropdown.get())
        self.refresh()

    def on_prev_station(self):
        if not self.has_table:
            return
        values = self.dropdown['values']
        if not values:
            logger.info("No stations to switch to.")
            return

        prev_ndx = self.dropdown.current() - 1
        if prev_ndx <= -1:
            prev_ndx = len(values) - 1

        self.dropdown.current(prev_ndx)
        self.dropdown.selection_clear()
        logger.info("Changing to station: %s", self.dropdown.get())
        self.refresh()

    def change_station(self, station):
        if not self.has_table:
            self.refresh()
            if not self.has_table:
                return

        def select_matching():
            # Prefer the exact full journal name so duplicate short names resolve.
            for display_name, full in self.station_map.items():
                if full == station:
                    self.station_var.set(display_name)
                    return True
            short_name = helpers.station_short_name(station)
            if short_name in self.station_map:
                self.station_var.set(short_name)
                return True
            return False

        if select_matching():
            self.display_station()
            return

        self.refresh()
        if select_matching():
            self.display_station()
            return
        logger.info("Could not change to station: %s", station)

    def on_delete_station(self):
        if not self.has_table:
            return
        sel = self.station_var.get()
        station_name = self.station_map.get(sel)
        if station_name and self.data.pop(station_name, None):
            logger.info("Deleted station: %s", station_name)
        else:
            logger.info("Could not delete station: %s", station_name)
            return

        try:
            with open(globals.SAVE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=4)
        except Exception as e:
            logger.error("Error saving data: %s", e)

        helpers.sync_site_location(self.data)
        self.refresh()

    def reset_Style(self, new_theme):
        self.theme = new_theme
        logger.info("reset_Style theme is: %s", self.theme)
        self.setStyle()
        self.refresh()

    def toggle_column(self, column, is_visible: bool):
        self.column_visibility[column] = is_visible
        self.refresh_columns()

    def toggle_hide_provided(self, val):
        self.hide_provided = val
        self.refresh()

    def refresh_columns(self):
        if not self.has_table:
            return
        visible_columns = [col for col, vis in self.column_visibility.items() if vis]
        self.tree["displaycolumns"] = visible_columns

    def on_toggle_prefMarket(self):
        old = helpers.getPreferedMarket()

        if old == globals.MARKET_MODE.Cheapest:
            config.set('ArchTrack_prefMarket', globals.MARKET_MODE.Closest.value)
        elif old == globals.MARKET_MODE.Closest:
            config.set('ArchTrack_prefMarket', globals.MARKET_MODE.Alternate.value)
        else:
            config.set('ArchTrack_prefMarket', globals.MARKET_MODE.Cheapest.value)
        self.refresh()
        
    def on_toggle_prefType(self):
        old = helpers.getPreferedType()
        if old == globals.STATION_TYPE.Orbital:            
            config.set('ArchTrack_prefType', globals.STATION_TYPE.Surface.value)
        else:
            config.set('ArchTrack_prefType', globals.STATION_TYPE.Orbital.value)
        self.refresh()

    def rename_column(self, c, v):
        cols = list(globals.DEFAULT_COLUMNS.keys())
        if c not in cols:
            return
        self.column_names[cols.index(c)] = v
        if self.has_table:
            self._refresh_sort_headings()
