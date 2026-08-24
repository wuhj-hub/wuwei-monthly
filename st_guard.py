#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
st_guard.py —— 实时 ST/退市 校验模块（qt.gtimg.cn 批量）
========================================================
背景：all_mainboard.csv 清单是快照式 ST 过滤，股票后续戴帽（如交大昂立→ST交昂）
     不会反映在清单中。本模块用腾讯行情接口实时校验名称，作为输出端兜底防线。
适用：所有输出标的的脚本（一统天下/才哥/妖股/龙头/双弦等），评分/输出前过滤。

用法：
  python3 st_guard.py 600530,600519        # 命令行：输出JSON {st_codes, names}
  from st_guard import check_st_batch, filter_st
"""
import json
import re
import sys
import urllib.request

GTIMG = "https://qt.gtimg.cn/q="
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com"}


def norm(code):
    """纯数字→sh/sz前缀"""
    code = str(code).strip()
    if code.startswith(("sh", "sz", "bj")):
        return code
    return ("sh" if code.startswith(("6", "9", "5")) else "sz") + code


def fetch_names(codes, batch=50):
    """批量查询实时名称，返回 {纯数字code: 名称}。失败项跳过。"""
    out = {}
    codes = [norm(c) for c in codes if str(c).strip()]
    for i in range(0, len(codes), batch):
        chunk = codes[i:i + batch]
        url = GTIMG + ",".join(chunk)
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            raw = urllib.request.urlopen(req, timeout=15).read().decode("gbk", "replace")
        except Exception:
            continue
        for line in raw.split(";"):
            m = re.match(r'v_(\w+)="([^"]*)"', line.strip())
            if not m:
                continue
            parts = m.group(2).split("~")
            if len(parts) >= 2:
                out[m.group(1)[2:]] = parts[1].strip()
    return out


def check_st_batch(codes):
    """批量校验，返回 (st_codes集合, names字典)。st_codes = 名称含ST/退的代码"""
    names = fetch_names(codes)
    st = {c for c, n in names.items() if "ST" in n.upper() or "退" in n}
    return st, names


def filter_st(items, code_key="code"):
    """从标的列表过滤ST/退市（原地过滤+返回被剔除的）。items: [{code,...},...]"""
    codes = [it[code_key] for it in items]
    st, _ = check_st_batch(codes)
    kept, dropped = [], []
    for it in items:
        c = str(it[code_key])
        if c[2:] in st if c.startswith(("sh", "sz")) else c in st:
            dropped.append(it)
        else:
            kept.append(it)
    return kept, dropped


if __name__ == "__main__":
    codes = sys.argv[1].split(",") if len(sys.argv) > 1 else []
    st, names = check_st_batch(codes)
    print(json.dumps({"st_codes": sorted(st), "names": names}, ensure_ascii=False, indent=1))
