"""
StrategyEvolver — 暴力穷举 + 遗传进化，自动发现有效规则。
参考 trump-code/analysis_11_brute_force.py + rule_evolver.py

流程:
  Phase 1  穷举搜索  — 枚举 1-3 条件组合 (~2.6万条候选规则)
  Phase 2  双通过筛选 — train/test 分割，两段胜率均达标才存活
  Phase 3  遗传进化  — 交叉(Crossover) + 变异(Mutation) + 蒸馏(Distill)
  Phase 4  写出结果  — evolved_rules_TICKER.json + 更新内存规则库

入口:
  run_evolver(ticker, df, is_gold=False)  → (survivors, report_str)
  load_evolved_rules(ticker)              → 存活规则列表（供 strategy_engine 调用）
"""

import json
import random
import hashlib
import itertools
from datetime import datetime
from pathlib import Path

import pandas as pd
import numpy as np

from config import SIGNALS_DIR
from i18n import t

# ── 特征空间 ─────────────────────────────────────────────────────────────────
# 使用语义区间而非任意阈值，每个指标分 3 个有意义的档位：
#
#   RSI 区间  (标准技术分析分界 35/70)
#     oversold   RSI < 35    超卖区，潜在反弹
#     neutral    35-70       中性区，无强信号
#     overbought RSI > 70    超买区，潜在回调
#
#   vol_ratio 区间  (以 1.0 对称，0.8/1.25 为边界)
#     shrink     < 0.80      缩量，趋势疲软
#     normal     0.80-1.25   正常成交
#     expand     > 1.25      放量，趋势确认或恐慌
#
#   CCI 区间  (行业标准 ±100 分界)
#     oversold   CCI < -100  超卖，价格大幅低于均值
#     neutral    -100 to 100 中性
#     overbought CCI > +100  超买，价格大幅高于均值

ATOMIC_CONDITIONS = [
    ("rsi_zone",  "=", "oversold"),
    ("rsi_zone",  "=", "neutral"),
    ("rsi_zone",  "=", "overbought"),
    ("vol_zone",  "=", "shrink"),
    ("vol_zone",  "=", "normal"),
    ("vol_zone",  "=", "expand"),
    ("cci_zone",  "=", "oversold"),
    ("cci_zone",  "=", "neutral"),
    ("cci_zone",  "=", "overbought"),
    ("trend",     "=", "up"),
    ("trend",     "=", "down"),
    ("ma_stack",  "=", "bull"),
    ("ma_stack",  "=", "bear"),
    ("is_new_52w_high", "=", True),
    # 穿越信号：发生在单根 K 线上的方向转换
    ("ma_cross",  "=", "golden"),    # MA5 上穿 MA20（金叉）
    ("ma_cross",  "=", "death"),     # MA5 下穿 MA20（死叉）
    ("rsi_cross", "=", "up_70"),     # RSI 上穿 70（进入超买）
    ("rsi_cross", "=", "dn_30"),     # RSI 下穿 30（进入超卖）
    ("cci_cross", "=", "up_100"),    # CCI 上穿 +100（进入超买区）
    ("cci_cross", "=", "dn_100"),    # CCI 下穿 -100（进入超卖区）
    # Bollinger Bands (20, 2σ)
    ("bb_zone",   "=", "above"),     # 价格突破布林上轨（极度拉伸，均值回归风险）
    ("bb_zone",   "=", "normal"),    # 价格在布林带内（中性）
    ("bb_zone",   "=", "below"),     # 价格跌破布林下轨（极度超卖，弹性区）
    # Parabolic SAR (AF=0.02/0.20)
    ("psar_signal", "=", "bear_flip"),  # SAR 刚从下方翻到上方（趋势反转转空）
    ("psar_signal", "=", "bull_flip"),  # SAR 刚从上方翻到下方（趋势反转转多）
    # NOTE: MACD/ADX 不放进 evolver — 300d 回测验证过拟合,
    # 加入后规则数翻倍但 alpha 大幅恶化。MACD/ADX 仍在 confluence + tech_bull/bear 评分里
]                                           # 总计 27 个语义条件

HOLD_PERIODS = [2, 3, 5, 7, 10]
ACTIONS      = ["WATCH_BUY", "REDUCE"]

# 筛选阈值（参考 trump-code learning_engine）
MIN_TRAIN_N  = 5
MIN_TEST_N   = 2
MIN_TRAIN_WR = 55.0
MIN_TEST_WR  = 50.0

# 遗传参数
CROSSOVER_TRIES = 150
MUTATION_TRIES  = 150
TOP_K           = 30   # 参与进化的存活规则数


# ── 工具函数 ─────────────────────────────────────────────────────────────────

def _rule_id(conditions: list, action: str, hold: int) -> str:
    key = str(sorted(conditions)) + action + str(hold)
    return "E" + hashlib.md5(key.encode()).hexdigest()[:8]


_ZONE_ZH = {
    ("rsi_zone",  "oversold"):   "RSI超卖",
    ("rsi_zone",  "neutral"):    "RSI中性",
    ("rsi_zone",  "overbought"): "RSI超买",
    ("vol_zone",  "shrink"):     "缩量",
    ("vol_zone",  "normal"):     "正常量",
    ("vol_zone",  "expand"):     "放量",
    ("cci_zone",  "oversold"):   "CCI超卖",
    ("cci_zone",  "neutral"):    "CCI中性",
    ("cci_zone",  "overbought"): "CCI超买",
    ("trend",     "up"):         "上升趋势",
    ("trend",     "down"):       "下降趋势",
    ("ma_stack",  "bull"):       "均线多排",
    ("ma_stack",  "bear"):       "均线空排",
    ("is_new_52w_high", True):   "52周新高",
    ("ma_cross",  "golden"):     "均线金叉",
    ("ma_cross",  "death"):      "均线死叉",
    ("rsi_cross", "up_70"):      "RSI上穿70",
    ("rsi_cross", "dn_30"):      "RSI下穿30",
    ("cci_cross", "up_100"):       "CCI上穿100",
    ("cci_cross", "dn_100"):       "CCI下穿-100",
    ("bb_zone",   "above"):        "布林上轨突破",
    ("bb_zone",   "normal"):       "布林带内",
    ("bb_zone",   "below"):        "布林下轨跌破",
    ("psar_signal", "bear_flip"):  "SAR转空",
    ("psar_signal", "bull_flip"):  "SAR转多",
}


def _rule_name(conditions: list) -> str:
    return "+".join(_ZONE_ZH.get((f, v), f"{f}={v}") for f, _, v in conditions)


def _is_valid(conditions: list) -> bool:
    """过滤同字段冲突和趋势/均线反向组合。"""
    seen: dict[str, str] = {}
    for f, _, v in conditions:
        if f in seen:
            if seen[f] != v:
                return False   # 同字段不同值 = 矛盾
        else:
            seen[f] = v
    # 趋势与均线方向一致性
    tr = seen.get("trend"); ma = seen.get("ma_stack")
    if tr == "up"   and ma == "bear": return False
    if tr == "down" and ma == "bull": return False
    return True


# ── 向量化回测核心 ────────────────────────────────────────────────────────────

def _prepare_df(df: pd.DataFrame) -> pd.DataFrame:
    """预计算所有原子条件信号列 + 各持仓周期的未来收益列。"""
    df = df.copy()
    # 原子条件列
    for f, op, v in ATOMIC_CONDITIONS:
        col = f"{f}_{op}_{v}"
        if   op == ">": df[col] = df[f] > v
        elif op == "<": df[col] = df[f] < v
        elif op == "=": df[col] = df[f] == v
    # 未来收益列（避免 shift 引发越界取值）
    for h in HOLD_PERIODS:
        df[f"fwd_{h}"] = df["close"].shift(-h) / df["close"] - 1
    return df


def _backtest_vec(trigger: pd.Series, fwd_ret: pd.Series,
                  is_bull: bool, split_i: int) -> tuple[dict, dict]:
    """向量化 train/test 回测，返回 (train_stats, test_stats)。"""
    mask = trigger & fwd_ret.notna()
    tr_mask = mask.iloc[:split_i]
    te_mask = mask.iloc[split_i:]
    tr_ret  = fwd_ret.iloc[:split_i][tr_mask]
    te_ret  = fwd_ret.iloc[split_i:][te_mask]

    def _s(rets):
        n = len(rets)
        if n == 0:
            return {"n": 0, "wr": 0.0, "avg": 0.0}
        wins = int((rets > 0).sum()) if is_bull else int((rets < 0).sum())
        return {"n": n, "wr": round(wins / n * 100, 1),
                "avg": round(float(rets.mean()) * 100, 2)}

    return _s(tr_ret), _s(te_ret)


def _eval_rule(conditions: list, action: str, hold: int,
               df_prep: pd.DataFrame, split_i: int) -> dict | None:
    """评估单条规则，不达标返回 None。"""
    # 构建触发 mask（AND 所有条件列）
    mask = pd.Series(True, index=df_prep.index)
    for f, op, v in conditions:
        col = f"{f}_{op}_{v}"
        if col not in df_prep.columns:
            return None
        mask = mask & df_prep[col]

    is_bull = action in ("WATCH_BUY", "BUY")
    tr, te  = _backtest_vec(mask, df_prep[f"fwd_{hold}"], is_bull, split_i)

    # REDUCE 规则放宽阈值：训练集多为牛市，下跌样本稀少，
    # 强行 50% 测试胜率门槛会把所有减仓信号过滤掉
    min_train_wr = MIN_TRAIN_WR if is_bull else 50.0
    min_test_wr  = MIN_TEST_WR  if is_bull else 45.0

    # 双通过筛选
    if tr["n"] < MIN_TRAIN_N:  return None
    if te["n"] < MIN_TEST_N:   return None
    if tr["wr"] < min_train_wr: return None
    if te["wr"] < min_test_wr:  return None

    combined = round(tr["wr"] * 0.4 + te["wr"] * 0.6, 1)
    return {
        "id":         _rule_id(conditions, action, hold),
        "name":       _rule_name(conditions),
        "conditions": list(conditions),
        "action":     action,
        "hold":       hold,
        "train_n":    tr["n"],
        "train_wr":   tr["wr"],
        "train_avg":  tr["avg"],
        "test_n":     te["n"],
        "test_wr":    te["wr"],
        "test_avg":   te["avg"],
        "combined":   combined,
        "source":     "brute_force",
        "weight":     1.0,
    }


# ── Phase 1 + 2: 穷举搜索 ─────────────────────────────────────────────────────

def brute_force_search(df_prep: pd.DataFrame, split_i: int,
                       max_cond: int = 3) -> list[dict]:
    """枚举 1~max_cond 条件组合，返回通过双通过筛选的存活规则。"""
    survivors = {}  # id → rule

    total_checked = 0
    for n_cond in range(1, max_cond + 1):
        for conds in itertools.combinations(ATOMIC_CONDITIONS, n_cond):
            conds = list(conds)
            if not _is_valid(conds):
                continue
            for action in ACTIONS:
                for hold in HOLD_PERIODS:
                    total_checked += 1
                    r = _eval_rule(conds, action, hold, df_prep, split_i)
                    if r and r["id"] not in survivors:
                        survivors[r["id"]] = r

    return sorted(survivors.values(), key=lambda x: x["combined"], reverse=True), total_checked


# ── Phase 3: 遗传进化 ─────────────────────────────────────────────────────────

def _crossover(ruleA: dict, ruleB: dict, df_prep: pd.DataFrame,
               split_i: int, survivors: dict) -> int:
    """交叉：合并两条规则的条件，测试新组合。返回新增存活数。"""
    added = 0
    cA = ruleA["conditions"]
    cB = ruleB["conditions"]
    # 合并去重后取长度 2-4 的子集
    merged = list({str(c): c for c in cA + cB}.values())
    if len(merged) < 2 or len(merged) > 5:
        return 0
    for size in range(2, min(len(merged) + 1, 4)):
        for comb in itertools.combinations(merged, size):
            comb = list(comb)
            if not _is_valid(comb):
                continue
            for action in [ruleA["action"], ruleB["action"]]:
                for hold in [ruleA["hold"], ruleB["hold"]]:
                    r = _eval_rule(comb, action, hold, df_prep, split_i)
                    if r and r["id"] not in survivors:
                        survivors[r["id"]] = r
                        added += 1
    return added


_ZONE_NEIGHBORS: dict[tuple, list] = {
    ("rsi_zone",  "oversold"):   [("rsi_zone",  "neutral")],
    ("rsi_zone",  "neutral"):    [("rsi_zone",  "oversold"), ("rsi_zone",  "overbought")],
    ("rsi_zone",  "overbought"): [("rsi_zone",  "neutral")],
    ("vol_zone",  "shrink"):     [("vol_zone",  "normal")],
    ("vol_zone",  "normal"):     [("vol_zone",  "shrink"),   ("vol_zone",  "expand")],
    ("vol_zone",  "expand"):     [("vol_zone",  "normal")],
    ("cci_zone",  "oversold"):   [("cci_zone",  "neutral")],
    ("cci_zone",  "neutral"):    [("cci_zone",  "oversold"), ("cci_zone",  "overbought")],
    ("cci_zone",  "overbought"): [("cci_zone",  "neutral")],
}


def _mutate(rule: dict, df_prep: pd.DataFrame,
            split_i: int, survivors: dict) -> int:
    """变异：将一个区间条件替换为相邻区间。"""
    added = 0
    conds = rule["conditions"]
    for i, (f, op, v) in enumerate(conds):
        for nf, nv in _ZONE_NEIGHBORS.get((f, v), []):
            new_conds = conds[:i] + [(nf, op, nv)] + conds[i+1:]
            if not _is_valid(new_conds):
                continue
            r = _eval_rule(new_conds, rule["action"], rule["hold"], df_prep, split_i)
            if r and r["id"] not in survivors:
                r["source"] = "mutation"
                survivors[r["id"]] = r
                added += 1
    return added


def _distill(top_rules: list, df_prep: pd.DataFrame,
             split_i: int, survivors: dict) -> int:
    """蒸馏：找最常见的条件对，组成新规则。"""
    from collections import Counter
    added = 0
    cond_count: Counter = Counter()
    for r in top_rules:
        for c in r["conditions"]:
            cond_count[str(c)] += 1

    # top 8 高频条件两两组合
    top_conds = [eval(k) for k, _ in cond_count.most_common(8)]
    for c1, c2 in itertools.combinations(top_conds, 2):
        comb = [c1, c2]
        if not _is_valid(comb):
            continue
        for action in ACTIONS:
            for hold in HOLD_PERIODS:
                r = _eval_rule(comb, action, hold, df_prep, split_i)
                if r and r["id"] not in survivors:
                    survivors[r["id"]] = r
                    r["source"] = "distill"
                    added += 1
    return added


def genetic_evolve(survivors_list: list, df_prep: pd.DataFrame,
                   split_i: int) -> tuple[list, dict]:
    """遗传进化：交叉 + 变异 + 蒸馏，返回更新后的规则列表 + 进化摘要。"""
    survivors = {r["id"]: r for r in survivors_list}
    top = sorted(survivors.values(), key=lambda x: x["combined"], reverse=True)[:TOP_K]

    cx_added = 0
    pairs_tried = 0
    shuffled = top[:]
    random.shuffle(shuffled)
    for rA, rB in itertools.combinations(shuffled[:20], 2):
        if pairs_tried >= CROSSOVER_TRIES:
            break
        cx_added += _crossover(rA, rB, df_prep, split_i, survivors)
        pairs_tried += 1

    mu_added = 0
    for rule in top[:MUTATION_TRIES]:
        mu_added += _mutate(rule, df_prep, split_i, survivors)

    di_added = _distill(top[:15], df_prep, split_i, survivors)

    result = sorted(survivors.values(), key=lambda x: x["combined"], reverse=True)
    summary = {
        "crossover_added": cx_added,
        "mutation_added":  mu_added,
        "distill_added":   di_added,
        "total_survivors": len(result),
    }
    for r in result:
        if r.get("source") in ("mutation", "distill", None):
            r.setdefault("source", "evolved")
    return result, summary


# ── 主入口 ────────────────────────────────────────────────────────────────────

def run_evolver(ticker: str, df: pd.DataFrame,
                is_gold: bool = False,
                regime_bucket: str | None = None) -> tuple[list, str]:
    """
    完整进化流程。
    df 必须已经过 strategy_engine.fetch_kline_history() 处理（含 rsi_14 等列）。
    regime_bucket: 若传入 (bull/neutral/bear), 只在那些天的样本上训练,
                   存到 evolved_rules_<ticker>_<bucket>.json
                   若不传 (None), 保持老行为, 存 evolved_rules_<ticker>.json
    返回 (survivors: list[dict], report: str)
    """
    t0 = datetime.now()

    # 按 regime bucket 过滤训练样本
    if regime_bucket:
        from regime_labeler import label_history, _fetch_spy_vix_history
        spy, vix = _fetch_spy_vix_history(days=max(len(df) + 100, 800))
        if spy is not None and vix is not None:
            labels = label_history(spy, vix)
            # df 可能用 integer index + time_key 列；统一对齐
            if "time_key" in df.columns:
                df_dates = pd.to_datetime(df["time_key"]).dt.tz_localize(None)
                df = df.copy()
                df["_date"] = df_dates
                date_to_bucket = labels.to_dict()
                df = df[df["_date"].map(lambda d: date_to_bucket.get(d) == regime_bucket)]
                df = df.drop(columns=["_date"]).reset_index(drop=True)
            else:
                common = df.index.intersection(labels.index)
                keep_idx = [d for d in common if labels.loc[d] == regime_bucket]
                df = df.loc[keep_idx]
            if len(df) < 30:
                return [], f"[evolver:{ticker}:{regime_bucket}] 样本太少 ({len(df)} 天) 跳过"

    split_i = int(len(df) * 0.8)
    df_prep = _prepare_df(df)

    raw_survivors, total_checked = brute_force_search(df_prep, split_i)

    if raw_survivors:
        final_survivors, evo_summary = genetic_evolve(raw_survivors, df_prep, split_i)
    else:
        final_survivors = []
        evo_summary = {"crossover_added": 0, "mutation_added": 0,
                       "distill_added": 0, "total_survivors": 0}

    elapsed = (datetime.now() - t0).total_seconds()

    # 保存存活规则
    suffix = f"_{regime_bucket}" if regime_bucket else ""
    out_path = Path(SIGNALS_DIR) / f"evolved_rules_{ticker.replace('.', '-')}{suffix}.json"
    out_path.write_text(
        json.dumps({
            "ts":       datetime.now().isoformat(),
            "ticker":   ticker,
            "regime_bucket": regime_bucket,
            "n_train_samples": len(df),
            "total_checked": total_checked,
            "survivors": final_survivors,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    report = _format_report(ticker, total_checked, raw_survivors,
                            final_survivors, evo_summary, elapsed)
    return final_survivors, report


def _format_report(ticker: str, total_checked: int, raw: list,
                   final: list, evo: dict, elapsed: float) -> str:
    W    = 68
    LINE = "-" * W
    name = ticker.split(".")[-1]
    ts   = datetime.now().strftime('%Y-%m-%d %H:%M')
    title = t(f"{name} 规则进化报告", f"{name} ルール進化レポート")
    lines = [
        "+" + "=" * (W - 2) + "+",
        "|  " + f"{title}  |  {ts}".ljust(W - 4) + "|",
        "+" + "=" * (W - 2) + "+",
        "",
        t(f"  穷举候选规则 : {total_checked:,}",
          f"  網羅候補ルール : {total_checked:,}"),
        t(f"  暴力搜索存活 : {len(raw)}  (train≥{MIN_TRAIN_WR}% & test≥{MIN_TEST_WR}%)",
          f"  網羅探索生存   : {len(raw)}  (訓練≥{MIN_TRAIN_WR}% & テスト≥{MIN_TEST_WR}%)"),
        t(f"  遗传进化新增 : 交叉+{evo['crossover_added']}  变异+{evo['mutation_added']}  蒸馏+{evo['distill_added']}",
          f"  遺伝進化追加 : 交叉+{evo['crossover_added']}  変異+{evo['mutation_added']}  蒸留+{evo['distill_added']}"),
        t(f"  最终存活规则 : {len(final)}",
          f"  最終生存ルール : {len(final)}"),
        t(f"  耗时         : {elapsed:.1f}秒",
          f"  所要時間       : {elapsed:.1f}秒"),
        "",
    ]

    if not final:
        lines.append(t("  未发现通过双通过筛选的规则（可能数据量不足）",
                       "  二重通過ルールなし（データ不足の可能性）"))
        lines.append("")
    else:
        # 列标签
        hdr_rule   = t("规则", "ルール")
        hdr_hold   = t("持仓", "保有")
        hdr_train  = t("训练", "訓練")
        hdr_test   = t("测试", "テスト")
        hdr_tr_wr  = t("训练胜率", "訓練勝率")
        hdr_te_wr  = t("测试胜率", "テスト勝率")
        hdr_avg    = t("均收益",   "平均収益")
        hdr_src    = t("来源",     "出所")

        src_map = {
            "brute_force": t("穷举", "網羅"),
            "mutation":    t("变异", "変異"),
            "distill":     t("蒸馏", "蒸留"),
            "evolved":     t("进化", "進化"),
        }

        for action in ["WATCH_BUY", "REDUCE", "BUY", "SELL"]:
            subset = [r for r in final if r["action"] == action][:6]
            if not subset:
                continue
            lines.append(f"  [{action}] Top {len(subset)}")
            lines.append(f"  {hdr_rule:<22} {hdr_hold:<5} {hdr_train:<6} {hdr_test:<6} "
                         f"{hdr_tr_wr:>8} {hdr_te_wr:>8} {hdr_avg:>7}  {hdr_src}")
            lines.append(f"  {'-'*22} {'-'*5} {'-'*6} {'-'*6} "
                         f"{'-'*8} {'-'*8} {'-'*7}  ----")
            for r in subset:
                src = src_map.get(r.get("source", ""), "?")
                lines.append(
                    f"  {r['name'][:22]:<22} {r['hold']:<5} {r['train_n']:<6} {r['test_n']:<6} "
                    f"{r['train_wr']:>7.1f}%  {r['test_wr']:>7.1f}%  {r['test_avg']:>+6.2f}%  {src}"
                )
            lines.append("")

    lines += [
        "=" * W,
        t(f"  存活规则已保存: evolved_rules_{ticker.replace('.', '-')}.json",
          f"  生存ルール保存先: evolved_rules_{ticker.replace('.', '-')}.json"),
        t(
            f"  筛选标准: 训练胜率≥{MIN_TRAIN_WR}%  测试胜率≥{MIN_TEST_WR}%  "
            f"训练样本≥{MIN_TRAIN_N}  测试样本≥{MIN_TEST_N}",
            f"  選別基準: 訓練勝率≥{MIN_TRAIN_WR}%  テスト勝率≥{MIN_TEST_WR}%  "
            f"訓練サンプル≥{MIN_TRAIN_N}  テストサンプル≥{MIN_TEST_N}",
        ),
        "=" * W,
    ]
    return "\n".join(lines)


# ── 加载存活规则（供 strategy_engine 调用）──────────────────────────────────

def _dedup_by_subset(rules: list[dict]) -> list[dict]:
    """
    规则相似度去重：如果 A 的条件是 B 的子集，且 A 的测试胜率不显著低于 B（差<3%），
    保留更简单的 A——避免冗余的"A+1条件、A+2条件、A+3条件"占满 Top 8。

    同 action 的规则之间比对；条件用 set 比较忽略顺序。
    """
    if not rules:
        return rules
    by_act: dict[str, list[dict]] = {}
    for r in rules:
        by_act.setdefault(r.get("action", "?"), []).append(r)

    kept: list[dict] = []
    for action, group in by_act.items():
        # 按条件数升序（简单的优先比较）
        group = sorted(group, key=lambda r: (len(r.get("conditions", [])), -r.get("test_wr", 0)))
        survived: list[dict] = []
        for r in group:
            cset_r = frozenset(tuple(c) for c in r.get("conditions", []))
            redundant = False
            for kr in survived:
                cset_k = frozenset(tuple(c) for c in kr.get("conditions", []))
                # kr 已通过 → 如果 kr 是 r 的子集（更简单），且胜率差<3%，则 r 冗余
                if cset_k.issubset(cset_r) and len(cset_k) < len(cset_r):
                    if kr.get("test_wr", 0) >= r.get("test_wr", 0) - 3.0:
                        redundant = True
                        break
            if not redundant:
                survived.append(r)
        kept.extend(survived)
    return kept


def load_evolved_rules(ticker: str) -> list[dict]:
    """读取上次进化结果，转换为 strategy_engine 可用的规则格式。"""
    path = Path(SIGNALS_DIR) / f"evolved_rules_{ticker.replace('.', '-')}.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        survivors = data.get("survivors", [])
        # 只返回测试胜率 >= 55% 的高质量规则；并去除冗余的扩展规则
        survivors = [r for r in survivors if r["test_wr"] >= 55.0]
        return _dedup_by_subset(survivors)
    except Exception:
        return []
