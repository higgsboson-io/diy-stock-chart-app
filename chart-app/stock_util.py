# stock_util.py
import logging
from typing import Optional, Tuple, Dict, Any
from datetime import datetime, timedelta
from pathlib import Path
import pytz
import numpy as np
import pandas as pd
import yfinance as yf

try:
    from finta import TA
    HAS_FINTA = True
except ImportError:
    HAS_FINTA = False

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
EASTERN = pytz.timezone("America/New_York")

APP_DIR = Path(__file__).resolve().parent
DEFAULT_CSV_DIR = APP_DIR / "csv"


def get_stock_history(ticker: str, start: str, end: Optional[str], interval: str = "1d", prepost: bool = False) -> pd.DataFrame:
    """
    Downloads historical stock data for a given ticker using yfinance.
    """
    try:
        stock = yf.Ticker(ticker)
        history = stock.history(start=start, end=end, interval=interval, auto_adjust=False, prepost=prepost)
        if history.empty:
            logger.warning(f"No data returned for {ticker} from {start} to {end}")
        return history
    except Exception as e:
        logger.error(f"Failed to fetch history for {ticker}: {e}")
        return pd.DataFrame()


def cleanup_old_cache(csv_dir_path: Optional[Path] = None, days: int = 7):
    """Removes price CSV files in the cache directory older than N days (preserves *_info.csv)."""
    try:
        csv_dir = Path(csv_dir_path) if csv_dir_path else DEFAULT_CSV_DIR
        if not csv_dir.exists():
            return

        now = datetime.now()
        cutoff = now - timedelta(days=days)

        count = 0
        for csv_file in csv_dir.glob("*.csv"):
            if csv_file.name.endswith("_info.csv"):
                continue
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


def get_metadata_path(ticker: str) -> Path:
    return DEFAULT_CSV_DIR / f"{ticker}_info.csv"


def load_ticker_metadata(ticker: str) -> Dict[str, Any]:
    """Loads static metadata from CSV sidecar (30-day TTL)."""
    try:
        path = get_metadata_path(ticker)
        if not path.exists():
            return {}

        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        if (datetime.now() - mtime).days > 30:
            return {}

        info: Dict[str, Any] = {}
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                parts = line.strip().split(',', 1)
                if len(parts) == 2:
                    info[parts[0]] = parts[1]

        if 'quoteType' not in info:
            return {}

        expected_keys = ['dividendRate', 'yield', 'fiftyTwoWeekLow', 'beta', 'previousClose']
        for k in expected_keys:
            if k not in info:
                logger.info(f"Metadata for {ticker} missing {k}. Forcing refresh.")
                return {}

        return info
    except Exception as e:
        logger.warning(f"Failed to load metadata CSV for {ticker}: {e}")
        return {}


def save_ticker_metadata(ticker: str, info_dict: Dict[str, Any]):
    """Saves static metadata to CSV sidecar."""
    try:
        path = get_metadata_path(ticker)
        path.parent.mkdir(parents=True, exist_ok=True)

        keys = [
            'shortName', 'longName', 'sector', 'industry', 'exchange', 'currency', 'quoteType',
            'dividendRate', 'trailingAnnualDividendRate', 'yield', 'dividendYield',
            'fiftyTwoWeekLow', 'fiftyTwoWeekHigh', 'averageVolume', 'beta', 'beta3Year',
            'exDividendDate', 'targetMeanPrice', 'earningsTimestamp', 'earningsTimestampStart',
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
                val = str(val).replace(',', ';') if val is not None else ''
                f.write(f"{k},{val}\n")
    except Exception as e:
        logger.warning(f"Failed to save metadata CSV for {ticker}: {e}")


def fetch_stock_data_with_cache(ticker: str, interval: str) -> Tuple[Optional[pd.DataFrame], str, str, float, float, dict]:
    """
    Fetches stock data with smart incremental CSV caching and metadata sidecar caching.
    Returns: (DataFrame, CompanyName, Interval, PrevClose, CurrPrice, InfoDict)
    """
    try:
        csv_dir = DEFAULT_CSV_DIR
        csv_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now()

        existing_files = list(csv_dir.glob(f"{ticker}_{interval}_*.csv"))
        existing_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)

        cache_file = None
        df = None

        if existing_files:
            cache_file = existing_files[0]
            try:
                df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
                df.columns = df.columns.str.lower()
                df.index = pd.to_datetime(df.index, utc=True)
                df.index = df.index.tz_convert(EASTERN)
            except Exception as e:
                logger.warning(f"Corrupt cache {cache_file}: {e}")
                df = None

        # BRANCH 1: 1-MINUTE DATA (Always refresh 5-day buffer)
        if interval == '1m':
            try:
                new_df = yf.Ticker(ticker).history(period="5d", interval="1m", auto_adjust=False, prepost=True)
                if not new_df.empty:
                    new_df.columns = new_df.columns.str.lower()
                    if new_df.index.tz is None:
                        new_df.index = new_df.index.tz_localize('UTC').tz_convert(EASTERN)
                    else:
                        new_df.index = new_df.index.tz_convert(EASTERN)

                    if df is not None:
                        combined = pd.concat([df, new_df])
                        combined = combined[~combined.index.duplicated(keep='last')]
                        df = combined.sort_index()
                    else:
                        df = new_df

                    today_str = now.strftime('%Y-%m-%d')
                    new_cache_path = csv_dir / f"{ticker}_{interval}_{today_str}.csv"
                    df.to_csv(new_cache_path)

                    if cache_file and cache_file != new_cache_path:
                        try:
                            cache_file.unlink()
                        except Exception:
                            pass
            except Exception as e:
                if df is None:
                    raise
                logger.warning("One-minute update failed for %s; using cached data: %s", ticker, e)

        # BRANCH 2: DAILY / HOURLY / INTRADAY (Incremental)
        else:
            updated = False
            if df is None:
                s_date = "2000-01-01"
                if interval == '1h':
                    s_date = (now - timedelta(days=700)).strftime('%Y-%m-%d')
                elif interval in ['2m', '5m', '15m', '30m', '90m']:
                    s_date = (now - timedelta(days=55)).strftime('%Y-%m-%d')

                fetch_end_date = (now + timedelta(days=1)).strftime('%Y-%m-%d')
                df = get_stock_history(ticker, start=s_date, end=fetch_end_date, interval=interval)
                if df is not None and not df.empty:
                    df.columns = df.columns.str.lower()
                    if df.index.tz is None:
                        df.index = df.index.tz_localize('UTC').tz_convert(EASTERN)
                    else:
                        df.index = df.index.tz_convert(EASTERN)
                updated = True
            else:
                last_dt = df.index[-1]
                last_date_str = last_dt.strftime('%Y-%m-%d')
                today_str = now.strftime('%Y-%m-%d')

                # The latest daily candle also changes during the trading day.
                if last_date_str <= today_str:
                    logger.info(f"Incremental update for {ticker}: {last_date_str} -> Now")
                    try:
                        delta_df = yf.Ticker(ticker).history(start=last_date_str, interval=interval, auto_adjust=False)
                        if not delta_df.empty:
                            if 'Stock Splits' in delta_df.columns and (delta_df['Stock Splits'] > 0).any():
                                logger.warning(f"Stock Split detected for {ticker}. Forcing full redownload.")
                                s_date = "2000-01-01"
                                if interval == '1h':
                                    s_date = (now - timedelta(days=700)).strftime('%Y-%m-%d')
                                refreshed_df = get_stock_history(ticker, start=s_date, end=None, interval=interval)
                                if refreshed_df is not None and not refreshed_df.empty:
                                    refreshed_df.columns = refreshed_df.columns.str.lower()
                                    if refreshed_df.index.tz is None:
                                        refreshed_df.index = refreshed_df.index.tz_localize('UTC').tz_convert(EASTERN)
                                    else:
                                        refreshed_df.index = refreshed_df.index.tz_convert(EASTERN)
                                    df = refreshed_df
                                    updated = True
                            else:
                                delta_df.columns = delta_df.columns.str.lower()
                                if delta_df.index.tz is None:
                                    delta_df.index = delta_df.index.tz_localize('UTC').tz_convert(EASTERN)
                                else:
                                    delta_df.index = delta_df.index.tz_convert(EASTERN)

                                combined = pd.concat([df, delta_df])
                                combined = combined[~combined.index.duplicated(keep='last')]
                                df = combined.sort_index()
                                updated = True
                    except Exception as e:
                        logger.warning("Incremental update failed for %s; using cached data: %s", ticker, e)

            if updated and df is not None and not df.empty:
                today_str = now.strftime('%Y-%m-%d')
                new_cache_path = csv_dir / f"{ticker}_{interval}_{today_str}.csv"
                df.to_csv(new_cache_path)

                if cache_file and cache_file != new_cache_path:
                    try:
                        cache_file.unlink()
                    except Exception:
                        pass

        if df is None:
            return None, ticker, interval, 0.0, 0.0, {}

        # Metadata Sidecar
        info_dict = load_ticker_metadata(ticker)
        if not info_dict:
            try:
                full_info = yf.Ticker(ticker).info
                save_ticker_metadata(ticker, full_info)
                info_dict = load_ticker_metadata(ticker)
            except Exception:
                pass

        company_name = info_dict.get('shortName') or info_dict.get('longName') or ticker

        prev_close = 0.0
        curr_price = 0.0

        if not df.empty:
            curr_price = float(df['close'].iloc[-1])

            if interval in ('1m', '1h'):
                try:
                    dates = df.index.date
                except AttributeError:
                    dates = pd.to_datetime(df.index).date

                today_date = dates[-1]
                past_data = df[dates < today_date]

                if not past_data.empty:
                    try:
                        last_past_date = past_data.index.date[-1]
                        last_day_data = past_data[past_data.index.date == last_past_date]
                        market_close_data = last_day_data.between_time('09:30', '16:00')
                        if not market_close_data.empty:
                            prev_close = float(market_close_data['close'].iloc[-1])
                        else:
                            prev_close = float(past_data['close'].iloc[-1])
                    except Exception:
                        prev_close = float(past_data['close'].iloc[-1])
                else:
                    prev_close = float(df['open'].iloc[0])
            else:
                if len(df) > 1:
                    prev_close = float(df['close'].iloc[-2])
                else:
                    prev_close = float(df['open'].iloc[0])

        return df, company_name, interval, prev_close, curr_price, info_dict
    except Exception as e:
        logger.error(f"Fetch error for {ticker}: {e}")
        return pd.DataFrame(), ticker, interval, 0.0, 0.0, {}


def get_ticker_name(ticker: str) -> str:
    """Fetches only the company display name for a ticker (uses metadata cache first)."""
    cached = load_ticker_metadata(ticker)
    if cached:
        name = cached.get('shortName') or cached.get('longName')
        if name:
            return name
    try:
        info = yf.Ticker(ticker).info
        if info:
            save_ticker_metadata(ticker, info)
            return info.get('shortName') or info.get('longName') or ticker
    except Exception as e:
        logger.warning(f"Failed to fetch name for {ticker}: {e}")
    return ticker


def get_interval_settings(window: str) -> Tuple[str, Optional[str]]:
    """Maps UI time-window label to (yfinance_interval, pandas_resample_rule)."""
    target_interval = "1d"
    resample_rule = None

    if window in ("20Y", "10Y"):
        target_interval = "1d"
        resample_rule = "MS"
    elif window == "5Y":
        target_interval = "1d"
        resample_rule = "W-MON"
    elif window == "3Y":
        target_interval = "1d"
        resample_rule = "3D"
    elif window == "2Y":
        target_interval = "1d"
        resample_rule = "2D"
    elif window == "1WK":
        target_interval = "5m"
        resample_rule = "10min"
    elif window == "YTD":
        today = datetime.now()
        days = (today - datetime(today.year, 1, 1)).days
        target_interval = "1h" if days <= 90 else "1d"
    elif window == "1D":
        target_interval = "1m"
    elif window in ("1Y", "6M"):
        target_interval = "1d"
    elif window in ("3M", "1M"):
        target_interval = "1h"

    return target_interval, resample_rule


def resample_data(df: pd.DataFrame, rule: Optional[str]) -> pd.DataFrame:
    """Applies trading-day integer grouping (2D/3D) or time-based OHLCV resampling."""
    if df.empty or not rule:
        return df

    df = df.copy()

    if rule.endswith("D"):
        try:
            n_days = int(rule[:-1])
            df.index.name = 'Date_Index'
            df = df.reset_index()
            df['group_id'] = df.index // n_days
            df['period_start'] = df['Date_Index']

            logic = {
                'Date_Index': 'last',
                'period_start': 'first',
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }
            agg_dict = {k: v for k, v in logic.items() if k in df.columns}
            df = df.groupby('group_id').agg(agg_dict)
            df = df.set_index('Date_Index')
            df.index.name = 'Date'
        except ValueError:
            pass
    else:
        logic = {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}
        cols = {k: v for k, v in logic.items() if k in df.columns}
        if cols:
            df = df.resample(rule, label='left', closed='left').agg(cols)
            df = df.dropna(subset=['close'])

    return df


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Calculates SMAs (5..250), MACD, RSI, and Bollinger Bands."""
    if df.empty:
        return df

    df = df.copy()
    df.columns = map(str.lower, df.columns)

    for window in [5, 20, 50, 60, 100, 120, 200, 250]:
        df[f'ma{window}'] = df['close'].rolling(window=window).mean()

    if HAS_FINTA:
        try:
            macd = TA.MACD(df)
            df['macd'] = macd['MACD']
            df['signal'] = macd['SIGNAL']

            df['rsi'] = TA.RSI(df)

            bb = TA.BBANDS(df)
            df['bb_upper'] = bb['BB_UPPER']
            df['bb_middle'] = bb['BB_MIDDLE']
            df['bb_lower'] = bb['BB_LOWER']
            return df
        except Exception as e:
            logger.warning(f"FinTA calculation fallback triggered: {e}")

    # Pure-pandas fallback (identical formulas)
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = ema12 - ema26
    df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()

    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    df['rsi'] = 100.0 - (100.0 / (1.0 + rs))

    mid = df['close'].rolling(window=20).mean()
    std = df['close'].rolling(window=20).std()
    df['bb_middle'] = mid
    df['bb_upper'] = mid + 2.0 * std
    df['bb_lower'] = mid - 2.0 * std

    return df
