# AI Development Log: The "Vibe Coding" Journey

This document chronicles the step-by-step evolution of the **DIY Stock Chart** application. It serves as a historical record of how a simple CLI script was transformed into a professional-grade GUI tool through iterative "Vibe Coding" (Prompt -> Error -> Fix -> Refine).

**Project Stats:**
*   **Timeline**: Dec 25 - Jan 31 (37 Days Elapsed)
*   **Active Vibe Coding Time**: ~35.5 Hours
    *   *Session 1*: ~0.5 Hrs (Dec 25) - "Genesis"
    *   *Session 2*: ~2.5 Hrs (Dec 26) - "Core Logic"
    *   *Session 3*: ~5.5 Hrs (Dec 27) - "Volume & Grid"
    *   *Session 4*: ~4.0 Hrs (Dec 29) - "Polishing"
    *   *Session 5*: ~2.0 Hrs (Dec 30) - "Publishing"
    *   *Session 6*: ~4.0 Hrs (Dec 31) - "Floating Info Panel"
    *   *Session 7*: ~2.0 Hrs (Jan 11) - "Watch List"
    *   *Session 8*: ~4.0 Hrs (Jan 12) - "Refactoring & Visuals"
    *   *Session 9*: ~3.0 Hrs (Jan 23) - "Pre/Post Market & Outliers"
    *   *Session 10*: ~3.0 Hrs (Jan 25) - "Chart Types & Bug Fixes"
    *   *Session 11*: ~4.5 Hrs (Jan 26) - "Optimization & Precision Mechanics"
    *   *Session 12*: ~3.5 Hrs (Jan 31) - "Global Assets & Data Smoothing"

---

## 📅 Session Chronology

### Phase 1: The Transition (CLI to GUI)
**Initial State**: A set of loose python scripts (`generate-charts.py`, `stock-history-download.py`) that generated static PNG images.
**User Prompt**: *"Based on the generate-charts.py, I want to make a interactive GUI app... input ticker name... show chart."*
*   **Challenge**: Migrating from static `matplotlib.pyplot` to an interactive `tkinter` application with an embedded canvas.
*   **Solution**: Created `stock_chart_app.py`, implementing a `Tkinter` class structure with a persistent `FigureCanvasTkAgg` and a threaded download worker queue to prevent UI freezing.

### Phase 2: Visual & Data Refinement
**User Prompt**: *"Your script does draw all indicators. But, you put the main chart section the price to small... should take 60%."*
*   **Fix**: Implemented `GridSpec` with explicit `height_ratios=[3, 1, 1]` to prioritize the price panel.

**User Prompt**: *"I want to advance my chart a bit... candle bars... green/red for up or down..."*
*   **Challenge**: Drawing custom candlesticks instead of using a library like `mplfinance` (to maintain control).
*   **Solution**: Manually plotted bars using `ax.bar()`: one wide bar for the body (Open-Close) and a thin bar for the wick (High-Low).

**User Prompt**: *"The Start up font is very small... cross hair move with mouse but it leaves all traces..."*
*   **Error**: `blitting` issues caused old crosshair lines to remain on screen.
*   **Fix**: Implemented `ax.draw_artist()` and `canvas.blit()` optimizations to clear and redraw only the crosshair layer, solving the "trace" issue.

### Phase 3: The Volume Profile Algorithms
**User Prompt**: *"When you drop volume profile, how do you determine the precision... is it 1 bar 1 dollar?"*
*   **Research**: Investigated how Interactive Brokers and TradingView calculate VP. found they use a "Fixed Number of Rows" (VPVR) approach.
*   **Initial Fail**: Tried to use a fixed "Price Step" (e.g., $1.00), which broke on low-priced stocks.
*   **Solution**: Switched to **100/200/400 Bin Mode**. Algorithm: `BinHeight = (Max - Min) / N`. This ensures consistent density regardless of price range.

**User Prompt**: *"If you change the 5Y and 10Y calculation to use daily price point, It will be more accurate."*
*   **Refinement**: Upgraded the 5Y/10Y profiles to download **Daily Data** in the background (instead of Weekly/Monthly) but still plot Weekly/Monthly candles. This gives "High-Definition" volume profiles on "Low-Resolution" charts.

### Phase 4: Time Axis & Resampling Logic
**User Prompt**: *"For the 1 week chart, we should use 10 or 15 minute interval instead of hourly data."*
*   **Logistics**: `yfinance` only provides 60 days of intraday data.
*   **Solution**: Implemented a hybrid fetching strategy. If "1WK" is selected, fetch `5m` data for the last 5 trading days and `resample('10T')` to create custom 10-minute bars.

**User Prompt**: *"Can you explain how you did resampling rule 2D 3D?"*
*   **Algorithm**: Implemented a Custom Aggregator that respects **Trading Days**.
    *   `2D` = Group index `// 2`. This ensures Thursday+Friday are grouped (2 days), and Monday+Tuesday are grouped (2 days), skipping the designated weekend gap entirely.

### Phase 5: The "Overlay" & Layout Complexities
**User Prompt**: *"I see the popular website draw volume and price together so that the long term MA can start lower..."*
*   **Challenge**: Maximizing screen real estate.
*   **Implementation**: Used `ax.twinx()` to overlay volume bars on the bottom 25% of the Price Panel.
*   **The Critical Bug**: *"The cross hair is not drawing anything now."*
    *   **Root Cause**: The new invisible Volume Overlay axis was "on top" of the Price axis, intercepting all mouse events.
    *   **Fix**: Added Event Routing in `_on_mouse_move`. If the event target is the "Twin Axis", map it back to the "Price Axis" context so the crosshair logic can find the date/price data.

**User Prompt**: *"Since volume is in price panel... make the price panel at least 70%... other 2 panels 15% each."*
*   **Algorithm**: Developed a Dynamic Weight system.
    *   Base Weights: Price=100, Others=15.
    *   Formula: `Price_Ratio = 100 - (15 * num_visible_panels)`.
    *   Result: Closing the RSI panel immediately transfers that 15% vertical space to the Price panel.

### Phase 6: Final Polish
*   **User Prompt**: *"Change the title... to DIY Stock Chart"* -> Rebranded.
*   **User Prompt**: *"The volume number can be shown at the right bottom..."* -> Relocated floating labels to avoid overlapping with Moving Average legends.
*   **User Prompt**: *"make 60 and 120 unchecked by default."* -> Configured default visibility states in `_setup_ui`.

---

### Phase 7: The "Floating Panel" Odyssey
**User Prompt**: *"I want to add a retractable pannel... occupy exactly 30%... scrollable."*
*   **Attempt 1**: Implemented a `PanedWindow` (Split View).
*   **Feedback**: *"The retractable is ugly... make a floatable panel... I can manually drag it."*

**The "High-DPI" Trap (The Drifting Bug)**
*   **Attempt 2**: Created a native floating frame with mouse-drag bindings.
*   **Critical Failure**: *"Once I click title, it moved to right edge... drifting... gap is constant."*
*   **Root Cause**: Windows Display Scaling (125%/150%) causes coordinate mismatches between Python's virtual pixels and the OS's physical pointer.
*   **The Pivot**: Proposed **"Corner Snapping"** instead of dragging.
    *   **User Decision**: *"Go ahead."*
    *   **Result**: Implemented a Dropdown (`Bottom-Right`, `Center`, etc.) using `relx/rely` positioning. **Zero Drift. 100% Stable.**

**Visual Polish (Auto-Sizing)**
*   **User Prompt**: *"Panel size does not change with font... attributes cut."*
*   **Fix 1**: Hooked into `update_ui_font` to sync panel font.
*   **Fix 2**: Removed fixed `height=600`. Enabled **Tkinter Auto-Sizing** to "shrink-wrap" the panel around the text, regardless of font size.

**Data Forensics: Stock vs. ETF**
*   **Challenge**: *"SPY missing expense ratio... AAPL yield is 3800%... PEG missing."*
*   **Investigation**: Created temporary debug scripts (`debug_peg.py`, `debug_etf.py`) to inspect raw `yfinance` dumps.
*   **Discoveries & Fixes**:
    1.  **PEG Ratio**: specific key `trailingPegRatio` was needed for AAPL (hidden from standard `pegRatio`).
    2.  **ETF Beta**: ETFs store beta in `beta3Year`, not `beta`.
    3.  **Expense Ratio**: Found in `netExpenseRatio`. Raw value `0.09` is already %, needed formatting fix.
    4.  **Dividend Yield**: 
        *   *Stock*: Manually calculated `Rate/Price` to fix API scaling errors.
        *   *ETF*: Switched to `yield` key (SEC 30-Day Yield) to match Yahoo Finance website (1.06% vs 0.83% TTM).
    5.  **Crash**: Fixed `UnboundLocalError: q_type` by hoisting type-check logic.

---

### Phase 8: Floating Panel Redux & Refinement
**User Prompt**: *"I want to convert the info panel to be floatable... use mouse to drag... control on menu bar like a check box."*
*   **The Pivot Back**: After previously abandoning dragging due to DPI bugs, we revisited it with a robust **Screen-Relative Coordinate** system.
*   **Implementation**:
    *   **Controls**: Swapped the "Position Dropdown" for a simple "Show Info" Toolbar Checkbox.
    *   **Drag Logic**: Implemented `dx = event.x_root - start_x` logic. Using screen-root coordinates solved the "Drifting" issue encountered in Phase 7.
    *   **Sync**: Clicking the panel's "X" button programmatically unchecks the toolbar box.

**User Prompt**: *"Improve: Auto-center on 1st time... Title should be company name... Narrower width."*
*   **Refinement 1 (Auto-Center)**: Added logic to calculate `(Screen_W - Panel_W) // 2` on first launch.
*   **Refinement 2 (Smart Formatting)**: Large stock prices (like **BRK-A** > ) broke the layout. Implemented a `trim_large` formatter to remove decimals for values > 10,000.
*   **Refinement 3 (Positioning)**: Adjusted "Center" to be "Upper Center" (10% from top) per user preference for better visibility.

---

### Phase 9: The Watch List & Management Overlay
**User Prompt**: *"I want to add a watch list function... click icon... add current ticker... dropdown list... saved in csv."*
*   **Implementation**:
    *   **The Star Icon**: Added a toggleable `★` button to the chart frame.
    *   **CSV Persistence**: Implemented `load_watchlist()` / `save_watchlist()` using Python's `csv` module to store favorites in `conf/watchlist.csv`.
    *   **Overlay UI**: Created a custom `Frame` overlay (instead of native OS popups) for seamless integration.

**User Prompt**: *"Popup is very small... I don't want a windows system popup."*
*   **Evolution of the Management UI**:
    1.  **Initial Attempt**: Small popup. User feedback: *"Not usable."*
    2.  **Refinement**: Increased size to 600x480px.
    3.  **Dynamic Sizing**: Replaced fixed dimensions with a content-aware sizing formula (`w = 600`, `h = calculated`).
    4.  **Feature Additions**: Added "Remove Ticker", "Delete List", and "Rename List" buttons.

**User Prompt**: *"Crash: unknown option -activator"*
*   **Fix**: Identified and removed an invalid Tkinter option `activator="dotbox"` that caused the app to crash on opening the management menu.

### Phase 10: 20-Year Horizon & Visual Tweaks
**User Prompt**: *"Change cross hair lines to dotted line in dark red... add a 20Y option."*
*   **Visual Refinement**: Updated crosshair to use `darkred` color and dotted line style (`:`) for better visibility against the chart background.
*   **20-Year View**:
    *   **Logic**: Implemented a `20Y` window mirroring the `10Y` logic (Monthly resolution, `1ME` resampling).
    *   **Filtering**: Updated data fetcher to filter exactly 20 years from the latest date.

**User Prompt**: *"In 20Y chart... only 1 date... ticks are too tight."*
*   **Crosshair Date Fix**: The crosshair originally showed a single date for the 20Y view. Updated the logic to identify `20Y` as a Monthly view, displaying the full Start/End range (e.g., `2024-01-01 / 2024-01-31`).
*   **Axis Tick Optimization**: The initial 20Y implementation labeled *every* month (240 ticks!), making the X-axis unreadable. Added `20Y` to the "Long Term" sparse labeling group to use **Quarterly** ticks (every 3 months), matching the clean look of the 10Y chart.

### Phase 11: Watch List Perfection
**User Prompt**: *"Separate 'Quick Remove' and 'Multi-Select Add' features."*
*   **Quick Toggle**: Changed logic for the Star button.
    *   **Previous**: Clicking a filled star allowed re-adding/moving.
    *   **New**: Clicking a filled star **instantly removes** the ticker from *all* watch lists. This streamlines the common workflow of "checking off" a watched item.
*   **Multi-Select Overlay**:
    *   **Problem**: Dropdown menu required multiple clicks/re-opens to add a ticker to multiple groups.
    *   **Solution**: Replaced `Combobox` with a multi-select `Listbox`. Users can now Ctrl+Click to select multiple target lists in a single action.

---

### Phase 12: The Great Refactoring
**User Prompt**: *"The app_stock_chart.py is monolithic. many functions are in one file. I want to re-org the file into smaller files... ZERO logic change."*
*   **Analysis**: The main file had grown to over 2000 lines, mixing UI, data fetching, math, and plotting logic.
*   **Modularization Strategy**:
    *   **`stock_util.py`**: Extracted all `yfinance` interaction, caching, dataframe resampling, and indicator math (`finta`).
    *   **`chart_drawing.py`**: Encapsulated the complex Matplotlib logic (Figure, Canvas, Axes, Events, Crosshair).
    *   **`watchlist.py`**: Consolidated the CSV management (`WatchListManager`) and the UI Overlays (`WatchListUI`) into a single cohesive module.
    *   **`info_panel.py`**: Isolated the floating "Stock Info" panel logic.
    *   **`app_stock_chart.py`**: Reduced to a clean skeleton that initializes the UI and delegates work to the new modules.
*   **Outcome**: The code is now significantly easier to maintain and extend, with clear separation of concerns.

### Phase 13: Enhanced Crosshair & Visual Tuning
**User Prompt**: *"I want to have the 2nd line and 3rd line to show O/C/H/L price... upper left corner legend is blocking... switch MA colors..."*
*   **OHLC Crosshair**: 
    *   Modified `chart_drawing.py` to fetch row data using `df.loc[current_date]`. This ensures the displayed Open/High/Low/Close matches the specific bar under the cursor (Time-Index Lookup) regardless of zoom level.
    *   Updated the tooltip to show a 3-line summary (Date / Open-Close / High-Low) aligned to the top edge of the chart.
*   **Legend Toggle**: Added a "Legend" checkbox to the toolbar. Users can now hide the top-left MA labels to prevent them from obscuring the new crosshair text.
*   **Visual Polish**:
    *   **MA Customization**: Switched MA 50/100 colors and updated MA 60 to Blue/MA 5 to Cyan based on user preference.
    *   **Volume Profile**: Changed default bin count from 100 to 200 for better initial precision.
### Phase 14: The Pre/Post Market & Outlier Odyssey
**User Prompt**: *"I want to see pre-market and post-market data... add a toggle... huge spikes 420-480... fix it."*
*   **The Feature**: Added a "Pre/Post" checkbox that dynamically resamples the 1-Day chart to cover 04:00-20:00.
*   **The Bug (Data Quality)**: `yfinance` raw data contained massive price spikes (e.g., $420 drop then back to $450) in extended hours, rendering the chart unreadable (Scale 0-1000).
*   **Research**: Investigated the official Yahoo Finance website and found their charts are clean. Confirmed `yfinance` serves raw, unfiltered ticks.
*   **The Solution (Sequential Filter)**: Implemented a robust **Sequential Outlier Filter**.
    *   Iterates minute-by-minute.
    *   Uses the *previous minute's Close* as the "Truth Baseline".
    *   If the current minute deviates >1% (Pre/Post) or >3% (Market), it resets the candle to the baseline.
    *   *Result*: A perfectly smooth, professional-grade chart that matches the official website's quality.
*   **Visuals**: Added gray background shading to visually distinguish Pre-Market (04:00-09:30) and Post-Market (16:00-20:00) sessions.

### Phase 15: Data Integrity & Smart Merging
**User Prompt**: *"The volume profile bins are wrong when Pre/Post is off... 1 minute data has gaps."*
*   **Smart Merging**: `yfinance` often returns partial datasets for usage limits. Implemented a "Smart Merge" system that downloads fresh data and carefully stitches it into the existing cache, strictly deduplicating by Time Index.
*   **Volume Profile Fix**: The VP algorithm originally calculated bins based on the *entire* day's range (including invisible post-market data). Updated logic to filter VP source data to strictly match the visible 09:30-16:00 window when the "Pre/Post" toggle is off.

### Phase 16: Visual Precision & Chart Types
**User Prompt**: *"Why the last trade day was not drawn on the chart?"*
*   **The Bug**: 1Y/2Y/3Y charts were missing the current/last trading day (Friday).
*   **Root Cause**: `yfinance` API uses an exclusive end date parameter. Requesting `end='2026-01-23'` results in data up to Jan 22.
*   **The Fix**: Updated the fetcher to always request `end = Today + 1 Day` to capture the full session. Added cache validation to redownload stale files.

**User Prompt**: *"I want to add a menu drop down for line chart and candle chart."*
*   **Implementation**: Added a "Type" dropdown to the toolbar.
    *   **Candle**: Uses the custom `_plot_candles` renderer.
    *   **Line**: Implemented `_plot_line` connecting Close Prices with a professional blue curve.
*   **Value Add**: Allows for cleaner long-term trend analysis without the noise of daily wicks.

**User Prompt**: *"I want to show time with from/to... 9:30 should show 9:30 / 9:40."*
*   **Refinement**: Upgraded the Crosshair Tooltip for intraday charts.
    *   **1WK**: Displays 10-minute ranges (`09:30 / 09:40`).
    *   **1M/3M**: Displays Hourly ranges (`10:30 / 11:30`).
    *   **The 15:30 Edge Case**: Added specific logic for the final trading bar (15:30) to show the end time as `16:00` (Market Close) instead of 16:30.

---

### Phase 17: Caching & Precision Engineering
**User Prompt**: *"Why does it take 8 seconds to start? I want it to be instant."*
*   **Optimization 1 (Incremental Caching)**: Implemented a persistent CSV cache mechanism.
    *   **Logic**: Before downloading, the app checks for existing `ticker_interval_date.csv`.
    *   **Smart Append**: If found, it selectively downloads only the *new* data (Delta) and merges it.
    *   **Safety**: Added logic to detect "Stock Splits" in the delta; if found, it discards the cache and performs a full clean download.
*   **Optimization 2 (Metadata Sidecar)**: Basic info (Sector, Name) was blocking the main thread.
    *   **Fix**: Cached metadata in lightweight `csv/{Ticker}_info.csv` sidecar files.
    *   **Validity**: This data is considered valid for 30 days. The app reads from disk instantly (0ms) instead of hitting the API, making chart switching instantaneous.

**User Prompt**: *"1WK chart is missing bars... 5Y/10Y chart missing current period."*
*   **The Resampling Bug**: The standard `resample('1ME')` logic (Month End) naturally excludes the current partial month.
*   **The Fix**:
    *   **Long Term**: Switched to `MS` (Month Start) and `W-MON` (Week Start) rules. This forces the current/partial data to be bucketed into the "Start of Period", ensuring the latest forming candle is always visible.
    *   **Intraday (1WK)**: Updated the 5-minute resampling logic to `closed='left'` to ensure the final partial 10-minute bar (e.g., 11:20-11:30) is preserved even if we are at 11:27.

**User Prompt**: *"For low priced stocks, I want 4 decimal precision... but keep 2 for others."*
*   **Adaptive Precision**: Implemented dynamic formatting logic in the Crosshair and Title.
    *   **Algorithm**: `decimals = 4 if price < 2.0 else 2`.
    *   **Result**: Displays `1.2345` for penny stocks/FX, but `450.20` for SPY.

**User Prompt**: *"SPY cache is stale... shows 11:30 when it is 11:55."*
*   **The Intraday Cache Paradox**: The incremental updater initially skipped downloading if "Last Date == Today".

### Phase 18: Global Assets & Data Integrity Overhaul
**User Prompt**: *"Investigate MSFT data... flat line... Global assets empty at night."*
*   **Global Assets (Forex/Crypto)**:
    *   **Logic**: Recognized `CAD=X`, `BTC-USD`, `GC=F` as 24/7 assets.
    *   **Fix**: Bypassed "Market Hours" filters for these types. Implemented a "Calendar Day" view (00:00 - 23:59) to capture overnight moves.
*   **Data Integrity (The MSFT Fix)**:
    *   **The Bug**: MSFT dropped 10% on earnings, but the chart showed a flat line.
    *   **Root Cause**: The "Sequential Outlier Filter" (Phase 14) was *too good*. It flagged the 10% drop as an error and "corrected" it to the previous day's price.
    *   **The Fix**: **Removed** the outlier filter entirely. Trust the raw feed. Real volatility > Smooth fake charts.
*   **Visual Gap Filling (The Smoothing)**:
    *   **Problem**: Small cap stocks (e.g., `IFC.TO`) had gaps in 1-minute data, looking broken.
    *   **Solution**: Implemented "Visual Forward Fill".
        *   If minute `T` is missing, draw a **Flat Candle** (`O=C=H=L=LastClose`) with **Volume=0**.
        *   This creates a "dash" indication of no-trade, visually smoothing the chart without corrupting the data.
*   **Fast Polling**: Increased auto-refresh rate from 60s to **15s** to better capture fleeting data points for illiquid stocks.

### Phase 19: The "Smart Axis" Revolution
**User Prompt**: *"The 3M chart starts with Oct 30... labels are squeezed... 1 mon chart jammed at begin/end... 6 mon chart missing middle marks."*
*   **The Problem**: The linear X-axis logic caused label collisions at the start of charts (e.g., "Jan 01" overlapping with "Dec 31") and erratic spacing on long-term views.
*   **Solution**: Implemented a **Backtrack Collision Resolution** algorithm.
    *   **Logic**: Before adding a label, check the distance to the *previous* label. If `< Threshold`, resolve conflict based on priority.
    *   **Priority System**: "Month Start" > "Day". If a new Month Start appears 2 days after a Day tick, the Day tick is retroactively deleted to make room.
    *   **Contextual Logic**:
        *   **Dense (3M/6M)**: Threshold = **6**. Allows mid-month ticks (e.g., 7th, 14th) to survive near month boundaries.
        *   **Hourly (1M)**: Threshold = **8**. Enforces an "Every Other Day" rhythm to prevent daily adjacent jamming.
        *   **Sparse (1Y+)**: Threshold = **10**. Prevents long month names (`Jan '25`) from overlapping.
*   **Value Add**: The X-axis now "breathes" correctly regardless of window size, always prioritizing the most significant time markers.

### Phase 20: Global Assets & Data Integrity (Part II)
**User Prompt**: *"Global assets empty at night... fix 1D view."*
*   **Calendar Day View**: For non-market assets (`CAD=X`, `BTC-USD`), we forced a **00:00 - 23:59** view, decoupling them from the standard NYSE 9:30-16:00 filter.
*   **Data Reliability**: Upgraded `fetch_stock_data` to request **5 Days** of minute data even for 1-Day charts. This safeguards against "Morning Data Loss" where `yfinance` returns only the current session (e.g., 6 PM - 8 PM) and forgets the 9 AM - 4 PM trading session of the *same calendar day*.

