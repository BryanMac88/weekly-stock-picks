import pandas as pd
import requests
from io import StringIO

def get_sp500_tickers() -> list[str]:
    """Fetch current S&P 500 tickers from Wikipedia."""
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; weekly-stock-picks/1.0; +https://github.com/BryanMac88/weekly-stock-picks)"
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    tables = pd.read_html(StringIO(resp.text))
    df = tables[0]
    tickers = (
        df["Symbol"]
        .astype(str)
        .str.replace(".", "-", regex=False)  # BRK.B → BRK-B for Yahoo
        .tolist()
    )
    return tickers
