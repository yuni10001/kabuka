#!/usr/bin/env python3
"""過去の日足株価をまとめて取得して data/long/ に保存する（分析用・手動で1回実行）。

- 取得元: yfinance（Yahoo Finance）
- 出力: data/long/<code>.csv  … 銘柄ごとに1ファイル
    列: date, code, name, weekday, open, high, low, close, adj_close, volume, ret_pct
      - weekday : 曜日（月〜金）
      - adj_close: 株式分割・配当を調整した終値（長い期間の比較はこちらを使う）
      - ret_pct : adj_close ベースの前日比（%）
- 期間は環境変数 PERIOD で変更可（既定 10y。例: 5y, max）
- 毎日の fetch_prices.py とは別ファイルなので、毎日の記録には影響しません。
"""

import csv
import math
import os
import sys
import time
from datetime import timedelta, timezone

JST = timezone(timedelta(hours=9))
WEEKDAYS = ["月", "火", "水", "木", "金", "土", "日"]

# 取得したい銘柄（追加・削除はここを編集）
TARGETS = [
    # 保有・売買した銘柄
    {"name": "ソフトバンクグループ", "code": "9984", "yahoo": "9984.T"},
    {"name": "イオン", "code": "8267", "yahoo": "8267.T"},
    {"name": "オリエンタルランド", "code": "4661", "yahoo": "4661.T"},
    {"name": "信越化学工業", "code": "4063", "yahoo": "4063.T"},
    {"name": "ラウンドワン", "code": "4680", "yahoo": "4680.T"},
    {"name": "オリックス", "code": "8591", "yahoo": "8591.T"},
    {"name": "日本郵政", "code": "6178", "yahoo": "6178.T"},
    {"name": "東京センチュリー", "code": "8439", "yahoo": "8439.T"},
    {"name": "良品計画", "code": "7453", "yahoo": "7453.T"},
    # 気になっている銘柄
    {"name": "FOOD & LIFE COMPANIES（スシロー）", "code": "3563", "yahoo": "3563.T"},
    {"name": "物語コーポレーション", "code": "3097", "yahoo": "3097.T"},
    {"name": "サンドラッグ", "code": "9989", "yahoo": "9989.T"},
    {"name": "ゆうちょ銀行", "code": "7182", "yahoo": "7182.T"},
    {"name": "SUBARU", "code": "7270", "yahoo": "7270.T"},
    # 物差し
    {"name": "日経平均", "code": "N225", "yahoo": "^N225"},
    {"name": "TOPIX（1306 ETFで代用）", "code": "TOPIX", "yahoo": "1306.T"},
    {"name": "業種:素材・化学（TOPIX-17／1620）", "code": "S17_1620", "yahoo": "1620.T"},
    {"name": "業種:情報通信・サービスその他（TOPIX-17／1626）", "code": "S17_1626", "yahoo": "1626.T"},
    {"name": "業種:小売（TOPIX-17／1630）", "code": "S17_1630", "yahoo": "1630.T"},
    {"name": "業種:金融・除く銀行（TOPIX-17／1632）", "code": "S17_1632", "yahoo": "1632.T"},
]

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "long")
FIELDS = ["date", "code", "name", "weekday", "open", "high", "low", "close",
          "adj_close", "volume", "ret_pct"]


def is_num(x) -> bool:
    try:
        return x is not None and not math.isnan(float(x))
    except (TypeError, ValueError):
        return False


def rnd(x, n=2):
    return round(float(x), n) if is_num(x) else None


def rows_from_df(df, t):
    """yfinance の DataFrame を、保存用の行（dict）のリストに変換する。"""
    rows, prev_adj = [], None
    for idx, r in df.iterrows():
        close = r.get("Close")
        if not is_num(close):
            continue
        d = idx.tz_convert(JST) if getattr(idx, "tzinfo", None) else idx
        adj = r.get("Adj Close") if is_num(r.get("Adj Close")) else close
        ret = (float(adj) / prev_adj - 1) * 100 if prev_adj else None
        rows.append({
            "date": d.strftime("%Y-%m-%d"),
            "code": t["code"], "name": t["name"],
            "weekday": WEEKDAYS[d.weekday()],
            "open": rnd(r.get("Open")), "high": rnd(r.get("High")),
            "low": rnd(r.get("Low")), "close": rnd(close),
            "adj_close": rnd(adj, 4),
            "volume": int(r["Volume"]) if is_num(r.get("Volume")) else None,
            "ret_pct": rnd(ret, 3),
        })
        prev_adj = float(adj)
    return rows


def main() -> int:
    try:
        import yfinance as yf
    except ImportError:
        print("yfinance が入っていません（pip install yfinance）", file=sys.stderr)
        return 1

    period = os.environ.get("PERIOD", "10y")
    os.makedirs(OUT_DIR, exist_ok=True)
    ok, failed = 0, []

    for t in TARGETS:
        rows, err = [], None
        for attempt in range(3):
            try:
                df = yf.Ticker(t["yahoo"]).history(period=period, interval="1d",
                                                   auto_adjust=False)
                rows = rows_from_df(df, t) if df is not None and not df.empty else []
                if rows:
                    break
                err = "データなし"
            except Exception as e:  # noqa: BLE001
                err = str(e)
            time.sleep(3)
        if not rows:
            failed.append(f"{t['code']} {t['name']}: {err}")
            continue
        path = os.path.join(OUT_DIR, f"{t['code']}.csv")
        with open(path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
        ok += 1
        print(f"OK  {t['code']} {t['name']}: {rows[0]['date']} 〜 {rows[-1]['date']}（{len(rows)}日分）")
        time.sleep(1)

    for msg in failed:
        print(f"NG  {msg}")
    print(f"完了: {ok}/{len(TARGETS)} 銘柄（期間 {period}）")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
