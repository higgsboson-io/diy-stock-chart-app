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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def read_tickers_from_file(file_path: str) -> List[str]:
    """
    Reads a list of stock tickers from a text file.

    Args:
        file_path (str): The absolute path to the ticker file.

    Returns:
        List[str]: A list of ticker symbols.
    """
    try:
        with open(file_path, 'r') as file:
            tickers = [line.strip() for line in file if line.strip()]
        logger.info(f"Loaded {len(tickers)} tickers from {file_path}")
        return tickers
    except FileNotFoundError:
        logger.error(f"Ticker file not found: {file_path}")
        return []
    except Exception as e:
        logger.error(f"Error reading ticker file: {e}")
        return []

def get_stock_history(ticker: str, start: str, end: str, interval: str = "1d") -> pd.DataFrame:
    """
    Downloads historical stock data for a given ticker.

    Args:
        ticker (str): The stock symbol (e.g., 'AAPL').
        start (str): Start date string (YYYY-MM-DD).
        end (str): End date string (YYYY-MM-DD).
        interval (str): Data interval (default 1d).

    Returns:
        pd.DataFrame: DataFrame containing historical data. 
                      Returns empty DataFrame on failure.
    """
    try:
        stock = yf.Ticker(ticker)
        # Use auto_adjust=False to match visual trading prices
        history = stock.history(start=start, end=end, interval=interval, auto_adjust=False)
        
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

def fetch_stock_data_with_cache(ticker: str, interval: str) -> Tuple[Optional[pd.DataFrame], str, str, float, float, dict]:
    """
    Fetches stock data, handling caching logic.
    Returns: (DataFrame, CompanyName, Interval, PrevClose, CurrPrice, InfoDict)
    """
    try:
        # Check for cached data (Skip for 1m interval)
        csv_dir = Path("csv")
        csv_dir.mkdir(exist_ok=True)
        
        # Weekend Logic: Snap to Friday if Sat/Sun
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
                    
                    # Enforce data types
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
                    # Use auto_adjust=False to get RAW price
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
            t = yf.Ticker(ticker)
            # Fetch FULL info for sidebar
            info_dict = t.info
            company_name = info_dict.get('shortName', info_dict.get('longName', ticker))
            prev_close = info_dict.get('previousClose', 0.0)
            curr_price = info_dict.get('currentPrice') or info_dict.get('regularMarketPrice') or 0.0
        except Exception as e:
            logger.warning(f"Failed to fetch metadata: {e}")

        return df, company_name, interval, prev_close, curr_price, info_dict
    except Exception as e:
        logger.error(f"Fetch error: {e}")
        raise e

def get_interval_settings(window: str) -> Tuple[str, Optional[str]]:
    """Returns (target_interval, resample_rule) based on time window."""
    target_interval = "1d"
    resample_rule = None
    
    if window == "20Y":
            target_interval = "1d"
            resample_rule = "1ME"
    elif window == "10Y":
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
            df = df.resample(rule).agg(cols).dropna()
            
    return df

def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Calculates technical indicators and adds them to the DataFrame."""
    if df.empty:
        return df
        
    df.columns = map(str.lower, df.columns)
    
    # Simple Moving Averages
    for window in [5, 20, 50, 60, 100, 120, 200]:
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