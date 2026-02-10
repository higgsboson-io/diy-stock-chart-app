# chart_drawing.py
import tkinter as tk
from tkinter import ttk
import logging
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
import matplotlib.dates as mdates
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class ChartPlotter:
    def __init__(self, fig, canvas, app_state):
        self.fig = fig
        self.canvas = canvas
        self.app = app_state # Reference to StockChartApp to access state vars
        
        # Crosshair refs
        self.crosshair_lines = {}
        self.crosshair_texts = {}
        self.panel_labels = {}
        self.axes_dict = {}
        self.is_dragging = False 
        self.current_df_dates = []
        
        # Bind Mouse Events
        self.canvas.mpl_connect('motion_notify_event', self._on_mouse_move)
        self.canvas.mpl_connect('button_press_event', self._on_mouse_down)
        self.canvas.mpl_connect('button_release_event', self._on_mouse_up)
        
    def _filter_data_by_window(self, df, window):
        end_date = df.index.max()
        if window == "20Y": start_date = end_date - pd.DateOffset(years=20)
        elif window == "10Y": start_date = end_date - pd.DateOffset(years=10)
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
        is_long_term = window in ["20Y", "10Y", "5Y", "3Y", "2Y"]
        is_hourly = (self.app.current_data_interval == '1h') or (window == "1WK")
        
        prev_year = -1
        prev_month = -1
        prev_day = -1
        prev_hour = -1
        
        font_size = self.app.font_size_var.get()

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

            # --- SMART MODE: 3M to 5Y ---
            # Handles: 3M, 6M (Dense: Month + Days)
            # Handles: 1Y, YTD, 2Y, 3Y, 5Y (Sparse: Months + Years)
            
            # Normalize window to allow loose matching
            w_norm = window.strip().upper()
            
            if w_norm in ["3M", "6M", "1Y", "1YTD", "YTD", "2Y", "3Y", "5Y"]:
                
                is_dense = w_norm in ["3M", "6M"]
                
                # Constants
                # For Dense mode (short labels like "12"), we can allow tighter packing (6 bars)
                # For Sparse mode (full Month names), we need more space (10 bars)
                MIN_COLLISION_GAP = 6 if is_dense else 10
                MIN_DENSITY_GAP = 5

                # Detect Month Change OR First Index
                is_month_change = (m != prev_month)
                
                if is_month_change:
                    
                    # --- Filter Density for Long Term (3Y/5Y) ---
                    # To avoid crowding, we only show specific months for very long views
                    should_show = True
                    is_year_change = (y != prev_year) or (len(major_indices) == 0)
                    
                    if not is_dense and not is_year_change:
                        if w_norm == "3Y":
                            # Quarterly (Jan, Apr, Jul, Oct)
                            if m not in [1, 4, 7, 10]:
                                should_show = False
                        elif w_norm == "5Y":
                             # Semi-Annual (Jan, Jul)
                             if m not in [1, 7]:
                                 should_show = False
                    
                    if should_show:
                        # --- 1. Priority Label: Month Start ---
                        
                        # Collision Check
                        # If filtering is active (3Y/5Y), collision is less likely but still good to keep.
                        if major_indices and (i - major_indices[-1] < MIN_COLLISION_GAP):
                             major_indices.pop()
                             major_labels.pop()
                        
                        # Formatting Logic
                        label_text = ""
                        if is_dense:
                             label_text = date.strftime("%b %d")
                        else:
                            # Sparse Mode (1Y+)
                            # Show Year if: Year changed OR First Label (to give context)
                            if is_year_change:
                                label_text = date.strftime("%b '%y") # e.g. Jan '24
                            else:
                                label_text = date.strftime("%b") # e.g. Feb
                        
                        major_indices.append(i)
                        major_labels.append(label_text)
                        
                        # --- 2. Look Ahead: Add Splits (Dense Mode Only) ---
                        if is_dense:
                            current_month_indices = []
                            for k in range(i, len(dates)):
                                if dates[k].month == m and dates[k].year == y:
                                    current_month_indices.append(k)
                                else:
                                    break
                            
                            n_days = len(current_month_indices)
                            
                            # Adaptive Splits
                            ticks_to_add = []
                            if n_days >= 15:
                                ticks_to_add.append(i + n_days // 3)
                                ticks_to_add.append(i + n_days * 2 // 3)
                            elif n_days >= 7:
                                ticks_to_add.append(i + n_days // 2)
                            
                            # Apply Mid-Ticks
                            last_idx_local = i
                            for t_idx in ticks_to_add:
                                if t_idx - last_idx_local >= MIN_DENSITY_GAP:
                                     major_indices.append(t_idx)
                                     major_labels.append(dates[t_idx].strftime("%d"))
                                     last_idx_local = t_idx

                    prev_month = m
                    prev_year = y
                    prev_day = d
                continue

            # --- HOURLY MODE (Day Grid) ---

            if is_hourly:
                if d != prev_day:
                    # Fix for 1WK: Skip first label if it starts mid-day (random cut)
                    # Use 10:00 as threshold (Stock market starts 09:30, Crypto 00:00)
                    # This suppresses labels for charts starting at 10:00, 11:00, 14:00 etc.
                    # Only allows 00:00 - 09:59 starts (Morning).
                    if i == 0 and date.hour >= 10:
                         prev_day = d
                         prev_month = m
                         prev_year = y
                         continue

                    # Collision/Density Constants
                    # Hourly bars: ~7 per day. Partial days can be 1-2 bars.
                    # We need to ensure labels don't bunch up.
                    MIN_HOURLY_GAP = 8 # Minimum bars between labels
                    
                    is_priority = (m != prev_month) or (len(major_indices) == 0)
                    
                    # 1. Backtrack Check: If we are too close to last label
                    if major_indices and (i - major_indices[-1] < MIN_HOURLY_GAP):
                        # If CURRENT is Priority (Month Start), we overwrite previous (Day)
                        if is_priority:
                             major_indices.pop()
                             major_labels.pop()
                        else:
                             # If CURRENT is standard day, and too close to previous, we skip CURRENT
                             # But update prev_day to suppress repeats
                             prev_day = d
                             prev_month = m
                             prev_year = y
                             continue

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
                    if window in ["20Y", "10Y", "5Y"]: # Show Quarters
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
        ax.set_xticklabels(major_labels, fontsize=font_size, fontweight='bold')
        
        # Apply Minor Ticks
        if is_long_term:
            ax.set_xticks(minor_indices, minor=True)
            ax.set_xticklabels(minor_labels, minor=True, fontsize=font_size-2)
            # Ticks styling
            ax.tick_params(axis='x', which='major', length=15, width=1.5, pad=5) # Years lower
            ax.tick_params(axis='x', which='minor', length=8, width=1) # Months
        else:
             # Short term / Hourly
             ax.set_xticks([], minor=True)
             ax.tick_params(axis='x', which='major', length=8, width=1) # Standard

        # Enable Grid for Intraday/Short Term (User Request)
        if window in ["1D", "1WK", "1M", "3M", "6M"]:
            ax.grid(True, linestyle='--', alpha=0.3)

    def update_chart(self, *args):
        if self.app.history_df.empty:
            self.fig.clf()
            self.canvas.draw()
            return
            
        # Update Global Font Size
        base_font_size = self.app.font_size_var.get()
        plt.rcParams.update({'font.size': base_font_size})
        
        # Filter Data
        df = self._filter_data_by_window(self.app.history_df, self.app.time_window_var.get())
        if df.empty:
            return

        # --- 1D Fixed Scale Logic ---
        # BYPASS for Global Assets (Crypto/Forex) which trade 24/7 or across days
        q_type = self.app.stock_info.get('quoteType', '').upper()
        is_global = q_type in ['CRYPTOCURRENCY', 'CURRENCY', 'FUTURE']
        
        if self.app.time_window_var.get() == "1D":
             # Force full day index (09:30 - 16:00 ET)
             try:
                 # Get the date from data
                 current_date = df.index.max().date() # Use MAX date (Today) for Safety
                 
                 # Construct start/end for this date
                 start_str = "09:30:00"
                 end_str = "16:00:00"
                 
                 if is_global:
                     # Global: Fixed Calendar Day
                     start_str = "00:00:00"
                     end_str = "23:59:59"
                 elif self.app.show_prepost.get():
                     start_str = "04:00:00"
                     end_str = "20:00:00"

                 start_ts = pd.Timestamp(f"{current_date} {start_str}").tz_localize("US/Eastern")
                 end_ts = pd.Timestamp(f"{current_date} {end_str}").tz_localize("US/Eastern")
                 
                 # Create Full Index
                 full_index = pd.date_range(start=start_ts, end=end_ts, freq="1min")
                 
                 # Reindex (Keep existing data, fill rest with NaN)
                 # This ensures X-axis always spans the desired range (Regular or Full)
                 df = df.reindex(full_index)
             except Exception as e:
                 print(f"Failed to apply fixed 1D scale: {e}")

        # Clear Figure
        self.fig.clear()
        self.crosshair_lines = {} # Reset refs
        self.crosshair_texts = {}
        self.panel_labels = {} 
        self.axes_dict = {}
        
        # Determine active layouts
        panels = ['price']
        if self.app.show_macd.get(): panels.append('macd')
        if self.app.show_rsi.get(): panels.append('rsi')
        
        num_panels = len(panels)
        
        # Dynamic Height Ratios (Fixed Weight: Others=15%, Price=Remainder)
        num_others = num_panels - 1
        other_weight = 15
        price_weight = 100 - (other_weight * num_others)
        ratios = [price_weight] + [other_weight] * num_others
        
        # Calculate Stats (Handle NaNs from Reindexing)
        company = getattr(self.app, 'company_name', self.app.current_ticker)
        
        valid_closes = df['close'].dropna()
        if not valid_closes.empty:
            start_price = valid_closes.iloc[0]
            end_price = valid_closes.iloc[-1]
            
            # Use Previous Close for 1D Daily Change
            if self.app.time_window_var.get() == "1D":
                if self.app.previous_close > 0: start_price = self.app.previous_close
                if self.app.current_price > 0: end_price = self.app.current_price
        else:
            start_price = 0.0
            end_price = 0.0
            
        change = end_price - start_price
        pct_change = (change / start_price) * 100 if start_price != 0 else 0
        sign = "+" if change >= 0 else ""
        color = "green" if change >= 0 else "red"
        
        # Draw Titles (1-Liner) with Adaptive Precision
        fmt = ".4f" if end_price < 2.0 else ".2f"
        title_text = f"{company} ({self.app.time_window_var.get()})   {end_price:{fmt}} {sign}{change:{fmt}} ({sign}{pct_change:.2f}%)"
        if self.app.time_window_var.get() == "1D":
             title_text += "   (15min Delayed)"
        self.fig.suptitle(title_text, fontsize=base_font_size+4, fontweight='bold', color=color, y=0.98)
        
        # Create GridSpec (Adjust top for title)
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
            
            # Tick parameters
            if i < num_panels - 1:
                plt.setp(ax.get_xticklabels(), visible=False)
                ax.tick_params(axis='x', labelbottom=False)
            
            # Price Axis on LEFT
            ax.yaxis.set_label_position("left")
            ax.yaxis.tick_left()

        # Plot Price
        ax_price = axes['price']
        
        # --- Pre/Post Market Shading ---
        if self.app.time_window_var.get() == "1D" and self.app.show_prepost.get():
            try:
                # Find indices for Pre-Market (< 09:30)
                # We use the raw timestamps from df.index which are localized to US/Eastern
                # Pre-market: everything before 09:30
                # Post-market: everything after 16:00
                
                # Convert index to time-only for comparison or just hour/minute
                # Optimization: Do it vectorized or just find boundaries
                
                # We need x_indices (integers) limits.
                # 09:30 is the start of regular market. 16:00 is end.
                
                # Find the integer index where 09:30 starts
                # Timestamps are monotonic.
                
                start_regular = None
                end_regular = None
                
                times = df.index
                
                # Simple boolean mask approach might segment if there are gaps (though reindex should handle gaps with NaNs)
                # But x_indices are gapless 0..N
                
                # Find first index >= 09:30
                # Find first index >= 16:00
                
                # Helper to convert time to minutes from midnight for easy compare
                def time_to_min(t): return t.hour * 60 + t.minute
                
                cutoff_open = 9 * 60 + 30 # 09:30
                cutoff_close = 16 * 60    # 16:00
                
                # Pre-Market Shading: From 0 to match_open
                # Post-Market Shading: From match_close to end
                
                # Since df is reindexed to 1min frequency, we can rely on data being sorted
                
                # Find indices
                pre_mask = [time_to_min(t) < cutoff_open for t in times]
                post_mask = [time_to_min(t) >= cutoff_close for t in times]
                
                # Draw Pre shading if any
                if any(pre_mask):
                    pre_indices = x_indices[pre_mask]
                    if len(pre_indices) > 0:
                        ax_price.axvspan(pre_indices[0], pre_indices[-1], facecolor='#F0F0F0', alpha=0.5, edgecolor=None)
                
                # Draw Post shading if any
                if any(post_mask):
                    post_indices = x_indices[post_mask]
                    if len(post_indices) > 0:
                        ax_price.axvspan(post_indices[0], post_indices[-1], facecolor='#F0F0F0', alpha=0.5, edgecolor=None)
                        
            except Exception as e:
                print(f"Error drawing pre/post shading: {e}")
        # -------------------------------
        
        # Overlay Volume (Bottom 20%)
        if self.app.show_volume.get():
             self._plot_volume_overlay(ax_price, df, x_indices)
        
        # Plot Type Selection
        chart_type = self.app.chart_type_var.get()
        if chart_type == "Line":
            self._plot_line(ax_price, df, x_indices)
        else:
            self._plot_candles(ax_price, df, x_indices)

        self._plot_ma(ax_price, df, x_indices)
        self._plot_bbands(ax_price, df, x_indices)
        if self.app.show_vp.get():
             # Use RAW High-Res Data for Volume Profile if available
             # Filter raw_df to match the chart's time window start
             if not self.app.raw_df.empty:
                 start_date = df.index.min()
                 vp_data = self.app.raw_df[self.app.raw_df.index >= start_date]
                 
                 # Apply limit to match chart (e.g. remove post-market if hidden)
                 if self.app.current_data_interval == '1m' and not self.app.show_prepost.get():
                     try:
                        vp_data = vp_data.between_time('09:30', '16:00')
                     except: pass
                     
                 self._plot_volume_profile(ax_price, vp_data)
             else:
                 self._plot_volume_profile(ax_price, df)
            
        ax_price.grid(True, alpha=0.3)
        if self.app.show_legend.get() and any([v.get() for v in [self.app.show_ma5, self.app.show_ma20, self.app.show_ma50, self.app.show_ma60, self.app.show_ma100, self.app.show_ma120, self.app.show_ma200, self.app.show_ma250]]):
             ax_price.legend(loc='upper left', prop={'size': base_font_size},  bbox_to_anchor=(0.02, 0.98), ncol=2)

        # Calculate Price Limits explicitly
        y_min = df['low'].min()
        y_max = df['high'].max()
        
        # Include BBands in range if shown
        if self.app.show_bbards.get() and 'bb_upper' in df.columns:
            y_max = max(y_max, df['bb_upper'].max())
            y_min = min(y_min, df['bb_lower'].min())
            
        # Include MAs in range if shown
        ma_cols = [
            (self.app.show_ma5, 'ma5'), (self.app.show_ma20, 'ma20'), 
            (self.app.show_ma50, 'ma50'), (self.app.show_ma60, 'ma60'),
            (self.app.show_ma100, 'ma100'), (self.app.show_ma120, 'ma120'),
            (self.app.show_ma200, 'ma200'), (self.app.show_ma250, 'ma250')
        ]
        for var, col in ma_cols:
            if var.get() and col in df.columns:
                 valid_ma = df[col].dropna()
                 if not valid_ma.empty:
                     y_max = max(y_max, valid_ma.max())
                     y_min = min(y_min, valid_ma.min())
            
        # Add padding
        # Validation for NaN/Inf
        if pd.isna(y_min) or pd.isna(y_max) or y_min == float('inf') or y_min == float('-inf'):
            y_min, y_max = 0, 100 # Default fallback
            
        # Add padding (Recalculate with safe values)
        pad = (y_max - y_min) * 0.05
        if pd.isna(pad): pad = 0
        
        # FIX: Ensure pad is non-zero to avoid singular transformation (ylim(x, x))
        if pad == 0:
            pad = (y_max * 0.01) if y_max != 0 else 1.0 # 1% Padding or 1.0 for zero
            
        ax_price.set_ylim(y_min - pad, y_max + pad)

        # Plot Other Panels
        if 'macd' in axes:
            self._plot_macd(axes['macd'], df, x_indices)
        if 'rsi' in axes:
            self._plot_rsi(axes['rsi'], df, x_indices)
            
        # Format X-Axis on the Bottom Panel
        bottom_panel = panels[-1]
        bottom_ax = axes[bottom_panel]
        self._setup_date_axis(bottom_ax, df, self.app.time_window_var.get())
        
        # Set margins to 0
        bottom_ax.set_xlim(-0.5, len(df) - 0.5)
        
        # Setup Crosshair Labels (Hidden by default)
        for name, ax in axes.items():
             lbl = ax.text(1.01, 0.5, "", transform=ax.transAxes, 
                           color='black', bbox=dict(boxstyle='round', facecolor='white', alpha=0.9, edgecolor='black'), ha='left',
                           fontsize=base_font_size)
             lbl.set_visible(False)
             self.panel_labels[ax] = {'label': lbl, 'name': name}

        # Date Label
        self.crosshair_date_lbl = ax_price.text(0.5, 1.0, "", transform=ax_price.transAxes, 
                                                color='black', ha='center', va='top', fontsize=base_font_size,
                                                bbox=dict(boxstyle='round', facecolor='white', alpha=0.9, edgecolor='none'))
        self.crosshair_date_lbl.set_visible(False)
        
        # Volume Label
        bottom_panel = panels[-1]
        bottom_ax = axes[bottom_panel]
        self.crosshair_vol_lbl = bottom_ax.text(0.99, 0.02, "", transform=bottom_ax.transAxes,
                                               color='black', ha='right', va='bottom', fontsize=base_font_size, fontweight='bold',
                                               bbox=dict(boxstyle='round', facecolor='white', alpha=0.8, edgecolor='none'))
        self.crosshair_vol_lbl.set_visible(False)
        
        # Setup Crosshair Lines
        self.crosshair_lines['vert'] = []
        self.crosshair_lines['horiz'] = []
        
        init_price = df['close'].iloc[-1]
        
        for ax in axes.values():
            # Vertical Line (shared x)
            vl = ax.axvline(x=len(df)-1, color='darkred', linestyle=':', lw=1.0, visible=False)
            self.crosshair_lines['vert'].append(vl)
            
            # Horizontal Line (per axis)
            curr_y = init_price if ax == ax_price else 0
            hl = ax.axhline(y=curr_y, color='darkred', linestyle=':', lw=1.0, visible=False)
            self.crosshair_lines['horiz'].append(hl)

        self.axes_dict = axes 
        self.canvas.draw()

    def _plot_candles(self, ax, df, x_indices):
        up = df['close'] >= df['open']
        down = df['close'] < df['open']
        width = 0.6
        
        up_idx = x_indices[up].astype(int)
        ax.vlines(up_idx, df.loc[up, 'low'], df.loc[up, 'high'], color='green', linewidth=1)
        ax.bar(up_idx, df.loc[up, 'close'] - df.loc[up, 'open'], width, bottom=df.loc[up, 'open'], color='white', edgecolor='green', linewidth=1, align='center')
        
        down_idx = x_indices[down].astype(int)
        ax.vlines(down_idx, df.loc[down, 'low'], df.loc[down, 'high'], color='red', linewidth=1)
        ax.bar(down_idx, df.loc[down, 'open'] - df.loc[down, 'close'], width, bottom=df.loc[down, 'close'], color='red', edgecolor='red', linewidth=1, align='center')

    def _plot_line(self, ax, df, x_indices):
        # Determine Color based on Trend (Last Close vs First Close)
        # Or just standard Blue? User requested "simple curve line".
        # Let's use a nice professional Blue.
        line_color = '#007ACC'
        
        ax.plot(x_indices, df['close'], color=line_color, linewidth=1.5, label='Price')
        
        # Optional: Fill Area under curve for modern look? No, user asked specific simple curve.

    def _plot_ma(self, ax, df, x_indices):
        if self.app.show_ma5.get(): ax.plot(x_indices, df['ma5'], label='MA5', color='cyan', linewidth=0.8, alpha=0.9)
        if self.app.show_ma20.get(): ax.plot(x_indices, df['ma20'], label='MA20', color='green', linewidth=0.8, alpha=0.9)
        if self.app.show_ma50.get(): ax.plot(x_indices, df['ma50'], label='MA50', color='orange', linewidth=0.8, alpha=0.9)
        if self.app.show_ma60.get(): ax.plot(x_indices, df['ma60'], label='MA60', color='blue', linewidth=0.8, alpha=0.9)
        if self.app.show_ma100.get(): ax.plot(x_indices, df['ma100'], label='MA100', color='purple', linewidth=0.8, alpha=0.9)
        if self.app.show_ma120.get(): ax.plot(x_indices, df['ma120'], label='MA120', color='magenta', linewidth=0.8, alpha=0.9)
        if self.app.show_ma200.get(): ax.plot(x_indices, df['ma200'], label='MA200', color='red', linewidth=0.8, alpha=0.9)
        if self.app.show_ma250.get(): ax.plot(x_indices, df['ma250'], label='MA250', color='brown', linewidth=0.8, alpha=0.9)

    def _plot_bbands(self, ax, df, x_indices):
        if self.app.show_bbards.get():
            ax.plot(x_indices, df['bb_upper'], color='gray', linestyle='--', alpha=0.5, linewidth=0.8)
            ax.plot(x_indices, df['bb_lower'], color='gray', linestyle='--', alpha=0.5, linewidth=0.8)
            ax.fill_between(x_indices, df['bb_upper'], df['bb_lower'], color='gray', alpha=0.1)

    def _plot_volume_overlay(self, ax, df, x_indices):
        colors = ['green' if c >= o else 'red' for c, o in zip(df['close'], df['open'])]
        
        ax_vol = ax.twinx()
        ax_vol.bar(x_indices.astype(int), df['volume'], color=colors, width=0.6, align='center', alpha=0.3)
        
        max_vol = df['volume'].max()
        if max_vol > 0:
            ax_vol.set_ylim(0, max_vol * 4)
            
        ax_vol.set_yticks([]) 
        ax_vol.set_zorder(0) 
        ax.set_zorder(1)
        ax.patch.set_visible(False)

    def _plot_macd(self, ax, df, x_indices):
        ax.plot(x_indices, df['macd'], color='blue', label='MACD')
        ax.plot(x_indices, df['signal'], color='orange', label='Signal')
        colors = ['green' if val >= 0 else 'red' for val in (df['macd'] - df['signal'])]
        ax.bar(x_indices.astype(int), df['macd'] - df['signal'], color=colors, width=1.0, align='center')
        ax.grid(True, alpha=0.3)
        ax.set_ylabel("") 
        ax.legend(loc='upper left', prop={'size': self.app.font_size_var.get()})

    def _plot_rsi(self, ax, df, x_indices):
        ax.plot(x_indices, df['rsi'], color='purple')
        ax.axhline(70, color='red', linestyle='--', alpha=0.5)
        ax.axhline(30, color='green', linestyle='--', alpha=0.5)
        ax.grid(True, alpha=0.3)
        ax.set_ylabel("")
        ax.text(0.02, 0.05, "RSI", transform=ax.transAxes, fontweight='bold', fontsize=self.app.font_size_var.get(), color='purple')

    def _plot_volume_profile(self, ax, df):
        price_min = df['low'].min()
        price_max = df['high'].max()
        
        try:
             mode_str = self.app.vp_mode_var.get()
             num_bins = int(mode_str.split()[0])
        except:
             num_bins = 100 
             
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
        
        ax_vp.set_zorder(0)
        ax.set_zorder(1)
        ax.patch.set_visible(False)
        
        max_vol = max(volume_profile) if volume_profile else 0
        if max_vol > 0:
            ax_vp.set_xlim(0, max_vol * 4)
        
        if self.app.vp_position.get() == "Right":
            ax_vp.invert_xaxis()

    def _on_mouse_down(self, event):
        if not event.inaxes or self.app.history_df.empty:
            return
        if event.button != 1: 
            return
            
        self.is_dragging = True
        
        target_axis = event.inaxes
        ax_price = self.axes_dict.get('price')
        if ax_price and target_axis != ax_price:
             if target_axis.get_position().bounds == ax_price.get_position().bounds:
                 target_axis = ax_price
                 
        self._update_crosshair(event.xdata, event.ydata, target_axis)

    def _on_mouse_up(self, event):
        self.is_dragging = False
        if hasattr(self, 'panel_labels'):
             for info in self.panel_labels.values():
                 info['label'].set_visible(False)
             self.crosshair_date_lbl.set_visible(False)
             self.crosshair_vol_lbl.set_visible(False)
             
             for line in self.crosshair_lines['vert'] + self.crosshair_lines['horiz']:
                 line.set_visible(False)
             self.canvas.draw_idle()

    def _on_mouse_move(self, event):
        if not event.inaxes or self.app.history_df.empty or not self.is_dragging:
            return
            
        target_axis = event.inaxes
        ax_price = self.axes_dict.get('price')
        
        if ax_price and target_axis != ax_price:
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

        # Update Vertical Lines
        for line in self.crosshair_lines['vert']:
            line.set_xdata([x_idx]) 
            line.set_visible(True)
            
        # Update Horizontal Lines
        for line in self.crosshair_lines['horiz']:
            if line.axes == in_axes:
                line.set_ydata([price])
                line.set_visible(True)
            else:
                line.set_visible(False)
        
        # Update Y Labels 
        if hasattr(self, 'panel_labels'):
            for info in self.panel_labels.values():
                info['label'].set_visible(False)
                
            if in_axes in self.panel_labels:
                info = self.panel_labels[in_axes]
                lbl = info['label']
                name = info['name']
                
                if name == 'volume':
                    val_str = f"{int(price):,}"
                else:
                    # Adaptive Precision for FX/Penny Stocks
                    if abs(price) < 2.0:
                         val_str = f"{price:.4f}"
                    else:
                         val_str = f"{price:.2f}"
                
                lbl.set_text(val_str)
                
                ymin, ymax = in_axes.get_ylim()
                rng = ymax - ymin
                if rng == 0: rng = 1
                y_rel = (price - ymin) / rng
                lbl.set_position((1.01, y_rel))
                lbl.set_visible(True)
            
            # Update Date Label
            window = self.app.time_window_var.get()
            interval = self.app.current_data_interval
            
            if window == '1WK': # 10m Interval
                dt_end = current_date + timedelta(minutes=10)
                # If end time crosses 16:00, clamp it? No, standard 10m bars end at :00, :10 etc.
                # If bar is 15:50, it ends 16:00.
                date_str = f"{current_date.strftime('%Y-%m-%d %H:%M')} / {dt_end.strftime('%H:%M')}"
                
            elif window in ['1M', '3M', 'YTD'] and ('h' in interval): # Hourly Mode (including YTD if recent)
                # Standard: Add 1 hour
                # Exception: 09:30 bar -> 10:30 (1 hr)
                # Exception: 15:30 bar -> 16:00 (30 min)
                if current_date.hour == 15 and current_date.minute == 30:
                     dt_end = current_date + timedelta(minutes=30)
                else:
                     dt_end = current_date + timedelta(hours=1)
                date_str = f"{current_date.strftime('%Y-%m-%d %H:%M')} / {dt_end.strftime('%H:%M')}"
            
            elif window == 'YTD': # Daily Mode fallback
                 date_str = current_date.strftime('%Y-%m-%d')
            
            elif window in ['10Y', '20Y'] or interval == '1mo':
                import calendar
                last_day = calendar.monthrange(current_date.year, current_date.month)[1]
                dt_start = current_date.replace(day=1)
                dt_end = current_date.replace(day=last_day)
                date_str = f"{dt_start.strftime('%Y-%m-%d')} / {dt_end.strftime('%Y-%m-%d')}"
            
            elif window == '5Y': # Weekly
                dt_start = current_date - timedelta(days=current_date.weekday()) 
                dt_end = dt_start + timedelta(days=4)
                date_str = f"{dt_start.strftime('%Y-%m-%d')} / {dt_end.strftime('%Y-%m-%d')}"
            
            elif window in ["2Y", "3Y"]:
                try:
                    row = self.app.history_df.loc[current_date]
                    if 'period_start' in row:
                        start_ts = pd.Timestamp(row['period_start'])
                        date_str = f"{start_ts.strftime('%Y-%m-%d')} / {current_date.strftime('%Y-%m-%d')}"
                    else:
                        date_str = current_date.strftime('%Y-%m-%d')
                except:
                     date_str = current_date.strftime('%Y-%m-%d')

            elif 'm' in self.app.current_data_interval or 'h' in self.app.current_data_interval:
                date_str = current_date.strftime('%Y-%m-%d %H:%M')
            else:
                date_str = current_date.strftime('%Y-%m-%d')
            self.crosshair_date_lbl.set_text(date_str)
            
            # --- OHLC Enhancement ---
            try:
                row_data = self.app.history_df.loc[current_date]
                o = row_data['open']
                h = row_data['high']
                l = row_data['low']
                c = row_data['close']
                
                # Adaptive formatting
                fmt = ".4f" if c < 2.0 else ".2f"
                ohlc_text = f"\nO : {o:{fmt}}, C : {c:{fmt}}\nH : {h:{fmt}}, L : {l:{fmt}}"
                self.crosshair_date_lbl.set_text(date_str + ohlc_text)
            except Exception:
                pass # Fallback to just date
            # ------------------------
            
            ax_price = self.axes_dict['price']
            xmin, xmax = ax_price.get_xlim()
            rng_x = xmax - xmin
            if rng_x == 0: rng_x = 1
            x_rel = (x_idx - xmin) / rng_x
            
            self.crosshair_date_lbl.set_position((x_rel, 1.0))
            self.crosshair_date_lbl.set_visible(True)
            
            # Update Volume Label
            if self.app.show_volume.get():
                try:
                    vol = self.app.history_df.loc[current_date]['volume']
                    if pd.notna(vol):
                        self.crosshair_vol_lbl.set_text(f"Vol: {int(vol):,}")
                        self.crosshair_vol_lbl.set_visible(True)
                except: pass
            
            self.canvas.draw_idle()
