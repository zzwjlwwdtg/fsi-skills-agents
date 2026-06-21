# 项目历史总结 — `f:\fsi-skills\agents` 多策略量化信号系统

> 由 2026-05-09 → 2026-05-29 跨多次 Claude Code 会话整理而成。来源：
> `c4097393-…ed54.jsonl` + `c85f6a3d-…e185d6.jsonl`（已去重，共 1904 条独立事件）。

---

## 1. 项目目标（一句话）

为 **TQQQ / SOXL / GLD** 三只 ETF 构建一个**多 agent 的日 K 信号系统**：
盘前/盘中/盘后定时跑（默认 15min），输出技术形态共振 + 规则进化策略 + 重大事件日历 + Claude 早盘策略文本，**不需要付费 API key**，可选 rule-engine fallback。

延伸目标（5-29 之后）：用 **PCA / CAPM 残差因子**对 SOX 半导体 30+ 只成分股做因子分解，识别 regime 后再喂给决策矩阵。

---

## 2. 当前文件结构

```
f:\fsi-skills\agents\
├─ run.bat / run_ja.bat / setup.bat   # 启动脚本（中文版 / 日语版）
├─ orchestrator.py                    # 主调度，15min 循环
├─ market_watch.py / nightwatch.py    # 盘中 / 夜盘+盘前 监控
├─ futures_watch.py                   # NQ/ES/GC/CL 期货监控
├─ events_watch.py                    # 重大事件日历（CPI/NFP/Earnings…）
├─ data_feeds.py / fred_feeds.py      # yfinance + FRED 数据源
├─ moomoo_pool.py                     # moomoo OpenD 行情池（实时交易）
├─ strategy_engine.py                 # 技术形态 → 规则胜率
├─ strategy_evolver.py                # 进化型规则库
├─ confluence.py                      # 多指标共振打分
├─ pca_sox.py                         # SOX 半导体 PCA 因子（最后阶段）
├─ decision_agent.py                  # 综合决策
├─ ai_prompt.py                       # 调用 Claude CLI（无 API key）做早盘策略
├─ report_generator.py / daily_review.py / notifier.py / i18n.py
├─ config.py
├─ signals/   # 各标的最新信号 + 每日 ai_analysis_morning_*.md
└─ logs/      # run_YYYYMMDD.log（最新 5-29）
```

---

## 3. 关键设计决策

| 决策 | 原因 |
|---|---|
| **不订 Claude/OpenAI API**，用 `ai_prompt.py` 调本地 Claude CLI（参考 `F:\trump-code`） | 用户只订阅了对话服务（Pro），API key 单收费 |
| 默认 fallback 到 **rule engine** | 同上，保证无 key 也能跑 |
| 技术指标分**三档**（量比/RSI/CCI 都离散化为 弱/正常/强 等） | 用户原话："任意数字都能比较的话系统就太复杂了" |
| 指标集：MA 上下穿、CCI、RSI（含上下穿）、BOLL、PSAR、量比，所有都要"多指标共振" | 像 moomoo 一样共振越多 = 信号越强 |
| **日 K 为主**，15min/小时 K 仅辅助 | 用户是日 K 交易者，不追高频 |
| 偏好**强趋势 + 追高**（半导体行情风格），上涨趋势权重调大 | 用户明确表态 |
| 数据源：`yfinance`（历史/回测足够）+ `moomoo OpenD`（实时交易）+ `FRED`（key=`53c148069b65666d50206a8876c19a7c`） | OpenD 用于回测被认为浪费 |
| 报告语言双轨：默认中文，`run_ja.bat` 输出日语（要给日本人看），思考层用英语 | — |
| PowerShell 输出用**颜色**区分等级，**不要 markdown 符号**（`**` 这种） | cmd 窗口里看不清 |
| 进化策略**不会因为反复启动而被强化**（已校验） | 用户提过这个担忧 |
| 日历事件源接入多个验证（防止 FRED 单源延迟把已发布的 CPI 显示成"待发布"） | 5-13 出过 CPI 已落地但显示未落地的 bug |

---

## 4. 用户表达过的偏好（用于后续对话）

- **节奏**：日 K 为主，15min/小时仅辅助判断。不追高频。
- **风格**：偏好上涨趋势、强者恒强、追高（半导体那波是范例）。
- **打分**：10 分制目前感觉偏低（置信度上不去 5 分），怀疑不科学，待调。
- **指标解释要详细**：不能只写"正常量"，要说明阈值（多少到多少算中性）、均线是哪条均线。
- **输出**：CMD 友好（颜色 > 符号）；同一日历不要输出两次。
- **多语言**：中文是主，日语版独立 bat，互不影响。
- **API**：能不花钱就不花钱，优先 CLI 调用本地 Claude。
- **K 线时间戳**严格：盘前/夜盘/盘后**不要混淆**前一天和当天（5-13 出过这个错）。
- **所有建议必须基于"当前最新可得 K 线"**：盘前时刻就用盘前 K，没数据就说没数据，不要硬编。

---

## 5. 已知 / 半成品的事

**新增（6-04）** Portfolio-level target exposure 重构（用户 6-04 提出）：
- 当前所有决策都是 **ticker-local**：每个 ticker 独立评估"该不该 BUY/SELL"，没有 portfolio 整体视角
- 暴露的具体问题：
  1. **反向对称盲区**：TQQQ CAUTION (NFP 在即) 但 SQQQ 可能同时被推 WATCH_BUY (RSI 低)——逻辑矛盾
  2. **杠杆叠加**：MU + MULL 同时持有 = 3x 集中暴露（已用 LEVERAGED_PAIRS 临时打补丁）
  3. **底层重复**：核心 TQQQ/SOXL 已经含 NVDA/AVGO 等，如果再单选 NVDA = 7x NVDA 集中
  4. **regime 不反馈到 portfolio**：regime=crisis 时阈值收紧，但仓位上限 8 / 单笔 10% 没变
- 临时补丁（6-04 做了）：`INVERSE_PAIRS` 防对冲 + `MARKET_UNCERTAIN` (event≥2 + conf<8 → BUY 降级 HOLD)
- 真正解法（下次重构）：
  1. 先算 board regime（已有）
  2. 再算 **portfolio target exposure**：根据 regime/事件/可用资金算出"今天目标 net exposure"
  3. 然后**为达成 target exposure 派单**——而不是每个 ticker 独立判断
  4. 单只 BUY/SELL 受 portfolio 余量约束（剩多少可用空间）
- 配套修复：5 种 regime 各跑一次 evolver，存 5 套规则，今天用对应那套（解决 regime↔进化冲突）

**新增（6-03）** Regime ↔ 进化系统结构性冲突：
- `strategy_evolver` 在 2 年历史数据上**不分 regime** 一锅炖训练规则
- 一条 "RSI 超买+缩量 → WATCH_BUY @ wr=100%" 可能从牛市学来，但 crisis regime 用就是反指标
- `quant_signal` 给的分也不看当前 regime 加权
- `decision_agent._RT` 按 regime 调阈值，但 evolver 输出与之打架
- **根治方案**（下次重构）：进化时把 `regime` 作为 atomic condition，规则长成 `regime=bull_trending AND rsi_zone=neutral...`；或按 5 种 regime 各跑一次 evolver 存 5 套规则



1. **PCA 因子**（`pca_sox.py`）：刚做完 SOX 30+ 只成分股的协方差矩阵 + 特征值谱，识别出市场因子 / 动量因子。最后的讨论卡在"低残差 vs 高残差"的悖论（CAPM 套利 vs 动量恒强），用户希望进一步用回归拆收益来源 + t 检验 + 时间序列模型评估波动。VIX 是否作为因子之一，**待定**。
2. **regime 警告**：用户最后建议——不要直接覆盖信号，而是先识别当前 regime（趋势/均值回归/高波动），再以此为前提给决策。**未落地**。
3. **置信度 10 分制**：用户怀疑不科学，**待重新设计**。
4. **run.bat 看不到分析内容**：5-29 用户最后一个问题就是"我运行 run.bat 怎么看不到这些分析内容"，**未确认是否修复**。
5. **盘前/盘后/夜盘数据**：moomoo OpenD 拉夜盘期货数据曾报"不可用"，是否最终走通**待核**。
6. **复盘自动化**：用户希望复盘时调用 moomoo AI 或本地 Claude CLI 帮忙总结（不走付费 API），参考 `F:\trump-code` 的 CLI 调用方式。**部分实现于 `ai_prompt.py` / `daily_review.py`**。

---

## 6. 重要外部依赖

- **moomoo OpenD**：已登录，需要本地启动才能拉实时行情。skill `install-moomoo-opend` 已用过。
- **FRED API key**：`53c148069b65666d50206a8876c19a7c`（已写入代码/配置）
- **Claude CLI**：用 `ai_prompt.py` 通过 stdio 调用，参考 `F:\trump-code` 仓库做法。
- **Python 3.12**，主要库：yfinance、moomoo-api（futu-api）、pandas、numpy、scikit-learn（PCA）。

---

## 7. 时间线（关键转折）

| 日期 | 里程碑 |
|---|---|
| 5-09 | 起步：分析 SOXL/TQQQ 估值 → 决定做多 agent 系统 → 安装 moomoo OpenD |
| 5-11 | 确定不用付费 API，改 rule engine + 云端 Schedule。接 FRED 拿宏观。 |
| 5-12 | 加入回测、进化策略库、CCI/PSAR/量比离散三档。调成日 K 频率。 |
| 5-13 | 加重大事件日历（CPI/NFP/Earnings），修 CPI"未落地"显示 bug。开始用 `ai_prompt.py` 调本地 Claude CLI 出早盘策略文本。 |
| 5-14 | 置信度问题浮现（一直上不去 5）。 |
| 5-18~19 | yfinance 数据源确定够用。颜色输出替代 markdown。修正盘前/盘后/夜盘时间戳混淆。 |
| 5-20 | 加日语版 `run_ja.bat`。 |
| 5-29 | 跳到因子建模阶段：SOX 半导体 PCA 协方差谱 → 市场因子 / 动量因子 → CAPM 残差讨论 → VIX 是否入因子 → regime 警告思路。**会话在"run.bat 看不到分析内容"处中断**。 |

---

## 8. 推荐给新对话的开场

> 我有一个本地多 agent 量化系统在 `f:\fsi-skills\agents`，覆盖 TQQQ / SOXL / GLD 三只 ETF，日 K 为主、15min 辅助，不用付费 API（rule engine + 本地 Claude CLI）。完整背景见 `f:\fsi-skills\extracted_sessions\PROJECT_CONTEXT.md`。当前最优先要解决的三件事：
>
> 1. `run.bat` 跑起来看不到分析内容（5-29 之后没确认是否修好）
> 2. 置信度 10 分制不科学（始终上不去 5）需要重新设计
> 3. PCA 因子已能跑出市场/动量因子，下一步要做 regime 识别 → 决策矩阵前置过滤；VIX 是否入因子待定

