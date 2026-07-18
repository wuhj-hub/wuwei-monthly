#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成主板股票清单 all_mainboard.csv (code,name)
============================================
数据源: 东方财富行情列表接口(公开, GitHub runner 可直连)。
过滤规则(与全市场量化技能一致):
  - 仅保留沪深主板 A 股
  - 排除 科创板(688) / 创业板(300,301) / 北交所及新三板(8,43,83,87 开头)
  - 排除 B 股(900/200 开头)
  - 排除 ST / *ST
输出: <仓库>/all_mainboard.csv, 表头 code,name (code 为纯数字, norm_code 会自动加 sh/sz 前缀)

缓存: 若 all_mainboard.csv 已存在且不超过 MAX_AGE_DAYS 天, 直接跳过(省额度)。
      强制刷新: 设置环境变量 WUWEI_FORCE_GEN=1
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

# 东方财富: 全部 A 股 (沪市 m:0+t:6,t:80 / 深市 m:1+t:2,t:23)
FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
API = ("https://push2.eastmoney.com/api/qt/clist/get"
       "?pn={pn}&pz=1000&po=1&np=1&fltt=2&invt=2"
       "&fs={fs}&fields=f12,f14&_={ts}")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://quote.eastmoney.com/",
}

# 需排除的代码前缀 (科创板/创业板/北交所/新三板/B股)
EXCLUDE_PREFIX = ("688", "300", "301", "900", "200", "8", "4")


def is_mainboard(code: str, name: str) -> bool:
    if not code:
        return False
    if "ST" in name.upper():
        return False
    if code.startswith(EXCLUDE_PREFIX):
        return False
    # 主板允许: 沪 600/601/603/605/689 ; 深 000/001/002/003/004
    if code.startswith(("600", "601", "603", "605", "689")):
        return True
    if code.startswith(("000", "001", "002", "003", "004")):
        return True
    return False


def fetch_all():
    stocks = []
    pn = 1
    while True:
        url = API.format(pn=pn, fs=FS, ts=int(time.time() * 1000))
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                txt = r.read().decode("utf-8", "ignore")
        except (urllib.error.URLError, OSError) as e:
            print(f"[gen-mainboard] 请求失败 pn={pn}: {e}", file=sys.stderr)
            break
        try:
            data = json.loads(txt)
        except Exception:
            print(f"[gen-mainboard] JSON 解析失败 pn={pn}", file=sys.stderr)
            break
        diff = (data.get("data") or {}).get("diff") or []
        if not diff:
            break
        for it in diff:
            code = (it.get("f12") or "").strip()
            name = (it.get("f14") or "").strip()
            if is_mainboard(code, name):
                stocks.append((code, name))
        print(f"[gen-mainboard] pn={pn} 累计 {len(stocks)} 只", file=sys.stderr)
        if len(diff) < 1000:
            break
        pn += 1
        time.sleep(0.3)
    return stocks


def main():
    force = os.environ.get("WUWEI_FORCE_GEN") == "1"
    if os.path.exists(OUT_CSV) and not force:
        age = (time.time() - os.path.getmtime(OUT_CSV)) / 86400.0
        if age < MAX_AGE_DAYS:
            print(f"[gen-mainboard] 已有清单({(age):.0f}天前), 跳过刷新", file=sys.stderr)
            return
        else:
            print(f"[gen-mainboard] 清单已 {(age):.0f} 天, 刷新中...", file=sys.stderr)

    stocks = fetch_all()
    if not stocks:
        if os.path.exists(OUT_CSV):
            print("[gen-mainboard] 拉取为空, 保留旧清单", file=sys.stderr)
            return
        print("[gen-mainboard][ERR] 拉取失败且无旧清单, 请检查网络或手动放置 all_mainboard.csv",
              file=sys.stderr)
        sys.exit(1)

    stocks.sort(key=lambda x: x[0])
    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["code", "name"])
        for code, name in stocks:
            w.writerow([code, name])
    print(f"[gen-mainboard] 已写入 {len(stocks)} 只主板股票 -> {OUT_CSV}")


if __name__ == "__main__":
    main()
