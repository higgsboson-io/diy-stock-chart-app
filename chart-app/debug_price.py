import argparse
import yfinance as yf
import pandas as pd
from datetime import timedelta

def analyze_gaps(df, interval_str):
    """
    Analyzes the DataFrame for missing time steps based on the interval.
    """
    if df.empty: return

    # Parse interval string to timedelta
    # e.g. "1m" -> 1 minute, "5m" -> 5 minutes, "1h" -> 1 hour, "1d" -> 1 day
    # "1mo" -> variable, skip strict frequency check
    
    delta = None
    if interval_str == "1m": delta = timedelta(minutes=1)
    elif interval_str == "2m": delta = timedelta(minutes=2)
    elif interval_str == "5m": delta = timedelta(minutes=5)
    elif interval_str == "15m": delta = timedelta(minutes=15)
    elif interval_str == "30m": delta = timedelta(minutes=30)
    elif interval_str == "60m" or interval_str == "1h": delta = timedelta(hours=1)
    elif interval_str == "90m": delta = timedelta(minutes=90)
    elif interval_str == "1d": delta = timedelta(hours=23) # Allow for 23h to be safe? No, 1d usually > 1d gap means missing day. 1d diff is exactly 1d.
    # Note: 1d daily data has gaps for weekends (3 days).
    # If we want to strictly find MISSING TRADING DAYS, we need to know market calendar.
    # But simple heuristic: > 1.1 days?
    # Actually, for 1d, 1wk, 1mo, simple diff checks are noisy due to weekends/holidays.
    # We will set loose thresholds.
    elif interval_str == "1d": delta = timedelta(days=1, hours=12) # > 1.5 days flags weekends.
    elif interval_str in ["1wk", "1w"]: delta = timedelta(days=8) # > 8 days (flags missing weeks)
    elif interval_str in ["1mo", "1m_monthly"]: delta = timedelta(days=32) # > 32 days (flags missing months)

    if not delta and interval_str == "1d":
         delta = timedelta(days=1)
    
    if not delta:
        print(f"Gap analysis not supported for variable interval: {interval_str}")
        return

    print(f"\n--- Gap Analysis (Threshold: > {delta}) ---")
    
    # Calculate time differences
    diffs = df.index.to_series().diff()
    
    # Filter for gaps larger than expected delta
    gaps = diffs[diffs > delta]
    
    if gaps.empty:
        print("No gaps found (Data is contiguous).")
    else:
        # Filter Normal Market Gaps
        abnormal_gaps = []
        for date, gap in gaps.items():
            prev_date = date - gap
            
            # Heuristic: Is this a standard market close -> open transition?
            # Standard Close: 15:XX or 16:XX (Daily bars usually 00:00, Intraday 15:30/15:59)
            # Early Close: 12:XX or 13:XX
            # Standard Open: 09:XX (Stocks)
            
            p_hour = prev_date.hour
            c_hour = date.hour
            
            is_close = (p_hour >= 15) or (p_hour == 12) or (p_hour == 13)
            is_open = (c_hour == 9) or (c_hour == 10) or (c_hour == 8) # Pre-market sometimes spills?
            
            # Duration Check: < 5 days covers Weekends (2d) and Long Weekends (3d)
            is_valid_duration = gap.days < 5
            
            if is_close and is_open and is_valid_duration:
                continue # Ignore normal market breaks
            
            abnormal_gaps.append((date, prev_date, gap))
            
        if not abnormal_gaps:
             print("No abnormal gaps found (all gaps were standard Market Close/Weekends).")
        else: 
            print(f"Found {len(abnormal_gaps)} ABNORMAL gaps (excluding standard Market breaks).")
            print(f"--- Abnormal Gaps List ---")
            
            count = 0
            for date, prev_date, gap in abnormal_gaps:
                note = ""
                # Heuristics for the remaining abnormal ones
                if gap.days > 2: note = "** LONG GAP **"
                
                print(f"  Gap at {date}: {gap} (From {prev_date}) {note}")
                count += 1
                if count >= 100:
                    print("  ... (Truncated)")
                    break

def main():
    parser = argparse.ArgumentParser(description="Fetch and Debug Yahoo Finance Data")
    parser.add_argument("ticker", type=str, help="Stock Ticker (e.g. SPY)")
    parser.add_argument("interval", type=str, help="Sampling Unit (e.g. 1m, 5m, 1h, 1d, 1wk, 1mo)")
    parser.add_argument("start_date", type=str, help="Start Date (YYYY-MM-DD)")
    
    args = parser.parse_args()
    
    # Normalize Interval for Yahoo
    # User might input "1w" but yfinance needs "1wk"
    # User might input "1mo" -> yfinance "1mo"
    yf_interval = args.interval
    if args.interval == "1w": yf_interval = "1wk"
    
    print(f"Fetching {args.ticker} [{yf_interval}] start={args.start_date}...")
    
    # Fetch Data
    try:
        # auto_adjust=False to see raw prices if possible
        df = yf.Ticker(args.ticker).history(start=args.start_date, interval=yf_interval, auto_adjust=False)
        
        if df.empty:
            print("RESULT: Empty DataFrame returned.")
            return

        # Basic Stats
        print(f"\n--- Statistics ---")
        print(f"Rows:      {len(df)}")
        print(f"Start:     {df.index.min()}")
        print(f"End:       {df.index.max()}")
        print(f"Columns:   {df.columns.tolist()}")
        
        # Head/Tail
        print(f"\n--- First 3 Rows ---")
        print(df.head(3))
        print(f"\n--- Last 3 Rows ---")
        print(df.tail(3))
        
        # Analyze Gaps
        analyze_gaps(df, args.interval)
        
        # Check for NaNs
        nans = df.isna().sum().sum()
        if nans > 0:
            print(f"\n[WARNING] Found {nans} NaN values in data!")
            print(df.isna().sum())
        
        # Determine output directory
        # Try 'app/csv' first (if running from root), then 'csv', else create 'csv'
        from pathlib import Path
        
        script_dir = Path(__file__).parent.resolve()
        out_dir = script_dir / "csv"
        out_dir.mkdir(exist_ok=True)
             
        filename = f"debug_{args.ticker}_{yf_interval}_{args.start_date}.csv"
        out_path = out_dir / filename
        
        df.to_csv(out_path)
        print(f"\n[SAVED] Raw data saved to: {out_path}")
        
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")

if __name__ == "__main__":
    main()
