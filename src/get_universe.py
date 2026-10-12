import pandas as pd
import requests
from io import StringIO

def get_sp500_tickers() -> tuple[list[str], dict[str, str]]:
    """
    Fetch current S&P 500 tickers + full company names from Wikipedia.
    Returns:
        tickers: list of Yahoo-compatible symbols (e.g. BRK-B)
        name_map: dict {ticker: full company name}
    """
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; weekly-stock-picks/1.0; +https://github.com/BryanMac88/weekly-stock-picks)"
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()

    tables = pd.read_html(StringIO(resp.text))
    df = tables[0]

    # Clean symbol for Yahoo Finance (BRK.B → BRK-B)
    df["Symbol"] = (
        df["Symbol"]
        .astype(str)
        .str.replace(".", "-", regex=False)
    )

    tickers = df["Symbol"].tolist()
    name_map = dict(zip(df["Symbol"], df["Security"]))

    return tickers, name_map
