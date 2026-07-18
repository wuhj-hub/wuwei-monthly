#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
武威 v2.1 质量过滤 + 六维评分自动脚本
=====================================
输入 : G1 全市场月线扫描结果  outputs/ww_period_{PERIOD}_full.csv (code,name,source=auto_双阴/auto_一阴)
输出 : outputs/ww_period_{PERIOD}_v21.csv  (逐只六维评分 + 否决原因 + 决策)
       outputs/ww_period_{PERIOD}_v21.md   (精选池汇总报告)
逻辑 :
  - 月线信号/支撑深度/缩量比例：复用 wuwei_scan_month.py 的 get_monthly / signal / month_end_of / norm_code
  - 基本面(盈利/亏损)：自行批量拉利润表(lrb) 取归属母公司净利润 NPParentCompanyOwners（复用 run_filter.py 逻辑）
  - 六维评分 + 一票否决 + 仓位决策：严格依据《武威评分标准_v2.1_回测校准版》
依赖 : npx westock-data-skillhub@1.0.3 (kline + finance)
用法 : python3 wuwei_v21_filter.py --period 202606
"""
import os, csv, sys, importlib.util, concurrent.futures

OUT = os.environ.get("WUWEI_OUT", "/sandbox/workspace/outputs")
HERE = os.path.dirname(os.path.abspath(__file__))
WESTOCK = "npx -y westock-data-skillhub@1.0.3"

# ---- 复用 G1 月线/信号逻辑 ----
_spec = importlib.util.spec_from_file_location("wsm", os.path.join(HERE, "wuwei_scan_month.py"))
wsm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wsm)


def cli(cmd, retry=3):
    import subprocess
    for _ in range(retry):
        try:
            p = subprocess.run(["timeout", "180"] + WESTOCK.split() + cmd.split(),
                               capture_output=True, text=True, timeout=190)
            return p.stdout + p.stderr
        except Exception:
            continue
    return ""


def fetch_finance(codes):
    """批量拉利润表(lrb)，返回 {code:(net_profit_str, enddate)}。复用 run_filter.py 逻辑。"""
    fin = {}
    if not codes:
        return fin
    for i in range(0, len(codes), 10):
        batch = codes[i:i + 10]
        out = cli(f"finance {','.join(batch)} --type lrb --num 1")
        lines = [l for l in out.splitlines() if l.strip().startswith("|")]
        if len(lines) >= 2:
            hdr = [h.strip() for h in lines[0].strip().strip("|").split("|")]
            if all(c in hdr for c in ("SecuCode", "NPParentCompanyOwners", "EndDate")):
                sci, npi, edi = hdr.index("SecuCode"), hdr.index("NPParentCompanyOwners"), hdr.index("EndDate")
                for l in lines[2:]:
                    cols = [x.strip() for x in l.strip().strip("|").split("|")]
                    if len(cols) > max(sci, npi, edi):
                        code, npv, ed = cols[sci], cols[npi], cols[edi]
                        if code in set(codes):
                            fin[code] = (npv, ed)
        print(f"[finance] batch {i} ({len(batch)}) done", file=sys.stderr)
    return fin


def status_of(npv):
    if npv in ("", "-", "--", "None", "null"):
        return "无数据"
    try:
        v = float(npv)
    except Exception:
        return "无数据"
    return "盈利" if v > 0 else "亏损"


def score(sig_type, support, shrink_max, fst):
    """六维评分（满分100），v2.1 权重：信号30/支撑30/缩量10/基本面20/大盘5/价格5"""
    s_signal = 30 if sig_type == "双阴" else 15
    if support >= 0.08:
        s_support = 30
    elif support >= 0.05:
        s_support = 25
    elif support >= 0.03:
        s_support = 12
    elif support >= 0.01:
        s_support = 6
    else:
        s_support = 0
    if shrink_max <= 0.4:
        s_shrink = 10
    elif shrink_max <= 0.5:
        s_shrink = 7
    elif shrink_max <= 0.6:
        s_shrink = 4
    else:
        s_shrink = 0
    if fst == "盈利":
        s_fin = 20
    elif fst == "无数据":
        s_fin = 12
    else:
        s_fin = 0
    s_market, s_price = 5, 5
    total = s_signal + s_support + s_shrink + s_fin + s_market + s_price
    return total, (s_signal, s_support, s_shrink, s_fin, s_market, s_price)


def decide(sig_type, support, fst, total):
    """一票否决 + 仓位决策（依据 v2.1 决策规则）"""
    if fst == "亏损":
        return "否决", "亏损股(一票否决)"
    if support < 0.05:
        return "否决", "浅支撑<5%(一票否决)"
    if sig_type == "双阴" and support >= 0.05 and fst == "盈利" and total >= 75:
        return "重仓", "双阴+深支撑+盈利+评分≥75 ★"
    if sig_type == "一阴" and support >= 0.05:
        return "轻仓", "一阴仅轻仓(永不重仓)"
    return "轻仓/观望", "未达重仓条件"


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", required=True, help="月份 YYYYMM")
    ap.add_argument("--input", default=None, help="G1 结果 CSV（默认 ww_period_{PERIOD}_full.csv）")
    a = ap.parse_args()
    period = a.period
    inp = a.input or os.path.join(OUT, f"ww_period_{period}_full.csv")
    if not os.path.exists(inp):
        print(f"[ERR] 缺 G1 结果 {inp}，请先跑 G1 全市场扫描", file=sys.stderr)
        sys.exit(1)
    month_end = wsm.month_end_of(period)

    # 读 G1 结果
    g1 = []
    with open(inp, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            code = wsm.norm_code((r.get("code") or "").strip())
            name = (r.get("name") or code).strip()
            if code:
                g1.append((code, name))
    print(f"[v21] G1 候选 {len(g1)} 只, period={period}", file=sys.stderr)

    # 并行取月线 + 算支撑深度/缩量max + 重算信号
    def worker(item):
        code, name = item
        recs = wsm.get_monthly(code, 24)
        res = wsm.signal(recs, month_end)
        if res == "无":
            return None
        k4 = None
        for i, r in enumerate(recs):
            if r["date"] <= month_end:
                k4 = i
        if k4 is None or k4 < 3:
            return None
        k1, k2, k3, k4r = recs[k4 - 3], recs[k4 - 2], recs[k4 - 1], recs[k4]
        support = 0.0
        if k4r["close"] > 0 and k1["low"] > 0:
            support = (k4r["close"] - k1["low"]) / k4r["close"]  # 支撑深度≥5%硬过滤
        ratios = []
        if k2["vol"] > 0:
            ratios.append(k3["vol"] / k2["vol"])
            ratios.append(k4r["vol"] / k2["vol"])
        shrink_max = max(ratios) if ratios else 1.0
        return code, name, res, support, shrink_max

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        for r in ex.map(worker, g1):
            if r:
                results.append(r)
    print(f"[v21] 月线有效 {len(results)} 只", file=sys.stderr)

    # 财务批量
    codes = [r[0] for r in results]
    fin = fetch_finance(codes)

    # 评分 + 决策
    out_rows = []
    for code, name, res, support, shrink_max in results:
        npv, ed = fin.get(code, ("", ""))
        fst = status_of(npv)
        total, _ = score(res, support, shrink_max, fst)
        decision, reason = decide(res, support, fst, total)
        out_rows.append({
            "code": code, "name": name, "signal": res,
            "support_pct": round(support * 100, 2),
            "shrink_max_pct": round(shrink_max * 100, 1),
            "finance": fst, "net_profit": npv, "report_end": ed,
            "score": total, "decision": decision, "reason": reason,
        })

    # 写 CSV
    csv_path = os.path.join(OUT, f"ww_period_{period}_v21.csv")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["code", "name", "signal", "support_pct", "shrink_max_pct",
                    "finance", "net_profit", "report_end", "score", "decision", "reason"])
        for r in out_rows:
            w.writerow([r["code"], r["name"], r["signal"], r["support_pct"], r["shrink_max_pct"],
                        r["finance"], r["net_profit"], r["report_end"], r["score"], r["decision"], r["reason"]])

    # 汇总
    n_heavy = sum(1 for r in out_rows if r["decision"] == "重仓")
    n_light = sum(1 for r in out_rows if r["decision"] == "轻仓")
    n_obs = sum(1 for r in out_rows if r["decision"] == "轻仓/观望")
    n_veto = sum(1 for r in out_rows if r["decision"] == "否决")
    n_profit = sum(1 for r in out_rows if r["finance"] == "盈利")
    n_loss = sum(1 for r in out_rows if r["finance"] == "亏损")
    n_nodata = sum(1 for r in out_rows if r["finance"] == "无数据")

    # 写 MD
    md_path = os.path.join(OUT, f"ww_period_{period}_v21.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# 武威 v2.1 质量过滤 · 精选池（{period}）\n\n")
        f.write(f"- 输入：G1 全市场月线扫描 **{len(g1)}** 只 → 月线有效 **{len(results)}** 只\n")
        f.write("- 规则：六维评分 + 一票否决（浅支撑<5% / 亏损股放弃），详见《武威评分标准_v2.1_回测校准版》\n")
        f.write("- 配套 SOP：《武威实战SOP_G1初筛_v2.1过滤_MA20止盈》\n\n")
        f.write("## 一、总体统计\n\n")
        f.write(f"- 重仓（★ 双阴+深支撑+盈利+评分≥75）：**{n_heavy}**\n")
        f.write(f"- 轻仓（一阴深支撑 / 未达重仓）：**{n_light}**\n")
        f.write(f"- 轻仓/观望：**{n_obs}**\n")
        f.write(f"- 否决（浅支撑 / 亏损）：**{n_veto}**\n")
        f.write(f"- 基本面：盈利 {n_profit} / 亏损 {n_loss} / 无数据 {n_nodata}\n\n")
        f.write("## 二、重仓精选池（★）\n\n")
        f.write("| 代码 | 名称 | 信号 | 支撑% | 缩量max% | 基本面 | 评分 | 报告期 |\n|---|---|---|---|---|---|---|---|\n")
        for r in sorted([x for x in out_rows if x["decision"] == "重仓"], key=lambda x: -x["score"]):
            f.write(f"| {r['code']} | {r['name']} | {r['signal']} | {r['support_pct']} | {r['shrink_max_pct']} | {r['finance']} | {r['score']} | {r['report_end']} |\n")
        f.write("\n## 三、轻仓 / 观望池\n\n")
        f.write("| 代码 | 名称 | 信号 | 支撑% | 缩量max% | 基本面 | 评分 | 决策 | 原因 |\n|---|---|---|---|---|---|---|---|---|\n")
        for r in sorted([x for x in out_rows if x["decision"] in ("轻仓", "轻仓/观望")], key=lambda x: -x["score"]):
            f.write(f"| {r['code']} | {r['name']} | {r['signal']} | {r['support_pct']} | {r['shrink_max_pct']} | {r['finance']} | {r['score']} | {r['decision']} | {r['reason']} |\n")
        f.write("\n## 四、否决池（浅支撑 / 亏损）\n\n")
        f.write("| 代码 | 名称 | 信号 | 支撑% | 基本面 | 原因 |\n|---|---|---|---|---|---|\n")
        for r in [x for x in out_rows if x["decision"] == "否决"]:
            f.write(f"| {r['code']} | {r['name']} | {r['signal']} | {r['support_pct']} | {r['finance']} | {r['reason']} |\n")
        f.write("\n> 本精选池为量化历史规律总结，非投资建议；实战需结合实时行情、大盘温度计动态调整，并严格按 SOP 执行 MA20 止盈与硬止损。\n")

    print(f"[v21] done -> {csv_path} + {md_path}  (重仓{n_heavy}/轻仓{n_light}/观望{n_obs}/否决{n_veto})", file=sys.stderr)


if __name__ == "__main__":
    main()
