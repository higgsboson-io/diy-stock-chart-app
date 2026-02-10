# Stock Chart App: Deep Dive & Algorithm Analysis

This document provides a comprehensive analysis of the algorithms used in the Stock Chart Application. It is designed to be understood by someone with minimal prior knowledge of Python or Financial Engineering.

## 1. System High-Level Architecture

The application follows a **Producer-Consumer** architecture to keep the User Interface (UI) responsive while downloading heavy data.

```mermaid
graph TD
    UI[User Interface (Main Thread)] -->|1. User Requests Ticker| Worker[Background Thread (Producer)]
    Worker -->|2. Check/Download Data| StockUtil[Stock Utility Module]
    StockUtil -->|3. Fetch CSV or API| YF[Yahoo Finance API]
    StockUtil -->|4. Return Data| Worker
    Worker -->|5. Put Data in Queue| Queue[Message Queue]
    Queue -->|6. Process Queue| UI
    UI -->|7. Render Chart| Plotter[Chart Plotter Module]
```

## 2. Algorithm: Data Acquisition (Smart Caching)
**File**: `app/stock_util.py` -> `fetch_stock_data_with_cache`

This algorithm ensures we don't spam the Yahoo Finance API (which is slow) if we already have the data.

### Logic Flow
1.  **Input**: Ticker (e.g., "AAPL"), Interval (e.g., "1d").
2.  **Date Calculation**: Determine "Today" (if weekend, snap to Friday).
3.  **Cache Check**:
    *   Look for file: `csv/{ticker}_{interval}_{date}.csv`.
    *   **IF** file exists:
        *   Load it into memory.
        *   **Smart Append Strategy**:
            *   Identify `LastDate` in cache.
            *   **Condition**: If `LastDate < Today` OR (`LastDate == Today` AND Interval is Intraday), trigger **Incremental Fetch**.
    *   **IF** file missing:
        *   Flag for full download.
4.  **Download Strategy**:
    *   **Full Download**: Fetches from strict start date (e.g. `2000-01-01` or `Now-59d` for minutes).
    *   **Incremental Download**: Fetches from `LastDate` to `Tomorrow`.
        *   **Split Detection**: If the delta contains a "Stock Split" event, the cache is discarded and a full download is forced to ensure price continuity.
5.  **Merge Logic**:
    *   `Combined = Cache + Delta`
    *   Deduplicate by Time Index (keep last).
    *   Intraday Refresh: For 1WK/1m charts, the system initiates a **Fast Polling** loop (every 15s) to capture the latest minute bar.
    *   **Logic**: For 1m data, we always request a fresh **5-day** buffer to prevent gaps during session rollovers.
6.  **Output**: Returns a cleaned Pandas DataFrame.

## 3. Algorithm: Visual Gap Filling (Smart Smoothing)
**File**: `app/app_stock_chart.py` -> `_apply_resampling`

Small cap stocks or illiquid assets often have minutes with zero trades, resulting in "broken" charts with missing candles. We fix this visually without corrupting the data.

### Logic Flow
1.  **Resample**: Force the DataFrame onto a strict 1-minute grid (`resample('1min').asfreq()`). This inserts `NaN` rows for missing minutes.
2.  **Forward Fill Close**: Propagate the last known `Close` price forward to the missing minute.
3.  **Construct Flat Candle**:
    *   Set `Open = High = Low = Close` (The propagated Close price).
    *   This renders a "Flat Dash" (Doji) on the chart, visually indicating "Price Unchanged".
4.  **Zero Volume**:
    *   Explicitly set `Volume = 0` for these filled rows.
5.  **Result**: A continuous, smooth chart where gaps are clear (flat lines, no volume) but the time axis remains linear.


## 4. Algorithm: Gapless Charting (The "Financial Axis" Trick)
**File**: `app/chart_drawing.py`

Standard charts (like Excel) plot data against linear Time.
*   **Problem**: Stocks don't trade on weekends. A linear time axis would show huge empty gaps (Sat/Sun) between Friday and Monday.
*   **Solution**: **Index-Based Plotting**.

### The Algorithm
1.  **Input**: A DataFrame with Dates: `[Fri, Mon, Tue]`.
2.  **Transformation**:
    *   Ignore the specific dates for plotting position.
    *   Create an integer array: `[0, 1, 2]`.
    *   Plot Price vs Integers (`0`=Fri, `1`=Mon).
    *   **Result**: Monday follows Friday immediately. No gap.
3.  **Axis Labeling (The Hard Part)**:
    *   The chart now sees "0, 1, 2". The user needs to see "Jan 23, Jan 26".
    *   **Formatter**: A custom function iterates through the integers.
    *   `Label(x) = DataFrame.Index[x].strftime("%b %d")`
    *   **Heuristics**:
        *   If `Year` changed since last tick -> Show Year.
        *   If `Month` changed -> Show Month.
        *   If `Day` changed -> Show Day.
        *   If `Zoomed In` (1D view) -> Show Hours (9:30, 10:30).

## 5. Algorithm: The "Smart Axis" (Collision Resolution)
**File**: `app/chart_drawing.py` -> `_setup_date_axis`

Standard matplotlib date formatting often results in overlapping labels ("jamming") or inconsistent density when switching between Daily, Weekly, and Monthly views. We implemented a custom **Backtrack Collision Resolution** engine.

### The Algorithm
1.  **Input**: A list of data indices `[0, 1, 2...]` and associated Dates.
2.  **Iterative Placement**: We look at every single bar on the chart.
3.  **Conflict Detection**:
    *   Before placing a label (e.g., "Jan 03"), calculate distance to the *previous* label.
    *   `Gap = CurrentIndex - LastLabelIndex`
    *   **Thresholds**:
        *   **Dense (3M/6M)**: Gap > **6**. (Allows mid-month ticks).
        *   **Hourly (1M)**: Gap > **8**. (Enforces ~2 day spacing).
        *   **Sparse (1Y+)**: Gap > **10**. (Prevents text overlap).
4.  **Priority Resolution (The "Smart" Part)**:
    *   If a **High Priority** label (Start of Month) collides with a **Low Priority** label (Day 29), we don't just skip the new one.
    *   **Backtrack**: We *retroactively delete* the Low Priority label (Day 29) to make room for the High Priority one (Feb 01).
    *   *Result*: The axis always anchors on significant time boundaries.
5.  **Contextual Formatter**:
    *   **Year Change**: Automatically appends year (`Jan '25`) if the year changed since the last tick.
    *   **Long Term (3Y/5Y)**: Automatically filters for Quarterly (Jan/Apr...) or Semi-Annual (Jan/Jul) months to prevent crowding.
    *   **Weekly Snap (1WK)**: For sliding window weekly charts, we enforce a strict **Day Start** threshold (10:00 AM). If a label would fall mid-day (e.g., 2:00 PM because the chart starts 7 days ago), it is suppressed, ensuring the grid always aligns with the **Start of Trading** (09:30).

## 6. Algorithm: The "Market Calendar" Gap Analyzer
**File**: `app/debug_price.py` (Standalone Tool)

To support advanced debugging of data integrity, we built a specialized heuristic analyzer to distinguish between "Missing Data" and "Normal Life".

### The Algorithm
1.  **Input**: A raw time-series from Yahoo Finance (e.g., `1h` bars).
2.  **Gap Detection**: Calculate `Delta = Time[i] - Time[i-1]`.
3.  **Heuristic Classification**:
    *   **Threshold**: If `Delta > Interval`, it's a Gap.
    *   **The "Normal" Filter**:
        *   Does it start at **Market Close** (16:00, 15:30)?
        *   Does it end at **Market Open** (09:30, 10:00)?
        *   Is it less than **5 Days** (Weekend + Holiday)?
        *   **Action**: If YES, we classify it as a **Standard Market Break** and hide it from the log.
4.  **Anomaly Reporting**:
    *   Any gap that *fails* the normal filter (e.g., a gap starting at 10:30 AM on a Tuesday) is flagged as **ABNORMAL** and reported to the user with exact duration.
    *   This allows pinpointing data loss (API failure) without wading through thousands of lines of "Friday Night -> Monday Morning" logs.

## 7. Algorithm: Crosshair & Tooltips
**File**: `app/chart_drawing.py` -> `_on_mouse_move`

How does the chart know which price to show when you hover your mouse?

### Logic Flow
1.  **Event Capture**: Python detects Mouse Move (X, Y pixels).
2.  **Data Mapping**:
    *   Convert Pixel X -> Data Coordinate X (Float).
    *   Round X to nearest Integer (Index).
    *   `DataIndex = round(X)`
3.  **Lookup**:
    *   `Date = DataFrame.Index[DataIndex]`
    *   `Open = DataFrame['Open'].iloc[DataIndex]`
    *   `Close = DataFrame['Close'].iloc[DataIndex]`
4.  **Drawing**:
    *   Draw Vertical Line at `DataIndex`.
    *   Draw Horizontal Line at `Mouse Y`.
    *   Render Text Label with `Date` and `Price` at the edges of the screen.

## 8. Algorithm: Data Resampling
**File**: `app/stock_util.py` -> `resample_data`

How the app turns "Daily" data into "Weekly" bars or "1m" into "5m".

### Logic Flow
1.  **Input**: High-frequency data (e.g., 1-minute).
2.  **Aggregation Rule**: e.g., "5min".
3.  **Group**: Split data into 5-minute buckets.
4.  **OHLC Aggregation**:
    *   **Open**: Take the `first` price of the bucket.
    *   **High**: Take the `max` price of the bucket.
    *   **Low**: Take the `min` price of the bucket.
    *   **Close**: Take the `last` price of the bucket.
    *   **Volume**: `sum` all volume in the bucket.
5.  **Output**: A new, smaller DataFrame representing 5-minute bars.
