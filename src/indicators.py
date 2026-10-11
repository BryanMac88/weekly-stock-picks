import pandas as pd
import numpy as np
from ta.momentum import RSIIndicator
from ta.trend import SMAIndicator

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add technical indicators to a single-ticker OHLCV dataframe."""
    if df.empty or len(df) < 30:
        return df

    df = df.copy()
    close = df["Close"]

    # Returns
    df["ret_5d"] = close.pct_change(5)
    df["ret_10d"] = close.pct_change(10)
    df["ret_20d"] = close.pct_change(20)

    # RSI
    rsi = RSIIndicator(close=close, window=14)
    df["rsi"] = rsi.rsi()

    # SMA
    sma20 = SMAIndicator(close=close, window=20)
    df["sma20"] = sma20.sma_indicator()
    df["above_sma20"] = (close > df["sma20"]).astype(float)

    # Volume
    df["vol_ma20"] = df["Volume"].rolling(20).mean()
    df["volume_ratio"] = df["Volume"] / df["vol_ma20"]

    return df
