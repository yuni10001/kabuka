#!/usr/bin/env python3
"""東証の大引け後に、指定銘柄の当日の株価を取得して data/ に保存する。

- 取得元: yfinance（第一候補）→ Yahoo Finance 直接 → Stooq（予備）
- 出力:
    data/latest.json   … 最新の取得結果（Claude が毎日読む）
    data/history.csv   … 毎日の記録（日付・コードで重複なし）
- 標準ライブラリのみ使用（追加インストール不要）
"""

import csv
import io
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))

# 取得したい銘柄（追加・削除はここを編集）
TARGETS = [
    {"name": "ソフトバンクグループ", "code": "9984", "yahoo": "9984.T", "stooq": "9984.jp"},
    {"name": "イオン", "code": "8267", "yahoo": "8267.T", "stooq": "8267.jp"},
    {"name": "オリエンタルランド", "code": "4661", "yahoo": "4661.T", "stooq": "4661.jp"},
    {"name": "日経平均", "code": "N225", "yahoo": "^N225", "stooq": "^nkx"},
]

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def http_get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def rnd(x):
    return None if x is None else round(float(x), 2)


def from_yfinance(symbol: str, today: str):
    """yfinance（ブラウザに近い形で Yahoo Finance にアクセスするライブラリ）で取得。"""
    try:
        import yfinance as yf
    except ImportError:
        return None, "yfinance: 未インストール"
    try:
        df = yf.Ticker(symbol).history(period="10d", interval="1d", auto_adjust=False)
        if df is None or df.empty:
            return None, "yfinance: データなし"
        rows = []
        for idx, r in df.iterrows():
            d = idx.tz_convert(JST) if idx.tzinfo else idx
            rows.append({"date": d.strftime("%Y-%m-%d"), "open": r["Open"], "high": r["High"],
                         "low": r["Low"], "close": r["Close"], "volume": r.get("Volume")})
        today_rows = [r for r in rows if r["date"] == today]
        if not today_rows:
            return None, f"yfinance: {today} の行なし（最新 {rows[-1]['date']}）"
        prev = [r for r in rows if r["date"] < today]
        return {**today_rows[-1], "prev_close": prev[-1]["close"] if prev else None,
                "source": "Yahoo Finance"}, None
    except Exception as e:  # noqa: BLE001
        return None, f"yfinance: {e}"


def from_yahoo(symbol: str, today: str):
    """Yahoo Finance の日足から today の行と前日終値を返す。"""
    last_err = None
    for host in ("query1", "query2"):
        url = (f"https://{host}.finance.yahoo.com/v8/finance/chart/"
               f"{urllib.request.quote(symbol)}?range=10d&interval=1d")
        try:
            js = json.loads(http_get(url))
            res = js["chart"]["result"][0]
            ts = res.get("timestamp") or []
            q = res["indicators"]["quote"][0]
            rows = []
            for i, t in enumerate(ts):
                c = q["close"][i]
                if c is None:
                    continue
                d = datetime.fromtimestamp(t, JST).strftime("%Y-%m-%d")
                rows.append({"date": d, "open": q["open"][i], "high": q["high"][i],
                             "low": q["low"][i], "close": c, "volume": q["volume"][i]})
            # 同じ日付が重複する場合は後ろを優先
            dedup = {}
            for r in rows:
                dedup[r["date"]] = r
            rows = [dedup[k] for k in sorted(dedup)]
            today_rows = [r for r in rows if r["date"] == today]
            if not today_rows:
                return None, f"yahoo: {today} の行なし（最新 {rows[-1]['date'] if rows else 'なし'}）"
            cur = today_rows[0]
            prev = [r for r in rows if r["date"] < today]
            prev_close = prev[-1]["close"] if prev else res["meta"].get("chartPreviousClose")
            return {**cur, "prev_close": prev_close, "source": "Yahoo Finance"}, None
        except Exception as e:  # noqa: BLE001
            last_err = f"yahoo({host}): {e}"
            time.sleep(2)
    return None, last_err


def from_stooq(symbol: str, today: str):
    url = f"https://stooq.com/q/d/l/?s={urllib.request.quote(symbol)}&i=d"
    try:
        text = http_get(url).decode("utf-8", "replace")
        rows = list(csv.DictReader(io.StringIO(text)))
        if not rows or "Close" not in rows[0]:
            return None, f"stooq: 想定外の応答 {text[:80]!r}"
        rows = [r for r in rows if r.get("Close") not in (None, "", "N/D")]
        today_rows = [r for r in rows if r["Date"] == today]
        if not today_rows:
            return None, f"stooq: {today} の行なし（最新 {rows[-1]['Date'] if rows else 'なし'}）"
        cur = today_rows[-1]
        prev = [r for r in rows if r["Date"] < today]
        return {
            "date": today,
            "open": float(cur["Open"]), "high": float(cur["High"]),
            "low": float(cur["Low"]), "close": float(cur["Close"]),
            "volume": float(cur["Volume"]) if cur.get("Volume") else None,
            "prev_close": float(prev[-1]["Close"]) if prev else None,
            "source": "Stooq",
        }, None
    except Exception as e:  # noqa: BLE001
        return None, f"stooq: {e}"


def main() -> int:
    now = datetime.now(JST)
    today = os.environ.get("TARGET_DATE") or now.strftime("%Y-%m-%d")
    items, ok_count = [], 0

    for t in TARGETS:
        data, errors = None, []
        for fn, sym in ((from_yfinance, t["yahoo"]), (from_yahoo, t["yahoo"]),
                        (from_stooq, t["stooq"])):
            data, err = fn(sym, today)
            if data:
                break
            errors.append(err)
        item = {"name": t["name"], "code": t["code"], "date": today}
        if data:
            ok_count += 1
            close, prev = data["close"], data["prev_close"]
            change = (close - prev) if (close is not None and prev) else None
            item.update({
                "status": "ok",
                "open": rnd(data["open"]), "high": rnd(data["high"]),
                "low": rnd(data["low"]), "close": rnd(close),
                "prev_close": rnd(prev), "change": rnd(change),
                "change_pct": rnd(change / prev * 100) if change is not None else None,
                "volume": int(data["volume"]) if data.get("volume") else None,
                "source": data["source"],
            })
        else:
            item.update({"status": "not_found", "errors": errors})
        items.append(item)
        time.sleep(1)

    os.makedirs(DATA_DIR, exist_ok=True)
    latest = {
        "target_date": today,
        "fetched_at_jst": now.strftime("%Y-%m-%d %H:%M"),
        "ok": ok_count,
        "total": len(TARGETS),
        "items": items,
    }
    with open(os.path.join(DATA_DIR, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(latest, f, ensure_ascii=False, indent=2)

    # 履歴（取得できた行だけ、日付×コードで上書き）
    hist_path = os.path.join(DATA_DIR, "history.csv")
    fields = ["date", "code", "name", "open", "high", "low", "close",
              "prev_close", "change", "change_pct", "volume", "source"]
    hist = {}
    if os.path.exists(hist_path):
        with open(hist_path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                hist[(r["date"], r["code"])] = r
    for it in items:
        if it["status"] == "ok":
            hist[(it["date"], it["code"])] = {k: it.get(k) for k in fields}
    with open(hist_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for key in sorted(hist):
            w.writerow(hist[key])

    print(json.dumps(latest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
