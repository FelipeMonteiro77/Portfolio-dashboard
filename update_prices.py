"""
Fetches live prices for SCREEN_WL tickers and updates index.html in-place.
Runs server-side (no CORS), triggered by GitHub Actions.
"""
import re, json, sys

try:
    import yfinance as yf
except ImportError:
    print("yfinance not installed"); sys.exit(1)

# ── Read index.html ────────────────────────────────────────────────────────────
with open("index.html", encoding="utf-8") as f:
    html = f.read()

# ── Extract current SCREEN_WL ─────────────────────────────────────────────────
m = re.search(r"const SCREEN_WL = \[(.*?)\];", html, re.DOTALL)
if not m:
    print("ERROR: SCREEN_WL not found in index.html"); sys.exit(1)

block = m.group(1)
# Parse each entry: {t:"X", n:"Y", s:"Z", p:N, lo:N, hi:N, chg:N}
entries = re.findall(
    r'\{t:"([^"]+)",n:"([^"]+)",s:"([^"]+)",p:([\d.]+),lo:([\d.]+),hi:([\d.]+),chg:([+-]?[\d.]+)\}',
    block
)
if not entries:
    print("ERROR: could not parse SCREEN_WL entries"); sys.exit(1)

rows = [{"t": t, "n": n, "s": s, "p": float(p), "lo": float(lo), "hi": float(hi), "chg": float(chg)}
        for t, n, s, p, lo, hi, chg in entries]

# ── Map BR ticker → Yahoo symbol ──────────────────────────────────────────────
def to_yahoo(t):
    if t.endswith(".SA"):
        return t
    if re.match(r"^[A-Z]{4}\d{1,2}$", t):
        return t + ".SA"
    return t

# Batch download — US tickers
tickers_yf = [to_yahoo(r["t"]) for r in rows]
unique = list(dict.fromkeys(tickers_yf))   # preserve order, dedupe

print(f"Fetching {len(unique)} tickers via yfinance...")
try:
    data = yf.download(unique, period="5d", interval="1d", progress=False, auto_adjust=True, group_by="ticker")
except Exception as e:
    print(f"Download error: {e}"); sys.exit(1)

updated = 0
failed_tickers = []

for row in rows:
    yf_sym = to_yahoo(row["t"])
    try:
        if len(unique) == 1:
            closes = data["Close"].dropna()
        else:
            closes = data["Close"][yf_sym].dropna()

        if len(closes) < 2:
            failed_tickers.append(row["t"]); continue

        price = float(closes.iloc[-1])
        prev  = float(closes.iloc[-2])
        chg   = round((price - prev) / prev * 100, 2) if prev else row["chg"]

        # Update 52W hi/lo if needed
        lo = min(row["lo"], price)
        hi = max(row["hi"], price)

        row["p"]   = round(price, 2)
        row["chg"] = chg
        row["lo"]  = round(lo, 2)
        row["hi"]  = round(hi, 2)
        updated += 1
    except Exception as e:
        failed_tickers.append(row["t"])

print(f"Updated: {updated}, Failed: {len(failed_tickers)}")
if failed_tickers:
    print(f"Failed: {failed_tickers}")

# ── Build new SCREEN_WL JS block ──────────────────────────────────────────────
def fmt(v):
    return f"{v:.2f}"

new_entries = []
for r in rows:
    new_entries.append(
        f'  {{t:"{r["t"]}",n:"{r["n"]}",s:"{r["s"]}",p:{fmt(r["p"])},lo:{fmt(r["lo"])},hi:{fmt(r["hi"])},chg:{fmt(r["chg"])}}}'
    )
new_block = "const SCREEN_WL = [\n" + ",\n".join(new_entries) + "\n];"

# ── Replace in HTML ───────────────────────────────────────────────────────────
html_new = re.sub(r"const SCREEN_WL = \[.*?\];", new_block, html, count=1, flags=re.DOTALL)

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html_new)

print("index.html updated successfully.")
