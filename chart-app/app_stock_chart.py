import tkinter as tk
from tkinter import ttk, messagebox
import logging
import threading
import pandas as pd
import numpy as np
import yfinance as yf
from finta import TA
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
import matplotlib.dates as mdates
from stock_util import get_stock_history
from datetime import datetime, timedelta
import queue
import ctypes
from pathlib import Path
import glob

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
        # self.root.geometry("1400x900")
        
        # Data storage
        self.current_ticker = ""
        self.history_df = pd.DataFrame()
        self.data_queue = queue.Queue()
        self.previous_close = 0.0 
        self.current_price = 0.0 # Store metadata price for Title accuracy

        
        # State variables for controls
        self.time_window_var = tk.StringVar(value="1Y")
        self.font_size_var = tk.IntVar(value=7) # Default font size
        
        self.raw_df = pd.DataFrame()
        self.current_data_interval = "1d"
        self.current_resample_rule = None
        
        # Indicator Vars
        self.show_ma5 = tk.BooleanVar(value=True)
        self.show_ma20 = tk.BooleanVar(value=True)
        self.show_ma50 = tk.BooleanVar(value=True) # Checked
        self.show_ma60 = tk.BooleanVar(value=False) # Unchecked
        self.show_ma100 = tk.BooleanVar(value=True)
        self.show_ma120 = tk.BooleanVar(value=False) # Unchecked
        self.show_ma200 = tk.BooleanVar(value=True)
        self.show_volume = tk.BooleanVar(value=True)
        self.show_macd = tk.BooleanVar(value=True)
        self.show_rsi = tk.BooleanVar(value=True)
        self.show_bbards = tk.BooleanVar(value=True)
        self.show_vp = tk.BooleanVar(value=True)
        self.auto_refresh = tk.BooleanVar(value=True) # Auto-refresh toggle
        self.vp_mode_var = tk.StringVar(value="100 Bins") # VP Mode
        self.vp_position = tk.StringVar(value="Right") # Left or Right
        # Info Panel State
        self.show_info = tk.BooleanVar(value=False) # Info Panel Toggle
        self.stock_info = {} # Store fetched metadata
        
        # Default Position (None = Centered on first show)
        self.panel_x = None
        self.panel_y = None
        
        # Crosshair refs
        
        # Crosshair refs
        self.crosshair_lines = {}
        self.crosshair_texts = {}
        self.is_dragging = False # Track mouse button state

        # Setup UI
        self._setup_ui()
        
        # Handle Closure
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.bind("<Destroy>", self.on_destroy)
        
        # Auto-start with SPY
        self.ticker_entry.insert(0, "SPY")
        self.fetch_data()
        
        # Polling for data
        self.root.after(100, self._process_queue)
        self.root.after(60000, self._auto_refresh_loop) # Start refresh loop
        
        # Cleanup old cache files on startup
        self._cleanup_old_cache()

    def _cleanup_old_cache(self):
        """Removes CSV files in the cache directory older than 7 days."""
        try:
             csv_dir = Path("csv")
             if not csv_dir.exists():
                 return
                 
             now = datetime.now()
             cutoff = now - timedelta(days=7)
             
             count = 0
             for csv_file in csv_dir.glob("*.csv"):
                 try:
                     mtime = datetime.fromtimestamp(csv_file.stat().st_mtime)
                     if mtime < cutoff:
                         csv_file.unlink()
                         count += 1
                 except Exception as e:
                     logger.warning(f"Failed to delete old cache file {csv_file}: {e}")
                     
             if count > 0:
                 logger.info(f"Cleaned up {count} old cache files.")
        except Exception as e:
             logger.error(f"Error during cache cleanup: {e}")

    def fetch_data(self, event=None, interval=None, silent=False):
        ticker = self.ticker_entry.get().upper().strip()
        if not ticker:
            return
        
        # Handle Event object (from bind) or missing arg
        if interval is None or hasattr(interval, 'widget'):
             window = self.time_window_var.get()
             interval, rule = self._get_interval_settings(window)
             self.current_resample_rule = rule
        
        self.current_ticker = ticker
        self.root.title(f"Loading {ticker}...")
        
        # Lock UI immediately (unless silent refresh)
        if not silent:
            self.root.focus() # Remove focus from entry
            self.root.config(cursor="watch") # Loading cursor
            self.go_btn.config(state="disabled")
            self.ticker_entry.config(state="disabled")
            self.root.update_idletasks() # Force UI update
        
        # Start background thread
        threading.Thread(target=self._download_worker, args=(ticker, interval), daemon=True).start()

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
                        self.update_info_panel()
                        
                        self.root.title(f"DIY - Interactive Stock Chart - {company_name} ({self.current_ticker})")
                        
                        # Initial Process based on current window
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

    def _auto_refresh_loop(self):
        # Refresh only if enabled, ticker exists, and strictly in 1D view (1m interval)
        if self.auto_refresh.get() and self.current_ticker:
             try:
                 if self.time_window_var.get() == "1D":
                    logger.info(f"Auto-refreshing {self.current_ticker}...")
                    self.fetch_data(silent=True)
             except Exception:
                 pass
                 
        if hasattr(self, 'root') and self.root.winfo_exists():
            self.root.after(60000, self._auto_refresh_loop) # Re-schedule

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

    def _download_worker(self, ticker, interval):
        try:
            # Check for cached data (Skip for 1m interval)
            csv_dir = Path("csv")
            csv_dir.mkdir(exist_ok=True)
            
            # Weekend Logic: Snap to Friday if Sat/Sun to avoid redownloading
            now = datetime.now()
            if now.weekday() == 5: # Saturday
                now -= timedelta(days=1)
            elif now.weekday() == 6: # Sunday
                now -= timedelta(days=2)
            today_str = now.strftime('%Y-%m-%d')
            
            cache_file = csv_dir / f"{ticker}_{interval}_{today_str}.csv"
            
            df = None
            
            # BYPASS CACHE for 1m interval (Day Chart)
            if interval != '1m':
                if cache_file.exists():
                    try:
                        df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
                        # Normalize columns to lowercase immediately
                        df.columns = df.columns.str.lower()
                        
                        # Enforce data types to prevent "Blank Screen" or "Range" issues
                        df.index = pd.to_datetime(df.index, utc=True)
                        try:
                            df.index = df.index.tz_convert('US/Eastern')
                        except:
                            pass
                        for col in ['open', 'high', 'low', 'close', 'volume']:
                            if col in df.columns:
                                df[col] = pd.to_numeric(df[col], errors='coerce')
                        df = df.dropna()
                        logger.info(f"Loaded {ticker} from cache.")
                    except Exception as e:
                        logger.warning(f"Failed to load cache for {ticker}: {e}")
                        df = None # Force redownload
            
            if df is None:
                # Download max history depending on interval
                if interval == '1m':
                     # 1m data: Get full 1 day (Intraday)
                     import yfinance as yf
                     # Use auto_adjust=False to get RAW price (matches IBKR/Screen)
                     df = yf.Ticker(ticker).history(period="1d", interval="1m", auto_adjust=False)
                else:
                    start_date = "2000-01-01"
                    if interval == '1h':
                         # 1h data limit ~730 days
                         start_date = (datetime.today() - timedelta(days=729)).strftime('%Y-%m-%d')
                    elif interval in ['2m', '5m', '15m', '30m', '90m']:
                         # Intraday limits ~60 days
                         start_date = (datetime.today() - timedelta(days=59)).strftime('%Y-%m-%d')
                    
                    df = get_stock_history(ticker, start=start_date, end=today_str, interval=interval)
                
                if df is not None and not df.empty:
                    df.columns = df.columns.str.lower()
                    # Ensure Index is Datetime and Convert to Eastern
                    df.index = pd.to_datetime(df.index, utc=True)
                    try:
                        df.index = df.index.tz_convert('US/Eastern')
                    except:
                        pass
                
                # Cache it (Skip for 1m)
                if df is not None and not df.empty and interval != '1m':
                     df.to_csv(cache_file)
                     # Cleanup old files
                     for f in csv_dir.glob(f"{ticker}_{interval}_*.csv"):
                        if f != cache_file:
                            try:
                                f.unlink()
                            except: pass
                        
            # Try to fetch Company Name, Metadata, etc
            company_name = ticker
            prev_close = 0.0
            curr_price = 0.0
            info_dict = {}
            try:
                import yfinance as yf
                t = yf.Ticker(ticker)
                # Fetch FULL info for sidebar
                info_dict = t.info
                company_name = info_dict.get('shortName', info_dict.get('longName', ticker))
                prev_close = info_dict.get('previousClose', 0.0)
                curr_price = info_dict.get('currentPrice') or info_dict.get('regularMarketPrice') or 0.0
            except Exception as e:
                logger.warning(f"Failed to fetch metadata: {e}")

            # Put in queue
            if df is None or df.empty:
                 self.data_queue.put(('error', f"No data found for {ticker}"))
            else:
                 self.data_queue.put(('data', (df, company_name, interval, prev_close, curr_price, info_dict)))
                 
        except Exception as e:
            logger.error(f"Download thread error: {e}")
            self.data_queue.put(('error', str(e)))

    def _get_interval_settings(self, window):
        target_interval = "1d"
        resample_rule = None
        
        if window == "10Y":
             target_interval = "1d"
             resample_rule = "1ME"
        elif window == "5Y":
             target_interval = "1d"
             resample_rule = "1W"
        elif window == "3Y":
             target_interval = "1d"
             resample_rule = "3D"
        elif window == "2Y":
            target_interval = "1d"
            resample_rule = "2D"
        elif window == "1WK":
            # Fetch 5m data, but Resample to 10m as requested
            target_interval = "5m"
            resample_rule = "10min"
        elif window == "YTD":
            # Dynamic interval for YTD
            today = datetime.now()
            start_year = datetime(today.year, 1, 1)
            days = (today - start_year).days
            # Less than ~3 months (90 days) -> Hourly, else Daily
            if days <= 90:
                 target_interval = "1h"
            else:
                 target_interval = "1d"
        elif window == "1D":
             target_interval = "1m"
        elif window == "1Y" or window == "6M":
            target_interval = "1d"
        elif window == "3M" or window == "1M" or window == "1WK":
            target_interval = "1h"
            
        return target_interval, resample_rule

    def on_window_change(self):
        window = self.time_window_var.get()
        target_interval, resample_rule = self._get_interval_settings(window)
            
        self.current_resample_rule = resample_rule
        
        # If interval change needed, re-fetch
        if target_interval != self.current_data_interval:
            self.fetch_data(interval=target_interval)
        else:
            # Just re-process (resample if needed)
            self._apply_resampling()
            
    def _apply_resampling(self):
        if self.raw_df.empty: return
        
        df = self.raw_df.copy()
        
        if self.current_resample_rule and self.current_resample_rule.endswith("D"):
            # Custom Integer-based Resampling (Trading Days)
            # This ensures consistent bar counts (every 2 or 3 trading days) ignoring weekends
            try:
                n_days = int(self.current_resample_rule[:-1])
                
                # Assign grouping ID based on integer position
                # Reset index to treat Date as data
                df.index.name = 'Date_Index'
                df = df.reset_index()
                
                # Create group ID
                df['group_id'] = df.index // n_days
                
                # Define aggregation
                # Define aggregation
                logic = {
                    'Date_Index': 'last', # Timestamp of the closed bar
                    'period_start': 'first', # Start of the bar
                    'open': 'first',
                    'high': 'max',
                    'low': 'min',
                    'close': 'last',
                    'volume': 'sum'
                }
                
                # Filter for existing columns (we added period_start by copying Date_Index)
                df['period_start'] = df['Date_Index']
                
                agg_dict = {k: v for k, v in logic.items() if k in df.columns}
                
                # Aggregate
                df = df.groupby('group_id').agg(agg_dict)
                
                # Restore Index
                df = df.set_index('Date_Index')
                df.index.name = 'Date'
                
            except ValueError:
                pass # Fallback if rule parsing fails
                
        elif self.current_resample_rule:
            # Standard Time-based resampling fallback
            logic = {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}
            cols = {k: v for k, v in logic.items() if k in df.columns}
            if cols:
                df = df.resample(self.current_resample_rule).agg(cols).dropna()
        
        self.history_df = df
        self._calculate_indicators(self.history_df)
        self.update_chart()

        
        # Initial Toggle State
        self.toggle_info_panel()
        
    def _apply_panel_position(self):
        if not self.show_info.get():
             return
        
        # First Time Show? Center it.
        if self.panel_x is None or self.panel_y is None:
            # Update idle tasks to ensure dimensions are accurate
            self.root.update_idletasks()
            
            rw = self.root.winfo_width()
            rh = self.root.winfo_height()
            
            # Dynamic Width Calculation
            # Base 600 + (25 * Font Size). 
            # Font 8 => 800. Font 4 => 700. Font 12 => 900.
            current_font = self.font_size_var.get()
            pw = 600 + (current_font * 25)
            
            ph = self.info_frame.winfo_reqheight() or 200 # Approx height if not rendered yet
            
            self.panel_x = (rw - pw) // 2
            self.panel_y = (rh - ph) // 10 # Upper Center (10% down)
            
        # Recalculate width on every apply (in case font changed)
        current_font = self.font_size_var.get()
        target_width = 600 + (current_font * 25)
            
        # Use simple place with x/y
        self.info_frame.place(
            x=self.panel_x, 
            y=self.panel_y, 
            width=target_width
        )
        self.info_frame.lift()

    def toggle_info_panel(self, event=None):
        if self.show_info.get():
             self._apply_panel_position()
             self.update_info_panel()
        else:
             self.info_frame.place_forget()
             
    def start_drag(self, event):
        self.drag_start_x = event.x_root
        self.drag_start_y = event.y_root
        self.drag_start_win_x = self.info_frame.winfo_x()
        self.drag_start_win_y = self.info_frame.winfo_y()

    def do_drag(self, event):
        dx = event.x_root - self.drag_start_x
        dy = event.y_root - self.drag_start_y
        
        new_x = self.drag_start_win_x + dx
        new_y = self.drag_start_win_y + dy
        
        self.panel_x = new_x
        self.panel_y = new_y
        
        self.info_frame.place(x=new_x, y=new_y)
        
    def close_info_panel(self):
        self.show_info.set(False)
        self.toggle_info_panel()

    def update_ui_font(self):
        """Called when font size spinbox changes"""
        try:
            size = self.font_size_var.get()
            # Update Tkinter Global Style
            import tkinter.font as tkfont
            default_font = tkfont.nametofont("TkDefaultFont")
            default_font.configure(size=size)
            text_font = tkfont.nametofont("TkTextFont")
            text_font.configure(size=size)
            self.root.option_add("*Font", default_font)
            
            # Update Header Title Font explicitly (since it has custom boldness)
            if hasattr(self, 'info_title_label'):
                self.info_title_label.configure(font=('Arial', size + 2, 'bold'))
                
        except Exception as e:
            print(f"Font update error: {e}")

        # Trigger chart update to redraw axis labels
        self.update_chart()
        # Trigger info panel update to resize text
        self.update_info_panel()

    def _fmt(self, num, is_percent=False, trim_large=False):
        if num is None or num == 'None': return "-"
        try:
            val = float(num)
            if is_percent:
                # Heuristic: If > 1, assume already %, else * 100? 
                # User report: 0.38 showed as 38% (Correct math, but maybe they meant 0.38%?)
                # Actually yfinance often returns 0.0038 for 0.38%.
                # But my checks showed '0.38' for AAPL Div. 
                # Let's show raw value with % appended if it seems scaled, or *100 if small.
                # Actually, simplest is just show value + "%" if user thinks 106% is wrong.
                # Wait, if yield is 0.05 (5%), val*100 = 5.
                return f"{val*100:.2f}%" if abs(val) < 1.0 else f"{val:.2f}%"
            
            abs_val = abs(val)
            if abs_val >= 1e12: return f"{val/1e12:.2f}T"
            if abs_val >= 1e9: return f"{val/1e9:.2f}B"
            if abs_val >= 1e6: return f"{val/1e6:.2f}M"
            if trim_large and abs_val >= 10000:
                return f"{val:,.0f}"
            return f"{val:,.2f}"
        except:
             return str(num)

    def _add_section(self, parent, title, items):
        # Dynamic Font Size
        try:
            base_size = int(self.font_size_var.get())
        except:
            base_size = 8
            
        title_font = ('Arial', base_size + 2, 'bold')
        label_font = ('Arial', base_size)
        val_font   = ('Arial', base_size, 'bold')
        
        # Section Header
        ttk.Label(parent, text=title, font=title_font, foreground="#333").pack(anchor="w", pady=(10, 5))
        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=(0, 10))
        
        # Grid (No fixed width labels)
        frame = ttk.Frame(parent)
        frame.pack(fill="x")
        row = 0
        for label, val in items:
            # Removed width=15 to allow expansion
            ttk.Label(frame, text=label, font=label_font).grid(row=row, column=0, sticky="w", padx=(0, 15), pady=2)
            ttk.Label(frame, text=val, font=val_font).grid(row=row, column=1, sticky="w", pady=2)
            row += 1

    def update_info_panel(self):
        # Clear existing content from the Direct Frame (No Canvas)
        for widget in self.info_content.winfo_children():
            widget.destroy()
            
        if not self.show_info.get() or not self.stock_info:
             if self.show_info.get():
                  # Use base size for loading text too
                 # Use base size for loading text too
                 base_size = self.font_size_var.get() or 9
                 ttk.Label(self.info_content, text="Loading Info...", font=('Arial', base_size, 'italic')).pack(pady=10)
             return

        i = self.stock_info
        
        # Determine Type Early for Logic Branching
        q_type = i.get('quoteType', '').upper()

        # --- Prepare Data Lists ---
        # 1. Key Stats (Common) -> LEFT Column
        
        # Try to find Earnings Date (Moved to Left)
        earn_ts = i.get('earningsTimestamp') or i.get('earningsTimestampStart')
        earn_str = "-"
        if earn_ts:
             earn_str = datetime.fromtimestamp(earn_ts).strftime('%Y-%m-%d')
             
        # Dividend Format: 1.04 (0.38%)
        # Dividend Format
        div_str = "-"
        div_rate = i.get('dividendRate') or i.get('trailingAnnualDividendRate')
        price = i.get('currentPrice') or i.get('regularMarketPrice')
        
        # ETF Special Logic: Use 'yield' field (Distribution/SEC Yield) to match Yahoo
        etf_yield = i.get('yield')
        if q_type == 'ETF' and etf_yield is not None:
             # etf_yield is typically decimal (0.0106 -> 1.06%)
             rate_str = f"{div_rate}" if div_rate else ""
             if rate_str:
                 div_str = f"{rate_str} ({etf_yield * 100:.2f}%)"
             else:
                 div_str = f"{etf_yield * 100:.2f}%"

        elif div_rate and price and price > 0:
             # Standard Stock Calculation (Rate / Price)
             calc_yield = (div_rate / price) * 100
             div_str = f"{div_rate} ({calc_yield:.2f}%)"
        else:
             # Fallback
             raw_yield = i.get('dividendYield')
             if raw_yield:
                 if raw_yield > 0.5: 
                     div_str = f"{raw_yield:.2f}%"
                 else:
                     div_str = f"{self._fmt(raw_yield, True)}"
        
        # Left Data (Common)
        # Beta fallback for ETF if handled in Left Column? 
        # User requested Beta in RIGHT column for ETF (implied by missing list), 
        # but standard layout has Beta in LEFT. 
        # I'll keep Beta in Left for Stocks, and use the specific ETF logic in Right?
        # Actually proper Beta for ETF is usually 3Y. 
        # Let's show Beta in LEFT for both, but fetch correct key.
        
        beta_key = 'beta3Year' if q_type == 'ETF' else 'beta'
        beta_val = i.get(beta_key) or i.get('beta')
        left_data = [
            ("52W Range", f"{self._fmt(i.get('fiftyTwoWeekLow'), trim_large=True)} - {self._fmt(i.get('fiftyTwoWeekHigh'), trim_large=True)}"),
            ("Avg Vol", self._fmt(i.get('averageVolume'))),
            ("Beta", self._fmt(beta_val)), # Uses 3Y for ETF
            ("Fwd Div&Yield", div_str),
            ("Ex-Div Date", datetime.fromtimestamp(i.get('exDividendDate', 0)).strftime('%Y-%m-%d') if i.get('exDividendDate') else "-"),
            ("Target Est", self._fmt(i.get('targetMeanPrice'))),
            ("Earnings Date", earn_str)
        ]
        
        # 2. Specifics -> RIGHT Column
        right_title = "Valuation"
        right_data = []
        
        
        if q_type == 'ETF':
            right_title = "ETF Profile"
            # ETF Specific Keys
            beta_val = i.get('beta3Year') or i.get('beta')
            
            # Expense Ratio logic
            # Raw value for SPY `netExpenseRatio` is 0.0945 (meaning 0.0945%)
            # Do NOT multiply by 100.
            exp_ratio = i.get('netExpenseRatio') or i.get('annualReportExpenseRatio') or i.get('expenseRatio')
            exp_str = "-"
            if exp_ratio is not None:
                exp_str = f"{exp_ratio}%"

            # PE for ETF (often exists as trailingPE)
            pe_val = i.get('trailingPE')
            
            right_data = [
                ("Net Assets", self._fmt(i.get('totalAssets'))),
                ("NAV", self._fmt(i.get('navPrice'))),
                ("Expense Ratio", exp_str),
                ("PE (TTM)", self._fmt(pe_val)),
                ("Beta (3Y)", self._fmt(beta_val))
            ]
        else: # Stock
             right_title = "Valuation & Earnings"
             
             # Try to find Earnings Date
             # 'earningsTimestamp' is widely used, or 'earningsTimestampStart'
             earn_ts = i.get('earningsTimestamp') or i.get('earningsTimestampStart')
             earn_str = "-"
             if earn_ts:
                 earn_str = datetime.fromtimestamp(earn_ts).strftime('%Y-%m-%d')
             
             
             right_data = [
                ("Market Cap", self._fmt(i.get('marketCap'))),
                ("Trailing PE", self._fmt(i.get('trailingPE'))),
                ("Forward PE", self._fmt(i.get('forwardPE'))),
                ("PEG Ratio", self._fmt(i.get('pegRatio') or i.get('trailingPegRatio'))),
                ("Price/Book", self._fmt(i.get('priceToBook'))),
                ("Price/Sales", self._fmt(i.get('priceToSalesTrailing12Months'))),
                ("EV/EBITDA", self._fmt(i.get('enterpriseToEbitda'))),
             ]

        # --- Render Layout (2 Columns via Grid) ---
        col_frame = ttk.Frame(self.info_content)
        col_frame.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Configure Grid Weights for 50/50 Split
        col_frame.columnconfigure(0, weight=1, uniform="group1")
        col_frame.columnconfigure(1, weight=1, uniform="group1")
        
        # Left Side
        left_frame = ttk.Frame(col_frame)
        left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self._add_section(left_frame, "Key Statistics", left_data)
        
        # Right Side
        right_frame = ttk.Frame(col_frame)
        right_frame.grid(row=0, column=1, sticky="nsew")
        self._add_section(right_frame, right_title, right_data)
        
        # Re-apply position to update height if font changed
        self._apply_panel_position()
        
        # Update Header Title
        if hasattr(self, 'info_title_label'):
             name = self.company_name if hasattr(self, 'company_name') and self.company_name else "Stock Info"
             self.info_title_label.config(text=name)

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
        
        # Time Window Buttons
        ttk.Label(control_frame, text="| Time:").pack(side=tk.LEFT, padx=10)
        time_frame = ttk.Frame(control_frame)
        time_frame.pack(side=tk.LEFT, padx=5)
        windows = ["10Y", "5Y", "3Y", "2Y", "1Y", "YTD", "6M", "3M", "1M", "1WK", "1D"]
        for w in windows:
            # Use Toolbutton for "Active" look
            btn = ttk.Radiobutton(time_frame, text=w, variable=self.time_window_var, value=w, command=self.on_window_change, style='Toolbutton')
            btn.pack(side=tk.LEFT, padx=0)
            
        # Font Size Control
        ttk.Label(control_frame, text="| Font:").pack(side=tk.LEFT, padx=10)
        font_spin = ttk.Spinbox(control_frame, from_=4, to=24, textvariable=self.font_size_var, width=3, command=self.update_ui_font)
        font_spin.pack(side=tk.LEFT, padx=5)
        font_spin.bind('<KeyRelease>', lambda e: self.update_ui_font()) # Bind typing too
            
        # Indicators Checkboxes
        indicator_frame = ttk.Frame(self.root, padding="5")
        indicator_frame.pack(side=tk.TOP, fill=tk.X)
        
        # MA Dropdown Menu
        ma_btn = ttk.Menubutton(indicator_frame, text="Moving Avg")
        ma_menu = tk.Menu(ma_btn, tearoff=0)
        ma_menu.add_checkbutton(label="MA 5 (Yel)", variable=self.show_ma5, command=self.update_chart)
        ma_menu.add_checkbutton(label="MA 20 (Grn)", variable=self.show_ma20, command=self.update_chart)
        ma_menu.add_checkbutton(label="MA 50 (Pur)", variable=self.show_ma50, command=self.update_chart)
        ma_menu.add_checkbutton(label="MA 60 (Cyn)", variable=self.show_ma60, command=self.update_chart)
        ma_menu.add_checkbutton(label="MA 100 (Org)", variable=self.show_ma100, command=self.update_chart)
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
        
        # Info Toggle (Checkbox)
        ttk.Checkbutton(indicator_frame, text="Show Info", variable=self.show_info, command=self.toggle_info_panel).pack(side=tk.RIGHT, padx=10)
        # Chart Area (Standard Pack)
        self.chart_frame = ttk.Frame(self.root)
        self.chart_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        
        # Floating Info Frame (Child of ROOT)
        self.info_frame = ttk.Frame(self.root, relief="raised", borderwidth=2)
        
        # --- Header for Dragging ---
        header = ttk.Frame(self.info_frame, style="Header.TFrame")
        header.pack(fill="x", side="top")
        
        # Title in Header
        self.info_title_label = ttk.Label(header, text="Stock Info", font=('Arial', 9, 'bold'))
        self.info_title_label.pack(side="left", padx=5, pady=2)
        
        # Close Button
        close_btn = ttk.Label(header, text="X", font=('Arial', 9, 'bold'), cursor="hand2")
        close_btn.pack(side="right", padx=5, pady=2)
        close_btn.bind("<Button-1>", lambda e: self.close_info_panel())
        
        # Bind Drag
        for w in [header, self.info_title_label]:
            w.bind("<Button-1>", self.start_drag)
            w.bind("<B1-Motion>", self.do_drag)

        # Content Frame (Directly inside Info Frame - NO SCROLLBAR)
        self.info_content = ttk.Frame(self.info_frame, padding=10)
        self.info_content.pack(fill="both", expand=True)
        
        # Initial placement of info_frame based on show_info state
        if self.show_info.get():
            self.info_frame.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.8, relheight=0.8)
        
        self.fig = plt.figure(figsize=(10, 8))
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.chart_frame)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        
        # Bind Mouse Events for Crosshair
        self.canvas.mpl_connect('motion_notify_event', self._on_mouse_move)
        self.canvas.mpl_connect('button_press_event', self._on_mouse_down)
        self.canvas.mpl_connect('button_release_event', self._on_mouse_up)
        
        # Toolbar
        toolbar = NavigationToolbar2Tk(self.canvas, self.chart_frame)
        toolbar.update()
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)

    def _filter_data_by_window(self, df, window):
        end_date = df.index.max()
        if window == "10Y": start_date = end_date - pd.DateOffset(years=10)
        elif window == "5Y": start_date = end_date - pd.DateOffset(years=5)
        elif window == "3Y": start_date = end_date - pd.DateOffset(years=3)
        elif window == "2Y": start_date = end_date - pd.DateOffset(years=2)
        elif window == "1Y": start_date = end_date - pd.DateOffset(years=1)
        elif window == "YTD": 
            start_date = pd.Timestamp(year=end_date.year, month=1, day=1)
            if end_date.tz is not None:
                start_date = start_date.tz_localize(end_date.tz)
        elif window == "6M": start_date = end_date - pd.DateOffset(months=6)
        elif window == "3M": start_date = end_date - pd.DateOffset(months=3)
        elif window == "1M": start_date = end_date - pd.DateOffset(months=1)
        elif window == "1WK": start_date = end_date - pd.DateOffset(weeks=1)
        elif window == "1D":
             # Should be caught by 1m logic, but ensure we don't filter out everything
             # 1D loads only current day, so filtering is just checking start of day?
             # Actually if we loaded 1d period, just show all.
             start_date = df.index.min()
        else: start_date = df.index.min()
        
        # FIX: return copy to avoid SettingWithCopyWarning
        return df[df.index >= pd.Timestamp(start_date)].copy()

    def _setup_date_axis(self, ax, df, window):
        major_indices = []
        major_labels = []
        minor_indices = []
        minor_labels = []
        
        dates = df.index
        years = dates.year
        months = dates.month
        days = dates.day
        
        # Define Modes
        is_long_term = window in ["10Y", "5Y", "3Y", "2Y"]
        is_hourly = (self.current_data_interval == '1h') or (window == "1WK")
        
        prev_year = -1
        prev_month = -1
        prev_day = -1
        prev_hour = -1
        
        for i, (date, y, m, d) in enumerate(zip(dates, years, months, days)):
            
            # --- 1D MODE (Minute Data) ---
            if window == "1D":
                # Show Hours
                curr_hour = date.hour
                if curr_hour != prev_hour:
                     major_indices.append(i)
                     major_labels.append(date.strftime("%H:%M"))
                     prev_hour = curr_hour
                continue

            # --- HOURLY MODE (Day Grid) ---
            if is_hourly:
                if d != prev_day:
                    major_indices.append(i)
                    # Label Logic
                    if window == "3M":
                        # Sparse Labels: Month Name on change, else Day Num on Mondays
                        if m != prev_month:
                            major_labels.append(date.strftime("%b %d"))
                        elif date.weekday() == 0: # Monday
                            major_labels.append(f"{d}")
                        else:
                            major_labels.append("") # Grid line only
                    elif window in ["1M", "YTD"]:
                        # Month + Day
                        if m != prev_month:
                            major_labels.append(date.strftime("%b %d"))
                        else:
                             major_labels.append(date.strftime("%d"))
                    else:
                        # 1WK: Full Detail
                        major_labels.append(date.strftime("%a %d"))
                        
                    prev_day = d
                    prev_month = m
                    prev_year = y
                continue # Skip standard logic
            
            # --- DAILY/LONG TERM MODE ---
            # Year Change Logic
            if y != prev_year:
                if is_long_term:
                    # Skip the very first index to avoid "previous year creep" at the left edge
                    if i > 5: 
                        major_indices.append(i)
                        major_labels.append(str(y))
                # For short term, we suppress years
                prev_year = y
                
            # Month Change Logic
            if m != prev_month:
                if is_long_term:
                    # Minor Ticks: 2-Digit Months
                    if window in ["10Y", "5Y"]: # Show Quarters
                         if m in [1, 4, 7, 10]:
                             minor_indices.append(i)
                             minor_labels.append(f"{m:02d}")
                    else: # 2Y, 3Y show all months
                         minor_indices.append(i)
                         minor_labels.append(f"{m:02d}")
                else: 
                    # Short Term (Daily): Major Ticks = Month Names
                    major_indices.append(i)
                    major_labels.append(dates[i].strftime('%b'))
                    
                prev_month = m
                
        # Apply Major Ticks
        ax.set_xticks(major_indices)
        ax.set_xticklabels(major_labels, fontsize=self.font_size_var.get(), fontweight='bold')
        
        # Apply Minor Ticks
        if is_long_term:
            ax.set_xticks(minor_indices, minor=True)
            ax.set_xticklabels(minor_labels, minor=True, fontsize=self.font_size_var.get()-2)
            # Ticks styling
            ax.tick_params(axis='x', which='major', length=15, width=1.5, pad=5) # Years lower
            ax.tick_params(axis='x', which='minor', length=8, width=1) # Months
        else:
             # Short term / Hourly
             ax.set_xticks([], minor=True)
             ax.tick_params(axis='x', which='major', length=8, width=1) # Standard

        # Enable Grid for Intraday/Short Term (User Request)
        if window in ["1D", "1WK", "1M"]:
            ax.grid(True, linestyle='--', alpha=0.3)



    def update_chart(self, *args):
        if self.history_df.empty:
            return
            
        # Update Global Font Size
        base_font_size = self.font_size_var.get()
        plt.rcParams.update({'font.size': base_font_size})
        
        # Filter Data
        df = self._filter_data_by_window(self.history_df, self.time_window_var.get())
        if df.empty:
            return

        if df.empty:
            return

        # --- 1D Fixed Scale Logic ---
        if self.time_window_var.get() == "1D":
             # Force full day index (09:30 - 16:00 ET)
             try:
                 # Get the date from data
                 current_date = df.index.min().date()
                 
                 # Construct start/end for this date
                 start_ts = pd.Timestamp(f"{current_date} 09:30:00").tz_localize("US/Eastern")
                 end_ts = pd.Timestamp(f"{current_date} 16:00:00").tz_localize("US/Eastern")
                 
                 # Create Full Index
                 full_index = pd.date_range(start=start_ts, end=end_ts, freq="1min")
                 
                 # Reindex (Keep existing data, fill rest with NaN)
                 # This ensures X-axis always spans 09:30 to 16:00
                 df = df.reindex(full_index)
             except Exception as e:
                 print(f"Failed to apply fixed 1D scale: {e}")

        # Prepare Indicators (Calculated globally now)
        # self._calculate_indicators(df) 
        
        # Clear Figure
        self.fig.clear()
        self.crosshair_lines = {} # Reset refs
        self.crosshair_texts = {}
        
        # Determine active layouts
        panels = ['price']
        if self.show_macd.get(): panels.append('macd')
        if self.show_rsi.get(): panels.append('rsi')
        
        num_panels = len(panels)
        
        
        # Dynamic Height Ratios (Fixed Weight: Others=15%, Price=Remainder)
        num_others = num_panels - 1
        other_weight = 15
        price_weight = 100 - (other_weight * num_others)
        ratios = [price_weight] + [other_weight] * num_others
        
        # Calculate Stats (Handle NaNs from Reindexing)
        company = getattr(self, 'company_name', self.current_ticker)
        
        valid_closes = df['close'].dropna()
        if not valid_closes.empty:
            start_price = valid_closes.iloc[0]
            end_price = valid_closes.iloc[-1]
            
            # Use Previous Close for 1D Daily Change
            if self.time_window_var.get() == "1D":
                if self.previous_close > 0: start_price = self.previous_close
                if self.current_price > 0: end_price = self.current_price
        else:
            start_price = 0.0
            end_price = 0.0
            
        change = end_price - start_price
        pct_change = (change / start_price) * 100 if start_price != 0 else 0
        sign = "+" if change >= 0 else ""
        color = "green" if change >= 0 else "red"
        
        # Draw Titles (1-Liner)
        # Draw Titles (1-Liner)
        title_text = f"{company} ({self.time_window_var.get()})   {end_price:.2f} {sign}{change:.2f} ({sign}{pct_change:.2f}%)"
        if self.time_window_var.get() == "1D":
             title_text += "   (15min Delayed)"
        self.fig.suptitle(title_text, fontsize=base_font_size+4, fontweight='bold', color=color, y=0.98)
        
        # Create GridSpec (Adjust top for title)
        # Create GridSpec (Adjust top for title)
        # Increased bottom margin for FHD screens (0.05 -> 0.10)
        gs = self.fig.add_gridspec(num_panels, 1, height_ratios=ratios, hspace=0.01, 
                                   left=0.05, right=0.95, top=0.94, bottom=0.08)
        
        axes = {}
        shared_ax = None
        
        # Create X-axis index (0, 1, 2...) for Gapless Plotting
        x_indices = np.arange(len(df))
        self.current_df_dates = df.index # Store for lookup
        
        for i, panel_name in enumerate(panels):
            if i == 0:
                ax = self.fig.add_subplot(gs[i])
                shared_ax = ax
            else:
                ax = self.fig.add_subplot(gs[i], sharex=shared_ax)
            axes[panel_name] = ax
            
            # Remove title
            ax.set_title("")
            
            # Vertical Titles on the LEFT - REMOVED

            # Tick parameters
            if i < num_panels - 1:
                plt.setp(ax.get_xticklabels(), visible=False)
                ax.tick_params(axis='x', labelbottom=False)
            
            # Price Axis on LEFT
            if panel_name == 'price':
                ax.yaxis.set_label_position("left")
                ax.yaxis.tick_left()
            else:
                 ax.yaxis.set_label_position("left")
                 ax.yaxis.tick_left()

        # Plot Price
        ax_price = axes['price']
        
        # Overlay Volume (Bottom 20%)
        if self.show_volume.get():
             self._plot_volume_overlay(ax_price, df, x_indices)
        
        self._plot_candles(ax_price, df, x_indices)
        self._plot_ma(ax_price, df, x_indices)
        self._plot_bbands(ax_price, df, x_indices)
        if self.show_vp.get():
             # Use RAW High-Res Data for Volume Profile if available
             # Filter raw_df to match the chart's time window start
             if not self.raw_df.empty:
                 start_date = df.index.min()
                 vp_data = self.raw_df[self.raw_df.index >= start_date]
                 self._plot_volume_profile(ax_price, vp_data)
             else:
                 self._plot_volume_profile(ax_price, df)
            
        ax_price.grid(True, alpha=0.3)
        if any([v.get() for v in [self.show_ma5, self.show_ma20, self.show_ma50, self.show_ma60, self.show_ma100, self.show_ma120, self.show_ma200]]):
             ax_price.legend(loc='upper left', prop={'size': base_font_size},  bbox_to_anchor=(0.02, 0.98), ncol=2)

        # Calculate Price Limits explicitly to avoid 0 artefacts
        y_min = df['low'].min()
        y_max = df['high'].max()
        
        # Include BBands in range if shown
        if self.show_bbards.get() and 'bb_upper' in df.columns:
            y_max = max(y_max, df['bb_upper'].max())
            y_min = min(y_min, df['bb_lower'].min())
            
        # Include MAs in range if shown (Fix for long-term charts)
        ma_cols = [
            (self.show_ma5, 'ma5'), (self.show_ma20, 'ma20'), 
            (self.show_ma50, 'ma50'), (self.show_ma60, 'ma60'),
            (self.show_ma100, 'ma100'), (self.show_ma120, 'ma120'),
            (self.show_ma200, 'ma200')
        ]
        for var, col in ma_cols:
            if var.get() and col in df.columns:
                 # Filter out NaN/Inf which might happen with rolling averages at start
                 valid_ma = df[col].dropna()
                 if not valid_ma.empty:
                     y_max = max(y_max, valid_ma.max())
                     y_min = min(y_min, valid_ma.min())
            
        # Add padding
        pad = (y_max - y_min) * 0.05
        ax_price.set_ylim(y_min - pad, y_max + pad)

        # Plot Other Panels
        if 'macd' in axes:
            self._plot_macd(axes['macd'], df, x_indices)
        if 'rsi' in axes:
            self._plot_rsi(axes['rsi'], df, x_indices)
            
        # Format X-Axis on the Bottom Panel
        bottom_panel = panels[-1]
        bottom_ax = axes[bottom_panel]
        self._setup_date_axis(bottom_ax, df, self.time_window_var.get())
        
        # Set margins to 0
        bottom_ax.set_xlim(-0.5, len(df) - 0.5)
        
        # Setup Crosshair Labels (Hidden by default)
        # One Y-label per panel
        self.panel_labels = {}
        for name, ax in axes.items():
             lbl = ax.text(1.01, 0.5, "", transform=ax.transAxes, 
                           color='black', bbox=dict(boxstyle='round', facecolor='white', alpha=0.9, edgecolor='black'), ha='left',
                           fontsize=base_font_size)
             lbl.set_visible(False)
             self.panel_labels[ax] = {'label': lbl, 'name': name}

        # Date Label (Always on Price panel top)
        self.crosshair_date_lbl = ax_price.text(0.5, 1.01, "", transform=ax_price.transAxes, 
                                                color='black', ha='center', fontsize=base_font_size,
                                                bbox=dict(boxstyle='round', facecolor='white', alpha=0.9, edgecolor='none'))
        self.crosshair_date_lbl.set_visible(False)
        
        # Volume Label (Moved to Bottom Right of Bottom Panel)
        bottom_panel = panels[-1]
        bottom_ax = axes[bottom_panel]
        self.crosshair_vol_lbl = bottom_ax.text(0.99, 0.02, "", transform=bottom_ax.transAxes,
                                               color='black', ha='right', va='bottom', fontsize=base_font_size, fontweight='bold',
                                               bbox=dict(boxstyle='round', facecolor='white', alpha=0.8, edgecolor='none'))
        self.crosshair_vol_lbl.set_visible(False)
        
        # Setup Crosshair Lines (Manual, Hidden by default)
        self.crosshair_lines['vert'] = []
        self.crosshair_lines['horiz'] = []
        
        # Init value for lines (non-zero to avoid autoscaling issues)
        init_price = df['close'].iloc[-1]
        
        for ax in axes.values():
            # Vertical Line (shared x)
            vl = ax.axvline(x=len(df)-1, color='red', lw=0.5, visible=False)
            self.crosshair_lines['vert'].append(vl)
            
            # Horizontal Line (per axis)
            curr_y = init_price if ax == ax_price else 0
            hl = ax.axhline(y=curr_y, color='red', lw=0.5, visible=False)
            self.crosshair_lines['horiz'].append(hl)

        self.axes_dict = axes 
        self.canvas.draw()
        
        # Removed MultiCursor

    def _on_mouse_down(self, event):
        if not event.inaxes or self.history_df.empty:
            return
        if event.button != 1: # Only Left Click
            return
            
        self.is_dragging = True
        
        # Handle Twin Axes Remapping
        target_axis = event.inaxes
        ax_price = self.axes_dict.get('price')
        if ax_price and target_axis != ax_price:
             if target_axis.get_position().bounds == ax_price.get_position().bounds:
                 target_axis = ax_price
                 
        self._update_crosshair(event.xdata, event.ydata, target_axis)

    def _on_mouse_up(self, event):
        self.is_dragging = False
        # Hide crosshair
        if hasattr(self, 'panel_labels'):
             for info in self.panel_labels.values():
                 info['label'].set_visible(False)
             self.crosshair_date_lbl.set_visible(False)
             self.crosshair_vol_lbl.set_visible(False)
             
             for line in self.crosshair_lines['vert'] + self.crosshair_lines['horiz']:
                 line.set_visible(False)
             self.canvas.draw_idle()

    def _on_mouse_move(self, event):
        if not event.inaxes or self.history_df.empty or not self.is_dragging:
            return
            
        # Handle Twin Axes (Volume Overlay, VP)
        # If event is on a twin axis, map it back to the main Price axis
        target_axis = event.inaxes
        ax_price = self.axes_dict.get('price')
        
        # Check if it's a sibling of price axis (sharing x or y)
        if ax_price and target_axis != ax_price:
             # If it shares bbox with price, treat as price
             if target_axis.get_position().bounds == ax_price.get_position().bounds:
                 target_axis = ax_price

        self._update_crosshair(event.xdata, event.ydata, target_axis)

    def _update_crosshair(self, x_data, y_data, in_axes):
        # Get Index and Price
        x_idx = int(x_data + 0.5)
        price = y_data
        
        # Clip index for Data
        safe_idx = max(0, min(x_idx, len(self.current_df_dates) - 1))
        current_date = self.current_df_dates[safe_idx]

        # Update Vertical Lines (Snap to candle center)
        for line in self.crosshair_lines['vert']:
            line.set_xdata([x_idx]) # Use integer index
            line.set_visible(True)
            
        # Update Horizontal Lines
        for line in self.crosshair_lines['horiz']:
            if line.axes == in_axes:
                line.set_ydata([price])
                line.set_visible(True)
            else:
                line.set_visible(False)
        
        # Update Y Labels (Per Panel)
        if hasattr(self, 'panel_labels'):
            # Hide all first
            for info in self.panel_labels.values():
                info['label'].set_visible(False)
                
            if in_axes in self.panel_labels:
                info = self.panel_labels[in_axes]
                lbl = info['label']
                name = info['name']
                
                # Format Value
                if name == 'volume':
                    val_str = f"{int(price):,}"
                else:
                    val_str = f"{price:.2f}"
                
                lbl.set_text(val_str)
                
                # Position Y
                ymin, ymax = in_axes.get_ylim()
                # Avoid div zero
                rng = ymax - ymin
                if rng == 0: rng = 1
                y_rel = (price - ymin) / rng
                lbl.set_position((1.01, y_rel))
                lbl.set_visible(True)
            
            # Update Date Label (Top of Price Axis)
            window = self.time_window_var.get()
            
            if self.current_data_interval == '1wk' or window == '5Y':
                # Weekly: Show Range (Mon - Fri)
                # Robust logic: Find Monday of the week, add 4 days for Friday
                # This works if date is Mon, Sun, Sat, etc. provided it falls within the week.
                dt_start = current_date - timedelta(days=current_date.weekday()) # Snap to Mon
                dt_end = dt_start + timedelta(days=4) # Friday
                date_str = f"{dt_start.strftime('%Y-%m-%d')} / {dt_end.strftime('%Y-%m-%d')}"
            
            elif self.current_data_interval == '1mo' or window == '10Y':
                # Monthly: Show Start / End of Month
                import calendar
                last_day = calendar.monthrange(current_date.year, current_date.month)[1]
                dt_start = current_date.replace(day=1)
                dt_end = current_date.replace(day=last_day)
                date_str = f"{dt_start.strftime('%Y-%m-%d')} / {dt_end.strftime('%Y-%m-%d')}"
            
            elif window in ["2Y", "3Y"]:
                # Custom Resampled Days (2D, 3D)
                # We stored 'period_start' in history_df during resampling
                try:
                    # Get the row corresponding to this date
                    row = self.history_df.loc[current_date]
                    if 'period_start' in row:
                        start_ts = pd.Timestamp(row['period_start'])
                        date_str = f"{start_ts.strftime('%Y-%m-%d')} / {current_date.strftime('%Y-%m-%d')}"
                    else:
                        date_str = current_date.strftime('%Y-%m-%d')
                except:
                     date_str = current_date.strftime('%Y-%m-%d')

            elif 'm' in self.current_data_interval or 'h' in self.current_data_interval:
                # Intraday: Show Date + Time (HH:MM)
                date_str = current_date.strftime('%Y-%m-%d %H:%M')
            else:
                # Daily/Weekly/Monthly
                date_str = current_date.strftime('%Y-%m-%d')
            self.crosshair_date_lbl.set_text(date_str)
            
            # Position X based on AX Price (Master X)
            ax_price = self.axes_dict['price']
            xmin, xmax = ax_price.get_xlim()
            rng_x = xmax - xmin
            if rng_x == 0: rng_x = 1
            x_rel = (x_idx - xmin) / rng_x
            
            self.crosshair_date_lbl.set_position((x_rel, 1.01))
            self.crosshair_date_lbl.set_visible(True)
            
            # Update Volume Label
            if self.show_volume.get():
                vol = self.history_df['volume'].iloc[safe_idx]
                if pd.notna(vol):
                    self.crosshair_vol_lbl.set_text(f"Vol: {int(vol):,}")
                    self.crosshair_vol_lbl.set_visible(True)
            
            self.canvas.draw_idle()

    def _calculate_indicators(self, df):
        df.columns = map(str.lower, df.columns)
        df.columns = map(str.lower, df.columns)
        df['ma5'] = df['close'].rolling(window=5).mean()
        df['ma20'] = df['close'].rolling(window=20).mean()
        df['ma50'] = df['close'].rolling(window=50).mean()
        df['ma60'] = df['close'].rolling(window=60).mean()
        df['ma100'] = df['close'].rolling(window=100).mean()
        df['ma120'] = df['close'].rolling(window=120).mean()
        df['ma200'] = df['close'].rolling(window=200).mean()
        
        macd = TA.MACD(df)
        df['macd'] = macd['MACD']
        df['signal'] = macd['SIGNAL']
        df['rsi'] = TA.RSI(df)
        bb = TA.BBANDS(df)
        df['bb_upper'] = bb['BB_UPPER']
        df['bb_middle'] = bb['BB_MIDDLE']
        df['bb_lower'] = bb['BB_LOWER']

    def _plot_candles(self, ax, df, x_indices):
        up = df['close'] >= df['open']
        down = df['close'] < df['open']
        
        # Width logic: 0.8 is standard for no-gap
        width = 0.6
        
        # Plot Up
        up_idx = x_indices[up].astype(int)
        ax.vlines(up_idx, df.loc[up, 'low'], df.loc[up, 'high'], color='green', linewidth=1)
        ax.bar(up_idx, df.loc[up, 'close'] - df.loc[up, 'open'], width, bottom=df.loc[up, 'open'], color='white', edgecolor='green', linewidth=1, align='center')
        
        # Plot Down
        down_idx = x_indices[down].astype(int)
        ax.vlines(down_idx, df.loc[down, 'low'], df.loc[down, 'high'], color='red', linewidth=1)
        ax.bar(down_idx, df.loc[down, 'open'] - df.loc[down, 'close'], width, bottom=df.loc[down, 'close'], color='red', edgecolor='red', linewidth=1, align='center')

    def _plot_ma(self, ax, df, x_indices):        # Plot Indicators
        if self.show_ma5.get(): ax.plot(x_indices, df['ma5'], label='MA5', color='yellow', linewidth=0.8, alpha=0.9)
        if self.show_ma20.get(): ax.plot(x_indices, df['ma20'], label='MA20', color='green', linewidth=0.8, alpha=0.9)
        if self.show_ma50.get(): ax.plot(x_indices, df['ma50'], label='MA50', color='purple', linewidth=0.8, alpha=0.9)
        if self.show_ma60.get(): ax.plot(x_indices, df['ma60'], label='MA60', color='cyan', linewidth=0.8, alpha=0.9)
        if self.show_ma100.get(): ax.plot(x_indices, df['ma100'], label='MA100', color='orange', linewidth=0.8, alpha=0.9)
        if self.show_ma120.get(): ax.plot(x_indices, df['ma120'], label='MA120', color='magenta', linewidth=0.8, alpha=0.9)
        if self.show_ma200.get(): ax.plot(x_indices, df['ma200'], label='MA200', color='red', linewidth=0.8, alpha=0.9)

    def _plot_bbands(self, ax, df, x_indices):
        if self.show_bbards.get():
            ax.plot(x_indices, df['bb_upper'], color='gray', linestyle='--', alpha=0.5, linewidth=0.8)
            ax.plot(x_indices, df['bb_lower'], color='gray', linestyle='--', alpha=0.5, linewidth=0.8)
            ax.fill_between(x_indices, df['bb_upper'], df['bb_lower'], color='gray', alpha=0.1)

    def _plot_volume_overlay(self, ax, df, x_indices):
        colors = ['green' if c >= o else 'red' for c, o in zip(df['close'], df['open'])]
        
        ax_vol = ax.twinx()
        ax_vol.bar(x_indices.astype(int), df['volume'], color=colors, width=0.6, align='center', alpha=0.3)
        
        # Scale Volume to Bottom 25%
        max_vol = df['volume'].max()
        if max_vol > 0:
            ax_vol.set_ylim(0, max_vol * 4)
            
        ax_vol.set_yticks([]) # Hide ticks
        ax_vol.set_zorder(0) # Behind
        ax.set_zorder(1)
        ax.patch.set_visible(False)

    def _plot_macd(self, ax, df, x_indices):
        ax.plot(x_indices, df['macd'], color='blue', label='MACD')
        ax.plot(x_indices, df['signal'], color='orange', label='Signal')
        colors = ['green' if val >= 0 else 'red' for val in (df['macd'] - df['signal'])]
        ax.bar(x_indices.astype(int), df['macd'] - df['signal'], color=colors, width=1.0, align='center')
        ax.grid(True, alpha=0.3)
        ax.set_ylabel("") # Remove left title
        ax.legend(loc='upper left', prop={'size': self.font_size_var.get()})

    def _plot_rsi(self, ax, df, x_indices):
        ax.plot(x_indices, df['rsi'], color='purple')
        ax.axhline(70, color='red', linestyle='--', alpha=0.5)
        ax.axhline(30, color='green', linestyle='--', alpha=0.5)
        ax.grid(True, alpha=0.3)
        ax.set_ylabel("") # Remove left title
        # Inner Title at Bottom Left
        ax.text(0.02, 0.05, "RSI", transform=ax.transAxes, fontweight='bold', fontsize=self.font_size_var.get(), color='purple')


    def _plot_volume_profile(self, ax, df):
        # VP needs to be drawn using Price Y-axis but shared geometry?
        # Actually VP is usually drawn ON TOP of price.
        # Since we use Index X-axis, we can't easily plot geometric VP bars unless we map them.
        # But VP is horizontal bars on Y axis. Y axis is Price (Shared).
        # The X-axis for VP is "Volume". We need a twinx or twiny?
        # Standard VP: Price on Y. Volume on X (TwinY).
        
        price_min = df['low'].min()
        price_max = df['high'].max()
        
        # --- Value Profile Binning Logic ---
        # Parse mode (e.g. "100 Bins")
        try:
             mode_str = self.vp_mode_var.get()
             num_bins = int(mode_str.split()[0])
        except:
             num_bins = 100 # Default
             
        # Calculate Bin Height
        if num_bins <= 0: num_bins = 100
        bin_height = (price_max - price_min) / num_bins
        if bin_height == 0: return

        bins = [price_min + i * bin_height for i in range(num_bins + 1)]
        volume_profile = [0] * num_bins
        
        for index, row in df.iterrows():
            start_bin = int((row['low'] - price_min) / bin_height)
            end_bin = int((row['high'] - price_min) / bin_height)
            start_bin = max(0, min(start_bin, num_bins - 1))
            end_bin = max(0, min(end_bin, num_bins - 1))
            
            if start_bin == end_bin:
                volume_profile[start_bin] += row['volume']
            else:
                vol_per = row['volume'] / (end_bin - start_bin + 1)
                for i in range(start_bin, end_bin + 1):
                    volume_profile[i] += vol_per
                    
        ax_vp = ax.twiny()
        ax_vp.barh(bins[:-1], volume_profile, height=bin_height, alpha=0.2, color='blue', align='edge', edgecolor='blue', linewidth=0.5)
        ax_vp.set_xticklabels([])
        ax_vp.tick_params(left=False, labelleft=False, right=False, labelright=False, top=False, labeltop=False, bottom=False, labelbottom=False)
        ax_vp.grid(False)
        
        # Ensure Main Axis is on TOP to capture events
        ax_vp.set_zorder(0)
        ax.set_zorder(1)
        ax.patch.set_visible(False) # Transparent background to see VP behind
        
        # Limit VP width to 1/4 of the span
        max_vol = max(volume_profile) if volume_profile else 0
        if max_vol > 0:
            ax_vp.set_xlim(0, max_vol * 4)
        
        if self.vp_position.get() == "Right":
            ax_vp.invert_xaxis()
            
if __name__ == "__main__":
    root = tk.Tk()
    app = StockChartApp(root)
    root.mainloop()
