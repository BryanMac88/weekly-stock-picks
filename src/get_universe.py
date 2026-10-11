import pandas as pd

def get_sp500_tickers() -> list[str]:
    """Fetch current S&P 500 tickers from Wikipedia."""
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    tables = pd.read_html(url)
    df = tables[0]
    tickers = (
        df["Symbol"]
        .astype(str)
        .str.replace(".", "-", regex=False)  # BRK.B → BRK-B for Yahoo
        .tolist()
    )
    return tickers
