import argparse
from datetime import timedelta
from pathlib import Path
import yfinance as yf


def analyze_gaps(df, interval_str):
    """Analyzes the DataFrame for missing time steps based on the interval."""
    if df.empty:
        return

    delta = None
    if interval_str == "1m":
        delta = timedelta(minutes=1)
    elif interval_str == "2m":
        delta = timedelta(minutes=2)
    elif interval_str == "5m":
        delta = timedelta(minutes=5)
    elif interval_str == "15m":
        delta = timedelta(minutes=15)
    elif interval_str == "30m":
        delta = timedelta(minutes=30)
    elif interval_str in ("60m", "1h"):
        delta = timedelta(hours=1)
    elif interval_str == "90m":
        delta = timedelta(minutes=90)
    elif interval_str == "1d":
        delta = timedelta(days=1, hours=12)
    elif interval_str in ["1wk", "1w"]:
        delta = timedelta(days=8)
    elif interval_str in ["1mo", "1m_monthly"]:
        delta = timedelta(days=32)

    if not delta:
        print(f"Gap analysis not supported for variable interval: {interval_str}")
        return

    print(f"\n--- Gap Analysis (Threshold: > {delta}) ---")
    diffs = df.index.to_series().diff()
    gaps = diffs[diffs > delta]

    if gaps.empty:
        print("No gaps found (Data is contiguous).")
    else:
        abnormal_gaps = []
        for date, gap in gaps.items():
            prev_date = date - gap
            p_hour = prev_date.hour
            c_hour = date.hour

            is_close = (p_hour >= 15) or (p_hour in (12, 13))
            is_open = c_hour in (8, 9, 10)
            is_valid_duration = gap.days < 5

            if is_close and is_open and is_valid_duration:
                continue
            abnormal_gaps.append((date, prev_date, gap))

        if not abnormal_gaps:
            print("No abnormal gaps found (all gaps were standard Market Close/Weekends).")
        else:
            print(f"Found {len(abnormal_gaps)} ABNORMAL gaps (excluding standard Market breaks).")
            for count, (date, prev_date, gap) in enumerate(abnormal_gaps):
                note = "** LONG GAP **" if gap.days > 2 else ""
                print(f"  Gap at {date}: {gap} (From {prev_date}) {note}")
                if count >= 99:
                    print("  ... (Truncated)")
                    break


def main():
    parser = argparse.ArgumentParser(description="Fetch and Debug Yahoo Finance Data")
    parser.add_argument("ticker", type=str, help="Stock Ticker (e.g. SPY)")
    parser.add_argument("interval", type=str, help="Sampling Unit (e.g. 1m, 5m, 1h, 1d, 1wk, 1mo)")
    parser.add_argument("start_date", type=str, help="Start Date (YYYY-MM-DD)")
    args = parser.parse_args()

    yf_interval = "1wk" if args.interval == "1w" else args.interval
    print(f"Fetching {args.ticker} [{yf_interval}] start={args.start_date}...")

    try:
        df = yf.Ticker(args.ticker).history(start=args.start_date, interval=yf_interval, auto_adjust=False)
        if df.empty:
            print("RESULT: Empty DataFrame returned.")
            return

        print(f"\n--- Statistics ---")
        print(f"Rows:      {len(df)}")
        print(f"Start:     {df.index.min()}")
        print(f"End:       {df.index.max()}")
        print(f"Columns:   {df.columns.tolist()}")
        print(f"\n--- First 3 Rows ---\n{df.head(3)}")
        print(f"\n--- Last 3 Rows ---\n{df.tail(3)}")

        analyze_gaps(df, args.interval)

        nans = df.isna().sum().sum()
        if nans > 0:
            print(f"\n[WARNING] Found {nans} NaN values in data!")
            print(df.isna().sum())

        script_dir = Path(__file__).parent.resolve()
        out_dir = script_dir / "csv"
        out_dir.mkdir(exist_ok=True)
        out_path = out_dir / f"debug_{args.ticker}_{yf_interval}_{args.start_date}.csv"
        df.to_csv(out_path)
        print(f"\n[SAVED] Raw data saved to: {out_path}")
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")


if __name__ == "__main__":
    main()
