# app_stock_chart.py
import tkinter as tk
from tkinter import ttk, messagebox
import logging
import threading
import pandas as pd
import queue
import ctypes
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

from stock_util import (
    fetch_stock_data_with_cache, 
    get_interval_settings, 
    resample_data, 
    calculate_indicators, 
    cleanup_old_cache
)
from watchlist import WatchListManager, WatchListUI
from chart_drawing import ChartPlotter
from info_panel import InfoPanel

# Enable High DPI Awareness for Windows
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class StockChartApp:
    def __init__(self, root):
        self.root = root
        self.root.title("DIY - Interactive Stock Chart")
        self.root.state('zoomed') # Start maximized
        
        # Data storage
        self.current_ticker = ""
        self.history_df = pd.DataFrame()
        self.data_queue = queue.Queue()
        self.previous_close = 0.0 
        self.current_price = 0.0 
        
        self.raw_df = pd.DataFrame()
        self.current_data_interval = "1d"
        self.current_resample_rule = None
        
        # State variables for controls
        self.time_window_var = tk.StringVar(value="1Y")
        self.font_size_var = tk.IntVar(value=7) 
        
        # Indicator Vars
        self.show_ma5 = tk.BooleanVar(value=True)
        self.show_ma20 = tk.BooleanVar(value=True)
        self.show_ma50 = tk.BooleanVar(value=True) 
        self.show_ma60 = tk.BooleanVar(value=False) 
        self.show_ma100 = tk.BooleanVar(value=True)
        self.show_ma120 = tk.BooleanVar(value=False) 
        self.show_ma200 = tk.BooleanVar(value=True)
        self.show_volume = tk.BooleanVar(value=True)
        self.show_macd = tk.BooleanVar(value=True)
        self.show_rsi = tk.BooleanVar(value=True)
        self.show_bbards = tk.BooleanVar(value=True)
        self.show_vp = tk.BooleanVar(value=True)
        self.auto_refresh = tk.BooleanVar(value=True) 
        self.vp_mode_var = tk.StringVar(value="200 Bins") 
        self.vp_position = tk.StringVar(value="Right") 
        
        # Info Panel State
        self.show_legend = tk.BooleanVar(value=True)
        self.show_info = tk.BooleanVar(value=False) 
        self.stock_info = {} 
        self.info_frame = None # Will be set by InfoPanel
        
        # Initialize Logic Components
        self.watchlist_manager = WatchListManager()
        self.watchlist_ui = WatchListUI(self)
        
        # Setup UI (Created Figure/Canvas)
        self._setup_ui()
        
        # Initialize Plotter and InfoPanel
        self.plotter = ChartPlotter(self.fig, self.canvas, self)
        self.info_panel = InfoPanel(self) # Creates info_frame
        
        # Handle Closure
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.bind("<Destroy>", self.on_destroy)
        
        # Auto-start with SPY
        self.ticker_entry.insert(0, "SPY")
        self.fetch_data()
        
        # Polling for data
        self.root.after(100, self._process_queue)
        self.root.after(60000, self._auto_refresh_loop) 
        
        # Cleanup
        cleanup_old_cache()

    def _setup_ui(self):
        # Top Control Panel
        control_frame = ttk.Frame(self.root, padding="5")
        control_frame.pack(side=tk.TOP, fill=tk.X)
        self.control_frame = control_frame
        
        # Ticker Input
        ttk.Label(control_frame, text="Ticker:").pack(side=tk.LEFT, padx=5)
        self.ticker_entry = ttk.Entry(control_frame, width=10)
        self.ticker_entry.pack(side=tk.LEFT, padx=5)
        self.ticker_entry.bind('<Return>', self.fetch_data)
        self.go_btn = ttk.Button(control_frame, text="Go", command=self.fetch_data)
        self.go_btn.pack(side=tk.LEFT, padx=5)
        
        # Watch List Star
        self.star_btn = ttk.Button(control_frame, text="★", width=3, command=self.on_star_click)
        self.star_btn.pack(side=tk.LEFT, padx=2)
        
        # Watch List Dropdown
        self.watchlist_mb = ttk.Menubutton(control_frame, text="Watch List")
        self.watchlist_menu = tk.Menu(self.watchlist_mb, tearoff=0)
        self.watchlist_mb.config(menu=self.watchlist_menu)
        self.watchlist_mb.pack(side=tk.LEFT, padx=5)
        self.refresh_watchlist_menu()
        
        # Time Window Buttons
        ttk.Label(control_frame, text="| Time:").pack(side=tk.LEFT, padx=10)
        time_frame = ttk.Frame(control_frame)
        time_frame.pack(side=tk.LEFT, padx=5)
        windows = ["20Y", "10Y", "5Y", "3Y", "2Y", "1Y", "YTD", "6M", "3M", "1M", "1WK", "1D"]
        for w in windows:
            ttk.Radiobutton(time_frame, text=w, variable=self.time_window_var, value=w, command=self.on_window_change, style='Toolbutton').pack(side=tk.LEFT, padx=0)
            
        # Font Size Control
        ttk.Label(control_frame, text="| Font:").pack(side=tk.LEFT, padx=10)
        font_spin = ttk.Spinbox(control_frame, from_=4, to=24, textvariable=self.font_size_var, width=3, command=self.update_ui_font)
        font_spin.pack(side=tk.LEFT, padx=5)
        font_spin.bind('<KeyRelease>', lambda e: self.update_ui_font()) 
            
        # Indicators Checkboxes
        indicator_frame = ttk.Frame(self.root, padding="5")
        indicator_frame.pack(side=tk.TOP, fill=tk.X)
        
        # MA Dropdown Menu
        ma_btn = ttk.Menubutton(indicator_frame, text="Moving Avg")
        ma_menu = tk.Menu(ma_btn, tearoff=0)
        ma_menu.add_checkbutton(label="MA 5 (Cyn)", variable=self.show_ma5, command=self.update_chart)
        ma_menu.add_checkbutton(label="MA 20 (Grn)", variable=self.show_ma20, command=self.update_chart)
        ma_menu.add_checkbutton(label="MA 50 (Org)", variable=self.show_ma50, command=self.update_chart)
        ma_menu.add_checkbutton(label="MA 60 (Blue)", variable=self.show_ma60, command=self.update_chart)
        ma_menu.add_checkbutton(label="MA 100 (Pur)", variable=self.show_ma100, command=self.update_chart)
        ma_menu.add_checkbutton(label="MA 120 (Mag)", variable=self.show_ma120, command=self.update_chart)
        ma_menu.add_checkbutton(label="MA 200 (Red)", variable=self.show_ma200, command=self.update_chart)
        ma_btn.config(menu=ma_menu)
        ma_btn.pack(side=tk.LEFT, padx=5)
        
        ttk.Separator(indicator_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)
        
        ttk.Checkbutton(indicator_frame, text="Volume", variable=self.show_volume, command=self.update_chart).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(indicator_frame, text="MACD", variable=self.show_macd, command=self.update_chart).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(indicator_frame, text="RSI", variable=self.show_rsi, command=self.update_chart).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(indicator_frame, text="BBands", variable=self.show_bbards, command=self.update_chart).pack(side=tk.LEFT, padx=5)
        
        ttk.Separator(indicator_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)
        
        # VP Controls
        ttk.Checkbutton(indicator_frame, text="Vol Profile", variable=self.show_vp, command=self.update_chart).pack(side=tk.LEFT, padx=5)
        
        ttk.Label(indicator_frame, text="Pos:").pack(side=tk.LEFT, padx=2)
        vp_pos_cb = ttk.Combobox(indicator_frame, textvariable=self.vp_position, values=["Left", "Right"], width=5, state="readonly")
        vp_pos_cb.pack(side=tk.LEFT)
        vp_pos_cb.bind("<<ComboboxSelected>>", lambda e: self.update_chart())
        
        ttk.Label(indicator_frame, text="Res:").pack(side=tk.LEFT, padx=2)
        vp_mode_cb = ttk.Combobox(indicator_frame, textvariable=self.vp_mode_var, values=["100 Bins", "200 Bins", "400 Bins"], width=10, state="readonly")
        vp_mode_cb.pack(side=tk.LEFT)
        vp_mode_cb.bind("<<ComboboxSelected>>", lambda e: self.update_chart())
        
        # Info Toggle
        ttk.Checkbutton(indicator_frame, text="Legend", variable=self.show_legend, command=self.update_chart).pack(side=tk.RIGHT, padx=5)
        ttk.Checkbutton(indicator_frame, text="Show Info", variable=self.show_info, command=self.toggle_info_panel).pack(side=tk.RIGHT, padx=5)
        
        # Chart Area
        self.chart_frame = ttk.Frame(self.root)
        self.chart_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        
        self.fig = plt.figure(figsize=(10, 8))
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.chart_frame)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        
        # Toolbar
        toolbar = NavigationToolbar2Tk(self.canvas, self.chart_frame)
        toolbar.update()
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)

    def fetch_data(self, event=None, interval=None, silent=False):
        ticker = self.ticker_entry.get().upper().strip()
        if not ticker:
            return
        
        if interval is None or hasattr(interval, 'widget'):
             window = self.time_window_var.get()
             interval, rule = get_interval_settings(window)
             self.current_resample_rule = rule
        
        self.current_ticker = ticker
        self.root.title(f"Loading {ticker}...")
        
        if not silent:
            self.root.focus() 
            self.root.config(cursor="watch") 
            self.go_btn.config(state="disabled")
            self.ticker_entry.config(state="disabled")
            self.root.update_idletasks() 
        
        threading.Thread(target=self._download_worker_wrapper, args=(ticker, interval), daemon=True).start()

    def _download_worker_wrapper(self, ticker, interval):
        try:
            # Delegate to stock_util
            data = fetch_stock_data_with_cache(ticker, interval)
            # data is (df, company_name, interval, prev_close, curr_price, info_dict)
            self.data_queue.put(('data', data))
        except Exception as e:
            logger.error(f"Download thread error: {e}")
            self.data_queue.put(('error', str(e)))

    def _process_queue(self):
        try:
            while True:
                msg_type, content = self.data_queue.get_nowait()
                # Restore UI state
                self.root.config(cursor="")
                self.go_btn.config(state="normal")
                self.ticker_entry.config(state="normal")
                
                if msg_type == 'data':
                    df, company_name, interval, prev_close, curr_price, info_dict = content
                    if df is not None and not df.empty:
                        self.raw_df = df
                        self.current_data_interval = interval
                        self.company_name = company_name
                        self.previous_close = prev_close
                        self.current_price = curr_price
                        self.stock_info = info_dict or {}
                        
                        self.info_panel.update_content()
                        
                        self.root.title(f"DIY - Interactive Stock Chart - {company_name} ({self.current_ticker})")
                        
                        self.update_star_state()
                        
                        # Process Data (Resampling)
                        self._apply_resampling()
                    else:
                        messagebox.showwarning("No Data", f"No data found for {self.current_ticker}")
                        self.root.title("DIY - Interactive Stock Chart")
                elif msg_type == 'error':
                    messagebox.showerror("Error", content)
                    self.root.title("DIY - Interactive Stock Chart")
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._process_queue)

    def _apply_resampling(self):
        if self.raw_df.empty: return
        
        # Delegate to stock_util
        df = resample_data(self.raw_df, self.current_resample_rule)
        
        self.history_df = df
        calculate_indicators(self.history_df) # Modifies in place
        
        self.update_chart()
        self.toggle_info_panel()

    def update_chart(self, *args):
        if hasattr(self, 'plotter'):
            self.plotter.update_chart()

    def on_window_change(self):
        window = self.time_window_var.get()
        target_interval, resample_rule = get_interval_settings(window)
            
        self.current_resample_rule = resample_rule
        
        if target_interval != self.current_data_interval:
            self.fetch_data(interval=target_interval)
        else:
            self._apply_resampling()

    def _auto_refresh_loop(self):
        if self.auto_refresh.get() and self.current_ticker:
             try:
                 if self.time_window_var.get() == "1D":
                    logger.info(f"Auto-refreshing {self.current_ticker}...")
                    self.fetch_data(silent=True)
             except Exception:
                 pass
                 
        if hasattr(self, 'root') and self.root.winfo_exists():
            self.root.after(60000, self._auto_refresh_loop)

    def toggle_info_panel(self, event=None):
        if hasattr(self, 'info_panel'):
            self.info_panel.toggle()

    def update_ui_font(self):
        try:
            size = self.font_size_var.get()
            import tkinter.font as tkfont
            default_font = tkfont.nametofont("TkDefaultFont")
            default_font.configure(size=size)
            text_font = tkfont.nametofont("TkTextFont")
            text_font.configure(size=size)
            self.root.option_add("*Font", default_font)
            
            # Management Overlay
            if hasattr(self, 'watchlist_ui'):
                self.watchlist_ui.update_manage_overlay_font(size)
            
        except Exception as e:
            print(f"Font update error: {e}")

        self.update_chart()
        if hasattr(self, 'info_panel'):
            self.info_panel.update_content()

    def refresh_watchlist_menu(self):
        self.watchlist_menu.delete(0, tk.END)
        groups = self.watchlist_manager.get_groups()
        if not groups:
            self.watchlist_menu.add_command(label="(Empty)", state="disabled")
            return
            
        for group in groups:
            group_menu = tk.Menu(self.watchlist_menu, tearoff=0)
            self.watchlist_menu.add_cascade(label=group, menu=group_menu)
            
            items = self.watchlist_manager.get_items(group)
            for item in items:
                ticker = item['ticker']
                name = item['name']
                label = f"{ticker} - {name}"
                group_menu.add_command(label=label, command=lambda t=ticker: self.load_ticker_from_watchlist(t))
                
        self.watchlist_menu.add_separator()
        self.watchlist_menu.add_command(label="Manage Watch Lists...", command=self.open_manage_watchlist_overlay)

    def load_ticker_from_watchlist(self, ticker):
        self.ticker_entry.delete(0, tk.END)
        self.ticker_entry.insert(0, ticker)
        self.fetch_data()

    def update_star_state(self):
        ticker = self.current_ticker
        if not ticker:
            self.star_btn.config(text="☆")
            return
            
        if self.watchlist_manager.is_watched(ticker):
            self.star_btn.config(text="★") 
        else:
            self.star_btn.config(text="☆") 

    def on_star_click(self):
        ticker = self.current_ticker
        if not ticker: return
        
        if self.watchlist_manager.is_watched(ticker):
             if self.watchlist_manager.remove_ticker_entirely(ticker):
                 self.refresh_watchlist_menu()
                 self.update_star_state()
        else:
             self.watchlist_ui.open_add_to_watchlist_dialog()

    def open_manage_watchlist_overlay(self):
        self.watchlist_ui.open_manage_watchlist_overlay()

    def on_closing(self):
        try:
            self.root.quit()
            self.root.destroy()
        except:
            pass
        finally:
            import sys
            sys.exit(0)
            
    def on_destroy(self, event):
        if event.widget == self.root:
            import sys
            try:
                sys.exit(0)
            except: pass

if __name__ == "__main__":
    root = tk.Tk()
    app = StockChartApp(root)
    root.mainloop()
