# stock_util.py
import logging
import time
from typing import List, Optional, Tuple, Dict, Any
import yfinance as yf
import pandas as pd
from finta import TA
from datetime import datetime, timedelta
from pathlib import Path
import glob
import pytz
import numpy as np

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
def get_stock_history(ticker: str, start: str, end: str, interval: str = "1d", prepost: bool = False) -> pd.DataFrame:
    """
    Downloads historical stock data for a given ticker.

    Args:
        ticker (str): The stock symbol (e.g., 'AAPL').
        start (str): Start date string (YYYY-MM-DD).
        end (str): End date string (YYYY-MM-DD).
        interval (str): Data interval (default 1d).
        prepost (bool): Include Pre and Post market data.

    Returns:
        pd.DataFrame: DataFrame containing historical data. 
                      Returns empty DataFrame on failure.
    """
    try:
        stock = yf.Ticker(ticker)
        # Use auto_adjust=False to match visual trading prices
        history = stock.history(start=start, end=end, interval=interval, auto_adjust=False, prepost=prepost)
        
        if history.empty:
            logger.warning(f"No data returned for {ticker} from {start} to {end}")
        
        return history
    except Exception as e:
        logger.error(f"Failed to fetch history for {ticker}: {e}")
        return pd.DataFrame()

def cleanup_old_cache(csv_dir_path: str = "csv", days: int = 7):
    """Removes CSV files in the cache directory older than N days."""
    try:
        csv_dir = Path(csv_dir_path)
        if not csv_dir.exists():
            return
            
        now = datetime.now()
        cutoff = now - timedelta(days=days)
        
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

# Helper for Metadata CSV
def get_metadata_path(ticker: str) -> Path:
    return Path("csv") / f"{ticker}_info.csv"

def load_ticker_metadata(ticker: str) -> Dict[str, Any]:
    """Loads static metadata from CSV sidecar."""
    try:
        path = get_metadata_path(ticker)
        if not path.exists():
            return {}
        
        # Check freshness (e.g. 30 days for static info)
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        if (datetime.now() - mtime).days > 30:
            return {}

        info = {}
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                parts = line.strip().split(',', 1)
                if len(parts) == 2:
                    info[parts[0]] = parts[1]
                    
        # VALIDATION: Check for critical keys.
        # If we are missing 'dividendRate' or 'yield' (newly added features),
        # consider the cache "incomplete" and force a refresh to populate them.
        # Check if 'quoteType' exists as a sanity check.
        if 'quoteType' not in info:
             return {}
             
        # Optional: Check for new fields to force upgrade
        # We check for new critical keys like 'fiftyTwoWeekLow' effectively forcing a refresh
        # for users with old cache files that missed these fields.
        expected_keys = ['dividendRate', 'yield', 'fiftyTwoWeekLow', 'beta', 'previousClose']
        for k in expected_keys:
             if k not in info:
                 logger.info(f"Metadata for {ticker} missing {k}. Forcing refresh.")
                 return {}
                 
        return info
    except Exception as e:
        logger.warning(f"Failed to load metadata CSV: {e}")
        return {}

def save_ticker_metadata(ticker: str, info_dict: Dict[str, Any]):
    """Saves static metadata to CSV sidecar."""
    try:
        path = get_metadata_path(ticker)
        path.parent.mkdir(exist_ok=True)
        
        # Fields to save
        keys = [
            'shortName', 'longName', 'sector', 'industry', 'exchange', 'currency', 'quoteType',
            'dividendRate', 'trailingAnnualDividendRate', 'yield', 'dividendYield',
            'fiftyTwoWeekLow', 'fiftyTwoWeekHigh', 'averageVolume', 'beta', 'beta3Year',
            'exDividendDate', 'targetMeanPrice',
            'totalAssets', 'navPrice', 'netExpenseRatio', 'annualReportExpenseRatio', 'expenseRatio',
            'trailingPE', 'forwardPE', 'pegRatio', 'trailingPegRatio', 'priceToBook',
            'priceToSalesTrailing12Months', 'enterpriseToEbitda', 'marketCap',
            'previousClose', 'regularMarketPreviousClose'
        ]
        
        with open(path, 'w', encoding='utf-8') as f:
            f.write("Key,Value\n")
            f.write(f"last_updated,{datetime.now().isoformat()}\n")
            for k in keys:
                val = info_dict.get(k, '')
                # Always write the key, even if value is empty
                # Escape commas in value
                val = str(val).replace(',', ';') if val is not None else ''
                f.write(f"{k},{val}\n")
    except Exception as e:
        logger.warning(f"Failed to save metadata CSV: {e}")

def fetch_stock_data_with_cache(ticker: str, interval: str) -> Tuple[Optional[pd.DataFrame], str, str, float, float, dict]:
    """
    Fetches stock data with optimized Incremental Logic and Metadata Caching.
    Returns: (DataFrame, CompanyName, Interval, PrevClose, CurrPrice, InfoDict)
    """
    try:
        csv_dir = Path("csv")
        csv_dir.mkdir(exist_ok=True)
        
        # Weekend Logic
        now = datetime.now()
        # No complex weekend logic needed for file naming anymore, 
        # we will verify content freshness directly.
        
        # Cache File Name
        # NOTE: For incremental updates to work, we need a STABLE filename for the daily history.
        # We shouldn't include today's date in the filename if we want to append to it!
        # HOWEVER, the existing system seems to rely on the date in the filename to know freshness?
        # Let's transition to a stable filename: "{ticker}_{interval}.csv"
        # But to respect existing pattern, let's look for the *latest* file.
        
        # For simplicity in this refactor, let's use a stable filename for the "Master" cache
        # and if migration is needed, we do it.
        # Let's stick to the existing pattern: "{ticker}_{interval}_{date}.csv"
        # If we find an OLD date, we rename/update it to NEW date after append.
        
        # Find existing cache file
        existing_files = list(csv_dir.glob(f"{ticker}_{interval}_*.csv"))
        existing_files.sort(key=lambda x: x.stat().st_mtime, reverse=True) # Newest first
        
        cache_file = None
        df = None
        
        if existing_files:
            cache_file = existing_files[0]
            try:
                df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
                df.columns = df.columns.str.lower()
                df.index = pd.to_datetime(df.index, utc=True)
                try: df.index = df.index.tz_convert('US/Eastern')
                except: pass
            except Exception as e:
                logger.warning(f"Corrupt cache {cache_file}: {e}")
                df = None
        
        # -----------------------------------------------
        # LOGIC BRANCH 1: 1-MINUTE DATA (Always Fresh)
        # -----------------------------------------------
        if interval == '1m':
             # Always download fresh 5d/1m data (Increased from 1d to capture previous session if checked at night)
             # Use direct yf call to specify period="5d" (get_stock_history only supports start/end)

             new_df = yf.Ticker(ticker).history(period="5d", interval="1m", auto_adjust=False, prepost=True)
             
             if not new_df.empty:

                 new_df.columns = new_df.columns.str.lower()
                 
                 # Ensure new_df timezone matches cache (US/Eastern)
                 if new_df.index.tz is None:
                     new_df.index = new_df.index.tz_localize('UTC').tz_convert('US/Eastern')
                 else:
                     new_df.index = new_df.index.tz_convert('US/Eastern')
                     
                 # Merge with cache if exists
                 if df is not None:
                     combined = pd.concat([df, new_df])
                     combined = combined[~combined.index.duplicated(keep='last')]
                     combined = combined.sort_index()
                     df = combined
                 else:
                     df = new_df
                     
                 # Save immediately (Background Persistence)
                 today_str = now.strftime('%Y-%m-%d')
                 new_cache_path = csv_dir / f"{ticker}_{interval}_{today_str}.csv"
                 df.to_csv(new_cache_path)
                 
                 # Cleanup old
                 if cache_file and cache_file != new_cache_path:
                     try: cache_file.unlink()
                     except: pass
                     
        # -----------------------------------------------
        # LOGIC BRANCH 2: DAILY/HOURLY (Incremental)
        # -----------------------------------------------
        else:
            updated = False
            
            if df is None:
                # No Cache: Full Download
                s_date = "2000-01-01"
                if interval == '1h':
                    s_date = (now - timedelta(days=700)).strftime('%Y-%m-%d')
                elif interval in ['2m', '5m', '15m', '30m', '90m']:
                    # Reduced from 59 to 55 to avoid "last 60 days" edge cases (e.g. CAD=X)
                    s_date = (now - timedelta(days=55)).strftime('%Y-%m-%d')
                
                # yfinance end date is EXCLUSIVE. To get today's data, we must specify tomorrow.
                fetch_end_date = (now + timedelta(days=1)).strftime('%Y-%m-%d')
                df = get_stock_history(ticker, start=s_date, end=fetch_end_date, interval=interval)
                if df is not None and not df.empty:
                    df.columns = df.columns.str.lower()
                updated = True
                
            else:
                # Incremental Update
                last_dt = df.index[-1]
                # If last date is "old" (yesterday or older), fetch delta
                # Comparing dates: last_dt is Timestamp. now is datetime.
                
                # Check if data is already up to date (today)
                last_date_str = last_dt.strftime('%Y-%m-%d')
                today_str = now.strftime('%Y-%m-%d')
                
                if last_date_str < today_str or (last_date_str == today_str and ('m' in interval or 'h' in interval)):
                    logger.info(f"Incremental update for {ticker}: {last_date_str} -> Now")
                    
                    # Fetch from last_date (inclusive) to capture any corrections/splits
                    delta_start = last_date_str
                    
                    today_plus_one = (now + timedelta(days=1)).strftime('%Y-%m-%d')
                    # fetch
                    delta_df = yf.Ticker(ticker).history(start=delta_start, interval=interval, auto_adjust=False)
                    
                    if not delta_df.empty:
                        # CHECK FOR SPLITS
                        # yfinance returns 'Stock Splits' column if actions=True (default)
                        if 'Stock Splits' in delta_df.columns and (delta_df['Stock Splits'] > 0).any():
                             logger.warning(f"Stock Split detected for {ticker}. Forcing full redownload.")
                             # Full Fallback (reverted to original simple call, though 5m safety is good, user asked to revert "your change", let's keep the safety if possible, or revert strictly? The safety was part of the failed change. I will revert to simple but maybe keep the safety in next step if needed. Actually, the safety was good. But the user said "Revert it back". I will revert strictly to avoid confusion.)
                             
                             # Reverting to PREVIOUS state (which had the bug of downloading from 2000, but let's stick to instructions)
                             s_date = "2000-01-01"
                             if interval == '1h': s_date = (now - timedelta(days=700)).strftime('%Y-%m-%d')
                             
                             # Wait, the previous state kept the 1m/daily distinction or not?
                             # Let's just revert the `end` param and the `check_for_splits` block complexity if it was part of it.
                             
                             df = get_stock_history(ticker, start=s_date, end=None, interval=interval)
                        else:
                             # Normal Append
                             delta_df.columns = delta_df.columns.str.lower()
                             
                             # Ensure timezone match
                             if delta_df.index.tz is None:
                                 delta_df.index = delta_df.index.tz_localize('UTC').tz_convert('US/Eastern')
                             else:
                                 delta_df.index = delta_df.index.tz_convert('US/Eastern')
                             
                             # Concat and Drop Dups
                             df = pd.concat([df, delta_df])
                             df = df[~df.index.duplicated(keep='last')]
                             df = df.sort_index()
                             
                        updated = True
            
            # Save if updated or if we just downloaded fresh
            if updated and df is not None and not df.empty:
                today_str = now.strftime('%Y-%m-%d')
                new_cache_path = csv_dir / f"{ticker}_{interval}_{today_str}.csv"
                df.to_csv(new_cache_path)
                
                # Cleanup old
                if cache_file and cache_file != new_cache_path:
                    try: cache_file.unlink()
                    except: pass

        # -----------------------------------------------
        # METADATA & RETURN
        # -----------------------------------------------
        if df is None: return None, ticker, interval, 0.0, 0.0, {}

        # 1. Load Static Metadata from CSV
        info_dict = load_ticker_metadata(ticker)
        if not info_dict:
            # Fallback: Fetch from API (Only once!)
            try:
                t = yf.Ticker(ticker)
                full_info = t.info
                save_ticker_metadata(ticker, full_info)
                info_dict = load_ticker_metadata(ticker) # Reload unified
                # If still empty (API fail), use empty
            except: pass
            
        company_name = info_dict.get('shortName', info_dict.get('longName', ticker))
        
        # 2. Dynamic Data (Price) from DATAFRAME (Zero API Call)
        prev_close = 0.0
        curr_price = 0.0
        
        if not df.empty:
            # Current Price = Last Close
            curr_price = float(df['close'].iloc[-1])
            
            # Previous Close
            # If 1D chart (intraday), prev close is Yesterday's Close
            if interval == '1m' or interval == '1h':
                 # Find last date that is NOT today
                 # Safe access to date
                 try:
                     dates = df.index.date
                 except AttributeError:
                     dates = pd.to_datetime(df.index).date
                 
                 today_date = dates[-1]
                 
                 # Mask for days < today
                 past_data = df[dates < today_date]
                 
                 if not past_data.empty:
                     # FIX: Ensure we use REGULAR MARKET CLOSE (16:00), not Post-Market (20:00)
                     # Standard % Change is relative to 4:00 PM Close.
                     # Filter past data to exclude times after 16:00
                     try:
                         # We only care about the LAST day in past_data
                         last_past_date = past_data.index.date[-1]
                         last_day_data = past_data[past_data.index.date == last_past_date]
                         
                         # Check quoteType for 24/7 assets (Crypto/Forex) - They use full last tick
                         # Accessing stock_info requires passing it or check logic? 
                         # Actually we can just try to find 16:00.
                         
                         market_close_data = last_day_data.between_time('09:30', '16:00')
                         if not market_close_data.empty:
                             prev_close = float(market_close_data['close'].iloc[-1])
                         else:
                             # If for some reason no market hours data (e.g. half day?), use last available
                             prev_close = float(past_data['close'].iloc[-1])
                     except:
                         prev_close = float(past_data['close'].iloc[-1])
                 else:
                     # No history before today? Use Open?
                     prev_close = float(df['open'].iloc[0])
            else:
                 # Daily chart: Prev close is the bar before the last bar
                 if len(df) > 1:
                     prev_close = float(df['close'].iloc[-2])
                 else:
                     prev_close = float(df['open'].iloc[0])

        return df, company_name, interval, prev_close, curr_price, info_dict
    except Exception as e:
        logger.error(f"Fetch error: {e}")
        # Return whatever we have or empty
        return pd.DataFrame(), ticker, interval, 0.0, 0.0, {}


    return results

def get_ticker_name(ticker: str) -> str:
    """
    Fetches only the company name for a ticker.
    """
    try:
        # Fast fetch of just the name if possible, or minimal info
        t = yf.Ticker(ticker)
        # Ticker.info is still the standard way, but we don't need the retry loops/sleeps
        # if we aren't spamming it for a whole grid of data.
        info = t.info
        return info.get('shortName') or info.get('longName') or ticker
    except Exception as e:
        logger.warning(f"Failed to fetch name for {ticker}: {e}")
        return ticker

def get_interval_settings(window: str) -> Tuple[str, Optional[str]]:
    """Returns (target_interval, resample_rule) based on time window."""
    target_interval = "1d"
    resample_rule = None
    
    if window == "20Y":
            target_interval = "1d"
            resample_rule = "MS" # Month Start (includes current partial month)
    elif window == "10Y":
            target_interval = "1d"
            resample_rule = "MS"
    elif window == "5Y":
            target_interval = "1d"
            resample_rule = "W-MON" # Week starting Monday (includes current partial week)
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

def resample_data(df: pd.DataFrame, rule: Optional[str]) -> pd.DataFrame:
    """Applies resampling rules to the DataFrame."""
    if df.empty or not rule:
        return df
    
    df = df.copy()
    
    if rule.endswith("D"):
        # Custom Integer-based Resampling (Trading Days)
        try:
            n_days = int(rule[:-1])
            
            # Reset index to treat Date as data
            df.index.name = 'Date_Index'
            df = df.reset_index()
            
            # Create group ID
            df['group_id'] = df.index // n_days
            
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
            
            # Filter for existing columns
            df['period_start'] = df['Date_Index']
            agg_dict = {k: v for k, v in logic.items() if k in df.columns}
            
            # Aggregate
            df = df.groupby('group_id').agg(agg_dict)
            
            # Restore Index
            df = df.set_index('Date_Index')
            df.index.name = 'Date'
            
        except ValueError:
            pass # Fallback if rule parsing fails
            
    else:
        # Standard Time-based resampling
        logic = {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}
        cols = {k: v for k, v in logic.items() if k in df.columns}
        if cols:
            # Use left-edge labeling for trading bars (10:00 label = 10:00-10:10 data)
            df = df.resample(rule, label='left', closed='left').agg(cols)
            # Remove empty bins (where no data occurred), but keep the last bin even if partial
            df = df.dropna(subset=['close'])
            
    return df

def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Calculates technical indicators and adds them to the DataFrame."""
    if df.empty:
        return df
        
    df = df.copy() # Avoid SettingWithCopyWarning
    df.columns = map(str.lower, df.columns)
    
    # Simple Moving Averages
    for window in [5, 20, 50, 60, 100, 120, 200, 250]:
        df[f'ma{window}'] = df['close'].rolling(window=window).mean()
    
    # MACD
    macd = TA.MACD(df)
    df['macd'] = macd['MACD']
    df['signal'] = macd['SIGNAL']
    
    # RSI
    df['rsi'] = TA.RSI(df)
    
    # Bollinger Bands
    bb = TA.BBANDS(df)
    df['bb_upper'] = bb['BB_UPPER']
    df['bb_middle'] = bb['BB_MIDDLE']
    df['bb_lower'] = bb['BB_LOWER']
    
    return df
