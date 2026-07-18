# 武威月线 G1 · 月底自动扫描（GitHub 版）

把「G1 全市场初筛 → v2.1 质量过滤评分 → 归档武威知识库」做成 **GitHub Actions 定时任务**，
每月 1 日北京时间 16:00 自动跑上月行情，产出精选池并（可选）入库。

> 思路：用 GitHub 的定时工作流（scheduled cron）替代沙箱缺失的 crontab / 平台 scheduler。
> 整个仓库自包含，纯 Python 标准库 + `npx westock-data-skillhub` 数据源，无需 pip 装第三方包。

## 目录结构

```
.
├── .github/workflows/wuwei_monthly.yml   # 月度定时工作流
├── wuwei_scan_month.py                    # G1 全市场月线初筛（原脚本，路径已可配置）
├── wuwei_v21_filter.py                    # v2.1 六维评分 + 一票否决（原脚本，路径已可配置）
├── wuwei_monthly_run.sh                   # 串联：初筛 → 过滤 → 归档
├── upload_kb.py                           # 上传到 ima 知识库（复用 ima-knowledge 的 upload_file.py）
├── gen_mainboard.py                       # 自动生成/刷新主板清单 all_mainboard.csv（东方财富）
├── all_mainboard.csv                      # 主板股票清单（首次运行自动生成，之后每月刷新）
├── outputs/                               # 每月产出（ww_period_YYYYMM_full.csv / _v21.csv / _v21.md）
└── README.md
```

## 快速开始

```bash
# 1. 初始化仓库并推送
git init
git add -A
git commit -m "init wuwei monthly"
gh repo create wuwei-monthly --private --source=. --push   # 或推到你已有的远端

# 2. 配置 Secrets（Settings → Secrets and variables → Actions）
#    至少配置下面两个，否则只生成产出、不上传知识库：
IMA_OPENAPI_CLIENTID    # ima 开放平台 Client ID  (https://ima.qq.com/agent-interface)
IMA_OPENAPI_APIKEY      # ima 开放平台 API Key
#    可选（不填则用默认值=你的武威知识库）：
WUWEI_KB_ID             # 知识库 ID（默认已填武威知识库）
WUWEI_FOLDER_ID         # 子文件夹 ID（默认已填「月线公式验证」）

# 3. 触发首次运行
#    Actions → 武威月线G1 月底自动扫描 → Run workflow
#    （可填 period=202606 指定月份；留空=上月）
```

## 定时说明

- 触发时间：`0 8 1 * *` UTC = 每月 1 日 **北京 16:00**（上月收盘后，月线已定稿）。
- 也可在 Actions 页面手动 `Run workflow`，并填 `period` 指定任意月份重跑。
- 每月运行会先 `gen_mainboard.py` 刷新主板清单（缓存 20 天，捕获新 IPO），再扫描。

## 主板清单从哪来

`gen_mainboard.py` 用**东方财富公开行情接口**枚举全部 A 股，按以下规则过滤：

- 保留：沪市 `600/601/603/605/689`、深市 `000/001/002/003/004`
- 排除：科创板 `688`、创业板 `300/301`、北交所/新三板 `8/43/83/87`、B 股 `900/200`、ST/*ST

首跑在 GitHub runner 上自动生成 `all_mainboard.csv` 并提交回仓库；之后每月刷新。
（沙箱/本地若东方财富不可达，可手动放一个 `all_mainboard.csv`，表头 `code,name` 即可。）

## 环境变量（均可不填，有默认值）

| 变量 | 默认 | 说明 |
|---|---|---|
| `WUWEI_OUT` | `<仓库>/outputs` | 产出目录 |
| `WUWEI_LIST` | `<仓库>/all_mainboard.csv` | 主板清单 |
| `WUWEI_KB_ID` | 武威知识库 | 知识库 ID |
| `WUWEI_FOLDER_ID` | 月线公式验证 | 子文件夹 ID |
| `IMA_OPENAPI_CLIENTID` / `IMA_OPENAPI_APIKEY` | 无 | 知识库上传凭证（缺则跳过上传）|

## 产出

- `outputs/ww_period_YYYYMM_full.csv` — G1 全市场初筛候选
- `outputs/ww_period_YYYYMM_v21.csv` — v2.1 六维评分逐只结果
- `outputs/ww_period_YYYYMM_v21.md` — 精选池汇总报告（重仓/轻仓/否决）
- 若配置了 ima 密钥：上述 md + csv 自动归档到武威知识库「月线公式验证」

## 风控 / 局限

- 量化历史规律总结，**非投资建议**；实战需结合实时行情、大盘温度计，按 SOP 执行 MA20 止盈与硬止损。
- GitHub 免费额度：私有库每月 2000 分钟、单任务最长 6 小时；全市场月线扫描在限额内（已设 360 分钟超时）。
- 知识库写入不可逆（KB API 不支持删除）；同名文件会追加时间戳生成新 media_id。
