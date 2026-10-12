#!/usr/bin/env python3
"""
Weekly Stock Ranking + Accuracy Tracker
Runs every Sunday via GitHub Actions.
"""

import os
import yaml
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf
import gspread
from google.oauth2.service_account import Credentials

from get_universe import get_sp500_tickers
from indicators import add_indicators

# -------------------------------------------------
# Config & Auth
# -------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
with open(ROOT / "config.yaml") as f:
    CFG = yaml.safe_load(f)

def get_gspread_client():
    # In GitHub Actions we write the secret to credentials.json
    creds_path = ROOT / "credentials.json"
    if not creds_path.exists():
        # Fallback for local testing
        creds_path = Path(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "credentials.json"))

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(str(creds_path), scopes=scopes)
    return gspread.authorize(creds)

# -------------------------------------------------
# Data & Scoring
# -------------------------------------------------
def download_data(tickers: list[str], period: str = "6mo") -> dict[str, pd.DataFrame]:
    """Download adjusted OHLCV for many tickers. Returns dict ticker → df."""
    print(f"Downloading data for {len(tickers)} tickers...")
    data = yf.download(
        tickers,
        period=period,
        group_by="ticker",
        auto_adjust=True,
        threads=True,
        progress=False,
    )

    result = {}
    if len(tickers) == 1:
        result[tickers[0]] = data
        return result

    for t in tickers:
        try:
            df = data[t].dropna(how="all")
            if not df.empty:
                result[t] = df
        except Exception:
            continue
    return result

def score_ticker(df: pd.DataFrame) -> dict | None:
    """Return a score dict or None if the stock fails filters."""
    if len(df) < 40:
        return None

    df = add_indicators(df)
    last = df.iloc[-1]

    price = float(last["Close"])
    avg_vol = float(df["Volume"].tail(20).mean())

    if price < CFG["min_price"] or avg_vol < CFG["min_avg_volume"]:
        return None
    if pd.isna(last["ret_5d"]) or pd.isna(last["rsi"]):
        return None

    # Simple RSI score: prefer 45-70 range
    rsi = float(last["rsi"])
    if rsi < 30:
        rsi_score = 0.3
    elif rsi > 75:
        rsi_score = 0.1
    else:
        rsi_score = 1.0 - abs(rsi - 55) / 40  # peak around 55

    vol_ratio = float(min(last["volume_ratio"], 3.0))  # cap extreme values

    w = CFG["weights"]
    score = (
        w["ret_5d"] * float(last["ret_5d"]) * 100 +          # scale returns
        w["ret_10d"] * float(last["ret_10d"]) * 100 +
        w["rsi_score"] * rsi_score +
        w["volume_ratio"] * (vol_ratio / 2) +
        w["above_sma20"] * float(last["above_sma20"])
    )

    return {
        "ticker": None,          # filled later
        "name": None,            # filled later
        "price": round(price, 2),
        "ret_5d": round(float(last["ret_5d"]) * 100, 2),
        "ret_10d": round(float(last["ret_10d"]) * 100, 2),
        "rsi": round(rsi, 1),
        "volume_ratio": round(vol_ratio, 2),
        "above_sma20": bool(last["above_sma20"]),
        "score": round(score, 4),
        "avg_volume": int(avg_vol),
    }

def rank_stocks(tickers: list[str], name_map: dict[str, str]) -> pd.DataFrame:
    data = download_data(tickers)
    rows = []

    for t, df in data.items():
        s = score_ticker(df)
        if s:
            s["ticker"] = t
            s["name"] = name_map.get(t, t)   # full company name
            rows.append(s)

    if not rows:
        return pd.DataFrame()

    ranked = pd.DataFrame(rows).sort_values("score", ascending=False)
    return ranked.head(CFG["top_n"]).reset_index(drop=True)

# -------------------------------------------------
# Accuracy / Performance tracking
# -------------------------------------------------
def update_accuracy(gc, sheet_id: str, previous_picks: list[dict]):
    """
    For each previous pick, fetch Mon open → Fri close return
    and append to the Accuracy tab.
    """
    if not previous_picks:
        return

    sh = gc.open_by_key(sheet_id)

    # Ensure Accuracy worksheet exists
    try:
        acc = sh.worksheet("Accuracy")
    except gspread.WorksheetNotFound:
        acc = sh.add_worksheet(title="Accuracy", rows=2000, cols=12)
        acc.append_row([
            "Week_Start", "Ticker", "Buy_Price_Mon", "Sell_Price_Fri",
            "Return_%", "Win", "Score", "Notes"
        ])

    # Determine last Monday and Friday
    today = datetime.now(timezone.utc).date()
    # We run on Sunday → previous week is Mon–Fri of the week before
    last_friday = today - timedelta(days=(today.weekday() + 3) % 7 + 1)
    last_monday = last_friday - timedelta(days=4)

    print(f"Evaluating previous week: {last_monday} → {last_friday}")

    tickers = [p["ticker"] for p in previous_picks]
    # Download the exact week
    data = yf.download(
        tickers,
        start=last_monday.isoformat(),
        end=(last_friday + timedelta(days=1)).isoformat(),
        group_by="ticker",
        auto_adjust=True,
        progress=False,
    )

    new_rows = []
    for pick in previous_picks:
        t = pick["ticker"]
        try:
            if len(tickers) == 1:
                df = data
            else:
                df = data[t]

            df = df.dropna(subset=["Open", "Close"])
            if len(df) < 3:
                continue

            buy = float(df.iloc[0]["Open"])      # Monday open
            sell = float(df.iloc[-1]["Close"])   # Friday close
            ret = (sell / buy - 1) * 100
            win = 1 if ret > 0 else 0

            new_rows.append([
                last_monday.isoformat(),
                t,
                round(buy, 2),
                round(sell, 2),
                round(ret, 2),
                win,
                pick.get("score", ""),
                "auto"
            ])
        except Exception as e:
            print(f"Could not evaluate {t}: {e}")

    if new_rows:
        acc.append_rows(new_rows)
        print(f"Added {len(new_rows)} accuracy rows")

def write_current_picks(gc, sheet_id: str, ranked: pd.DataFrame, week_label: str):
    sh = gc.open_by_key(sheet_id)

    # Current Top 10 sheet
    try:
        ws = sh.worksheet("Current Top 10")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title="Current Top 10", rows=50, cols=14)

    ws.clear()
    headers = [
        "Rank", "Ticker", "Company Name", "Price", "Score",
        "5d %", "10d %", "RSI", "Vol Ratio", "Above SMA20",
        "Avg Volume", "Week", "Generated"
    ]
    ws.append_row(headers)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    rows = []
    for i, r in ranked.iterrows():
        rows.append([
            i + 1,
            r["ticker"],
            r["name"],                 # ← full company name
            r["price"],
            r["score"],
            r["ret_5d"],
            r["ret_10d"],
            r["rsi"],
            r["volume_ratio"],
            r["above_sma20"],
            r["avg_volume"],
            week_label,
            now
        ])
    ws.append_rows(rows)

    # Also keep a History log
    try:
        hist = sh.worksheet("History")
    except gspread.WorksheetNotFound:
        hist = sh.add_worksheet(title="History", rows=5000, cols=14)
        hist.append_row(headers)

    hist.append_rows(rows)

# -------------------------------------------------
# Main
# -------------------------------------------------
def main():
    sheet_id = os.environ.get("SHEET_ID")
    if not sheet_id:
        raise RuntimeError("SHEET_ID environment variable is required")

    gc = get_gspread_client()

    # 1. Get previous picks (from Current Top 10) so we can score them
    previous_picks = []
    try:
        sh = gc.open_by_key(sheet_id)
        ws = sh.worksheet("Current Top 10")
        records = ws.get_all_records()
        previous_picks = [
            {"ticker": r["Ticker"], "score": r.get("Score")}
            for r in records if r.get("Ticker")
        ]
    except Exception as e:
        print(f"No previous picks found (first run?): {e}")

    # 2. Update accuracy of last week's picks
    if previous_picks:
        update_accuracy(gc, sheet_id, previous_picks)

    # 3. Rank this week's stocks
    tickers, name_map = get_sp500_tickers()
    ranked = rank_stocks(tickers, name_map)

    if ranked.empty:
        print("No stocks passed filters!")
        return

    print("\nTop 10 this week:")
    print(ranked[["ticker", "name", "score", "ret_5d", "rsi"]].to_string(index=False))

    # 4. Write new picks
    today = datetime.now(timezone.utc).date()
    # Next Monday
    days_ahead = (7 - today.weekday()) % 7
    next_monday = today + timedelta(days=days_ahead or 7)
    week_label = next_monday.isoformat()

    write_current_picks(gc, sheet_id, ranked, week_label)
    print(f"\nSuccessfully wrote top 10 for week starting {week_label}")

if __name__ == "__main__":
    main()
