# dga-edge

面向嵌入式平台的油浸式变压器 DGA 故障诊断内核。
A zero-dependency dissolved gas analysis (DGA) diagnosis kernel for embedded
transformer condition monitoring.

**核心特点：零第三方依赖。** 整个诊断内核只用 Python 标准库，可运行于
Jetson Nano（JetPack 4.6.4 / Python 3.6 / aarch64）。

[![CI](https://github.com/pppengs/dga-edge/actions/workflows/ci.yml/badge.svg)](https://github.com/pppengs/dga-edge/actions/workflows/ci.yml)
![python](https://img.shields.io/badge/python-3.6%20%7C%203.13-blue)
![license](https://img.shields.io/badge/license-MIT-green)

---

## 为什么做这个

现有开源 DGA 项目几乎全是 PC / Notebook / Web GUI 形态，依赖 pandas、
matplotlib、Dash 或 plotly。这在嵌入式侧有两个问题：这些包在 aarch64 +
Python 3.6 上没有可靠 wheel，而诊断算法本身其实**根本不需要它们**。

三比值是 3 次除法加查表，Duval 是归一化加点在多边形内判定。把算法从 GUI 里
剥离出来，一个 20 KB、零依赖、单样本十几微秒的内核就出来了。

> **关于创新性的边界**：上面这句话只针对**开源项目**。商业在线监测装置早已把
> Duval 判定写进固件（闭源），2025–2026 也有多篇边缘端 DGA 论文（但全是机器
> 学习路线，依赖深度学习框架）。本项目的位置、可声称与不可声称的创新点，
> 见 [`docs/NOVELTY.md`](docs/NOVELTY.md)——**写论文前请先读**。

| 指标 | 实测（宿主 x86） |
|---|---|
| 可部署代码（`dga_core` + `dga_service`） | **约 39 KB / 20 KB**（11 个文件，1056 + 549 行） |
| 运行时模型（Duval 七区） | **0.9 KB**（40 个顶点） |
| 第三方依赖 | **0** |
| 单样本（4 方法 + 状态判定）延迟 | **P50 11.8 µs / P99 25.6 µs** |
| 批处理吞吐 | **约 87,000 samples/s** |
| 每样本常驻内存 | **≈ 1 字节**，峰值 0.8 KB |

对比：numpy + pandas 约 101 MB，matplotlib 另需 30–50 MB。**内核比它们小约
1700 倍**——这个倍数随功能增加在下降，但每加一个方法只加几 KB，而科学计算栈
是固定 100 MB 起步。

---

## 实现的方法

系统分两半，回答两个不同的问题。

### 故障诊断（which fault?）

| 方法 | 依据 | 说明 |
|---|---|---|
| `iec_three_ratio` | IEC 60599 三比值法（经典 0/1/2 编码） | 未覆盖的编码组合返回 `ND`，不猜 |
| `iec_ratio` | IEC 60599 (2015) 直接比值带 | 与编码版并列报告，行为不同 |
| `rogers_ratio` | IEEE C57.104-2019 | 即 1991 修订版 |
| `duval_triangle1` | Duval Triangle 1 | 七区（PD/T1/T2/T3/D1/D2/DT） |
| `doernenburg` | IEEE C57.104-2019 | 需要 CO，默认不启用 |

### 状态监测（is anything wrong?）

在线监测首先要回答的不是"哪种故障"，而是"要不要报警"。`dga_core/condition.py`
按 **IEEE C57.104-2019** 给出可直接落地的状态判定：

| 能力 | 依据 | 说明 |
|---|---|---|
| `assess_condition` | C57.104 Table 1 | 单样本 → Condition 1–4，含 TDCG 与限制气体 |
| `assess_rate` | C57.104 Table 3 / 4 | 两次采样间的绝对变化与 ppm/年 产气速率 |
| `monitor` | C57.104 Table 1 + 5 | 综合判定；产气速率显著时**最多升级一级** |
| 采样间隔建议 | C57.104 Table 5 | 按状态给出 annual / monthly / weekly / daily |

**每条阈值的出处都记录在 [`docs/STANDARDS.md`](docs/STANDARDS.md)**，包括文献
之间的分歧点以及本项目如何取舍。没有任何一个表是凭记忆写的。

从标准里读出来的两个可验证结论（见 `docs/STANDARDS.md` §7.2）：

- **TDCG 分级永远不会成为限制因素。** 每一级的"各气体限值之和"都小于该级的
  TDCG 限值（686<720、1879<1920、4585<4630），所以单气体限值恒严于 TDCG。
  这一点用 2000 组随机样本做了属性测试，不是推测。
- **乙炔是最严的通道**：2 ppm 即 Condition 2，35 ppm 即 Condition 4。

---

## 快速开始

```bash
# 内核与管线需要 Python 3.6+，无任何依赖
python -m unittest discover -s tests        # 102 个单测，零依赖

# 单条样本
python - <<'PY'
from dga_core import GasSample, diagnose
s = GasSample(h2=100.0, ch4=200.0, c2h6=50.0, c2h4=100.0, c2h2=1.0)
for m in diagnose(s).results:
    print(m.method, m.code, "(decided)" if m.applicable else "(no decision)")
PY

# 批量诊断 + 状态评估
python -m dga_service.cli --input samples.csv --output results.csv --jsonl results.jsonl

# 时间序列模式：按 id 分组、按日期排序，评估产气速率（需要 date 列）
python -m dga_service.cli --input examples/samples_timeseries.csv --trend --output trend.csv
```

输入 CSV 的列名按别名匹配，可直接吃现场导出文件：
`H2/hydrogen/氢气`、`CH4/methane/甲烷`、`C2H6/ethane/乙烷`、`C2H4/ethylene/乙烯`、
`C2H2/acetylene/乙炔`，可选 id 列（`group`/`组号`/`sample_id`），
时间序列模式另需 `date`/`日期`/`timestamp` 列（支持 `2025-01-15`、
`2025/01/15 08:30`、`20250115` 等格式）。

单样本直接调用状态监测：

```python
from dga_core import GasSample, monitor, diagnose

s = GasSample(h2=100.0, ch4=200.0, c2h6=50.0, c2h4=100.0, c2h2=1.0, co=120.0)
m = monitor(s)
print(m.condition, m.label, m.assessment.tdcg, m.assessment.limiting_gas)
print(m.advice)
```

### 示例文件

`examples/` 下有三个可直接跑的合成样例（**不是实测数据**）：

| 文件 | 用途 |
|---|---|
| `samples_batch.csv` | 批量诊断，含 1 条全零行和 1 条负浓度行，用来演示异常隔离 |
| `samples_timeseries.csv` | 三台设备的时间序列，一台稳定、一台缓升、一台发展成高能放电 |
| `samples_chinese_headers.csv` | 中文列名（`编号`/`氢气`/…）+ 趋势模式 |

```bash
python -m dga_service.cli --input examples/samples_batch.csv --output out/batch.csv
python -m dga_service.cli --input examples/samples_timeseries.csv --trend --output out/trend.csv
```

趋势输出的关键列：

```
T-001   cond=2  escalated=0   H2 略升但未越限，Condition 2 来自 H2=110 > 100
T-002   cond=4  escalated=1   绝对值仅 Condition 3，产气速率显著 → 升级一级
T-003   cond=1  escalated=0   稳定
```

### 一键验证

```bash
python tools/verify_all.py          # 4 道静态门禁，零依赖、无网络
python tools/verify_all.py --full   # 另跑数据集验证、状态验证与基准
```

`verify_all.py` 跑的就是 CI 的全部门禁：单测、Python 3.6 语法、第三方导入扫描、
以及**在禁用 site-packages 的子进程里导入**（这才是"零依赖"的真正检验）。

### 一个值得记下的门禁失效案例

`tools/check_py36_compat.py` 里的"自文档 f-string（`f"{x=}"`，Python 3.8+）"检测
**曾经完全失效**：它按 `tokenize.STRING` 提取 f-string，而 **Python 3.12 起
（PEP 701）f-string 被拆成 `FSTRING_START` / `FSTRING_MIDDLE` / `FSTRING_END`，
表达式部分甚至变成普通 `NAME`/`OP` token**。结果是：CI 在 3.13 上跑，报告
"0 violations"，实际一个都没查。

这类失效比误报更危险——**门禁绿灯，但它什么也没查**。现在检测改为按源码位置
切片重建整流，并配了 20 个正反用例锁住行为
（`tests/test_py36_compat.py`），包括"普通字符串里提到这个语法不能被误报"——
因为原版检查器**把自己的提示文本当成了违规**。

同一个文件里还修了一处：跨 Windows 盘符时 `os.path.relpath` 会抛
`ValueError`，让"检查某个目录"直接崩溃。

---

## 方法对比结果

在 589 + 202 条真实公开样本上（数据集的公开标注作为真值）：

| 数据集 | 方法 | 有效判定率 | 判定样本准确率 | 全样本准确率 | 宏 F1 |
|---|---|---|---|---|---|
| alan456 (589) | IEC 三比值（编码） | 68.1% | **76.3%** | 52.0% | 0.746 |
| alan456 (589) | IEC 60599 直接比值 | 64.0% | 72.9% | 46.7% | 0.725 |
| alan456 (589) | Rogers | 50.1% | 75.6% | 37.9% | 0.627 |
| alan456 (589) | Duval Triangle 1 | **100%** | 62.8% | 62.8% | 0.613 |
| cliango (202) | IEC 三比值（编码） | 83.2% | 64.3% | 53.5% | 0.660 |
| cliango (202) | Duval Triangle 1 | **100%** | **34.7%** | 34.7% | 0.315 |

**必须同时报"有效判定率"和"准确率"。** 只报一个是最常见的误导方式：

- **Duval 不设"正常"区**，任何输入都会被塞进某个故障区。在含 34 条正常样本的
  cliango 上，它的 100% 判定率变成了负债而非优势（准确率从 62.8% 掉到 34.7%）。
  剔除正常样本后回升到 41.7%，仍然最差。
- **Rogers 只敢判一半样本**，但判出来的最准。
- **IEC 三比值（编码版）在"判得多"和"判得准"之间平衡最好**。

完整结果（含逐类召回、混淆矩阵、正常类对照）见
[`experiments/results/REPORT.md`](experiments/results/REPORT.md)。

---

## 状态监测结果：它才是该先看的那个指标

同一个问题换个问法，结论完全反转。把 C57.104 的 "Condition ≥ 2 即报警" 当作
二分类器，去区分"正常"和"故障"：

| 数据集 | 样本 | 故障召回率 | 特异度 | 误报率 | 准确率 |
|---|---|---|---|---|---|
| alan456 (589，无正常类) | 589 | 95.8% | n/a | n/a | 95.8% |
| cliango (202，含 34 条正常) | 202 | 95.2% | **88.2%** | 11.8% | **94.1%** |

对比同一批 cliango 样本上 Duval Triangle 的 **34.7%** —— **阈值分级在"要不要报警"
这件事上比比值法准确得多。**

把这个对比再推一层：直接在 34 台标注正常机组上，量各方法"把健康设备判成故障"的比例。
这个数字在比值法的文献里几乎从不出现，而逐类召回率是看不出来的：

| 方法 | 34 台正常机组中被判成故障 | 误报率 |
|---|---|---|
| Duval Triangle 1 | 34 | **100.0%** |
| IEC 三比值（编码） | 11 | 32.4% |
| Rogers 比值 | 10 | 29.4% |
| IEC 60599 直接比值 | 4 | 11.8% |
| **C57.104 状态分级** | 4 | **11.8%** |

Duval 三角形根本没有"正常"区，所以它**必然**对每一台健康变压器报警。这就是
"先用绝对浓度分级做闸门、再用比值法定性"最直接的证据。

而且"正常"类与故障类是干净分开的：

| 真实类别 | 样本 | 平均 Condition |
|---|---|---|
| Normal | 34 | **1.21** |
| T1 | 30 | 2.60 |
| PD | 27 | 2.63 |
| D1 | 35 | 2.89 |
| D2 | 45 | 3.44 |
| T3 | 31 | 3.52 |

**工程含义**：在线监测应该先用绝对浓度分级做"报警闸门"，再用比值法/三角法做
"故障定性"。反过来做会得到大量无效判定。完整数据见
[`experiments/results/CONDITION_REPORT.md`](experiments/results/CONDITION_REPORT.md)，
图见 `dga_viz/figures/condition_by_label.png`。

---

## 仓库结构

```
dga_core/            零依赖诊断内核 ← 只有这个包上板
  tables.py            所有阈值表（含出处注释）
  methods.py           比值计算 + 五个诊断方法
  condition.py         IEEE C57.104 状态监测（分级 / 产气速率 / 采样建议）
  models.py            纯数据容器（NamedTuple，兼容 Python 3.6）
  validation.py        输入校验、哨兵零值检测
dga_service/         批量管线、CSV/JSONL 读写、CLI、时间序列趋势 ← 也上板
dga_viz/             可视化（matplotlib，仅宿主机）
deployment/jetson-nano/   setup.sh、systemd unit、spool 监听、tegrastats 采集
experiments/         数据集加载、方法验证、状态验证、基准测试、可行性 spike（仅宿主机）
examples/            合成示例 CSV（批量 / 时间序列 / 中文列名）
tools/               Python 3.6 兼容性检查、一键验证门禁
tests/              87 个单测（内核 + 管线 + CLI），零依赖
docs/                STANDARDS.md、DEPLOY_JETSON_NANO.md
```

---

## 数据集（不随仓库分发）

**所有上游数据集仓库都没有开源许可证**，所以本仓库不包含任何原始数据——那会
构成侵权。改用按需下载 + SHA-256 校验：

```bash
python scripts/fetch_datasets.py
```

清单与指纹见 [`data/manifest.json`](data/manifest.json)。仅用于非商业研究与教学，
请引用原始来源而非本仓库。

---

## 部署到 Jetson Nano

```bash
cd deployment/jetson-nano && sudo ./setup.sh
```

脚本会检查平台、扩 4 GB swap、切 10 W 模式、只装系统包、以 `--no-deps` 安装
本项目。详见 [`docs/DEPLOY_JETSON_NANO.md`](docs/DEPLOY_JETSON_NANO.md)。

**本项目只交付适配，不做真实上板部署。** 由于 CI 里没有开发板，
`tools/check_py36_compat.py`（语法检查）和
`tests/test_dga_core.py::TestZeroDependency`（依赖检查）共同替代了真机验证。

---

## 限制（诚实清单）

- **阈值表版本**：实现的是 2015 年前后的表。IEC 60599:2022 更新过典型气体浓度、
  比值边界与故障识别表，**尚未逐条核对**。见 `docs/STANDARDS.md` 的 Open items。
- **编码表分歧未强行消歧**：编码组合 (2,0,1) / (2,0,2) 在文献中表述矛盾，本实现
  返回 `ND` 而非猜测，这会压低编码版的有效判定率。
- **标签是真值但不是"标准答案"**：数据集标签来自其公开标注，不是独立物理检查。
- **`中低温过热` 映射有损**：cliango 数据集把两个 IEC 过热等级合并了，映射到 T1。
- **未做测量不确定度**：IEC 60599 附录讨论了测量误差在比值边界上的传播，本项目
  和现有开源工具一样没有实现。
- **未验证于真实变压器**：全部结果来自基准数据集，现场部署前需要实际验证。
- **C57.104 的典型浓度表未实现**：90th/95th 百分位"典型浓度"表在不同二手来源里
  数值不一致，因此没有实现，而不是挑一个写进去。见 `docs/STANDARDS.md` §7.5。
- **状态监测的分级阈值来自二手转抄**：Table 1 有两个独立来源逐位一致，但
  Table 4（产气速率）与 Table 5（采样间隔）只有单一来源，尚未对标准原文核对。
- **数据集无时间序列**：公开数据集是静态快照，所以产气速率（Table 3/4）**没有
  在真实数据上验证过**，只有单元测试覆盖。这部分是本项目最大的未验证面。

---

## 许可证

MIT，见 [`LICENSE`](LICENSE)。第三方归因见 [`NOTICE`](NOTICE)（含
`ToniMellin/dga-diagtool` 的 MIT 声明与阈值表出处）。

---

## English summary

A **zero-dependency** DGA diagnosis and condition-monitoring kernel for embedded
transformer monitoring. Implements the classic IEC three-ratio coded method, the
IEC 60599 (2015) ratio-band method, the Rogers ratio method (IEEE C57.104-2019),
Doernenburg and Duval Triangle 1, plus IEEE C57.104-2019 Condition 1-4 grading,
gas generation rate and sampling-interval advice — using nothing outside the
Python standard library, so it runs on a Jetson Nano (JetPack 4.6.4, Python 3.6,
aarch64) where pandas and matplotlib have no usable wheels.

Measured on x86: ~60 KB of deployable source, 0 dependencies, P50 11.8 µs per
sample across all four methods plus the condition assessment, ~87,000 samples/s
throughput, and effectively no heap retained per diagnosis. Validated on 791 real
public samples across two datasets.

Two results are worth carrying forward:

1. **Decision rate and accuracy must always be reported together.** Duval
   Triangle has no "normal" zone, so it is forced to misclassify every healthy
   unit; on the one dataset containing Normal samples its 100% decision rate
   drops its accuracy to 34.7% (from 62.8% elsewhere).
2. **Threshold grading beats ratio methods at the question that matters first.**
   Scoring C57.104 "Condition >= 2" as a binary alarm separates healthy from
   faulted units at 94.1% accuracy with an 11.8% false-alarm rate — against
   34.7% for Duval on the same samples. Use absolute grading as the alarm gate,
   ratio methods for fault identification.
3. **Measured on the 34 labelled healthy units**, the false-alarm rate is Duval
   100%, IEC coded three-ratio 32.4%, Rogers 29.4%, IEC 60599 ratio-band 11.8%,
   C57.104 grading 11.8%. Duval has no normal zone, so it must alarm on every
   healthy transformer — a number per-class recall cannot reveal.

Dataset provenance, threshold-table citations and documented divergences between
published sources are in `docs/STANDARDS.md`. Deploying on a Jetson Nano is
covered in `docs/DEPLOY_JETSON_NANO.md`.

MIT licensed. Third-party attributions in `NOTICE`.
