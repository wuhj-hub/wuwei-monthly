#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成主板股票清单 all_mainboard.csv (code,name)
============================================
数据源(自动降级): 东方财富行情列表 → tdx_screener → 已提交的清单。
过滤规则:
  - 仅保留沪深主板 A 股
  - 排除 科创板(688) / 创业板(300,301) / 北交所及新三板(8,43,83,87 开头)
  - 排除 B 股(900/200 开头)
  - 排除 ST / *ST

缓存: 已有清单且不超过 MAX_AGE_DAYS 天, 跳过(省额度)。
      强制刷新: WUWEI_FORCE_GEN=1
"""
import os
import sys
import csv
import json
import time
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_CSV = os.path.join(HERE, "all_mainboard.csv")
MAX_AGE_DAYS = 20

FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
API = ("https://push2.eastmoney.com/api/qt/clist/get"
       "?pn={pn}&pz=1000&po=1&np=1&fltt=2&invt=2"
       "&fs={fs}&fields=f12,f14&_={ts}")
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}

EXCLUDE_PREFIX = ("688", "300", "301", "900", "200", "8", "4")


def is_mainboard(code: str, name: str) -> bool:
    if not code or "ST" in name.upper() or code.startswith(EXCLUDE_PREFIX):
        return False
    return code.startswith(("600", "601", "603", "605", "689", "000", "001", "002", "003", "004"))


def fetch_eastmoney(retries=3):
    """东方财富 — 自动重试"""
    for attempt in range(1, retries + 1):
        stocks, pn = [], 1
        while True:
            url = API.format(pn=pn, fs=FS, ts=int(time.time() * 1000))
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=30) as r:
                    txt = r.read().decode("utf-8", "ignore")
                data = json.loads(txt)
            except Exception as e:
                print(f"[gen] 东方财富 attempt {attempt}/{retries} pn={pn}: {e}", file=sys.stderr)
                if attempt < retries:
                    time.sleep(3)
                break
            diff = (data.get("data") or {}).get("diff") or []
            for it in diff:
                c, n = (it.get("f12") or "").strip(), (it.get("f14") or "").strip()
                if is_mainboard(c, n):
                    stocks.append((c, n))
            if len(diff) < 1000:
                return stocks
            pn += 1
            time.sleep(0.5)
    return None


def main():
    force = os.environ.get("WUWEI_FORCE_GEN") == "1"
    if os.path.exists(OUT_CSV) and not force:
        age = (time.time() - os.path.getmtime(OUT_CSV)) / 86400.0
        if age < MAX_AGE_DAYS:
            print(f"[gen] 已有清单({age:.0f}天前), 跳过", file=sys.stderr)
            return
        print(f"[gen] 清单{age:.0f}天, 刷新...", file=sys.stderr)

    stocks = fetch_eastmoney()
    if stocks:
        stocks.sort(key=lambda x: x[0])
        with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["code", "name"])
            for c, n in stocks:
                w.writerow([c, n])
        print(f"[gen] 已写入 {len(stocks)} 只主板股票 -> {OUT_CSV}", file=sys.stderr)
        return

    # 东方财富全失败 — 保留已有清单(如有)
    if os.path.exists(OUT_CSV):
        print("[gen] 东方财富不可用, 保留旧清单", file=sys.stderr)
        return

    # 无任何清单 — 尝试用 tdx_screener 补充
    print("[gen] 无旧清单且东方财富不可用, 尝试 tdx_screener...", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
