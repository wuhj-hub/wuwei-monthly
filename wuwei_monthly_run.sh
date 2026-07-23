#!/usr/bin/env bash
# ============================================================
# 武威月线 G1 体系 · 月底自动运行脚本（GitHub Actions / 本地通用）
# 流程: G1 全市场初筛 → v2.1 质量过滤评分 → 归档精选池至武威知识库
#
# 依赖: python3 / npx(westock-data-skillhub) / upload_kb.py / all_mainboard.csv
# 配置(环境变量, 均有默认值):
#   WUWEI_OUT        产出目录       默认 <仓库>/outputs
#   WUWEI_LIST       主板清单CSV    默认 <仓库>/all_mainboard.csv
#   WUWEI_KB_ID      知识库ID       默认 武威知识库
#   WUWEI_FOLDER_ID  子文件夹ID     默认 武威G1月度自动扫描
#   IMA_OPENAPI_CLIENTID / IMA_OPENAPI_APIKEY  知识库上传凭证(缺则跳过上传)
#   PUSHPLUS_TOKEN   pushplus 微信推送 token (缺则跳过推送)
# 用法:
#   ./wuwei_monthly_run.sh            # 自动跑上月 (YYYYMM)
#   ./wuwei_monthly_run.sh 202606     # 指定月份
# ============================================================
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${WUWEI_OUT:-$REPO/outputs}"
export WUWEI_OUT="$OUT"
mkdir -p "$OUT"

LIST="${WUWEI_LIST:-$REPO/all_mainboard.csv}"
KB_ID="${WUWEI_KB_ID:-Q2g2GtNNL-9VcrQkbIfCRKzZl5K2ag2sQlcqcNMr3Mc=}"
FOLDER_ID="${WUWEI_FOLDER_ID:-folder_7484032975660724}"
UPLOAD="$REPO/upload_kb.py"
PY="${PYTHON:-python3}"

# 1. 目标月份: 参数优先, 否则上月 (用 python 算, 跨平台)
if [ $# -ge 1 ]; then
  PERIOD="$1"
else
  PERIOD=$(python3 -c 'import datetime;d=datetime.date.today();m=d.month-1 or 12;y=d.year-(d.month==1);print(f"{y}{m:02d}")')
fi
echo "[wuwei-monthly] period=$PERIOD  $(date '+%F %T')"

# 2. 前置检查 / 主板清单
if [ ! -f "$LIST" ]; then
  echo "[wuwei-monthly] 缺少主板清单 $LIST, 尝试自动生成..."
  "$PY" "$REPO/gen_mainboard.py" || { echo "[ERR] 主板清单生成失败, 请手动放置 all_mainboard.csv"; exit 1; }
fi
test -f "$LIST" || { echo "[ERR] 缺少主板清单 $LIST"; exit 1; }
test -f "$REPO/wuwei_scan_month.py" || { echo "[ERR] 缺少 G1 脚本"; exit 1; }
test -f "$REPO/wuwei_v21_filter.py" || { echo "[ERR] 缺少 v2.1 过滤脚本"; exit 1; }

# 3. Step1 G1 全市场初筛 (宽口径捞双阴/一阴信号)
"$PY" "$REPO/wuwei_scan_month.py" --full --period "$PERIOD" --list "$LIST"
G1="$OUT/ww_period_${PERIOD}_full.csv"
test -f "$G1" || { echo "[ERR] G1 未产出 $G1"; exit 1; }
echo "[wuwei-monthly] G1 初筛完成 -> $G1"

# 4. Step2 v2.1 质量过滤 + 六维评分
"$PY" "$REPO/wuwei_v21_filter.py" --period "$PERIOD"
V21MD="$OUT/ww_period_${PERIOD}_v21.md"
V21CSV="$OUT/ww_period_${PERIOD}_v21.csv"
test -f "$V21MD" || { echo "[ERR] v2.1 未产出 $V21MD"; exit 1; }
echo "[wuwei-monthly] v2.1 过滤完成 -> $V21MD"

# 5. 归档: 上传到「武威G1月度自动扫描」子文件夹 (缺密钥则跳过, 仅保留本地产出)
if [ -n "${IMA_OPENAPI_CLIENTID:-}" ] && [ -n "${IMA_OPENAPI_APIKEY:-}" ]; then
  "$PY" "$UPLOAD" --file-path "$V21MD"  --knowledge-base-id "$KB_ID" --folder-id "$FOLDER_ID" || echo "[WARN] v21.md 上传失败, 跳过"
  "$PY" "$UPLOAD" --file-path "$V21CSV" --knowledge-base-id "$KB_ID" --folder-id "$FOLDER_ID" || echo "[WARN] v21.csv 上传失败, 跳过"
  echo "[wuwei-monthly] 精选池已归档至「武威G1月度自动扫描」  $(date '+%F %T')"
else
  echo "[wuwei-monthly] 未配置 IMA_OPENAPI_CLIENTID/APIKEY, 跳过知识库上传, 仅本地产出已生成"
fi

# 6. pushplus 微信推送 (缺 token 则跳过)
if [ -n "${PUSHPLUS_TOKEN:-}" ]; then
  "$PY" -c "
import json, urllib.request, csv, os

period = '$PERIOD'
out = '$OUT'
token = '$PUSHPLUS_TOKEN'

# 读取 v21 结果
v21_csv = os.path.join(out, f'ww_period_{period}_v21.csv')
heavy, reject_shallow, reject_loss = 0, 0, 0
heavy_list = []
if os.path.exists(v21_csv):
    with open(v21_csv, encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            dec = row.get('decision','')
            if dec == '重仓':
                heavy += 1
                heavy_list.append(f\"{row.get('name','')}({row.get('code','')})\")
            elif '亏损' in dec:
                reject_loss += 1
            else:
                reject_shallow += 1

title = f'武威 {period} 月度扫描完成'
lines = [
    f'## 📊 武威月线G1扫描报告 ({period})',
    f'',
    f'| 指标 | 数值 |',
    f'|---|---|',
    f'| G1初筛信号 | {heavy+reject_shallow+reject_loss} 只 |',
    f'| ✅ 重仓精选 | **{heavy} 只** |',
    f'| ❌ 否决(浅支撑) | {reject_shallow} 只 |',
    f'| ❌ 否决(亏损股) | {reject_loss} 只 |',
]
if heavy_list:
    lines += ['', '### 🏆 重仓精选池', '']
    lines += [f'- {h}' for h in heavy_list]
lines += ['', f'> 详情: https://github.com/wuhj-hub/wuwei-monthly/actions']

content = '\n'.join(lines)
payload = json.dumps({'token': token, 'title': title, 'content': content, 'template': 'markdown'}).encode()
req = urllib.request.Request('https://www.pushplus.plus/send', data=payload,
    headers={'Content-Type': 'application/json'})
try:
    resp = urllib.request.urlopen(req, timeout=15)
    result = json.loads(resp.read().decode())
    if result.get('code') == 200:
        print('[pushplus] 推送成功')
    else:
        print(f'[pushplus] 推送失败: {result}')
except Exception as e:
    print(f'[pushplus] 推送异常: {e}')
" || echo "[WARN] pushplus 推送失败, 跳过"
fi

echo "[wuwei-monthly] 完成  $(date '+%F %T')"
