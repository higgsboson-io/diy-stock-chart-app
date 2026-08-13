# app_stock_chart.py
import tkinter as tk
from tkinter import ttk, messagebox
import logging
import threading
import pandas as pd
import queue
import ctypes
import matplotlib.pyplot as plt
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
import json
import os

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
        self._maximize_window()  # Start maximized on Windows and Linux/WSL
        
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
        self.show_ma250 = tk.BooleanVar(value=True)
        self.show_volume = tk.BooleanVar(value=True)
        self.show_macd = tk.BooleanVar(value=True)
        self.show_rsi = tk.BooleanVar(value=True)
        self.show_bbards = tk.BooleanVar(value=True)
        self.show_vp = tk.BooleanVar(value=True)
        self.auto_refresh = tk.BooleanVar(value=True) 
        self.vp_mode_var = tk.StringVar(value="200 Bins") 
        self.vp_position = tk.StringVar(value="Right")
        self.chart_type_var = tk.StringVar(value="Candle")
        self.show_prepost = tk.BooleanVar(value=False) 
        
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
        # Auto-start with SPY
        self.ticker_entry.insert(0, "SPY")
        
        # Load Settings (Last, to override defaults)
        self.load_settings()
        
        self.fetch_data()
        
        # Polling for data
        self.root.after(100, self._process_queue)
        self.root.after(60000, self._auto_refresh_loop) 
        
        # Cleanup
        cleanup_old_cache()

    def _maximize_window(self):
        """Maximize the main window across Windows and Linux/WSL."""
        # Windows Tk supports wm state "zoomed".
        try:
            self.root.state("zoomed")
            return
        except tk.TclError:
            pass

        # Linux/X11 (including WSLg) commonly supports the -zoomed attribute.
        try:
            self.root.attributes("-zoomed", True)
            return
        except tk.TclError:
            pass

        # Fallback for window managers that support neither method.
        self.root.update_idletasks()
        width = self.root.winfo_screenwidth()
        height = self.root.winfo_screenheight()
        self.root.geometry(f"{width}x{height}+0+0")

    def load_settings(self):
        try:
            if not os.path.exists("conf/settings.json"): return
            
            with open("conf/settings.json", "r") as f:
                settings = json.load(f)
                
            # Boolean Vars
            self.show_ma5.set(settings.get("ma5", True))
            self.show_ma20.set(settings.get("ma20", True))
            self.show_ma50.set(settings.get("ma50", True))
            self.show_ma60.set(settings.get("ma60", False))
            self.show_ma100.set(settings.get("ma100", True))
            self.show_ma120.set(settings.get("ma120", False))
            self.show_ma200.set(settings.get("ma200", True))
            self.show_ma250.set(settings.get("ma250", True))
            
            self.show_volume.set(settings.get("volume", True))
            self.show_macd.set(settings.get("macd", True))
            self.show_rsi.set(settings.get("rsi", True))
            self.show_bbards.set(settings.get("bbands", True))
            self.show_vp.set(settings.get("vp", True))
            self.show_legend.set(settings.get("legend", True))
            self.show_info.set(settings.get("show_info", False))
            self.show_prepost.set(settings.get("show_prepost", False))
            
            # String/Int Vars
            self.time_window_var.set(settings.get("time_window", "1Y"))
            self.vp_mode_var.set(settings.get("vp_mode", "200 Bins"))
            self.vp_position.set(settings.get("vp_pos", "Right"))
            self.chart_type_var.set(settings.get("chart_type", "Candle"))
            
            # Font Size - Trigger Update
            saved_font = settings.get("font_size", 9)
            self.font_size_var.set(saved_font)
            self.update_ui_font() 
            
            logger.info("Settings loaded successfully.")
            
        except Exception as e:
            logger.error(f"Failed to load settings: {e}")

    def save_settings(self):
        try:
            settings = {
                "ma5": self.show_ma5.get(),
                "ma20": self.show_ma20.get(),
                "ma50": self.show_ma50.get(),
                "ma60": self.show_ma60.get(),
                "ma100": self.show_ma100.get(),
                "ma120": self.show_ma120.get(),
                "ma200": self.show_ma200.get(),
                "ma250": self.show_ma250.get(),
                "volume": self.show_volume.get(),
                "macd": self.show_macd.get(),
                "rsi": self.show_rsi.get(),
                "bbands": self.show_bbards.get(),
                "vp": self.show_vp.get(),
                "legend": self.show_legend.get(),
                "show_info": self.show_info.get(),
                "show_prepost": self.show_prepost.get(),
                "time_window": self.time_window_var.get(),
                "vp_mode": self.vp_mode_var.get(),
                "vp_pos": self.vp_position.get(),
                "chart_type": self.chart_type_var.get(),
                "font_size": self.font_size_var.get()
            }
            
            os.makedirs("conf", exist_ok=True)
            with open("conf/settings.json", "w") as f:
                json.dump(settings, f, indent=4)
                
            logger.info("Settings saved.")
        except Exception as e:
            logger.error(f"Failed to save settings: {e}")

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
        
        # MA Popup Button
        self.ma_btn = ttk.Button(indicator_frame, text="Moving Avg", command=self.open_ma_popup)
        self.ma_btn.pack(side=tk.LEFT, padx=5)
        
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
        
        # Chart Type Toggle
        ttk.Label(indicator_frame, text="| Type:").pack(side=tk.LEFT, padx=5)
        type_cb = ttk.Combobox(indicator_frame, textvariable=self.chart_type_var, values=["Candle", "Line"], width=8, state="readonly")
        type_cb.pack(side=tk.LEFT)
        type_cb.bind("<<ComboboxSelected>>", lambda e: self.update_chart())
        
        # Info Toggle
        ttk.Checkbutton(indicator_frame, text="Legend", variable=self.show_legend, command=self.update_chart).pack(side=tk.RIGHT, padx=5)
        ttk.Checkbutton(indicator_frame, text="Show Info", variable=self.show_info, command=self.toggle_info_panel).pack(side=tk.RIGHT, padx=5)
        self.prepost_check = ttk.Checkbutton(indicator_frame, text="Pre/Post", variable=self.show_prepost, command=self._apply_resampling)
        self.prepost_check.pack(side=tk.RIGHT, padx=5)
        
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
                        
                        # --- Inject Dynamic Data from DataFrame ---
                        # 1. Price
                        self.stock_info['currentPrice'] = curr_price
                        self.stock_info['regularMarketPrice'] = curr_price
                        self.stock_info['previousClose'] = prev_close
                        
                        # 2. Day Stats (High, Low, Volume, Open)
                        try:
                            if not df.empty:
                                last_dt = df.index[-1]
                                
                                # If Interval is '1d' (or larger), last row is the "Day"
                                if 'd' in self.current_data_interval.lower() or 'w' in self.current_data_interval.lower() or 'm' in self.current_data_interval.lower():
                                    row = df.iloc[-1]
                                    self.stock_info['dayHigh'] = row.get('high')
                                    self.stock_info['dayLow'] = row.get('low')
                                    # Volume might be int or float
                                    self.stock_info['volume'] = int(row.get('volume', 0))
                                    self.stock_info['open'] = row.get('open')
                                else:
                                    # Intraday: Aggregate data for the "Last Day" present in DF
                                    # Normalize to midnight to find the day
                                    last_day_acc = last_dt.normalize()
                                    today_data = df[df.index >= last_day_acc]
                                    
                                    if not today_data.empty:
                                        self.stock_info['dayHigh'] = today_data['high'].max()
                                        self.stock_info['dayLow'] = today_data['low'].min()
                                        self.stock_info['volume'] = int(today_data['volume'].sum())
                                        self.stock_info['open'] = today_data.iloc[0]['open']
                        except Exception as e:
                            logger.error(f"Failed to calculate dynamic stats: {e}")
                            
                        self.info_panel.update_content()
                        
                        self.root.title(f"DIY - Interactive Stock Chart - {company_name} ({self.current_ticker})")
                        
                        self.update_star_state()
                        
                        # UI Logic: Disable Pre/Post for Global Assets (Fixed Calendar View)
                        q_type = self.stock_info.get('quoteType', '').upper()
                        if q_type in ['CRYPTOCURRENCY', 'CURRENCY', 'FUTURE']:
                            self.show_prepost.set(False) # Force unchecked
                            self.prepost_check.state(['disabled'])
                        else:
                            self.prepost_check.state(['!disabled'])
                        
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
        
        # Pre/Post Market Filtering for 1-Day Chart
        # SKIP filtering for 24/7 assets (Crypto, Forex, Futures)
        q_type = self.stock_info.get('quoteType', '').upper()
        # Note: Futures have breaks but effectively are "Pre/Post" heavy. 
        # Treating them like Global Assets for now avoids the strict 9:30-16:00 cut.
        is_global_asset = q_type in ['CRYPTOCURRENCY', 'CURRENCY', 'FUTURE']
        
        # 1. Global Assets: STRICT Calendar Day View (00:00 - 23:59)
        # We forced show_prepost=False in UI logic, so we just enforce the filter here.
        if self.current_data_interval == '1m' and is_global_asset:
             if not df.empty and isinstance(df.index, pd.DatetimeIndex):
                 # Filter to keep ONLY records from the LATEST DATE in the dataset (Today)
                 # This mimics "Midnight to Midnight" relative to the data
                 latest_date = df.index.date[-1]
                 df = df[df.index.date == latest_date]

        # 2. Stocks: Pre/Post Market Filtering
        if self.current_data_interval == '1m' and not self.show_prepost.get() and not is_global_asset:
            if not df.empty:
                # Filter for 09:30 to 16:00 (Market Hours)
                # Ensure index is DatetimeIndex
                if isinstance(df.index, pd.DatetimeIndex):
                    # Localize if needed (assuming raw_df is TZ-aware from yfinance)
                    # Filter: keep if time >= 09:30 AND time < 16:00
                    # Using between_time is efficient
                    try:
                        filtered_df = df.between_time('09:30', '16:00').copy()
                        if not filtered_df.empty:
                            df = filtered_df
                        else:
                            # If filtering results in empty data (e.g. only pre-market exists so far),
                            # keep original or show empty properly.
                            # For now, let's just keep original with a warning or empty?
                            # Better: If regular market hasn't started, and we requested NO prepost,
                            # showing NOTHING is technically correct, but might crash plotter.
                            # Let's return empty, but handle it in plotter.
                            df = filtered_df 
                    except Exception as e:
                        logger.warning(f"Failed to filter market hours: {e}")

        # Safety Check
        if df.empty:
             logger.info("Dataframe empty after filtering logic.")
             # Clear logic?
             self.history_df = df 
             self.update_chart()
             return

        # -----------------------------------------------------------
        # GAP FILLING (Visual Smoothing)
        # -----------------------------------------------------------
        # If showing 1m data (intraday), fill gaps visually.
        # This keeps the CSV sparse (handled by stock_util) but makes the chart smooth.
        if self.current_data_interval == '1m' and not df.empty:
            try:
                # 1. Resample to 1min fixed grid
                # Use asfreq() to create NaNs for missing minutes
                df_resampled = df.resample('1min').asfreq()
                
                # 2. Forward Fill CLOSE Price (The reference price)
                # We propagate the LAST CLOSE to be the price for the gap.
                df_resampled['close'] = df_resampled['close'].ffill()
                
                # 3. Fill O/H/L/Adj with the Forward-Filled Close
                # This creates a "Flat Candle" (Doji) at the last price level.
                for col in ['open', 'high', 'low', 'adj close']:
                    if col in df_resampled.columns:
                        df_resampled[col] = df_resampled[col].fillna(df_resampled['close'])
                        
                # 4. Force Volume to 0 for filled rows
                # Logic: Fill remaining NaNs in volume with 0
                df_resampled['volume'] = df_resampled['volume'].fillna(0)
                
                df = df_resampled
            except Exception as e:
                logger.error(f"Gap filling failed: {e}")

        self.history_df = df
        self.history_df = calculate_indicators(self.history_df) # Now returns a copy
        
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
            
            # Global Relative Font Control
            # 1. Menus (Base + 1)
            menu_font = ('Arial', size + 1)
            self.root.option_add("*Menu.font", menu_font)
            self.root.option_add("*Menubutton.font", menu_font)
            
            # 2. Labels & Buttons (Explicitly set to ensure propagation)
            base_font = ('Arial', size)
            self.root.option_add("*Label.font", base_font)
            self.root.option_add("*Button.font", base_font)
            self.root.option_add("*TButton.font", base_font)
            self.root.option_add("*TLabel.font", base_font)
            self.root.option_add("*Listbox.font", base_font)
            
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

    def open_ma_popup(self):
        """Opens a custom popup for MA selection that stays open."""
        if hasattr(self, 'ma_popup') and self.ma_popup.winfo_exists():
            self.ma_popup.destroy()
            return

        # Create Toplevel
        self.ma_popup = tk.Toplevel(self.root)
        self.ma_popup.wm_overrideredirect(True) # Remove window decorations
        
        # Position it below the button
        x = self.ma_btn.winfo_rootx()
        y = self.ma_btn.winfo_rooty() + self.ma_btn.winfo_height()
        self.ma_popup.wm_geometry(f"+{x}+{y}")
        
        # Frame with border
        frame = tk.Frame(self.ma_popup, relief="raised", borderwidth=1, bg="white")
        frame.pack(fill="both", expand=True)

        # Text Font (Normal)
        base_size = self.font_size_var.get()
        text_font = ('Arial', base_size)
        
        # Checkbox Icon Font (Large)
        icon_font = ('Arial', max(14, base_size + 6))
        
        # Add Custom Checkboxes
        options = [
            ("MA 5 (Cyn)", self.show_ma5),
            ("MA 20 (Grn)", self.show_ma20),
            ("MA 50 (Org)", self.show_ma50),
            ("MA 60 (Blue)", self.show_ma60),
            ("MA 100 (Pur)", self.show_ma100),
            ("MA 120 (Mag)", self.show_ma120),
            ("MA 200 (Red)", self.show_ma200),
            ("MA 250 (Brn)", self.show_ma250),
        ]
        
        def toggle(var, icon_lbl):
            new_val = not var.get()
            var.set(new_val)
            icon_lbl.config(text="☑" if new_val else "☐")
            self.update_chart()

        for text, var in options:
            row = tk.Frame(frame, bg="white")
            row.pack(fill="x", padx=5, pady=2)
            
            # Icon
            icon_char = "☑" if var.get() else "☐"
            icon_lbl = tk.Label(row, text=icon_char, font=icon_font, bg="white", width=2, anchor="center")
            icon_lbl.pack(side="left")
            
            # Text
            text_lbl = tk.Label(row, text=text, font=text_font, bg="white", anchor="w")
            text_lbl.pack(side="left", fill="x", expand=True)
            
            # Bind Clicks
            # Use default args in lambda to capture current var/lbl
            row.bind("<Button-1>", lambda e, v=var, l=icon_lbl: toggle(v, l))
            icon_lbl.bind("<Button-1>", lambda e, v=var, l=icon_lbl: toggle(v, l))
            text_lbl.bind("<Button-1>", lambda e, v=var, l=icon_lbl: toggle(v, l))
            
        sep = ttk.Separator(frame, orient="horizontal")
        sep.pack(fill="x", pady=2)
        
        btn_close = ttk.Button(frame, text="Close", command=self.ma_popup.destroy)
        btn_close.pack(fill="x")

    def on_closing(self):
        try:
            self.save_settings()
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
