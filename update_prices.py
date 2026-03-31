"""
Fetches live prices for SCREEN_WL tickers and updates index.html in-place.
Runs server-side (no CORS), triggered by GitHub Actions.
"""
import re, sys

try:
    import yfinance as yf
except ImportError:
    print("yfinance not installed"); sys.exit(1)

with open("index.html", encoding="utf-8") as f:
    html = f.read()

m = re.search(r"const SCREEN_WL = \[(.*?)\];", html, re.DOTALL)
if not m:
    print("ERROR: SCREEN_WL not found"); sys.exit(1)

block = m.group(1)
entries = re.findall(
    r'\{t:"([^"]+)",n:"([^"]+)",s:"([^"]+)",p:([\d.]+),lo:([\d.]+),hi:([\d.]+),chg:([+-]?[\d.]+)\}',
    block
)
if not entries:
    print("ERROR: could not parse SCREEN_WL entries"); sys.exit(1)

rows = [{"t": t, "n": n, "s": s, "p": float(p), "lo": float(lo), "hi": float(hi), "chg": float(chg)}
        for t, n, s, p, lo, hi, chg in entries]

def to_yahoo(t):
    if t.endswith(".SA"):
        return t
    if re.match(r"^[A-Z]{4}\d{1,2}$", t):
        return t + ".SA"
    return t

tickers_yf = [to_yahoo(r["t"]) for r in rows]
unique = list(dict.fromkeys(tickers_yf))

print(f"Fetching {len(unique)} tickers via yfinance...")
try:
    data = yf.download(unique, period="5d", interval="1d", progress=False, auto_adjust=True)
except Exception as e:
    print(f"Download error: {e}"); sys.exit(1)

updated = 0
failed_tickers = []

for row in rows:
    yf_sym = to_yahoo(row["t"])
    try:
        closes = data["Close"][yf_sym].dropna() if len(unique) > 1 else data["Close"].dropna()
        if len(closes) < 2:
            failed_tickers.append(row["t"]); continue
        price = float(closes.iloc[-1])
        prev  = float(closes.iloc[-2])
        chg   = round((price - prev) / prev * 100, 2) if prev else row["chg"]
        row["p"]   = round(price, 2)
        row["chg"] = chg
        row["lo"]  = round(min(row["lo"], price), 2)
        row["hi"]  = round(max(row["hi"], price), 2)
        updated += 1
    except Exception:
        failed_tickers.append(row["t"])

print(f"Updated: {updated}, Failed: {len(failed_tickers)}")
if failed_tickers:
    print(f"Failed: {failed_tickers}")

def fmt(v):
    return f"{v:.2f}"

new_entries = [
    f'  {{t:"{r["t"]}",n:"{r["n"]}",s:"{r["s"]}",p:{fmt(r["p"])},lo:{fmt(r["lo"])},hi:{fmt(r["hi"])},chg:{fmt(r["chg"])}}}'
    for r in rows
]
new_block = "const SCREEN_WL = [\n" + ",\n".join(new_entries) + "\n];"

html_new = re.sub(r"const SCREEN_WL = \[.*?\];", new_block, html, count=1, flags=re.DOTALL)

# ── Also update VAL_PRICES — from SCREEN_WL + fetch missing tickers ──────
screen_map = {r["t"]: r["p"] for r in rows}  # ticker → latest price
val_prices_m = re.search(r"const VAL_PRICES = \{([^}]+)\};", html_new)
if val_prices_m:
    val_block = val_prices_m.group(1)
    # Find VAL tickers missing from SCREEN_WL
    val_tickers = re.findall(r'"?([A-Z][A-Z0-9 ]+)"?:[\d.]+', val_block)
    missing = [t for t in val_tickers if t not in screen_map]

    # Fetch missing tickers via yfinance
    if missing:
        VAL_YF_MAP = {"ENR GY": "ENR.DE"}  # special ticker mappings
        missing_yf = [VAL_YF_MAP.get(t, t) for t in missing]
        print(f"Fetching {len(missing_yf)} extra VAL tickers: {missing}")
        try:
            vdata = yf.download(missing_yf, period="5d", interval="1d", progress=False, auto_adjust=True)
            for orig, yf_sym in zip(missing, missing_yf):
                try:
                    if len(missing_yf) > 1:
                        closes = vdata["Close"][yf_sym].dropna()
                    else:
                        closes = vdata["Close"].dropna()
                    if len(closes) >= 1:
                        screen_map[orig] = round(float(closes.iloc[-1]), 2)
                        print(f"  VAL extra: {orig} = {screen_map[orig]}")
                except Exception as ex:
                    print(f"  VAL extra FAILED: {orig} — {ex}")
        except Exception as ex:
            print(f"  VAL extra download error: {ex}")

    def replace_val_price(match):
        raw_key = match.group(1)          # e.g. NVDA  or  "ENR GY"
        key = raw_key.strip('"')
        old_val = match.group(2)
        if key in screen_map:
            return f'{raw_key}:{screen_map[key]:.2f}'
        return match.group(0)
    new_val_block = re.sub(r'("?[A-Z0-9 ]+"?):([0-9.]+)', replace_val_price, val_block)
    html_new = html_new.replace(
        f"const VAL_PRICES = {{{val_block}}};",
        f"const VAL_PRICES = {{{new_val_block}}};"
    )
    print("VAL_PRICES updated.")
else:
    print("WARNING: VAL_PRICES not found, skipping.")

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html_new)

print("index.html updated successfully.")
