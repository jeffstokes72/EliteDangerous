import tkinter as tk
from tkinter import ttk

import globals
from globals import logger

class LogViewerGUI(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Log Viewer")
        self.build_gui()
        self.transient(parent)
        self.grab_set()
        self.after(100, self.focus_window)
        
    def focus_window(self):
        self.lift()
        self.focus_force()
        self.keyword_entry.focus_set()
        
    # Function to filter log entries
    def filter_logs(self):
        keyword = self.keyword_entry.get()
        level = self.level_var.get()
        
        self.log_display.delete(1.0, tk.END)  # Clear previous log entries
        
        try:
            #the log is written as UTF-8, so do not let the system encoding decide
            with open(globals.LOG_FILE, 'r', encoding='utf-8', errors='replace') as file:
                for line in file:
                    if keyword in line and (level == 'All' or level in line):
                        self.log_display.insert(tk.END, line)
        except Exception as e:
            logger.error("Error reading log file: %s", e)
        
    def copy_logs_to_clipboard(self):
        try:
            text = self.log_display.get("1.0", tk.END)
            self.clipboard_clear()
            self.clipboard_append(text)
            self.status_label.config(text="Copied to clipboard!")
            # keep clipboard after app/window closes
            self.update()
        except Exception as e:
            logger.error("Failed to copy log to clipboard: %s", e)
            self.status_label.config(text="Failed to copy log to clipboard!")

    def build_gui(self):
        # Create a Frame for filters
        filter_frame = ttk.LabelFrame(self, text="Filters")
        filter_frame.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        # Keyword filter
        keyword_label = ttk.Label(filter_frame, text="Keyword:")
        keyword_label.grid(row=0, column=0, padx=5, pady=5)
        self.keyword_entry = ttk.Entry(filter_frame)
        self.keyword_entry.grid(row=0, column=1, padx=5, pady=5)
        self.keyword_entry.bind('<KeyRelease>', lambda event=None: self.filter_logs())

        # Log level filter
        level_label = ttk.Label(filter_frame, text="Log Level:")
        level_label.grid(row=1, column=0, padx=5, pady=5)
        self.level_var = tk.StringVar()
        self.level_var.set('All')
        level_combobox = ttk.Combobox(filter_frame, textvariable=self.level_var, values=['All', 'INFO', 'WARNING', 'ERROR'])
        level_combobox.grid(row=1, column=1, padx=5, pady=5)
        level_combobox.bind('<<ComboboxSelected>>', lambda event=None: self.filter_logs())

        # Create a Text widget for displaying log entries
        self.log_display = tk.Text(self, wrap=tk.WORD)
        self.log_display.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        self.status_label = ttk.Label(self, text=f"Opened log: {globals.LOG_FILE}")
        self.status_label.pack()

        # Open log file button
        open_button = ttk.Button(
            self,
            text="Copy Log to Clipboard",
            command=self.copy_logs_to_clipboard
        )
        open_button.pack(padx=10, pady=5)
        self.filter_logs()
