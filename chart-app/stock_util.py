# stock_util.py
import logging
import time
from typing import List, Optional
import yfinance as yf
import pandas as pd

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