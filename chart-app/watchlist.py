# watchlist.py
import tkinter as tk
from tkinter import ttk, messagebox
import pandas as pd
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class WatchListManager:
    def __init__(self, filepath="csv/watchlist.csv"):
        self.filepath = Path(filepath)
        self.data = {} # { 'GroupName': [ {'ticker': 'AAPL', 'name': 'Apple Inc'}, ... ] }
        self.load()

    def load(self):
        self.data = {}
        if not self.filepath.exists():
            return
            
        try:
            df = pd.read_csv(self.filepath)
            # Ensure columns exist
            if not all(col in df.columns for col in ['WatchList', 'Ticker', 'Name']):
                return
                
            # Group by WatchList
            for group_name, group_df in df.groupby('WatchList'):
                self.data[group_name] = []
                for _, row in group_df.iterrows():
                    self.data[group_name].append({
                        'ticker': str(row['Ticker']),
                        'name': str(row['Name'])
                    })
        except Exception as e:
            logger.error(f"Failed to load watchlist: {e}")

    def save(self):
        try:
            # Flatten data
            rows = []
            for group, items in self.data.items():
                for item in items:
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
        
        # Check duplicate in this group
        for item in self.data[group]:
            if item['ticker'] == ticker:
                return # Already exists
        
        self.data[group].append({'ticker': ticker, 'name': name})
        self.save()

    def get_groups(self):
        return sorted(self.data.keys())

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
        
        self.data[new_name] = self.data.pop(old_name)
        self.save()
        return True

    def delete_group(self, group_name):
        if group_name in self.data:
            del self.data[group_name]
            self.save()
            return True
        return False

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
        lbl_close = ttk.Label(header_frame, text="✖", font=('Arial', 10), cursor="hand2", foreground="#555")
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
            
        # Pre-select first if available (Optional, but helpful)
        if groups:
            lb.selection_set(0)
            
        def save():
            selected_indices = lb.curselection()
            if not selected_indices:
                return # Silent fail if nothing selected
            
            for idx in selected_indices:
                group = lb.get(idx)
                self.app.watchlist_manager.add_ticker(group, ticker, name)
                
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
        # Close overlapping popups (Add to Watchlist)
        if hasattr(self.app, 'watchlist_popup') and self.app.watchlist_popup.winfo_exists():
            self.app.watchlist_popup.destroy()
            
        # Close existing management if open
        if hasattr(self.app, 'manage_popup') and self.app.manage_popup.winfo_exists():
            self.app.manage_popup.destroy()
            return

        self.app.manage_popup = ttk.Frame(self.app.root, relief="raised", borderwidth=3)
        # Placement happens in _resize_management_overlay
        popup = self.app.manage_popup
        
        # Header
        header = ttk.Frame(popup)
        header.pack(fill="x", pady=5)
        self.manage_lbl_title = ttk.Label(header, text="Manage Watch Lists", font=('Arial', 12, 'bold'))
        self.manage_lbl_title.pack(side="left", padx=10)
        
        lbl_close = ttk.Label(header, text="✖", font=('Arial', 11), cursor="hand2", foreground="#555")
        lbl_close.pack(side="right", padx=10)
        lbl_close.bind("<Button-1>", lambda e: self.close_manage_popup())
        self.manage_lbl_close = lbl_close
        
        ttk.Separator(popup, orient="horizontal").pack(fill="x", pady=(0, 10))
        
        # Paned Window for 2 Columns
        self.manage_paned = tk.PanedWindow(popup, orient=tk.HORIZONTAL, bg="#f0f0f0")
        self.manage_paned.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        
        # --- LEFT PANEL (Groups) ---
        left_frame = ttk.Frame(self.manage_paned)
        self.manage_paned.add(left_frame, minsize=200)
        
        # 1. Bottom Controls (Rename & Delete)
        btn_box_left = ttk.Frame(left_frame)
        btn_box_left.pack(side="bottom", fill="x", pady=5)
        ttk.Button(btn_box_left, text="Rename", command=self._do_rename_group).pack(side="left", fill="x", expand=True, padx=(0, 2))
        ttk.Button(btn_box_left, text="Delete List", command=self._do_delete_group).pack(side="right", fill="x", expand=True, padx=(2, 0))

        rename_frame = ttk.Frame(left_frame)
        rename_frame.pack(side="bottom", fill="x", pady=(0, 5))
        self.rename_var = tk.StringVar()
        self.rename_entry = ttk.Entry(rename_frame, textvariable=self.rename_var)
        self.rename_entry.pack(fill="x")
        
        # 2. Top Label
        self.manage_lbl_groups = ttk.Label(left_frame, text="Watch Lists", font=('Arial', 10, 'bold'))
        self.manage_lbl_groups.pack(side="top", anchor="w", pady=5)
        
        # 3. Middle Listbox (Takes remaining space)
        self.group_listbox = tk.Listbox(left_frame, font=('Arial', 10), selectmode=tk.SINGLE, exportselection=False)
        self.group_listbox.pack(side="top", fill="both", expand=True)
        self.group_listbox.bind('<<ListboxSelect>>', self._on_group_select)
        

        # --- RIGHT PANEL (Tickers) ---
        right_frame = ttk.Frame(self.manage_paned, padding=(10, 0, 0, 0)) # Pad left
        self.manage_paned.add(right_frame, minsize=300)
        
        # 1. Bottom Controls (Remove)
        btn_box_right = ttk.Frame(right_frame)
        btn_box_right.pack(side="bottom", fill="x", pady=5)
        ttk.Button(btn_box_right, text="Remove Ticker", command=self._do_remove_ticker).pack(fill="x")
        
        # 2. Top Label
        self.ticker_lbl = ttk.Label(right_frame, text="Tickers", font=('Arial', 10, 'bold'))
        self.ticker_lbl.pack(side="top", anchor="w", pady=5)
        
        # 3. Middle Listbox with Scrollbars
        list_container = ttk.Frame(right_frame)
        list_container.pack(side="top", fill="both", expand=True)
        
        x_scroll = ttk.Scrollbar(list_container, orient="horizontal")
        y_scroll = ttk.Scrollbar(list_container, orient="vertical")
        
        self.ticker_listbox = tk.Listbox(list_container, font=('Arial', 10), selectmode=tk.SINGLE, exportselection=False,
                                         xscrollcommand=x_scroll.set, yscrollcommand=y_scroll.set)
        
        x_scroll.config(command=self.ticker_listbox.xview)
        y_scroll.config(command=self.ticker_listbox.yview)
        
        y_scroll.pack(side="right", fill="y")
        x_scroll.pack(side="bottom", fill="x")
        self.ticker_listbox.pack(side="left", fill="both", expand=True)

        # Load Initial Data
        self._refresh_group_list()
        
        # Initial Coloring/Sizing
        base_size = self.app.font_size_var.get()
        self.update_manage_overlay_font(base_size)
    
    def update_manage_overlay_font(self, size):
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
        
        self._resize_management_overlay()

    def _resize_management_overlay(self):
        if not hasattr(self.app, 'manage_popup') or not self.app.manage_popup.winfo_exists():
            return
            
        base_size = self.app.font_size_var.get()
        char_w = max(6, int(base_size * 0.7)) 
        
        # Calculate Group Width
        groups = self.app.watchlist_manager.get_groups()
        max_g_len = 0
        if groups:
            max_g_len = max([len(g) for g in groups])
        req_g_w = max(200, max_g_len * char_w + 50)
        
        # Calculate Ticker Width
        max_t_len = 0
        try:
            items = self.ticker_listbox.get(0, tk.END)
            if items:
                max_t_len = max([len(str(i)) for i in items])
        except: pass
            
        req_t_w = max(400, max_t_len * char_w + 50)
        
        total_w = req_g_w + req_t_w + 40 
        screen_w = self.app.root.winfo_width()
        total_w = min(screen_w - 50, total_w)
        
        total_h = max(500, 400 + (base_size * 15))
        screen_h = self.app.root.winfo_height()
        total_h = min(screen_h - 50, total_h)
        
        x = (screen_w - total_w) // 2
        y = (screen_h - total_h) // 2
        
        self.app.manage_popup.place(x=x, y=y, width=total_w, height=total_h)
        self.app.manage_popup.lift()
        
        try:
             self.manage_paned.sash_place(0, req_g_w, 0)
        except: pass

    def close_manage_popup(self):
        if hasattr(self.app, 'manage_popup'):
            self.app.manage_popup.destroy()
            self.app.refresh_watchlist_menu()
            self.app.update_star_state()

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
            
        self._resize_management_overlay()

    def _do_rename_group(self):
        sel = self.group_listbox.curselection()
        if not sel: return
        
        old_name = self.group_listbox.get(sel[0])
        new_name = self.rename_var.get().strip()
        
        if not new_name: return
        if old_name == new_name: return
        
        if self.app.watchlist_manager.rename_group(old_name, new_name):
            self._refresh_group_list()
            try:
                idx = self.group_listbox.get(0, tk.END).index(new_name)
                self.group_listbox.selection_set(idx)
                self.group_listbox.activate(idx)
                self.rename_var.set(new_name) 
            except: pass
        else:
             pass

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
        raw_text = self.ticker_listbox.get(ticker_sel[0])
        ticker = raw_text.split(" - ")[0]
        
        if self.app.watchlist_manager.remove_ticker(group, ticker):
            self._on_group_select(None)
