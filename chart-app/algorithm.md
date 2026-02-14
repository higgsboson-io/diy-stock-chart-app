# Stock Chart App: Deep Dive & Algorithm Analysis

> *Updated by Anti Gravity (Claude Opus 4.6 Thinking)*

This document provides a comprehensive analysis of the algorithms used in the Stock Chart Application. It is designed to be understood by someone with minimal prior knowledge of Python or Financial Engineering.

> **See also**: [Software Design Document](../design.md) for full HLD, LLD, class diagrams, and data model.
> **See also**: [README](../readme.md) for features overview and installation.

## 1. System High-Level Architecture

The application follows a **Producer-Consumer** architecture to keep the User Interface (UI) responsive while downloading heavy data. See [Design — Threading & Concurrency Model](../design.md#14-threading--concurrency-model) for the full threading diagram.

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
**File**: `stock_util.py` → `fetch_stock_data_with_cache()`
**Design Ref**: [Caching & Persistence Strategy](../design.md#24-caching--persistence-strategy)

This algorithm ensures we don't spam the Yahoo Finance API (which is slow) if we already have the data.

### Logic Flow
1.  **Input**: Ticker (e.g., "AAPL"), Interval (e.g., "1d").
2.  **Date Calculation**: Determine "Today" (if weekend, snap to Friday).
3.  **Cache Check**:
    *   Look for file: `csv/{ticker}_{interval}_{date}.csv` via `glob()`.
    *   **IF** file exists:
        *   Load it into memory.
        *   **Smart Append Strategy**:
            *   Identify `LastDate` in cache.
            *   **Condition**: If `LastDate < Today` OR (`LastDate == Today` AND Interval is Intraday), trigger **Incremental Fetch**.
    *   **IF** file missing:
        *   Flag for full download.
4.  **Download Strategy**:
    *   **Branch: Minute Data (`1m`)**:
        *   Always fetches a fresh **5-day** buffer via `period="5d"` to prevent gaps during session rollovers.
        *   This is a full replacement, not an incremental merge.
    *   **Branch: Daily/Hourly Data**:
        *   **Full Download**: Fetches from strict start date (e.g., `2000-01-01` for daily, `Now-59d` for hourly).
        *   **Incremental Download**: Fetches from `LastDate` to `Tomorrow`.
        *   **Split Detection**: If the delta contains a "Stock Split" event (any value ≠ 0.0), the cache is discarded and a full download is forced to ensure price continuity.
5.  **Merge Logic**:
    *   `Combined = Cache + Delta`
    *   Deduplicate by Time Index (`keep='last'` — prefer newer data).
    *   The merged result is saved back to disk with today's date in the filename.
    *   Old cache files for the same ticker/interval are deleted.
6.  **Metadata Fetch**:
    *   Loads `{ticker}_info.csv` sidecar file via `load_ticker_metadata()`.
    *   If missing, stale (>30 days), or lacking required keys (`dividendRate`, `yield`, `fiftyTwoWeekLow`, `beta`, `previousClose`), a full API refresh is triggered.
7.  **Output**: Returns a 6-tuple: `(DataFrame, company_name, interval, previous_close, current_price, info_dict)`.

## 3. Algorithm: Visual Gap Filling (Smart Smoothing)
**File**: `app_stock_chart.py` → `_apply_resampling()`
**Design Ref**: [Resampling Pipeline](../design.md#27-interaction-flow--resampling-pipeline)

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

> **Note**: This gap-fill only applies to 1-minute interval data. Daily and hourly intervals are not gap-filled.


## 4. Algorithm: Gapless Charting (The "Financial Axis" Trick)
**File**: `chart_drawing.py` → `ChartPlotter.update_chart()`
**Design Ref**: [Rendering Pipeline](../design.md#25-rendering-pipeline)

Standard charts (like Excel) plot data against linear Time.
*   **Problem**: Stocks don't trade on weekends. A linear time axis would show huge empty gaps (Sat/Sun) between Friday and Monday.
*   **Solution**: **Index-Based Plotting**.

### The Algorithm
1.  **Input**: A DataFrame with Dates: `[Fri, Mon, Tue]`.
2.  **Transformation**:
    *   Ignore the specific dates for plotting position.
    *   Create an integer array: `x_indices = np.arange(len(df))` → `[0, 1, 2]`.
    *   Plot Price vs Integers (`0`=Fri, `1`=Mon).
    *   **Result**: Monday follows Friday immediately. No gap.
3.  **Axis Labeling (The Hard Part)**:
    *   The chart now sees "0, 1, 2". The user needs to see "Jan 23, Jan 26".
    *   **Formatter**: A custom function maps integers back to formatted dates.
    *   `Label(x) = DataFrame.Index[int(x)].strftime("%b %d")`
    *   **Heuristics** (implemented in `_setup_date_axis()`):
        *   If `Year` changed since last tick → Show Year.
        *   If `Month` changed → Show Month.
        *   If `Day` changed → Show Day.
        *   If `Zoomed In` (1D/1WK view) → Show Hours (9:30, 10:30).

## 5. Algorithm: The "Smart Axis" (Collision Resolution)
**File**: `chart_drawing.py` → `ChartPlotter._setup_date_axis()`
**Design Ref**: [Rendering Pipeline](../design.md#25-rendering-pipeline)

Standard matplotlib date formatting often results in overlapping labels ("jamming") or inconsistent density when switching between Daily, Weekly, and Monthly views. We implemented a custom **Backtrack Collision Resolution** engine.

### The Algorithm
1.  **Input**: A list of data indices `[0, 1, 2...]` and associated Dates, plus the `window` parameter.
2.  **Iterative Placement**: We look at every single bar on the chart.
3.  **Conflict Detection**:
    *   Before placing a label (e.g., "Jan 03"), calculate distance to the *previous* label.
    *   `Gap = CurrentIndex - LastLabelIndex`
    *   **Thresholds** (vary by window):
        *   **Dense (3M/6M)**: Gap > **6**. (Allows mid-month ticks).
        *   **Hourly (1M)**: Gap > **8**. (Enforces ~2 day spacing).
        *   **Sparse (1Y+)**: Gap > **10**. (Prevents text overlap).
        *   **Intraday (1WK)**: Gap > **5** (10-min bars).
4.  **Priority Resolution (The "Smart" Part)**:
    *   If a **High Priority** label (Start of Month) collides with a **Low Priority** label (Day 29), we don't just skip the new one.
    *   **Backtrack**: We *retroactively delete* the Low Priority label (Day 29) to make room for the High Priority one (Feb 01).
    *   *Result*: The axis always anchors on significant time boundaries.
5.  **Contextual Formatter**:
    *   **Year Change**: Automatically appends year (`Jan '25`) if the year changed since the last tick.
    *   **Long Term (3Y/5Y)**: Automatically filters for Quarterly (Jan/Apr...) or Semi-Annual (Jan/Jul) months to prevent crowding.
    *   **Weekly Snap (1WK)**: For sliding window weekly charts, we enforce a strict **Day Start** threshold (10:00 AM). If a label would fall mid-day (e.g., 2:00 PM because the chart starts 7 days ago), it is suppressed, ensuring the grid always aligns with the **Start of Trading** (09:30).

## 6. Algorithm: The "Market Calendar" Gap Analyzer
**File**: `debug_price.py` (Standalone CLI Tool)

To support advanced debugging of data integrity, we built a specialized heuristic analyzer to distinguish between "Missing Data" and "Normal Life".

### The Algorithm
1.  **Input**: A raw time-series from Yahoo Finance (e.g., `1h` bars), fetched via `yf.download()`.
2.  **Gap Detection**: Calculate `Delta = Time[i] - Time[i-1]`.
3.  **Heuristic Classification**:
    *   **Threshold**: If `Delta > Expected Interval`, it's a Gap.
    *   **The "Normal" Filter**:
        *   Does it start at **Market Close** (16:00, 15:30)?
        *   Does it end at **Market Open** (09:30, 10:00)?
        *   Is it less than **5 Days** (Weekend + Holiday)?
        *   **Action**: If YES, we classify it as a **Standard Market Break** and hide it from the log.
4.  **Anomaly Reporting**:
    *   Any gap that *fails* the normal filter (e.g., a gap starting at 10:30 AM on a Tuesday) is flagged as **ABNORMAL** and reported to the user with exact duration.
    *   This allows pinpointing data loss (API failure) without wading through thousands of lines of "Friday Night → Monday Morning" logs.

## 7. Algorithm: Crosshair & Tooltips
**File**: `chart_drawing.py` → `ChartPlotter._on_mouse_move()` / `_update_crosshair()`
**Design Ref**: [Crosshair Interaction Flow](../design.md#28-interaction-flow--crosshair)

How does the chart know which price to show when you click and drag your mouse?

### Logic Flow
1.  **Event Capture**: Left mouse button down (`_on_mouse_down`) enables crosshair mode (`is_dragging = True`).
2.  **Target Axis Resolution**: The mouse may land on twin axes (price/volume overlap). The code resolves to the content axis by checking `inaxes` against `axes_dict`.
3.  **Data Mapping**:
    *   Convert Pixel X → Data Coordinate X (Float) via `ax.transData.inverted()`.
    *   Snap X to nearest Integer (Index) using `round()` and clamp to `[0, len-1]`.
    *   `DataIndex = clamped round(X)`
4.  **Lookup**:
    *   `Date = current_df_dates[DataIndex]`
    *   `Close = DataFrame['close'].iloc[DataIndex]`
    *   OHLC values are retrieved via `history_df.loc[current_date]`
5.  **Drawing**:
    *   Draw **Vertical Line** at `DataIndex` across **all** axes (price, MACD, RSI).
    *   Draw **Horizontal Line** at `Mouse Y` on the **active** axis only.
    *   Render Y-axis price labels for each panel at the right edge.
    *   Render Date/OHLC label above the price panel.
    *   Render Volume label on the volume axis if active.
    *   **Adaptive Precision**: Prices < $2.00 display 4 decimal places; otherwise 2.
6.  **Release**: On mouse up (`_on_mouse_up`), all crosshair elements are hidden and `is_dragging = False`.

## 8. Algorithm: Data Resampling
**File**: `stock_util.py` → `resample_data()`
**Design Ref**: [Window-to-Interval Mapping](../design.md#window-to-interval-mapping)

How the app turns "Daily" data into "Weekly" bars or "1m" into "10m".

### Logic Flow
1.  **Input**: High-frequency data (e.g., 1-minute) and a resample `rule` (e.g., `"10min"`, `"2D"`, `"W-MON"`, `"MS"`).
2.  **Branch: Integer-Day Rules ("2D", "3D")**:
    *   These cannot use standard `pandas.resample()` because Pandas doesn't understand trading-day grouping.
    *   **Custom Algorithm**: Group consecutive trading days into buckets of N, preserving the last bucket even if incomplete.
    *   Each bucket records `period_start` so the crosshair can display the date range.
3.  **Branch: Standard Time Rules ("10min", "W-MON", "MS")**:
    *   Uses standard `pandas.resample(rule, closed='left', label='left')`.
4.  **OHLC Aggregation**:
    *   **Open**: Take the `first` price of the bucket.
    *   **High**: Take the `max` price of the bucket.
    *   **Low**: Take the `min` price of the bucket.
    *   **Close**: Take the `last` price of the bucket.
    *   **Volume**: `sum` all volume in the bucket.
5.  **NaN Cleanup**: Drop any all-NaN rows from resampled output.
6.  **Output**: A new, smaller DataFrame representing the resampled bars.

## 9. Algorithm: Sequential Outlier Filter
**File**: `stock_util.py` → `fetch_stock_data_with_cache()` (inline within minute-data processing)

Extended hours data from public sources often contains erroneous ticks (e.g., price dropping from $450 to $420 and back in 1 minute). This is addressed when `prepost=True` data is fetched.

### Logic Flow
1.  **Iterate**: Walk through the dataset minute-by-minute.
2.  **Baseline**: Use the *previous minute's Cleaned Close* as the "Truth".
3.  **Thresholds**:
    *   **1%** deviation for Pre/Post market hours (thin liquidity).
    *   **3%** for regular market hours (higher volatility accepted).
4.  **Correction**: If a tick deviates beyond the threshold, it is capped at the baseline price. This effectively "flattens" bad ticks while preserving chart continuity.

## 10. Algorithm: Technical Indicator Calculation
**File**: `stock_util.py` → `calculate_indicators()`
**Design Ref**: [Moving Average Color Map](../design.md#moving-average-color-map)

### Moving Averages (SMA)
*   **Formula**: $SMA_k = \frac{1}{k} \sum_{i=n-k+1}^{n} P_i$
*   **Implementation**: `df['ma20'] = df['close'].rolling(window=20).mean()`
*   **Periods**: 5, 20, 50, 60, 100, 120, 200, 250 — each stored as `ma{N}` column.

### MACD (Moving Average Convergence Divergence)
*   **Library**: `finta.TA.MACD(df)` — returns `MACD` and `SIGNAL` columns.
*   **Standard Parameters**: EMA(12) - EMA(26) for MACD line; EMA(9) of MACD for Signal.
*   **Histogram**: Computed during rendering as `MACD - SIGNAL`.

### RSI (Relative Strength Index)
*   **Library**: `finta.TA.RSI(df)` — default 14 periods.
*   **Uses Wilder's Smoothing** internally for accuracy matching broker platforms.

### Bollinger Bands
*   **Library**: `finta.TA.BBANDS(df)` — returns `BB_UPPER`, `BB_MIDDLE`, `BB_LOWER`.
*   **Standard Parameters**: 20-period SMA ± 2 standard deviations.
