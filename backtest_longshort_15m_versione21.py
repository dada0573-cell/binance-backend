"""
╔══════════════════════════════════════════════════════════════════════════════╗
║   WALK-FORWARD BACKTEST — LONG + SHORT 15m — versione21                    ║
║   Laboratorio Sperimentale Controllato (NON ottimizzazione)                ║
║   Event-Driven Architecture + Pattern Confirmation + ATR Anchored          ║
╚══════════════════════════════════════════════════════════════════════════════╝

FILOSOFIA v21: modello OHLC two-pass corretto + trailing_activation 2.5%.

CAMBIAMENTI rispetto a v20:

  BUG FIX DEFINITIVO — two-pass OHLC model
  • [FIX] check_exit_ohlc completamente ristrutturato in due passaggi:

    PASS 1 — ATTIVAZIONI (contro HIGH per long, LOW per short):
      1a. Breakeven trigger  → sposta sl_price a breakeven_price
      1b. Trailing activation → imposta trailing_active=True
      1c. Trailing best_price update + calc trailing_stop
      1d. TP1 parziale
      1e. TP2 parziale

    PASS 2 — USCITE (contro LOW per long, HIGH per short):
      2a. Trailing stop check  → "trailing_stop"
      2b. SL / Breakeven check → "SL_atr" | "breakeven_hit"
      2c. Timeout              → "timeout" | "timeout_profit"

  Perché v19/v20 non funzionavano:
    SSV entry=3.808. Su una singola candela: HIGH raggiunge +3.5%
    (trailing dovrebbe attivarsi in step 6), poi LOW scende sotto
    breakeven_price. Nel modello single-pass, step 3 (breakeven check)
    girava prima di step 6 (trailing activation): trailing_active era
    ancora False → usciva come "breakeven_hit" invece di "trailing_stop".
    Il fix v20 (skip step1 se trailing_active) non copriva questo caso:
    trailing_active diventava True SOLO allo step 6 dello stesso candle.
    Con il two-pass: pass1 attiva TUTTO sul HIGH (breakeven + trailing),
    poi pass2 controlla il LOW con trailing_active=True → "trailing_stop".

  CONFIG — TRAILING (ripristino)
  • trailing_activation:   0.035 → 0.025
    Con il two-pass corretto il parametro è tornato sicuro.
    Ripristinato a 0.025 (v19 originale): più trade in trailing.

  INVARIATI rispetto a v19/v20
  • breakeven_buffer:      0.010
  • trailing_distance:     0.012
  • sl_atr_max_distance:   0.060
  • runner_score_min:      30
  • runner_momentum_pct:   0.015
  • [FIX] idx < 479, calc_adx delega a calc_adx_with_di

  SHORT — invariato (abilitato, simulato)
  ⚠️  SHORT su Binance Spot non è eseguibile in produzione.

CONFRONTO:
  v18: PF 0.43, Return -3.25%, Trade 29, WR 75.9%
  v19: PF 0.79, Return -1.04%, Trade 29, WR 79.3%  (bug single-pass residuo)
  v20: PF 0.77, Return -1.11%, Trade 29, WR 75.9%  (fix incompleto)
  v21 target: PF > 1.0 — SSV+XVG+TURTLE → trailing_stop col two-pass
"""

# ─────────────────────────────────────────────────────────────────────────────
#  TEST RAPIDO vs RUN COMPLETO
# ─────────────────────────────────────────────────────────────────────────────
TEST_PAIRS = []

BACKTEST_DAYS = 365

CONFIG = {

    # — Mercato —
    "exchange":             "binance",
    "timeframe_signal":     "15m",
    "timeframe_context":    "1h",

    # — Direzione —
    "long_enabled":         True,
    "short_enabled":        True,           # ⚠️ simulato su spot, non eseguibile reale

    # — Screening bidirezionale —
    "screening_interval_hours": 4,
    "screening_top_n":          5,
    "screening_warmup_days":    30,

    # — Filtro liquidità —
    "position_to_volume_pct":   0.003,
    "liquidity_window_days":    30,

    # — Filtro attività body-based —
    "activity_window_days":         90,
    "activity_metric":              "body",
    "significant_move_pct":         0.007,
    "min_significant_moves_90d":    20,

    "min_volume_usdc":          500_000,    # LEGACY non usato

    # — Screener criteri runner —
    "runner_vol_spike":         2.0,
    "runner_momentum_pct":      0.015,      # v19: 0.020 → 0.015
    "runner_adx_min":           18,
    "runner_rsi_up_min":        50,
    "runner_rsi_up_max":        75,
    "runner_rsi_down_min":      25,
    "runner_rsi_down_max":      50,
    "runner_green_min":         3,
    "runner_red_min":           3,
    "runner_net_mom_min":       0.8,
    "runner_score_min":         30,         # v19: 40 → 30

    # — Margin whitelist —
    "margin_whitelist": {
        "BTC/USDC","ETH/USDC","BNB/USDC","SOL/USDC","XRP/USDC",
        "ADA/USDC","AVAX/USDC","DOT/USDC","LINK/USDC","MATIC/USDC",
        "UNI/USDC","ATOM/USDC","LTC/USDC","BCH/USDC","NEAR/USDC",
        "ALGO/USDC","FIL/USDC","AAVE/USDC","MKR/USDC","CRV/USDC",
        "ZEC/USDC","DASH/USDC","ETC/USDC","XLM/USDC","TRX/USDC",
        "GRT/USDC","CHZ/USDC","MANA/USDC","SAND/USDC","AXS/USDC",
        "ICP/USDC","FTM/USDC","HBAR/USDC","STX/USDC","OP/USDC",
        "ARB/USDC","APT/USDC","SUI/USDC","INJ/USDC","SEI/USDC",
        "WLD/USDC","TON/USDC","RENDER/USDC","PENDLE/USDC","ZEN/USDC",
        "ONDO/USDC","PLUME/USDC","EDEN/USDC","SOMI/USDC","NIL/USDC",
        "MITO/USDC","BERA/USDC","PENGU/USDC","EIGEN/USDC",
        "HYPE/USDC","JUP/USDC","TIA/USDC","PYTH/USDC",
    },

    # — Stablecoin —
    "stablecoin": {
        "USDT","BUSD","DAI","FDUSD","TUSD","USDP",
        "USDD","GUSD","FRAX","LUSD","SUSD","CUSD","USDC",
    },

    # — Capitale (5 slot da 100 USDC) —
    "capital_total":        1000.0,
    "reserve_pct":          0.50,
    "n_slots":              5,

    # — Commissioni —
    "commission_pct":       0.00075,

    # — Contesto 1h —
    "ctx_ema_fast":         9,
    "ctx_ema_slow":         21,
    "ctx_adx_period":       14,
    "ctx_adx_min":          20,

    # — Segnale 15m —
    "sig_ema_fast":         9,
    "sig_ema_slow":         21,
    "sig_adx_period":       14,
    "sig_adx_min":          20,
    "sig_rsi_period":       14,
    "sig_rsi_min_long":     50,
    "sig_rsi_max_long":     70,
    "sig_rsi_min_short":    30,
    "sig_rsi_max_short":    50,
    "sig_volume_mult":      2.0,
    "confirm_candle":       True,

    # — Entry Confirmation —
    "entry_confirmation_required":  True,
    "entry_confirmation_window":    1,
    "pattern_body_min_pct":         0.50,
    "pattern_doji_max_pct":         0.10,
    "pattern_long_shadow_max":      0.60,
    "pattern_pullback_required":    False,

    # — Breakeven (trigger ±1.5%, target ±1.0%) —
    "breakeven_trigger":    0.015,
    "breakeven_buffer":     0.010,          # v19: 0.005 → 0.010

    # — TP parziali (invariati) —
    "tp1_pct":              0.030,
    "tp1_close_pct":        0.30,
    "tp2_pct":              0.070,
    "tp2_close_pct":        0.30,

    # — Trailing v21 — two-pass fix rende sicuro il valore originale v19
    "trailing_activation":  0.025,          # v21: 0.035 → 0.025 (ripristino v19)
    "trailing_distance":    0.012,

    # — SL ATR-anchored —
    "sl_atr_period":                20,
    "sl_atr_anchor_lookback":       2,
    "sl_atr_multiplier_long":       4.0,
    "sl_atr_multiplier_short":      3.0,
    "sl_atr_min_distance":          0.02,
    "sl_atr_max_distance":          0.06,   # v19: 0.12 → 0.06

    # — Timeout (24h safety rail) —
    "max_duration_hours_long":      24,
    "max_duration_hours_short":     24,

    # — Modello OHLC —
    "ohlc_fill_model":              "pessimistic",

    # — LEGACY —
    "sl_long_enabled":              True,
    "sl_long_catastrophic_pct":     0.150,
    "sl_short_pct":                 0.080,
    "fast_fail_enabled":            False,
    "fast_fail_minutes":            180,

    # — Sessioni: 24h —
    "sessions": [(0, 24)],
}

# ─────────────────────────────────────────────────────────────────────────────
#  IMPORTS
# ─────────────────────────────────────────────────────────────────────────────

import os
import sys
import time
import warnings
from datetime import datetime, timezone, timedelta

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from tqdm import tqdm

warnings.filterwarnings("ignore")

try:
    import ccxt
except ImportError:
    raise ImportError("pip install ccxt")

os.makedirs("results_wf_v21", exist_ok=True)
os.makedirs("data_cache",     exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
#  INDICATORI NATIVI
# ─────────────────────────────────────────────────────────────────────────────

def calc_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta    = series.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs       = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c    = df["high"], df["low"], df["close"]
    prev_close = c.shift(1)
    tr = pd.concat([h-l, (h-prev_close).abs(), (l-prev_close).abs()],
                   axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, min_periods=period, adjust=False).mean()

def calc_adx_with_di(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Calcola ADX, +DI e -DI. Unica implementazione, usata da calc_adx."""
    h, l, c  = df["high"], df["low"], df["close"]
    up_move   = h.diff()
    down_move = -l.diff()
    plus_dm   = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm  = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    atr14    = calc_atr(df, period)
    plus_di  = 100 * (plus_dm.ewm(alpha=1/period, adjust=False).mean()  / atr14)
    minus_di = 100 * (minus_dm.ewm(alpha=1/period, adjust=False).mean() / atr14)
    dx  = (100 * (plus_di - minus_di).abs() /
           (plus_di + minus_di).replace(0, np.nan))
    adx = dx.ewm(alpha=1/period, adjust=False).mean()
    return pd.DataFrame({"adx": adx, "plus_di": plus_di, "minus_di": minus_di})

def calc_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Restituisce solo la serie ADX. Delega a calc_adx_with_di (no duplicazione)."""
    return calc_adx_with_di(df, period)["adx"]

# ─────────────────────────────────────────────────────────────────────────────
#  DOWNLOAD E CACHE
# ─────────────────────────────────────────────────────────────────────────────

def get_exchange() -> ccxt.Exchange:
    return ccxt.binance({"enableRateLimit": True})

def get_usdc_pairs(exchange: ccxt.Exchange, cfg: dict) -> list:
    markets = exchange.load_markets()
    pairs   = []
    for sym, mkt in markets.items():
        if not mkt.get("active", False): continue
        if mkt.get("type","")  != "spot": continue
        if mkt.get("quote","") != "USDC": continue
        if mkt.get("base","")  in cfg["stablecoin"]: continue
        pairs.append(sym)
    return sorted(pairs)

def read_csv_fast(path: str) -> pd.DataFrame | None:
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True,
                         dtype={"open":"float32","high":"float32",
                                "low":"float32","close":"float32",
                                "volume":"float32"})
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")
        return df if len(df) > 100 else None
    except Exception:
        return None

def download_pair(exchange: ccxt.Exchange, symbol: str,
                  timeframe: str, days: int) -> pd.DataFrame | None:
    safe       = symbol.replace("/","_")
    cache_path = f"data_cache/{safe}_{timeframe}_{days}gg.csv"
    if os.path.exists(cache_path):
        df = read_csv_fast(cache_path)
        expected = days * 24 * 60 // {"5m":5,"15m":15,"1h":60,"1d":1440}[timeframe]
        if df is not None and len(df) >= expected * 0.90:
            return df
    now_ms   = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = now_ms - days * 24 * 3600 * 1000
    tf_mins  = {"5m":5,"15m":15,"1h":60,"1d":1440}
    mins     = tf_mins.get(timeframe, 5)
    all_data = []
    since    = start_ms
    try:
        while True:
            batch = exchange.fetch_ohlcv(symbol, timeframe,
                                          since=since, limit=1000)
            if not batch: break
            all_data.extend(batch)
            last_ts = batch[-1][0]
            if last_ts >= now_ms - mins * 60 * 1000: break
            since = last_ts + 1
            time.sleep(exchange.rateLimit / 1000)
    except Exception:
        return None
    if len(all_data) < 50:
        return None
    df = pd.DataFrame(all_data,
                      columns=["timestamp","open","high","low","close","volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("timestamp").sort_index()
    df = df[~df.index.duplicated(keep="first")]
    df.to_csv(cache_path)
    return df

def calculate_liquidity_threshold(cfg: dict) -> float:
    capital_op = cfg["capital_total"] * (1 - cfg["reserve_pct"])
    slot_size  = capital_op / cfg["n_slots"]
    return slot_size / cfg["position_to_volume_pct"]

def measure_pair_liquidity(file_1h_path: str, window_days: int) -> float:
    try:
        df = pd.read_csv(file_1h_path, index_col=0)
        if len(df) < 24 * 7:
            return -1
        hours_needed = window_days * 24
        df = df.tail(hours_needed).copy()
        df["vol_usdc"] = df["volume"].astype(float) * df["close"].astype(float)
        df.index = pd.to_datetime(df.index)
        daily_vol = df["vol_usdc"].resample("1D").sum()
        daily_vol = daily_vol[daily_vol > 0]
        if len(daily_vol) < 7:
            return -1
        return float(daily_vol.median())
    except Exception:
        return -1

def count_significant_moves(file_15m_path: str, window_days: int,
                             move_threshold_pct: float,
                             metric: str = "body") -> int:
    try:
        df = pd.read_csv(file_15m_path, index_col=0)
        if len(df) < 96 * 7:
            return -1
        candles_needed = window_days * 24 * 4
        df = df.tail(candles_needed).copy()
        if metric == "body":
            df["move_pct"] = (df["close"].astype(float) - df["open"].astype(float)).abs() / df["open"].astype(float)
        elif metric == "range":
            df["move_pct"] = (df["high"].astype(float) - df["low"].astype(float)) / df["open"].astype(float)
        else:
            return -1
        return int((df["move_pct"] > move_threshold_pct).sum())
    except Exception:
        return -1

def download_all_pairs(exchange: ccxt.Exchange, pairs: list,
                       days: int, cfg: dict) -> dict:
    if TEST_PAIRS:
        original_count = len(pairs)
        pairs = [p for p in pairs if p in TEST_PAIRS]
        print(f"\n  [TEST MODE] {original_count} → {len(pairs)} pair: {pairs}")
        if not pairs:
            print(f"  ⚠️  Nessun TEST_PAIR trovato.")

    liquidity_threshold = calculate_liquidity_threshold(cfg)
    window_days = cfg["liquidity_window_days"]
    capital_op  = cfg["capital_total"] * (1 - cfg["reserve_pct"])
    slot_size   = capital_op / cfg["n_slots"]

    print(f"\n  [FILTRO LIQUIDITÀ]")
    print(f"  Capitale operativo:      {capital_op:>10,.0f} USDC")
    print(f"  Slot size:               {slot_size:>10,.2f} USDC")
    print(f"  → Soglia volume mediano: {liquidity_threshold:>10,.0f} USDC/giorno")

    data        = {}
    to_fetch    = []
    liquid_syms = []
    rejected    = []

    print(f"\n  [FASE 1] Filtro liquidità su {len(pairs)} pair...")
    for sym in pairs:
        safe = sym.replace("/","_")
        f1h  = f"data_cache/{safe}_1h_{days}gg.csv"
        f15m = f"data_cache/{safe}_15m_{days}gg.csv"
        if not os.path.exists(f1h):
            to_fetch.append(sym)
            continue
        median_vol = measure_pair_liquidity(f1h, window_days)
        if median_vol < 0:
            continue
        if median_vol >= liquidity_threshold:
            if os.path.exists(f15m):
                liquid_syms.append(sym)
            else:
                to_fetch.append(sym)
        else:
            rejected.append((sym, median_vol))

    print(f"  Pair liquidi in cache:   {len(liquid_syms)}")
    print(f"  Pair da scaricare:       {len(to_fetch)}")
    print(f"  Pair illiquidi scartati: {len(rejected)}")

    print(f"\n  [FILTRO ATTIVITÀ body-based]")
    print(f"  Metrica: |close-open|/open > {cfg['significant_move_pct']*100:.2f}%  "
          f"(soglia: {cfg['min_significant_moves_90d']} candele / {cfg['activity_window_days']}gg)")

    active_syms = []
    inactive    = []
    for sym in liquid_syms:
        safe = sym.replace("/","_")
        f15m = f"data_cache/{safe}_15m_{days}gg.csv"
        if not os.path.exists(f15m):
            continue
        n_moves = count_significant_moves(
            f15m,
            cfg["activity_window_days"],
            cfg["significant_move_pct"],
            cfg.get("activity_metric", "body"),
        )
        if n_moves < 0:
            continue
        if n_moves >= cfg["min_significant_moves_90d"]:
            active_syms.append(sym)
        else:
            inactive.append((sym, n_moves))

    print(f"  Pair attivi:             {len(active_syms)}")
    print(f"  Pair dormienti scartati: {len(inactive)}")

    if inactive:
        threshold = cfg["min_significant_moves_90d"]
        print(f"  Top 10 borderline:")
        for sym, n in sorted(inactive, key=lambda x: -x[1])[:10]:
            print(f"    ✗ {sym:20s} {n:>4d} moves ({n/threshold*100:5.1f}%)")

    liquid_syms = active_syms

    if rejected and len(rejected) <= 30:
        print(f"\n  Pair scartati (illiquidi):")
        for sym, vol in sorted(rejected, key=lambda x: -x[1])[:15]:
            print(f"    ✗ {sym:20s} {vol:>12,.0f} USDC/d  ({vol/liquidity_threshold*100:5.1f}%)")
    elif rejected:
        print(f"\n  Top 10 borderline illiquidi:")
        for sym, vol in sorted(rejected, key=lambda x: -x[1])[:10]:
            print(f"    ✗ {sym:20s} {vol:>12,.0f} USDC/d  ({vol/liquidity_threshold*100:5.1f}%)")

    print(f"\n  [FASE 2] Carico 15m+1h per {len(liquid_syms)} pair attivi...")
    for sym in tqdm(liquid_syms, desc="  Lettura cache", unit="pair"):
        safe = sym.replace("/","_")
        d15m = read_csv_fast(f"data_cache/{safe}_15m_{days}gg.csv")
        d1h  = read_csv_fast(f"data_cache/{safe}_1h_{days}gg.csv")
        if d15m is not None and d1h is not None:
            data[sym] = {"15m": d15m, "1h": d1h}

    if to_fetch:
        print(f"\n  Download {len(to_fetch)} pair mancanti...")
        try:
            tickers  = exchange.fetch_tickers(to_fetch)
            preliminary_threshold = liquidity_threshold * 0.5
            to_fetch = [s for s in to_fetch
                        if (tickers.get(s, {}).get("quoteVolume") or 0)
                        >= preliminary_threshold]
            print(f"  Dopo filtro ticker: {len(to_fetch)} pair")
        except Exception:
            pass

        if to_fetch:
            for sym in tqdm(to_fetch, desc="  Download", unit="pair"):
                d15m = download_pair(exchange, sym, "15m", days)
                d1h  = download_pair(exchange, sym, "1h",  days)
                if d15m is not None and d1h is not None:
                    if len(d15m) > 100:
                        safe     = sym.replace("/","_")
                        f1h_new  = f"data_cache/{safe}_1h_{days}gg.csv"
                        f15m_new = f"data_cache/{safe}_15m_{days}gg.csv"
                        median_vol = measure_pair_liquidity(f1h_new, window_days)
                        n_moves    = count_significant_moves(
                            f15m_new,
                            cfg["activity_window_days"],
                            cfg["significant_move_pct"],
                            cfg.get("activity_metric", "body"),
                        )
                        if (median_vol >= liquidity_threshold and
                                n_moves >= cfg["min_significant_moves_90d"]):
                            data[sym] = {"15m": d15m, "1h": d1h}
                time.sleep(0.05)

    print(f"\n  Pair con dati completi: {len(data)}")
    return data

# ─────────────────────────────────────────────────────────────────────────────
#  SCREENER BIDIREZIONALE
# ─────────────────────────────────────────────────────────────────────────────

def run_screening(all_data: dict, cutoff_ts: pd.Timestamp,
                  cfg: dict) -> tuple:
    runners_up   = []
    runners_down = []

    for sym, dfs in all_data.items():
        try:
            closed_1h_cutoff = cutoff_ts - pd.Timedelta(hours=1)
            d1h = dfs.get("1h_screen", dfs["1h"])
            idx = d1h.index.searchsorted(closed_1h_cutoff, side="right") - 1

            if idx < 479:
                continue

            row = d1h.iloc[idx]
            vol_ma20d = row.get("screen_vol_ma20d", np.nan)
            if pd.isna(vol_ma20d) or vol_ma20d == 0:
                continue
            vol_24h   = row.get("screen_vol_24h", np.nan)
            vol_ratio = vol_24h / (vol_ma20d * 24)
            if vol_ratio < cfg["runner_vol_spike"]:
                continue

            price        = float(row["close"])
            rsi_now      = float(row.get("screen_rsi", np.nan))
            adx_now      = float(row.get("screen_adx", np.nan))
            plus_di_now  = float(row.get("screen_plus_di", np.nan))
            minus_di_now = float(row.get("screen_minus_di", np.nan))

            if pd.isna(rsi_now) or pd.isna(adx_now): continue
            if adx_now < cfg["runner_adx_min"]:       continue

            price_72h    = float(row.get("screen_price_72h", np.nan))
            if pd.isna(price_72h):
                continue
            momentum_72h = (price - price_72h) / price_72h if price_72h > 0 else 0
            price_24h    = float(row.get("screen_price_24h", np.nan))
            atr_val      = float(row.get("screen_atr", np.nan))
            if pd.isna(price_24h) or pd.isna(atr_val):
                continue
            net_move = price - price_24h
            net_mom  = net_move / (atr_val * 24) if atr_val > 0 else 0

            last6   = d1h.iloc[idx-5:idx+1]
            hv6     = last6[last6["volume"] > vol_ma20d]
            if len(hv6) > 0:
                n_green = int((hv6["close"] > hv6["open"]).sum())
                n_red   = len(hv6) - n_green
            else:
                n_green = int((last6["close"] > last6["open"]).sum())
                n_red   = 6 - n_green

            # ── SCORING UP ────────────────────────────────────────────────
            if momentum_72h < cfg["runner_momentum_pct"]:
                is_up = False
            else:
                vol_score_up  = min(30, (vol_ratio - cfg["runner_vol_spike"])
                                   / cfg["runner_vol_spike"] * 30)
                mom_score_up  = min(25, momentum_72h
                                   / cfg["runner_momentum_pct"] * 25)
                net_score_up  = min(20, max(0, net_mom
                                   / cfg["runner_net_mom_min"] * 20))
                rsi_score_up  = max(0, 15 - abs(rsi_now - 62) / 62 * 15) \
                                if cfg["runner_rsi_up_min"] <= rsi_now \
                                   <= cfg["runner_rsi_up_max"] else 0
                di_score_up   = 10 if plus_di_now > minus_di_now else 0
                score_up      = (vol_score_up + mom_score_up + net_score_up
                                 + rsi_score_up + di_score_up)
                is_up = score_up >= cfg.get("runner_score_min", 30)

            # ── SCORING DOWN ──────────────────────────────────────────────
            if momentum_72h > -cfg["runner_momentum_pct"]:
                is_down = False
            else:
                vol_score_dn  = min(30, (vol_ratio - cfg["runner_vol_spike"])
                                   / cfg["runner_vol_spike"] * 30)
                mom_score_dn  = min(25, abs(momentum_72h)
                                   / cfg["runner_momentum_pct"] * 25)
                net_score_dn  = min(20, max(0, abs(net_mom)
                                   / cfg["runner_net_mom_min"] * 20))
                rsi_score_dn  = max(0, 15 - abs(rsi_now - 38) / 38 * 15) \
                                if cfg["runner_rsi_down_min"] <= rsi_now \
                                   <= cfg["runner_rsi_down_max"] else 0
                di_score_dn   = 10 if minus_di_now > plus_di_now else 0
                score_down    = (vol_score_dn + mom_score_dn + net_score_dn
                                 + rsi_score_dn + di_score_dn)
                is_down = score_down >= cfg.get("runner_score_min", 30)

            if not is_up and not is_down:
                continue

            if is_up:
                score = (vol_score_up + mom_score_up + net_score_up
                         + rsi_score_up + di_score_up)
            else:
                score = (vol_score_dn + mom_score_dn + net_score_dn
                         + rsi_score_dn + di_score_dn)

            entry = {"symbol": sym, "score": round(score, 1)}
            if is_up:   runners_up.append(entry)
            else:       runners_down.append(entry)

        except Exception:
            continue

    runners_up.sort(  key=lambda x: x["score"], reverse=True)
    runners_down.sort(key=lambda x: x["score"], reverse=True)

    basket_long  = [r["symbol"] for r in runners_up[:cfg["screening_top_n"]]]
    basket_short = [r["symbol"] for r in runners_down[:cfg["screening_top_n"]]]
    return basket_long, basket_short

# ─────────────────────────────────────────────────────────────────────────────
#  PRE-CALCOLO SEGNALI
# ─────────────────────────────────────────────────────────────────────────────

def precompute_signals(all_data: dict, cfg: dict) -> dict:
    print("\n  Pre-calcolo segnali (v21 TF15m + ATR anchored)...")
    signals = {}

    atr_period   = cfg["sl_atr_period"]
    atr_lookback = cfg.get("sl_atr_anchor_lookback", 2)

    for sym, dfs in tqdm(all_data.items(), desc="  Indicatori", unit="pair"):
        try:
            df  = dfs["15m"].copy()
            d1h = dfs["1h"].copy()

            # ── Indicatori 15m ─────────────────────────────────────────
            df["ema9"]    = calc_ema(df["close"], cfg["sig_ema_fast"])
            df["ema21"]   = calc_ema(df["close"], cfg["sig_ema_slow"])
            df["rsi"]     = calc_rsi(df["close"], cfg["sig_rsi_period"])
            df["adx"]     = calc_adx(df,          cfg["sig_adx_period"])
            df["vol_sma"] = df["volume"].rolling(20).mean()

            # ── ATR anchored ────────────────────────────────────────────
            df["atr"]          = calc_atr(df, atr_period)
            df["atr_anchored"] = df["atr"].shift(atr_lookback)

            # ── Pattern metadata ────────────────────────────────────────
            rng  = (df["high"] - df["low"]).replace(0, np.nan)
            body = (df["close"] - df["open"]).abs()
            df["body_pct"]           = (body / rng).fillna(0.0)
            df["is_green"]           = df["close"] > df["open"]
            df["is_red"]             = df["close"] < df["open"]
            df["is_doji"]            = df["body_pct"] < cfg["pattern_doji_max_pct"]
            df["upper_shadow_pct"]   = ((df["high"] - df[["close","open"]].max(axis=1)) / rng).fillna(0.0)
            df["lower_shadow_pct"]   = ((df[["close","open"]].min(axis=1) - df["low"]) / rng).fillna(0.0)
            df["close_in_upper_third"] = ((df["close"] - df["low"]) / rng).fillna(0.0) > 0.66
            df["close_in_lower_third"] = ((df["close"] - df["low"]) / rng).fillna(0.0) < 0.34

            # ── Contesto 1h ─────────────────────────────────────────────
            d1h["ctx_ema9"]  = calc_ema(d1h["close"], cfg["ctx_ema_fast"])
            d1h["ctx_ema21"] = calc_ema(d1h["close"], cfg["ctx_ema_slow"])
            d1h["ctx_adx"]   = calc_adx(d1h,          cfg["ctx_adx_period"])

            d1h["screen_rsi"] = calc_rsi(d1h["close"], 14)
            screen_adx = calc_adx_with_di(d1h, 14)
            d1h["screen_adx"]       = screen_adx["adx"]
            d1h["screen_plus_di"]   = screen_adx["plus_di"]
            d1h["screen_minus_di"]  = screen_adx["minus_di"]
            d1h["screen_atr"]       = calc_atr(d1h, 14)
            d1h["screen_vol_ma20d"] = d1h["volume"].rolling(480).mean()
            d1h["screen_vol_24h"]   = d1h["volume"].rolling(24).sum()
            d1h["screen_price_72h"] = d1h["close"].shift(72)
            d1h["screen_price_24h"] = d1h["close"].shift(24)

            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC")
            if d1h.index.tz is None:
                d1h.index = d1h.index.tz_localize("UTC")
            else:
                d1h.index = d1h.index.tz_convert("UTC")

            dfs["1h_screen"] = d1h

            for col in ["ctx_ema9","ctx_ema21","ctx_adx"]:
                s = d1h[col].copy()
                s.index = s.index + pd.Timedelta(hours=1)
                df = df.join(s, how="left")
                df[col] = df[col].ffill()

            df["session_ok"] = True

            # ── Segnale base LONG ────────────────────────────────────────
            ctx_long   = ((df["ctx_ema9"]  > df["ctx_ema21"]) &
                          (df["ctx_adx"]   > cfg["ctx_adx_min"]) &
                          (df["close"]     > df["ctx_ema21"]))
            entry_long = ((df["close"]   > df["open"]) &
                          (df["close"]   > df["ema9"]) &
                          (df["ema9"]    > df["ema21"]) &
                          (df["adx"]     > cfg["sig_adx_min"]) &
                          (df["rsi"]     >= cfg["sig_rsi_min_long"]) &
                          (df["rsi"]     <= cfg["sig_rsi_max_long"]) &
                          (df["volume"]  > df["vol_sma"] * cfg["sig_volume_mult"]))
            df["sig_base_long"] = ctx_long & entry_long

            # ── Segnale base SHORT ───────────────────────────────────────
            ctx_short   = ((df["ctx_ema9"]  < df["ctx_ema21"]) &
                           (df["ctx_adx"]   > cfg["ctx_adx_min"]) &
                           (df["close"]     < df["ctx_ema21"]))
            entry_short = ((df["close"]   < df["open"]) &
                           (df["close"]   < df["ema9"]) &
                           (df["ema9"]    < df["ema21"]) &
                           (df["adx"]     > cfg["sig_adx_min"]) &
                           (df["rsi"]     >= cfg["sig_rsi_min_short"]) &
                           (df["rsi"]     <= cfg["sig_rsi_max_short"]) &
                           (df["volume"]  > df["vol_sma"] * cfg["sig_volume_mult"]))
            df["sig_base_short"] = ctx_short & entry_short

            # ── Pattern confirmation ─────────────────────────────────────
            df["pattern_confirm_long"] = (
                df["is_green"] &
                (df["body_pct"] >= cfg["pattern_body_min_pct"]) &
                (~df["is_doji"]) &
                df["close_in_upper_third"] &
                (df["upper_shadow_pct"] <= cfg["pattern_long_shadow_max"])
            )
            df["pattern_confirm_short"] = (
                df["is_red"] &
                (df["body_pct"] >= cfg["pattern_body_min_pct"]) &
                (~df["is_doji"]) &
                df["close_in_lower_third"] &
                (df["lower_shadow_pct"] <= cfg["pattern_long_shadow_max"])
            )

            signals[sym] = df.dropna(subset=["ema9","ema21","rsi","adx",
                                              "ctx_ema9","ctx_ema21","ctx_adx",
                                              "atr_anchored"])
        except Exception:
            continue

    print(f"  Segnali pre-calcolati per {len(signals)} pair")
    return signals

# ─────────────────────────────────────────────────────────────────────────────
#  CLASSE POSIZIONE
# ─────────────────────────────────────────────────────────────────────────────

class Position:
    """
    Posizione v21 — two-pass OHLC model:
      PASS 1 (HIGH per long, LOW per short) — attivazioni:
        1a. breakeven trigger   1b. trailing activation   1c. trailing update
        1d. TP1 parziale        1e. TP2 parziale
      PASS 2 (LOW per long, HIGH per short) — uscite:
        2a. trailing_stop       2b. SL/breakeven          2c. timeout
      trailing_activation: 0.025 (ripristinato, ora corretto col two-pass)
    """

    def __init__(self, symbol: str, direction: str,
                 entry_price: float, size_usd: float,
                 entry_time: pd.Timestamp, cfg: dict,
                 slot_id: int, atr_anchor: float = None,
                 is_reversal: bool = False):
        self.symbol      = symbol
        self.direction   = direction
        self.entry_price = entry_price
        self.size_usd    = size_usd
        self.entry_time  = entry_time
        self.cfg         = cfg
        self.slot_id     = slot_id
        self.is_reversal = is_reversal
        self.atr_anchor  = atr_anchor

        self.tp1_done      = False
        self.tp2_done      = False
        self.remaining_pct = 1.0

        # ── SL ATR-anchored ────────────────────────────────────────────
        if atr_anchor is not None and atr_anchor > 0 and entry_price > 0:
            atr_ratio = atr_anchor / entry_price
        else:
            atr_ratio = 0.02

        multiplier  = (cfg["sl_atr_multiplier_long"] if direction == "long"
                       else cfg["sl_atr_multiplier_short"])
        sl_distance = atr_ratio * multiplier
        sl_distance = max(cfg["sl_atr_min_distance"], sl_distance)
        sl_distance = min(cfg["sl_atr_max_distance"], sl_distance)
        self.sl_distance = sl_distance

        if direction == "long":
            self.sl_price = entry_price * (1 - sl_distance)
        else:
            self.sl_price = entry_price * (1 + sl_distance)
        self.sl_enabled = True

        # ── Breakeven: buffer 1.0% ─────────────────────────────────────
        if direction == "long":
            self.breakeven_price = entry_price * (1 + cfg["breakeven_buffer"])
        else:
            self.breakeven_price = entry_price * (1 - cfg["breakeven_buffer"])
        self.breakeven_done = False

        # ── Timeout ─────────────────────────────────────────────────────
        if direction == "long":
            self.max_duration_min = cfg.get("max_duration_hours_long", 24) * 60
        else:
            self.max_duration_min = cfg.get("max_duration_hours_short", 24) * 60

        # ── Trailing ────────────────────────────────────────────────────
        self.trailing_active = False
        self.best_price      = entry_price
        self.trailing_stop   = None

        # ── State ───────────────────────────────────────────────────────
        self.closed           = False
        self.exit_price       = None
        self.exit_time        = None
        self.exit_reason      = None
        self.trigger_reversal = False

        self.fast_fail_enabled = cfg.get("fast_fail_enabled", False)
        self.fast_fail_min     = cfg.get("fast_fail_minutes", 180)

    def pnl_pct(self, price: float) -> float:
        if self.direction == "long":
            return (price - self.entry_price) / self.entry_price
        else:
            return (self.entry_price - price) / self.entry_price

    def update_trailing_stop(self):
        cfg = self.cfg
        if not self.trailing_active:
            return
        if self.direction == "long":
            trail = self.best_price * (1 - cfg["trailing_distance"])
            if self.breakeven_done:
                trail = max(trail, self.breakeven_price)
            self.trailing_stop = trail
        else:
            trail = self.best_price * (1 + cfg["trailing_distance"])
            if self.breakeven_done:
                trail = min(trail, self.breakeven_price)
            self.trailing_stop = trail

    def check_exit_ohlc(self, candle_open: float, candle_high: float,
                         candle_low: float, candle_close: float,
                         ts: pd.Timestamp) -> bool:
        """
        Two-pass OHLC model v21.

        PASS 1 — attivazioni (HIGH per long, LOW per short):
          Prima processa il lato favorevole della candela per attivare
          breakeven, trailing e prendere i TP parziali.

        PASS 2 — uscite (LOW per long, HIGH per short):
          Poi controlla il lato avverso per le uscite, con trailing_active
          già aggiornato dal pass 1 della stessa candela.

        Questo risolve il bug v19/v20: su candele dove HIGH attiva il
        trailing E LOW tocca il breakeven nello stesso bar, il pass 1
        imposta trailing_active=True prima che il pass 2 controlli le uscite.
        """
        cfg = self.cfg

        # ══════════════════════════════════════════════════════════════
        # PASS 1 — ATTIVAZIONI
        # ══════════════════════════════════════════════════════════════

        # 1a. Breakeven trigger
        if not self.breakeven_done:
            if self.direction == "long":
                triggered = candle_high >= self.entry_price * (1 + cfg["breakeven_trigger"])
            else:
                triggered = candle_low  <= self.entry_price * (1 - cfg["breakeven_trigger"])
            if triggered:
                self.sl_price       = self.breakeven_price
                self.breakeven_done = True

        # 1b. Trailing activation
        if not self.trailing_active:
            if self.direction == "long":
                act = candle_high >= self.entry_price * (1 + cfg["trailing_activation"])
            else:
                act = candle_low  <= self.entry_price * (1 - cfg["trailing_activation"])
            if act:
                self.trailing_active = True
                if self.direction == "long":
                    self.best_price = max(self.best_price, candle_high)
                else:
                    self.best_price = min(self.best_price, candle_low)

        # 1c. Trailing best_price update + calc trailing_stop
        if self.trailing_active:
            if self.direction == "long":
                if candle_high > self.best_price:
                    self.best_price = candle_high
            else:
                if candle_low < self.best_price:
                    self.best_price = candle_low
            self.update_trailing_stop()

        # 1d. TP1 parziale
        if not self.tp1_done:
            if self.direction == "long":
                tp1_hit = candle_high >= self.entry_price * (1 + cfg["tp1_pct"])
            else:
                tp1_hit = candle_low  <= self.entry_price * (1 - cfg["tp1_pct"])
            if tp1_hit:
                self.tp1_done      = True
                self.remaining_pct -= cfg["tp1_close_pct"]
                if not self.breakeven_done:
                    self.sl_price       = self.breakeven_price
                    self.breakeven_done = True

        # 1e. TP2 parziale
        if self.tp1_done and not self.tp2_done:
            if self.direction == "long":
                tp2_hit = candle_high >= self.entry_price * (1 + cfg["tp2_pct"])
            else:
                tp2_hit = candle_low  <= self.entry_price * (1 - cfg["tp2_pct"])
            if tp2_hit:
                self.tp2_done      = True
                self.remaining_pct -= cfg["tp2_close_pct"]

        # ══════════════════════════════════════════════════════════════
        # PASS 2 — USCITE
        # ══════════════════════════════════════════════════════════════

        # 2a. Trailing stop (priorità su SL quando attivo)
        if self.trailing_active and self.trailing_stop is not None:
            if self.direction == "long":
                trail_hit = candle_low <= self.trailing_stop
            else:
                trail_hit = candle_high >= self.trailing_stop
            if trail_hit:
                self._close(self.trailing_stop, ts, "trailing_stop")
                return True

        # 2b. SL / Breakeven
        if self.sl_enabled:
            if self.direction == "long":
                sl_hit = candle_low <= self.sl_price
            else:
                sl_hit = candle_high >= self.sl_price
            if sl_hit:
                reason = "breakeven_hit" if self.breakeven_done else "SL_atr"
                self._close(self.sl_price, ts, reason)
                return True

        # 2c. Timeout
        if self.max_duration_min > 0 and not self.trailing_active:
            elapsed_min = (ts - self.entry_time).total_seconds() / 60
            if elapsed_min >= self.max_duration_min:
                reason = "timeout_profit" if self.pnl_pct(candle_close) > 0 else "timeout"
                self._close(candle_close, ts, reason)
                return True

        return False

    def _close(self, price: float, ts: pd.Timestamp, reason: str):
        self.closed      = True
        self.exit_price  = price
        self.exit_time   = ts
        self.exit_reason = reason

    def realized_pnl(self, commission_pct: float) -> float:
        cfg   = self.cfg
        entry = self.entry_price
        size  = self.size_usd
        gross = 0.0
        comm  = size * commission_pct

        if self.tp1_done:
            gross += size * cfg["tp1_close_pct"] * cfg["tp1_pct"]
            comm  += size * cfg["tp1_close_pct"] * commission_pct

        if self.tp2_done:
            gross += size * cfg["tp2_close_pct"] * cfg["tp2_pct"]
            comm  += size * cfg["tp2_close_pct"] * commission_pct

        residual = size * self.remaining_pct
        if self.direction == "long":
            gross += residual * (self.exit_price - entry) / entry
        else:
            gross += residual * (entry - self.exit_price) / entry
        comm += residual * commission_pct

        return gross - comm

# ─────────────────────────────────────────────────────────────────────────────
#  WALK-FORWARD ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class PendingSignal:
    """
    Stato esplicito di un segnale in attesa di conferma pattern.
    Lifecycle: created → pending → confirmed | expired
    """
    def __init__(self, symbol: str, direction: str,
                 created_at: pd.Timestamp,
                 confirmation_at: pd.Timestamp,
                 expires_at: pd.Timestamp,
                 screener_rank: int = 0):
        self.symbol          = symbol
        self.direction       = direction
        self.created_at      = created_at
        self.confirmation_at = confirmation_at
        self.expires_at      = expires_at
        self.screener_rank   = screener_rank
        self.status          = "pending"

    def is_expired(self, ts: pd.Timestamp) -> bool:
        return ts > self.expires_at


def run_walkforward(all_data: dict, signals: dict,
                    cfg: dict, days: int) -> tuple:
    """Walk-forward v20 — Event-driven, anti-lookahead."""
    all_indices = set()
    for sym, df in signals.items():
        all_indices.update(df.index)

    all_ts   = sorted(all_indices)
    end_ts   = max(all_ts)
    start_ts = end_ts - pd.Timedelta(days=days)
    all_ts   = [t for t in all_ts if t >= start_ts]

    capital_op = cfg["capital_total"] * (1 - cfg["reserve_pct"])
    slot_size  = capital_op / cfg["n_slots"]

    print(f"\n  Periodo: {start_ts.date()} → {end_ts.date()}")
    print(f"  Candele 15m: {len(all_ts):,}")
    print(f"  Capitale operativo: {capital_op:.0f} USDC  |  Slot: {cfg['n_slots']} × {slot_size:.0f} USDC")
    print(f"  Breakeven buffer: {cfg['breakeven_buffer']*100:.1f}%  "
          f"Trailing activation: {cfg['trailing_activation']*100:.1f}%  "
          f"SL max: {cfg['sl_atr_max_distance']*100:.0f}%")

    capital         = capital_op
    slots           = {i: None for i in range(cfg["n_slots"])}
    trade_log       = []
    equity_curve    = []
    screening_log   = []
    pending_signals = {}
    last_screen_ts  = None
    warmup_end      = start_ts + pd.Timedelta(days=cfg["screening_warmup_days"])

    diag_signals_created   = 0
    diag_signals_confirmed = 0
    diag_signals_expired   = 0

    candle_minutes = 15
    window_minutes = cfg["entry_confirmation_window"] * candle_minutes

    print(f"  Warmup: {warmup_end.date()}  |  Score_min: {cfg['runner_score_min']}\n")

    for ts in tqdm(all_ts, desc="  Walk-Forward v21", unit="candela"):

        # ═══ FASE A — Gestione posizioni aperte ════════════════════════════
        open_syms    = {p.symbol for p in slots.values() if p is not None and not p.closed}
        pending_syms = set(pending_signals.keys())

        for slot_id, pos in list(slots.items()):
            if pos is None or pos.closed:
                continue
            sym = pos.symbol
            if sym not in signals or ts not in signals[sym].index:
                continue

            row = signals[sym].loc[ts]
            exited = pos.check_exit_ohlc(
                float(row["open"]), float(row["high"]),
                float(row["low"]),  float(row["close"]), ts
            )

            if exited:
                pnl_net = pos.realized_pnl(cfg["commission_pct"])
                capital += pnl_net
                trade_log.append({
                    "entry_time":  pos.entry_time,
                    "exit_time":   pos.exit_time,
                    "symbol":      pos.symbol,
                    "direction":   pos.direction,
                    "entry_price": round(pos.entry_price, 6),
                    "exit_price":  round(pos.exit_price,  6),
                    "size_usd":    round(pos.size_usd,    4),
                    "pnl_net":     round(pnl_net,         4),
                    "pnl_pct":     round(pnl_net / pos.size_usd * 100, 3),
                    "exit_reason": pos.exit_reason,
                    "duration_min": round((pos.exit_time - pos.entry_time)
                                          .total_seconds() / 60, 1),
                    "tp1_done":    pos.tp1_done,
                    "tp2_done":    pos.tp2_done,
                    "sl_distance": round(pos.sl_distance * 100, 2),
                    "atr_anchor":  round(pos.atr_anchor, 6) if pos.atr_anchor else None,
                    "slot_id":     slot_id,
                })
                slots[slot_id] = None

        equity_curve.append((ts, capital))

        # ═══ FASE A2 — Check pending signals ═══════════════════════════════
        for sym in list(pending_syms):
            ps = pending_signals.get(sym)
            if ps is None: continue

            if ps.is_expired(ts):
                diag_signals_expired += 1
                del pending_signals[sym]
                continue

            if ts < ps.confirmation_at:
                continue

            if sym not in signals or ts not in signals[sym].index:
                continue

            row = signals[sym].loc[ts]
            pattern_ok = bool(row.get(
                "pattern_confirm_long" if ps.direction == "long"
                else "pattern_confirm_short", False
            ))

            if pattern_ok:
                ps.status = "confirmed"
                diag_signals_confirmed += 1
            else:
                if cfg["entry_confirmation_window"] <= 1:
                    diag_signals_expired += 1
                    del pending_signals[sym]

        # ═══ FASE B — Discovery (screener ogni N ore) ═══════════════════════
        if ts >= warmup_end:
            do_screen = (last_screen_ts is None or
                         (ts - last_screen_ts).total_seconds() / 3600
                         >= cfg["screening_interval_hours"])
            if do_screen:
                new_long, new_short = run_screening(all_data, ts, cfg)

                excluded = pending_syms | open_syms

                if cfg["long_enabled"]:
                    for rank, sym in enumerate(new_long):
                        if sym in excluded: continue
                        if sym not in signals or ts not in signals[sym].index: continue
                        if not bool(signals[sym].loc[ts].get("sig_base_long", False)): continue
                        confirmation_at = ts + pd.Timedelta(minutes=candle_minutes)
                        expires_at      = ts + pd.Timedelta(minutes=window_minutes + candle_minutes)
                        pending_signals[sym] = PendingSignal(
                            symbol=sym, direction="long",
                            created_at=ts,
                            confirmation_at=confirmation_at,
                            expires_at=expires_at,
                            screener_rank=rank,
                        )
                        diag_signals_created += 1

                if cfg["short_enabled"]:
                    for rank, sym in enumerate(new_short):
                        if sym in excluded: continue
                        if sym not in signals or ts not in signals[sym].index: continue
                        if not bool(signals[sym].loc[ts].get("sig_base_short", False)): continue
                        confirmation_at = ts + pd.Timedelta(minutes=candle_minutes)
                        expires_at      = ts + pd.Timedelta(minutes=window_minutes + candle_minutes)
                        pending_signals[sym] = PendingSignal(
                            symbol=sym, direction="short",
                            created_at=ts,
                            confirmation_at=confirmation_at,
                            expires_at=expires_at,
                            screener_rank=rank,
                        )
                        diag_signals_created += 1

                screening_log.append({
                    "timestamp":    ts,
                    "basket_long":  list(new_long),
                    "basket_short": list(new_short),
                })
                last_screen_ts = ts

        # ═══ FASE C — Entry execution su confermati ═════════════════════════
        if ts < warmup_end:
            continue

        confirmed_list = [(sym, ps) for sym, ps in pending_signals.items()
                          if ps.status == "confirmed"]
        if not confirmed_list:
            continue

        confirmed_list.sort(key=lambda x: (x[1].screener_rank, x[0]))
        free_slots = [sid for sid, p in slots.items() if p is None]

        for sym, ps in confirmed_list:
            if not free_slots:
                break

            if any(p is not None and p.symbol == sym for p in slots.values()):
                del pending_signals[sym]
                continue

            row         = signals[sym].loc[ts]
            entry_price = float(row["close"])
            atr_anchor  = (float(row["atr_anchored"])
                           if not pd.isna(row.get("atr_anchored", None)) else None)

            slot_id = free_slots.pop(0)
            slots[slot_id] = Position(
                symbol      = sym,
                direction   = ps.direction,
                entry_price = entry_price,
                size_usd    = slot_size,
                entry_time  = ts,
                cfg         = cfg,
                slot_id     = slot_id,
                atr_anchor  = atr_anchor,
                is_reversal = False,
            )
            del pending_signals[sym]

    # ── Chiudi posizioni aperte a fine backtest ─────────────────────────────
    final_ts = all_ts[-1]
    for slot_id, pos in slots.items():
        if pos is not None and not pos.closed:
            sym = pos.symbol
            final_price = (float(signals[sym]["close"].iloc[-1])
                           if sym in signals else pos.entry_price)
            pos._close(final_price, final_ts, "end_of_test")
            pnl_net = pos.realized_pnl(cfg["commission_pct"])
            capital += pnl_net
            trade_log.append({
                "entry_time":  pos.entry_time,
                "exit_time":   final_ts,
                "symbol":      pos.symbol,
                "direction":   pos.direction,
                "entry_price": round(pos.entry_price, 6),
                "exit_price":  round(final_price,     6),
                "size_usd":    round(pos.size_usd,    4),
                "pnl_net":     round(pnl_net,         4),
                "pnl_pct":     round(pnl_net / pos.size_usd * 100, 3),
                "exit_reason": "end_of_test",
                "duration_min": round((final_ts - pos.entry_time)
                                      .total_seconds() / 60, 1),
                "tp1_done":    pos.tp1_done,
                "tp2_done":    pos.tp2_done,
                "sl_distance": round(pos.sl_distance * 100, 2),
                "atr_anchor":  round(pos.atr_anchor, 6) if pos.atr_anchor else None,
                "slot_id":     slot_id,
            })

    print(f"\n  ── DIAGNOSTICA ENTRY CONFIRMATION ──")
    print(f"  Signals creati:     {diag_signals_created}")
    print(f"  Signals confermati: {diag_signals_confirmed}")
    print(f"  Signals scaduti:    {diag_signals_expired}")
    if diag_signals_created > 0:
        rate = diag_signals_confirmed / diag_signals_created * 100
        print(f"  Tasso conferma:     {rate:.1f}%")

    return equity_curve, trade_log, screening_log

# ─────────────────────────────────────────────────────────────────────────────
#  STATISTICHE E OUTPUT
# ─────────────────────────────────────────────────────────────────────────────

def compute_stats(trade_log: list, cap_initial: float,
                  cap_final: float, equity_curve: list) -> dict:
    if not trade_log:
        return {}
    df_t   = pd.DataFrame(trade_log)
    wins   = df_t[df_t["pnl_net"] > 0]
    losses = df_t[df_t["pnl_net"] <= 0]
    wr     = len(wins) / len(df_t) * 100
    gp     = wins["pnl_net"].sum()             if len(wins)   > 0 else 0
    gl     = abs(losses["pnl_net"].sum())      if len(losses) > 0 else 1e-9
    pf     = gp / gl

    eq_vals = [e[1] for e in equity_curve]
    peak = eq_vals[0]
    maxdd = 0.0
    for v in eq_vals:
        if v > peak: peak = v
        dd = (peak - v) / peak * 100
        if dd > maxdd: maxdd = dd

    long_t  = df_t[df_t["direction"] == "long"]
    short_t = df_t[df_t["direction"] == "short"]
    n_rev   = 0
    pnl_rev = 0.0

    return {
        "n_trades":       len(df_t),
        "win_rate":       round(wr, 1),
        "profit_factor":  round(pf, 2),
        "max_drawdown":   round(maxdd, 2),
        "return_pct":     round((cap_final - cap_initial) / cap_initial * 100, 2),
        "pnl_net":        round(cap_final - cap_initial, 4),
        "avg_pnl":        round(df_t["pnl_net"].mean(), 4),
        "avg_duration":   round(df_t["duration_min"].mean(), 1),
        "n_long":         len(long_t),
        "pnl_long":       round(long_t["pnl_net"].sum(), 4),
        "wr_long":        round((long_t["pnl_net"] > 0).mean() * 100, 1) if len(long_t) > 0 else 0,
        "n_short":        len(short_t),
        "pnl_short":      round(short_t["pnl_net"].sum(), 4),
        "wr_short":       round((short_t["pnl_net"] > 0).mean() * 100, 1) if len(short_t) > 0 else 0,
        "n_reversals":    n_rev,
        "pnl_reversals":  pnl_rev,
    }


def plot_results(equity_curve: list, trade_log: list, stats: dict, days: int):
    if not equity_curve:
        return

    fig, axes = plt.subplots(2, 1, figsize=(15, 10),
                              gridspec_kw={"height_ratios": [3, 1]})
    ax1 = axes[0]
    ts   = [e[0] for e in equity_curve]
    vals = [e[1] for e in equity_curve]
    ax1.plot(ts, vals, color="#2196F3", linewidth=1.2, label="Capitale Operativo")

    cap_op = CONFIG["capital_total"] * (1 - CONFIG["reserve_pct"])
    ax1.axhline(cap_op, color="gray", linestyle="--",
                linewidth=0.7, alpha=0.6,
                label=f"Capitale iniziale ({cap_op:.0f} USDC)")

    s = stats
    if s:
        title = (f"Walk-Forward LONG+SHORT 15m — {days}gg  |  "
                 f"Return: {s['return_pct']:+.2f}%  "
                 f"WR: {s['win_rate']}%  PF: {s['profit_factor']}  "
                 f"MaxDD: -{s['max_drawdown']}%  Trade: {s['n_trades']}  |  "
                 f"LONG: {s['n_long']} ({s['wr_long']}% WR)  "
                 f"SHORT: {s['n_short']} ({s['wr_short']}% WR)  "
                 f"Inversioni: {s['n_reversals']}")
        ax1.set_title(title, fontsize=9, fontweight="bold")

    ax1.set_ylabel("Capitale Operativo (USDC)")
    ax1.legend(fontsize=8)
    ax1.grid(True, alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    ax1.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
    plt.setp(ax1.get_xticklabels(), rotation=30, ha="right", fontsize=7)

    ax2 = axes[1]
    if trade_log:
        df_t = pd.DataFrame(trade_log)
        df_t["exit_time"] = pd.to_datetime(df_t["exit_time"])
        colors = []
        for _, row in df_t.iterrows():
            if row["pnl_net"] > 0:
                colors.append("#4CAF50" if row["direction"] == "long" else "#2196F3")
            else:
                colors.append("#F44336")
        ax2.bar(df_t["exit_time"], df_t["pnl_net"],
                color=colors, width=0.03, alpha=0.8)
        ax2.axhline(0, color="gray", linewidth=0.6)
        ax2.set_ylabel("PnL per Trade (USDC)")
        ax2.set_xlabel("Data")
        ax2.grid(True, alpha=0.2)
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
        ax2.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
        plt.setp(ax2.get_xticklabels(), rotation=30, ha="right", fontsize=7)

        from matplotlib.patches import Patch
        legend_elements = [
            Patch(facecolor="#4CAF50", label="LONG vincente"),
            Patch(facecolor="#2196F3", label="SHORT vincente"),
            Patch(facecolor="#F44336", label="Perdente"),
        ]
        ax2.legend(handles=legend_elements, fontsize=7, loc="upper left")

    plt.tight_layout()
    out = f"results_wf_v21/equity_wf_{days}gg.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  [CHART] {out}")


def print_summary(stats: dict, trade_log: list, days: int):
    cap_op = CONFIG["capital_total"] * (1 - CONFIG["reserve_pct"])
    print(f"\n{'═'*70}")
    print(f"{'RIEPILOGO v21 — LONG+SHORT —' + str(days) + 'gg':^70}")
    print(f"{'═'*70}")
    if not stats:
        print("  Nessun trade.")
        return
    print(f"  Capitale iniziale:   {cap_op:.0f} USDC")
    print(f"  Capitale finale:     {cap_op + stats['pnl_net']:.4f} USDC")
    print(f"  Return:              {stats['return_pct']:+.2f}%")
    print(f"  PnL netto:           {stats['pnl_net']:+.4f} USDC")
    print(f"  Trade totali:        {stats['n_trades']}")
    print(f"  Win Rate:            {stats['win_rate']}%")
    print(f"  Profit Factor:       {stats['profit_factor']}")
    print(f"  Max Drawdown:        -{stats['max_drawdown']}%")
    print(f"  Durata media:        {stats['avg_duration']:.1f} min")
    print(f"\n  ── LONG ──────────────────────────────────")
    print(f"  Trade LONG:  {stats['n_long']} | WR: {stats['wr_long']}% | PnL: {stats['pnl_long']:+.4f}")
    print(f"\n  ── SHORT ─────────────────────────────────")
    print(f"  Trade SHORT: {stats['n_short']} | WR: {stats['wr_short']}% | PnL: {stats['pnl_short']:+.4f}")

    if trade_log:
        df_t = pd.DataFrame(trade_log)
        print(f"\n  ── EXIT REASONS ──────────────────────────")
        er = df_t.groupby("exit_reason")["pnl_net"].agg(["count","sum","mean"]).round(4)
        print(er.to_string())

        print(f"\n  ── TOP 5 PAIR ────────────────────────────")
        by_sym = df_t.groupby("symbol")["pnl_net"].agg(["count","sum"]).round(4)
        print(by_sym.sort_values("sum", ascending=False).head(5).to_string())

        print(f"\n  ── LONG vs SHORT ─────────────────────────")
        for direction in ["long", "short"]:
            sub = df_t[df_t["direction"] == direction]
            if len(sub) == 0:
                continue
            wins   = sub[sub["pnl_net"] > 0]
            losses = sub[sub["pnl_net"] <= 0]
            gw     = wins["pnl_net"].sum()
            gl     = abs(losses["pnl_net"].sum())
            pf     = gw / gl if gl > 0 else float("inf")
            avg_w  = wins["pnl_net"].mean()   if len(wins)   > 0 else 0
            avg_l  = losses["pnl_net"].mean() if len(losses) > 0 else 0
            wr     = len(wins) / len(sub) * 100
            print(f"  {direction.upper():6s}: n={len(sub):4d} | WR={wr:5.1f}% | "
                  f"PF={pf:5.2f} | avg_win={avg_w:+.2f} | avg_loss={avg_l:+.2f} | "
                  f"PnL_tot={sub['pnl_net'].sum():+.2f}")

        print(f"\n  ── HOLD TIME per EXIT_REASON ─────────────")
        ht = df_t.groupby("exit_reason")["duration_min"].agg(
            ["count", "median", "mean",
             lambda x: x.quantile(0.25),
             lambda x: x.quantile(0.75),
             lambda x: x.quantile(0.95)]
        ).round(1)
        ht.columns = ["count", "median", "mean", "p25", "p75", "p95"]
        print(ht.to_string())

        sl_trades = df_t[df_t["exit_reason"] == "SL_atr"]
        if len(sl_trades) > 0:
            print(f"\n  ── SL_ATR DISTRIBUTION (cap 6%) ─────────")
            print(sl_trades[["symbol","direction","sl_distance","pnl_net"]]
                  .sort_values("pnl_net").to_string(index=False))

        trailing_trades = df_t[df_t["exit_reason"] == "trailing_stop"]
        if len(trailing_trades) > 0:
            print(f"\n  ── TRAILING STOP TRADES ──────────────────")
            print(trailing_trades[["symbol","direction","pnl_net","duration_min"]]
                  .sort_values("pnl_net", ascending=False).to_string(index=False))

    print(f"{'═'*70}")

# ─────────────────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    days = BACKTEST_DAYS
    cfg  = CONFIG

    print(f"\n{'═'*65}")
    print(f"  WALK-FORWARD BACKTEST — LONG+SHORT 15m — versione21")
    print(f"  Two-pass OHLC model + trailing_activation 2.5%")
    print(f"{'═'*65}\n")

    print("  v21 vs v20 delta:")
    print(f"   trailing_activation: 0.035 → {cfg['trailing_activation']:.3f}  (ripristino v19)")
    print(f"   BUG FIX: two-pass OHLC (pass1=attivazioni HIGH, pass2=uscite LOW)")
    print(f"\n  v21 vs v18 delta (totale):")
    print(f"   breakeven_buffer:    0.005 → {cfg['breakeven_buffer']:.3f}")
    print(f"   trailing_activation: 0.040 → {cfg['trailing_activation']:.3f}")
    print(f"   trailing_distance:   0.015 → {cfg['trailing_distance']:.3f}")
    print(f"   sl_atr_max_distance: 0.120 → {cfg['sl_atr_max_distance']:.3f}")
    print(f"   runner_score_min:    40    → {cfg['runner_score_min']}")
    print(f"   runner_momentum_pct: 0.020 → {cfg['runner_momentum_pct']:.3f}")
    print()

    exchange = get_exchange()

    print("[1/5] Recupero pair USDC da Binance...")
    all_pairs = get_usdc_pairs(exchange, cfg)
    print(f"  Pair USDC trovati: {len(all_pairs)}")

    print(f"\n[2/5] Download dati storici ({days}gg)...")
    all_data = download_all_pairs(exchange, all_pairs, days, cfg)
    if not all_data:
        print("  ERRORE: nessun dato.")
        return

    print(f"\n[3/5] Pre-calcolo segnali...")
    signals = precompute_signals(all_data, cfg)
    if not signals:
        print("  ERRORE: nessun segnale.")
        return

    print(f"\n[4/5] Esecuzione walk-forward ({days} giorni)...")
    equity_curve, trade_log, screening_log = run_walkforward(
        all_data, signals, cfg, days)

    cap_op    = cfg["capital_total"] * (1 - cfg["reserve_pct"])
    cap_final = equity_curve[-1][1] if equity_curve else cap_op
    stats     = compute_stats(trade_log, cap_op, cap_final, equity_curve)

    print(f"\n[5/5] Generazione output...")

    if trade_log:
        path_t = f"results_wf_v21/trades_wf_{days}gg.csv"
        pd.DataFrame(trade_log).to_csv(path_t, index=False)
        print(f"  [CSV] Trade: {path_t} ({len(trade_log)} trade)")

    if screening_log:
        path_s = f"results_wf_v21/screening_log_{days}gg.csv"
        pd.DataFrame(screening_log).to_csv(path_s, index=False)
        print(f"  [CSV] Screening: {path_s}")

    if equity_curve:
        df_eq = pd.DataFrame(equity_curve, columns=["timestamp","capital"])
        df_eq.to_csv(f"results_wf_v21/equity_wf_{days}gg.csv", index=False)

    plot_results(equity_curve, trade_log, stats, days)
    print_summary(stats, trade_log, days)

    print(f"\n✔  Walk-Forward v21 completato.")
    print(f"   Output → ./results_wf_v21/\n")


if __name__ == "__main__":
    main()
