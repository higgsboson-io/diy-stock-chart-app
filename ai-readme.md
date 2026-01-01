# AI Development Log: The "Vibe Coding" Journey

This document chronicles the step-by-step evolution of the **DIY Stock Chart** application. It serves as a historical record of how a simple CLI script was transformed into a professional-grade GUI tool through iterative "Vibe Coding" (Prompt -> Error -> Fix -> Refine).

**Project Stats:**
*   **Timeline**: Dec 25 - Dec 29 (4 Days Elapsed)
*   **Active Vibe Coding Time**: ~8 Hours
    *   *Session 1*: ~1 Hr (Dec 25)
    *   *Session 2*: ~1.5 Hrs (Dec 26)
    *   *Session 3*: ~5.5 Hrs (Dec 29)

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

## 🏆 Summary
This project evolved from a script that "drew a picture" to a fully interactive financial workspace. The key to success was the **Iterative Feedback Loop**:
1.  **User**: "This looks wrong." (e.g., Weekends showing as gaps)
2.  **Dev**: "Here's a fix using Resampling."
3.  **User**: "Now the crosshair is broken."
4.  **Dev**: "Fixing Z-Order event handling."

**Result**: A robust, Python-based stock analyzer ready for open source.

---

## Trace Log – Codex Plugin (after Gemini 3.0 Pro)
*Previous work above was done with Gemini 3.0 Pro. The following changes were implemented with the Codex plugin in this session.*

**Date**: Dec 31, 2025  
**Agent**: Codex plugin  

**User Goals**
- Preserve all existing info panel content.
- Make the panel floatable/drag-to-move with a checkbox to show/hide and a close button that syncs the toggle.
- Fix drag offset issues when the window is not maximized.
- Update README to reflect the floating panel behavior.

**Key Changes**
- Replaced the positioning dropdown with a checkbox and header `×`; closing also unchecks.
- Added drag handlers on the info panel header; store/restore last position; clamp within the chart area; corrected coordinate math for restored windows to remove pointer gap.
- Kept the info content layout intact (Key Stats left; Valuation or ETF Profile right).
- Updated README to describe the floatable panel and the new control behavior.

**Notes**
- The panel remains a Tk overlay (not a separate OS window). Dragging now works consistently in maximized and restored states after the coordinate fixes.
