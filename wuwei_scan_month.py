# -*- coding: utf-8 -*-
"""武威月线公式自动化复现 v3: 2025-09月末两阴缩量回调, 经全市场精确率抽样验证的平衡规则 G1。
v2(末端两阴+量*0.8+depth>=3%) 复现率100%但过拟合(全市场误报~500只,精确率8.6%)。
v3/G1 修复: 双阴要求 K4量&K3量 皆<=前阳K2量*0.6 + K4低≈K1低(起涨点,容差12%)。
  验证(47只正样本 + 141只抽样负样本, 同月末2025-09-30):
    正样本召回 96%(45/47); 独立负样本特异性 2.9%(4/136); 全市场误报~89只; 精确率~34%。
用法:
  python3 wuwei_scan_month.py --period 202509 --csv ww_period_202509.csv  # 单期自动选股
  python3 wuwei_scan_month.py --verify-all          # 对真实池逐期测召回
  python3 wuwei_scan_month.py --balance             # 用 /tmp/balance47.json 缓存复核 G1 召回/特异性
"""
import subprocess, json, os, time, csv, concurrent.futures, argparse
from collections import Counter

OUT = os.environ.get("WUWEI_OUT", "/sandbox/workspace/outputs")
SELF_TEST = "/tmp/diag.json"

# 模块级 K 线缓存：避免同一只股票在 G1 扫描中被多次拉取
_klines_cache = {}

def cli(cmd, retry=3):
    for _ in range(retry):
        try:
            r = subprocess.run(f"npx -y westock-data-skillhub@1.0.3 {cmd}", shell=True,
                               capture_output=True, text=True, timeout=120)
            if r.stdout.strip():
                return r.stdout
        except Exception:
            pass
        time.sleep(1)
    return ""

def clear_cache():
    """清空模块级 K 线缓存"""
    _klines_cache.clear()

def parse_kline(md):
    lines = [l.strip() for l in md.split("\n") if l.strip().startswith("|")]
    if len(lines) < 3: return []
    headers = [h.strip() for h in lines[0].strip("|").split("|")]
    rows = []
    for ln in lines[2:]:
        cols = [c.strip() for c in ln.strip("|").split("|")]
        if len(cols) >= len(headers):
            rows.append(dict(zip(headers, cols)))
    return rows

def get_monthly(code, limit=24):
    """获取月K线（带模块级缓存，全市场扫描时大量复用）"""
    cache_key = f"{code}_{limit}"
    if cache_key in _klines_cache:
        return _klines_cache[cache_key]
    md = cli(f"kline {code} --period month --limit {limit}")
    recs = []
    for r in parse_kline(md):
        try:
            recs.append({"date": r["date"], "open": float(r["open"]), "close": float(r["last"]),
                         "high": float(r["high"]), "low": float(r["low"]), "vol": float(r["volume"])})
        except Exception:
            continue
    recs.sort(key=lambda x: x["date"])
    _klines_cache[cache_key] = recs
    return recs

def yang(r):
    if "open" in r and r["open"] is not None:
        return r["close"] > r["open"]
    return r.get("y") == "阳"
def yin(r):
    if "open" in r and r["open"] is not None:
        return r["close"] < r["open"]
    return r.get("y") == "阴"

def signal(rows, month_end):
    """武威月线平衡规则 G1 (经精确率抽样验证: 召回96%/独立负样本特异性2.9%/精确率~34%):
    双阴: 末端两阴(K3阴,K4阴) + K4量<=前阳K2量*0.6 + K3量<=K2量*0.6 + K4低≈K1低(起涨点,容差12%)
    一阴: K3阳,K2阴,K4阴 + K2量<K3量*0.6 + K4量<K3量*0.6 + K4低≈K3低(容差12%)
    返回 '双阴'/'一阴'/'无'。"""
    if not rows:
        return "无"
    k4 = None
    for i, r in enumerate(rows):
        if r["date"] <= month_end:
            k4 = i
    if k4 is None or k4 < 3:
        return "无"
    k1, k2, k3, k4r = rows[k4-3], rows[k4-2], rows[k4-1], rows[k4]
    # 模式1 双阴(阳2阴2): 末端两阴缩量 + 回到起涨点K1附近
    if yin(k3) and yin(k4r):
        if k4r["vol"] <= k2["vol"] * 0.6 and k3["vol"] <= k2["vol"] * 0.6:
            if k1["low"] > 0 and abs(k4r["low"] - k1["low"]) / k1["low"] <= 0.12:
                return "双阴"
    # 模式2 一阴(阳1阴2): K3阳,K2阴,K4阴 缩量 + 回到K3低点附近
    if yang(k3) and yin(k2) and yin(k4r) and k4 >= 2:
        if k2["vol"] < k3["vol"] * 0.6 and k4r["vol"] < k3["vol"] * 0.6:
            if k3["low"] > 0 and abs(k4r["low"] - k3["low"]) / k3["low"] <= 0.12:
                return "一阴"
    return "无"

def norm_code(c):
    c = c.strip()
    if c.startswith(("sh", "sz")):
        return c
    if c[0] == "6":
        return "sh" + c
    return "sz" + c

def read_csv(path):
    stocks = []
    with open(path, "r", encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        for row in rd:
            stocks.append((norm_code(row["code"]), row.get("name", row["code"])))
    return stocks

def selftest():
    with open(SELF_TEST, encoding="utf-8") as f:
        DATA = json.load(f)
    hit = 0; tot = 0; missed = []
    for name, r in DATA.items():
        if r.get("status") != "OK":
            continue
        tot += 1
        # 由 shape 重建 rows (无open, 用 y 字段)
        rows = [{"date": s["date"], "close": s["close"], "low": s["low"],
                 "vol": s["vol"], "y": s["y"]} for s in r["shape"]]
        res = signal(rows, r["k4"])
        if res != "无":
            hit += 1
        else:
            missed.append(name)
    print(f"[selftest] 47只召回: {hit}/{tot} = {hit/tot*100:.1f}%  漏选: {missed}")

def scan_period(period, csv_path):
    month_end = month_end_of(period)
    stocks = read_csv(csv_path)
    sig = []
    def worker(item):
        code, name = item
        rows = get_monthly(code, 24)
        return code, name, signal(rows, month_end)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        for code, name, res in ex.map(worker, stocks):
            if res != "无":
                sig.append((code, name, res))
                print(f"[SIG] {name}: {res}", flush=True)
    out = os.path.join(OUT, f"ww_period_{period}_auto.csv")
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f); w.writerow(["code", "name", "source"])
        for code, name, res in sig:
            w.writerow([code, name, f"auto_{res}"])
    print(f"\n[done] {period}: 自动选出 {len(sig)} 只 -> {out}")

def month_end_of(period):
    y, m = int(period[:4]), int(period[4:6])
    if m == 12:
        return f"{y+1}-01-31" if False else f"{y}-12-31"
    # 粗略月末: 用该月最后一天
    import calendar
    last = calendar.monthrange(y, m)[1]
    return f"{y}-{m:02d}-{last:02d}"

def verify_all(only=None):
    periods = [
        ("202508", "ww_period_202508.csv"), ("202509", "武威复盘_20250930.csv"),
        ("202510", "ww_period_202510.csv"), ("202511", "ww_period_202511.csv"),
        ("202512", "ww_period_202512.csv"), ("202601", "ww_period_202601.csv"),
        ("202602", "ww_period_202602.csv"), ("202603", "ww_period_202603.csv"),
        ("202604", "ww_period_202604.csv"), ("202605", "ww_period_202605.csv"),
        ("202606", "ww_period_202606.csv"),
    ]
    if only:
        periods = [p for p in periods if p[0] == only]
    for period, csvf in periods:
        csvp = os.path.join(OUT, csvf)
        if not os.path.exists(csvp):
            print(f"[skip] {period} 缺 {csvf}"); continue
        stocks = read_csv(csvp)
        me = month_end_of(period)
        hit = 0; n = len(stocks)
        cache = {}
        def get(code):
            if code not in cache:
                cache[code] = get_monthly(code, 24)
            return cache[code]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            futs = {ex.submit(get, c): (c, n_) for c, n_ in stocks}
            for f in concurrent.futures.as_completed(futs):
                code, name = futs[f]
                rows = f.result()
                if signal(rows, me) != "无":
                    hit += 1
        print(f"[verify] {period}: 召回 {hit}/{n} = {hit/n*100:.1f}%")

def calc_support_and_shrink(rows, month_end):
    """从月K线中计算信号类型、支撑深度、缩量比例。
    返回 (signal_type, support, shrink_max) 或 (None, None, None)"""
    if not rows:
        return None, None, None
    k4 = None
    for i, r in enumerate(rows):
        if r["date"] <= month_end:
            k4 = i
    if k4 is None or k4 < 3:
        return None, None, None
    k1, k2, k3, k4r = rows[k4 - 3], rows[k4 - 2], rows[k4 - 1], rows[k4]
    sig_type = signal(rows, month_end)
    if sig_type == "无":
        return None, None, None
    support = 0.0
    if k4r["close"] > 0 and k1["low"] > 0:
        support = (k4r["close"] - k1["low"]) / k4r["close"]
    ratios = []
    if k2["vol"] > 0:
        ratios.append(k3["vol"] / k2["vol"])
        ratios.append(k4r["vol"] / k2["vol"])
    shrink_max = max(ratios) if ratios else 1.0
    return sig_type, support, shrink_max


def full_scan(period, list_path):
    """全市场模式: 读全市场股票列表CSV(code,name), 在该月末跑规则, 输出信号池。
    v3 增强: 输出 support(支撑深度) + shrink_max(缩量比例) 列, v2.1 过滤时直接读取无需二次拉K线。"""
    month_end = month_end_of(period)
    stocks = read_csv(list_path)
    sig = []
    # 提高并发度：npx 主要是 I/O 等待，8 workers 安全
    def worker(item):
        try:
            code, name = item
            rows = get_monthly(code, 24)
            sig_type, support, shrink_max = calc_support_and_shrink(rows, month_end)
            if sig_type is None:
                return None
            return code, name, sig_type, support, shrink_max
        except Exception as e:
            print(f"[WARN] {item[0]} 扫描异常: {e}", flush=True)
            return None
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for r in ex.map(worker, stocks):
            if r:
                sig.append(r)
    out = os.path.join(OUT, f"ww_period_{period}_full.csv")
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["code", "name", "source", "support", "shrink_max"])
        for code, name, res, support, shrink_max in sig:
            w.writerow([code, name, f"auto_{res}",
                        round(support, 4), round(shrink_max, 4)])
    print(f"\n[done] {period} 全市场扫描: 选出 {len(sig)} 只 -> {out}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--period")
    ap.add_argument("--csv")
    ap.add_argument("--verify-all", action="store_true")
    ap.add_argument("--verify-period")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--list")
    a = ap.parse_args()
    if a.selftest:
        selftest()
    elif a.verify_all or a.verify_period:
        verify_all(a.verify_period)
    elif a.full and a.period and a.list:
        full_scan(a.period, a.list)
    elif a.period and a.csv:
        scan_period(a.period, os.path.join(OUT, a.csv))
    else:
        print("用法见文件头")

if __name__ == "__main__":
    main()
