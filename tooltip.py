import tkinter as tk

# --- Tooltip class ---
class Tooltip:
    def __init__(self, widget, text, delay=400, follow_mouse=False):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.follow_mouse = follow_mouse

        self.tooltip = None
        self.after_id = None

        self.widget.bind("<Enter>", self._on_enter, add="+")
        self.widget.bind("<Leave>", self._on_leave, add="+")
        self.widget.bind("<ButtonPress>", self._on_leave, add="+")

        if follow_mouse:
            self.widget.bind("<Motion>", self._on_motion, add="+")

    # --------------------

    def _on_enter(self, event=None):
        self._schedule()

    def _on_leave(self, event=None):
        self._unschedule()
        self._hide()

    def _on_motion(self, event):
        if self.tooltip:
            self._position(event)

    # --------------------

    def _schedule(self):
        self._unschedule()
        self.after_id = self.widget.after(self.delay, self._show)

    def _unschedule(self):
        if self.after_id:
            self.widget.after_cancel(self.after_id)
            self.after_id = None

    # --------------------

    def _show(self):
        if self.tooltip:
            return

        root = self.widget.winfo_toplevel()

        self.tooltip = tk.Frame(
            root,
            bg="#FFFFEA",
            highlightbackground="black",
            highlightthickness=1,
            bd=0
        )

        label = tk.Label(
            self.tooltip,
            text=self.text,
            bg="#FFFFEA",
            justify="left",
            wraplength=250
        )
        label.pack(ipadx=6, ipady=4)

        self._position()

        # Force above everything in this window
        self.tooltip.lift()

    def _position(self, event=None):
        root = self.widget.winfo_toplevel()

        if event:
            x = event.x_root + 15
            y = event.y_root + 15
        else:
            x, y = self.widget.winfo_pointerxy()
            x += 15
            y += 15

        # Convert screen coords to root coords
        rx = root.winfo_rootx()
        ry = root.winfo_rooty()

        x -= rx
        y -= ry

        self.tooltip.place(x=x, y=y)

    def _hide(self):
        if self.tooltip:
            self.tooltip.destroy()
            self.tooltip = None
