# watchlist.py
import tkinter as tk
from tkinter import ttk, messagebox, font as tkfont, simpledialog
import pandas as pd
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class WatchListManager:
    def __init__(self, filepath="conf/watchlist.csv"):
        self.filepath = Path(filepath)
        self.data = {} # { 'GroupName': [ {'ticker': 'AAPL', 'name': 'Apple Inc'}, ... ] }
        self.load()

    def load(self):
        self.data = {}
        self._group_order = [] # Track insertion order for groups
        if not self.filepath.exists():
            return
            
        try:
            df = pd.read_csv(self.filepath)
            # Ensure columns exist
            if not all(col in df.columns for col in ['WatchList', 'Ticker', 'Name']):
                return
                
            # Iterate rows in order to preserve sequence
            for _, row in df.iterrows():
                group_name = str(row['WatchList'])
                if group_name not in self.data:
                    self.data[group_name] = []
                    self._group_order.append(group_name)
                self.data[group_name].append({
                    'ticker': str(row['Ticker']),
                    'name': str(row['Name'])
                })
        except Exception as e:
            logger.error(f"Failed to load watchlist: {e}")

    def create_group(self, group_name):
        """Creates a new empty watchlist group."""
        if group_name not in self.data:
            self.data[group_name] = []
            self._group_order.append(group_name)
            self.save()
            return True
        return False

    def save(self):
        try:
            # Flatten data in order
            rows = []
            for group in self._group_order:
                if group in self.data:
                    for item in self.data[group]:
                        rows.append({
                            'WatchList': group,
                            'Ticker': item['ticker'],
                            'Name': item['name']
                        })
            
            df = pd.DataFrame(rows)
            # Ensure Persistence directory exists
            self.filepath.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(self.filepath, index=False)
        except Exception as e:
             logger.error(f"Failed to save watchlist: {e}")

    def add_ticker(self, group, ticker, name):
        if group not in self.data:
            self.data[group] = []
            self._group_order.append(group)
        
        # Check duplicate in this group
        for item in self.data[group]:
            if item['ticker'] == ticker:
                return # Already exists
        
        self.data[group].append({'ticker': ticker, 'name': name})
        self.save()

    def update_ticker_name(self, group, ticker, new_name):
        """Updates the name of an existing ticker in a specific group."""
        if group not in self.data: return False
        
        changed = False
        for item in self.data[group]:
            if item['ticker'] == ticker:
                if item['name'] != new_name:
                    item['name'] = new_name
                    changed = True
                break
        
        if changed:
            self.save()
            return True
        return False

    def get_groups(self):
        # Return in user-defined order (not sorted)
        return list(self._group_order)

    def get_items(self, group):
        return self.data.get(group, [])

    def is_watched(self, ticker):
        for group, items in self.data.items():
            for item in items:
                if item['ticker'] == ticker:
                    return True
        return False

    def rename_group(self, old_name, new_name):
        if old_name not in self.data or new_name in self.data:
            return False # Fail if old doesn't exist or new already exists
        
        # Update data dict
        self.data[new_name] = self.data.pop(old_name)
        # Update order list
        idx = self._group_order.index(old_name)
        self._group_order[idx] = new_name
        self.save()
        return True

    def delete_group(self, group_name):
        if group_name in self.data:
            del self.data[group_name]
            self._group_order.remove(group_name)
            self.save()
            return True
        return False

    def move_group(self, group_name, delta):
        """Move a group up (delta=-1) or down (delta=+1) in the order."""
        if group_name not in self._group_order:
            return False
        idx = self._group_order.index(group_name)
        new_idx = idx + delta
        if new_idx < 0 or new_idx >= len(self._group_order):
            return False # Out of bounds
        # Swap
        self._group_order[idx], self._group_order[new_idx] = self._group_order[new_idx], self._group_order[idx]
        self.save()
        return True

    def move_ticker(self, group, ticker, delta):
        """Move a ticker up (delta=-1) or down (delta=+1) within its group."""
        if group not in self.data:
            return False
        items = self.data[group]
        idx = None
        for i, item in enumerate(items):
            if item['ticker'] == ticker:
                idx = i
                break
        if idx is None:
            return False
        new_idx = idx + delta
        if new_idx < 0 or new_idx >= len(items):
            return False # Out of bounds
        # Swap
        items[idx], items[new_idx] = items[new_idx], items[idx]
        self.save()
        return True

    def remove_ticker(self, group, ticker):
        if group in self.data:
            # Filter out the ticker
            initial_len = len(self.data[group])
            self.data[group] = [item for item in self.data[group] if item['ticker'] != ticker]
            if len(self.data[group]) < initial_len:
                self.save()
                return True
        return False

    def remove_ticker_entirely(self, ticker):
        """Removes the ticker from ALL watchlists. Returns True if removed from at least one."""
        removed_any = False
        for group in list(self.data.keys()):
            # We reuse remove_ticker which handles saving if changed
            if self.remove_ticker(group, ticker):
                removed_any = True
        return removed_any


class WatchListUI:
    def __init__(self, app_state):
        self.app = app_state
        # self.app needs to expose: 
        # root, watchlist_manager, current_ticker, company_name, font_size_var, star_btn, 
        # refresh_watchlist_menu(), update_star_state()

    def open_add_to_watchlist_dialog(self):
        # Close existing if open
        if hasattr(self.app, 'watchlist_popup') and self.app.watchlist_popup.winfo_exists():
            self.app.watchlist_popup.destroy()
            return

        ticker = self.app.current_ticker
        if not ticker: return
        
        # Get Current Company Name safely
        name = self.app.company_name if hasattr(self.app, 'company_name') else ticker
        
        # Font settings
        base_size = self.app.font_size_var.get()
        dlg_font_size = max(9, base_size + 1)
        font_style = ('Arial', dlg_font_size)
        font_bold = ('Arial', dlg_font_size, 'bold')
        
        # Create Overlay Frame (Child of Root) - Dynamic Size
        self.app.watchlist_popup = ttk.Frame(self.app.root, relief="raised", borderwidth=3)
        popup = self.app.watchlist_popup

        # --- Header ---
        header_frame = ttk.Frame(popup)
        header_frame.pack(fill="x", pady=5)
        
        ttk.Label(header_frame, text="Add to Watch List", font=font_bold).pack(side="left", padx=10)
        
        # Close 'X'
        lbl_close = ttk.Label(header_frame, text="\u2715", font=('Arial', 10), cursor="hand2", foreground="#555")
        lbl_close.pack(side="right", padx=10)
        lbl_close.bind("<Button-1>", lambda e: popup.destroy())
        
        ttk.Separator(popup, orient="horizontal").pack(fill="x", pady=(0, 10))

        # --- Content ---
        content_frame = ttk.Frame(popup, padding=15)
        content_frame.pack(fill="both", expand=True)
        
        ttk.Label(content_frame, text=f"Ticker: {ticker}", font=font_bold).pack(anchor="w")
        # Increase wrap length slightly to accomodate dynamic width preference
        ttk.Label(content_frame, text=f"{name}", font=font_style, wraplength=400).pack(anchor="w", pady=(0, 10))
        
        ttk.Label(content_frame, text="Select Lists (Multi-select):", font=font_style).pack(anchor="w")
        
        # Multi-Select Listbox
        groups = self.app.watchlist_manager.get_groups()
        lb = tk.Listbox(content_frame, selectmode=tk.MULTIPLE, height=5, font=font_style, exportselection=False)
        lb.pack(fill="x", pady=5)
        
        for g in groups:
            lb.insert(tk.END, g)
            
        # Pre-select first (Removed per user request)
        # if groups:
        #    lb.selection_set(0)

        new_grp_frame = ttk.Frame(content_frame)
        new_grp_frame.pack(fill="x", pady=(10, 0))
        
        ttk.Label(new_grp_frame, text="New List:", font=font_style).pack(side="left")
        new_list_var = tk.StringVar()
        ttk.Entry(new_grp_frame, textvariable=new_list_var, font=font_style).pack(side="left", fill="x", expand=True, padx=5)
            
        def save():
            # Check for new list creation
            new_list_name = new_list_var.get().strip()
            if new_list_name:
                # Create and Add to New List
                self.app.watchlist_manager.add_ticker(new_list_name, ticker, name)
            
            # Add to Selected Lists
            selected_indices = lb.curselection()
            if selected_indices:
                for idx in selected_indices:
                    group = lb.get(idx)
                    self.app.watchlist_manager.add_ticker(group, ticker, name)
            
            if not new_list_name and not selected_indices:
                 messagebox.showwarning("Select List", "Please select a Watch List or create a new one.")
                 return # Don't close popup
                
            self.app.refresh_watchlist_menu()
            self.app.update_star_state()
            popup.destroy()

        # Save Button Container
        btn_frame = ttk.Frame(content_frame)
        btn_frame.pack(fill="x", pady=20)
        
        ttk.Button(btn_frame, text="Save", command=save, width=15).pack(side="top")
        
        # --- Dynamic Placement ---
        popup.update_idletasks() # Compute size
        req_w = popup.winfo_reqwidth()
        req_h = popup.winfo_reqheight()
        
        try:
            # Get Button absolute coords
            root_x = self.app.root.winfo_rootx()
            root_y = self.app.root.winfo_rooty()
            btn_x = self.app.star_btn.winfo_rootx()
            btn_y = self.app.star_btn.winfo_rooty()
            btn_h = self.app.star_btn.winfo_height()
            
            # Position: x = button_x, y = button_bottom + margin
            pos_x = btn_x - root_x
            pos_y = (btn_y - root_y) + btn_h + 5
            
            # Safety check: Keep within window bounds
            win_w = self.app.root.winfo_width()
            if pos_x + req_w > win_w:
                pos_x = win_w - req_w - 10
            
            popup.place(x=pos_x, y=pos_y, width=req_w, height=req_h)
            popup.lift()
        except:
             # Fallback
             popup.place(relx=0.5, rely=0.3, anchor="center")

    def open_manage_watchlist_overlay(self):
        """Opens the Manage Watch Lists overlay with dynamic sizing and responsive layout."""
        # Close overlapping popups
        if hasattr(self.app, 'watchlist_popup') and self.app.watchlist_popup.winfo_exists():
            self.app.watchlist_popup.destroy()
        if hasattr(self.app, 'manage_popup') and self.app.manage_popup.winfo_exists():
            self.app.manage_popup.destroy()
            return

        # Create Overlay Frame
        self.app.manage_popup = ttk.Frame(self.app.root, relief="raised", borderwidth=3)
        popup = self.app.manage_popup
        
        # --- Header ---
        header = ttk.Frame(popup)
        header.pack(fill="x", pady=5)
        # Title with slightly larger font
        base_size = self.app.font_size_var.get()
        title_font = ('Arial', base_size + 2, 'bold')
        self.manage_lbl_title = ttk.Label(header, text="Manage Watch Lists", font=title_font)
        self.manage_lbl_title.pack(side="left", padx=10)
        
        # Close Button
        lbl_close = ttk.Label(header, text="\u2715", font=('Arial', base_size), cursor="hand2", foreground="#555")
        lbl_close.pack(side="right", padx=10)
        lbl_close.bind("<Button-1>", lambda e: self.close_manage_popup())
        self.manage_lbl_close = lbl_close
        
        ttk.Separator(popup, orient="horizontal").pack(fill="x", pady=(0, 10))
        
        # --- Content Panes ---
        self.manage_paned = tk.PanedWindow(popup, orient=tk.HORIZONTAL, bg="#f0f0f0", sashwidth=4, sashrelief="raised")
        self.manage_paned.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        
        # LEFT PANEL (Groups)
        # LEFT PANEL (Groups)
        left_frame = ttk.Frame(self.manage_paned)
        self.manage_paned.add(left_frame, minsize=280)
        
        # RIGHT PANEL (Tickers)
        right_frame = ttk.Frame(self.manage_paned, padding=(10, 0, 0, 0))
        self.manage_paned.add(right_frame)

        # Normal Font
        font_norm = ('Arial', base_size)

        # -- Left Panel Controls --
        # 1. Buttons (Icons) - Single Row
        btn_box_left = ttk.Frame(left_frame)
        btn_box_left.pack(side="bottom", fill="x", pady=5)
        
        # Unicode Icons: Pencil (Edit), Cross (Delete), Up, Down
        # Using robust Unicode escape sequences for Windows compatibility
        ttk.Button(btn_box_left, text="\u270E", width=3, command=self._do_rename_group).pack(side="left", fill="x", expand=True, padx=(0, 2))
        ttk.Button(btn_box_left, text="\u2716", width=3, command=self._do_delete_group).pack(side="left", fill="x", expand=True, padx=(2, 2))
        ttk.Button(btn_box_left, text="\u25B2", width=3, command=lambda: self._do_move_group(-1)).pack(side="left", fill="x", expand=True, padx=(2, 2))
        ttk.Button(btn_box_left, text="\u25BC", width=3, command=lambda: self._do_move_group(1)).pack(side="left", fill="x", expand=True, padx=(2, 0))
        
        # Rename Entry
        rename_frame = ttk.Frame(left_frame)
        rename_frame.pack(side="bottom", fill="x", pady=(0, 5))
        self.rename_var = tk.StringVar()
        self.rename_entry = ttk.Entry(rename_frame, textvariable=self.rename_var, font=font_norm)
        self.rename_entry.pack(fill="x")
        self.rename_entry.bind('<Return>', lambda e: self._do_rename_group())

        # Label
        self.manage_lbl_groups = ttk.Label(left_frame, text="Watch Lists", font=('Arial', base_size, 'bold'))
        self.manage_lbl_groups.pack(side="top", anchor="w", pady=5)

        # Listbox
        self.group_listbox = tk.Listbox(left_frame, font=font_norm, selectmode=tk.SINGLE, exportselection=False)
        self.group_listbox.pack(side="top", fill="both", expand=True)
        self.group_listbox.bind('<<ListboxSelect>>', self._on_group_select)

        # -- Right Panel Controls --
        # 1. Buttons (Icons)
        btn_box_right = ttk.Frame(right_frame)
        btn_box_right.pack(side="bottom", fill="x", pady=5)
        
        ttk.Button(btn_box_right, text="+", width=3, command=self._do_add_ticker).pack(side="left", fill="x", expand=True, padx=(0, 2))
        ttk.Button(btn_box_right, text="x", width=3, command=self._do_remove_ticker).pack(side="left", fill="x", expand=True, padx=(0, 2))
        ttk.Button(btn_box_right, text="\u25B2", width=3, command=lambda: self._do_move_ticker(-1)).pack(side="left", padx=(2, 0))
        ttk.Button(btn_box_right, text="\u25BC", width=3, command=lambda: self._do_move_ticker(1)).pack(side="left", padx=(2, 0))

        # Label
        self.ticker_lbl = ttk.Label(right_frame, text="Tickers", font=('Arial', base_size, 'bold'))
        self.ticker_lbl.pack(side="top", anchor="w", pady=5)

        # Listbox
        list_container = ttk.Frame(right_frame)
        list_container.pack(side="top", fill="both", expand=True)
        x_scroll = ttk.Scrollbar(list_container, orient="horizontal")
        y_scroll = ttk.Scrollbar(list_container, orient="vertical")
        self.ticker_listbox = tk.Listbox(list_container, font=font_norm, selectmode=tk.SINGLE, exportselection=False,
                                         xscrollcommand=x_scroll.set, yscrollcommand=y_scroll.set)
        x_scroll.config(command=self.ticker_listbox.xview)
        y_scroll.config(command=self.ticker_listbox.yview)
        y_scroll.pack(side="right", fill="y")
        x_scroll.pack(side="bottom", fill="x")
        self.ticker_listbox.pack(side="left", fill="both", expand=True)

        # Initial Load
        self._refresh_group_list()
        
        # Initial Geometry Calculation and Binding
        self._update_overlay_geometry()
        
        # Bind to root resize to update height dynamically
        self.resize_binding = self.app.root.bind("<Configure>", self._on_root_configure, add="+")
        
    def _on_root_configure(self, event):
        # Only react if the event is from the root window itself, not children
        if event.widget == self.app.root:
            self._update_overlay_geometry(only_height=True)

    def update_manage_overlay_font(self, size):
        """Called when main app font size changes."""
        if not hasattr(self.app, 'manage_popup') or not self.app.manage_popup.winfo_exists():
            return
            
        font_norm = ('Arial', size)
        font_bold = ('Arial', size, 'bold')
        font_title = ('Arial', size + 2, 'bold')
        
        self.manage_lbl_title.config(font=font_title)
        self.manage_lbl_close.config(font=font_norm)
        self.manage_lbl_groups.config(font=font_bold)
        self.ticker_lbl.config(font=font_bold)
        self.group_listbox.config(font=font_norm)
        self.ticker_listbox.config(font=font_norm)
        self.rename_entry.config(font=font_norm)
        
        # Re-calculate geometry with new font metrics
        self._update_overlay_geometry()

    def _update_overlay_geometry(self, only_height=False):
        """Calculates and applies size based on content and window size."""
        if not hasattr(self.app, 'manage_popup') or not self.app.manage_popup.winfo_exists():
            return

        screen_w = self.app.root.winfo_width()
        screen_h = self.app.root.winfo_height()
        base_size = self.app.font_size_var.get()
        
        # --- Height Calculation ---
        # "Make the height half of the whole window height"
        total_h = int(screen_h * 0.5)
        total_h = max(300, total_h) # Minimum height

        if only_height:
            # Just update height and y position
            current_w = self.app.manage_popup.winfo_width()
            x = self.app.manage_popup.winfo_x() # Keep X
            y = (screen_h - total_h) // 2
            self.app.manage_popup.place(x=x, y=y, height=total_h)
            return

        # --- Width Calculation (Content-Based) ---
        list_font = tkfont.Font(family='Arial', size=base_size)
        btn_font = tkfont.Font(family='TkDefaultFont', size=base_size) # Buttons use default
        
        # 1. Left Panel Width (Groups)
        # Max of: Longest Group Name OR Button Row
        groups = self.app.watchlist_manager.get_groups()
        max_group_w = 100
        if groups:
            for g in groups:
                 w = list_font.measure(g)
                 if w > max_group_w: max_group_w = w
        
        # Button Row: [Edit][Del][Up][Down] - 4 buttons
        # Assuming avg button width + padding. 
        # width=3 roughly 3 chars. 
        button_w = 4 # roughly 4 chars per button
        # 4 buttons * (text_width + internal_padding) + gaps
        # A safe estimation for 4 small icon buttons is ~250-300px at normal sizes
        btn_row_w = 280 # Minimum adequate space for 4 buttons including padding
        
        req_g_w = max(max_group_w + 50, btn_row_w) # +50 for scroll/pad

        # 2. Right Panel Width (Tickers)
        # Scan ALL groupings for the widest ticker line
        max_ticker_w = 200
        if groups:
            for g in groups:
                items = self.app.watchlist_manager.get_items(g)
                for item in items:
                    txt = f"{item['ticker']} - {item['name']}"
                    w = list_font.measure(txt)
                    if w > max_ticker_w: max_ticker_w = w
        
        req_t_w = max_ticker_w + 60 # +60 for scroll/pad

        # Total Width
        total_w = req_g_w + req_t_w + 50 # +50 for sash/margins
        total_w = min(screen_w - 50, total_w) # Cap at screen width
        total_w = max(total_w, 400) # Absolute minimum

        x = (screen_w - total_w) // 2
        y = (screen_h - total_h) // 2

        self.app.manage_popup.place(x=x, y=y, width=total_w, height=total_h)
        self.app.manage_popup.lift()
        
        # Set Sash Position
        try:
            # We need to wait for idle to ensure geometry is known for sash logic
            # or just try setting it directly if the widget is mapped.
            self.manage_paned.update_idletasks()
            self.manage_paned.sash_place(0, req_g_w, 0)
        except: pass

    def close_manage_popup(self):
        if hasattr(self, 'resize_binding'):
             try:
                 self.app.root.unbind("<Configure>", self.resize_binding)
             except: pass
             
        if hasattr(self.app, 'manage_popup'):
            self.app.manage_popup.destroy()
            self.app.refresh_watchlist_menu()
            self.app.update_star_state()
            
            # Refresh Table View if active
            # if hasattr(self.app, 'table_view') and self.app.table_view.winfo_viewable():
            #    self.app.table_view.load_watch_lists() # Sync dropdown
            #    self.app.table_view.refresh_current_list() # Sync content

    def _refresh_group_list(self):
        self.group_listbox.delete(0, tk.END)
        groups = self.app.watchlist_manager.get_groups()
        for g in groups:
            self.group_listbox.insert(tk.END, g)
            

    def _on_group_select(self, event):
        sel = self.group_listbox.curselection()
        if not sel: return
        
        group = self.group_listbox.get(sel[0])
        self.rename_var.set(group)
        self.ticker_lbl.config(text=f"Tickers in '{group}'")
        
        self.ticker_listbox.delete(0, tk.END)
        items = self.app.watchlist_manager.get_items(group)
        for item in items:
            self.ticker_listbox.insert(tk.END, f"{item['ticker']} - {item['name']}")

    def _do_rename_group(self):
        sel = self.group_listbox.curselection()
        if not sel: return
        
        old_name = self.group_listbox.get(sel[0])
        new_name = self.rename_var.get().strip()
        
        if not new_name: return
        if old_name == new_name: 
            # UX Improvement: If clicked without changes, focus the entry
            self.rename_entry.focus_set()
            self.rename_entry.select_range(0, tk.END)
            return
        
        if self.app.watchlist_manager.rename_group(old_name, new_name):
            self._refresh_group_list()
            try:
                idx = self.group_listbox.get(0, tk.END).index(new_name)
                self.group_listbox.selection_set(idx)
                self.group_listbox.activate(idx)
                self.rename_var.set(new_name) 
            except: pass

    def _do_delete_group(self):
        sel = self.group_listbox.curselection()
        if not sel: return
        group = self.group_listbox.get(sel[0])

        if messagebox.askyesno("Confirm", f"Delete list '{group}'?"):
             self.app.watchlist_manager.delete_group(group)
             self._refresh_group_list()
             self.ticker_listbox.delete(0, tk.END)
             self.rename_var.set("")
             self.ticker_lbl.config(text="Tickers")

    def _do_remove_ticker(self):
        group_sel = self.group_listbox.curselection()
        ticker_sel = self.ticker_listbox.curselection()
        
        if not group_sel or not ticker_sel: return
        
        group = self.group_listbox.get(group_sel[0])
        idx = ticker_sel[0]
        # Text is "TICKER - Name"
        raw_text = self.ticker_listbox.get(idx)
        ticker = raw_text.split(" - ")[0]
        
        if self.app.watchlist_manager.remove_ticker(group, ticker):
            self.ticker_listbox.delete(idx)
            
    def _do_add_ticker(self):
        """Prompt to add a new ticker to the selected group."""
        sel = self.group_listbox.curselection()
        if not sel:
            messagebox.showinfo("Info", "Please select a Watch List first.")
            return

        group = self.group_listbox.get(sel[0])
        
        ticker_input = simpledialog.askstring("Add Ticker", f"Enter ticker symbol to add to '{group}':", parent=self.app.manage_popup)
        
        if ticker_input:
            ticker = ticker_input.upper().strip()
            if ticker:
                # Fetch Company Name
                name = ticker
                # Fetch Company Name
                name = ticker
                try:
                    import stock_util
                    fetched_name = stock_util.get_ticker_name(ticker)
                    if fetched_name:
                         name = fetched_name
                except Exception as e:
                    logger.error(f"Failed to fetch name for {ticker}: {e}")

                # Add to manager with real name
                self.app.watchlist_manager.add_ticker(group, ticker, name)
                
                # Refresh Ticker List
                self.ticker_listbox.insert(tk.END, f"{ticker} - {name}")
                self.ticker_listbox.see(tk.END)

    def _do_move_group(self, delta):
        """Move selected group up (-1) or down (+1)."""
        sel = self.group_listbox.curselection()
        if not sel: return
        
        group = self.group_listbox.get(sel[0])
        if self.app.watchlist_manager.move_group(group, delta):
            new_idx = sel[0] + delta
            self._refresh_group_list()
            # Re-select the moved item
            self.group_listbox.selection_set(new_idx)
            self.group_listbox.activate(new_idx)
            self.group_listbox.see(new_idx)

    def _do_move_ticker(self, delta):
        """Move selected ticker up (-1) or down (+1) within its group."""
        group_sel = self.group_listbox.curselection()
        ticker_sel = self.ticker_listbox.curselection()
        
        if not group_sel or not ticker_sel: return
        
        group = self.group_listbox.get(group_sel[0])
        raw_text = self.ticker_listbox.get(ticker_sel[0])
        ticker = raw_text.split(" - ")[0]
        
        if self.app.watchlist_manager.move_ticker(group, ticker, delta):
            new_idx = ticker_sel[0] + delta
            self._on_group_select(None) # Refresh ticker list
            # Re-select the moved item
            self.ticker_listbox.selection_set(new_idx)
            self.ticker_listbox.activate(new_idx)
            self.ticker_listbox.see(new_idx)
