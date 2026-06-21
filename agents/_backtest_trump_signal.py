"""
Trump 信号接入回测：把我们的 trump_signal.analyze_posts 在历史日期上跑，
对比 trump-code 同日的 prediction direction + 当日实际市场方向。

Ground truth：trump-code/data/predictions_log.json 的 `correct` 字段是该 model 是否预测正确，
              `direction` 是该天的预测方向（LONG/SHORT），`actual_return` 是实际收益百分比。

回测流程：
  1. 加载 predictions_log → 取唯一 date_signal 列表
  2. 随机抽 N 天（默认 25 天）— 避开数据稀疏期
  3. 每天从 trump_posts_all.json 取那天所有推文 → analyze_posts → aggregate_direction
  4. 同日 trump-code 的 majority direction → baseline
  5. 真实方向 = actual_return 的符号
  6. 比较 hit rate: new vs baseline

判据：new hit rate ≥ baseline hit rate（按 feedback_backtest_gate.md）
"""
from __future__ import annotations
import json
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)

TRUMP_LOG = Path("F:/trump-code/data/predictions_log.json")
TRUMP_POSTS = Path("F:/trump-code/data/trump_posts_all.json")
N_SAMPLES = 25      # 随机抽样天数（控制 CLI 调用次数）
SEED = 42


def load_ground_truth() -> dict:
    """{date_signal: {'tc_direction': 'LONG/SHORT', 'actual_return': float, 'correct': bool}}"""
    data = json.loads(TRUMP_LOG.read_text(encoding="utf-8"))
    per_date: dict = defaultdict(list)
    for rec in data:
        if rec.get("status") != "VERIFIED":
            continue
        d = rec.get("date_signal")
        if not d:
            continue
        per_date[d].append(rec)
    out = {}
    for d, recs in per_date.items():
        dirs = Counter(r["direction"] for r in recs)
        # majority vote direction
        tc_dir = dirs.most_common(1)[0][0]
        # actual_return: 用第一条非空的（同一天理论上一致）
        ret = next((r.get("actual_return") for r in recs
                    if r.get("actual_return") is not None), None)
        out[d] = {
            "tc_direction": tc_dir,
            "tc_models": len(recs),
            "actual_return": ret,
        }
    return out


def load_posts_by_date() -> dict:
    """{YYYY-MM-DD: [post, ...]}"""
    data = json.loads(TRUMP_POSTS.read_text(encoding="utf-8"))
    posts = data.get("posts", [])
    per_date = defaultdict(list)
    for p in posts:
        ts = p.get("created_at", "")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            continue
        d = dt.date().isoformat()
        per_date[d].append(p)
    return per_date


def aggregate_to_direction(d: str, posts: list, max_posts: int = 12) -> tuple[str, dict]:
    """跑 trump_signal.analyze_posts → 取 aggregate_direction。"""
    if not posts:
        return "neutral", {"posts_count": 0, "fallback": True}
    # 控制 CLI 成本：限 max_posts 条（取重要的，长度优先）
    posts_sorted = sorted(posts, key=lambda p: len(p.get("content") or ""), reverse=True)
    chunk = posts_sorted[:max_posts]
    from trump_signal import analyze_posts, _aggregate
    parsed = analyze_posts(chunk)
    items = parsed.get("items", [])
    direction, magnitude, score = _aggregate(items)
    return direction, {
        "posts_count": len(chunk),
        "items_n": len(items),
        "magnitude": magnitude,
        "score": score,
        "fallback": parsed.get("fallback", False),
    }


def main():
    print("="*72)
    print("  Trump signal 接入回测：new (我们的 CLI 聚合) vs baseline (trump-code 投票)")
    print(f"  样本天数={N_SAMPLES}  seed={SEED}")
    print("="*72)

    gt = load_ground_truth()
    posts_by_date = load_posts_by_date()
    # 仅保留有推文且有 actual_return 的天
    candidates = [d for d, info in gt.items()
                   if info["actual_return"] is not None
                   and posts_by_date.get(d)]
    print(f"  ground truth 共 {len(gt)} 天，可用样本 {len(candidates)} 天")
    rng = random.Random(SEED)
    sample = rng.sample(candidates, min(N_SAMPLES, len(candidates)))
    sample.sort()

    print()
    print(f"  {'date':<12} {'truth':<7} {'tc':<5} {'new':<9} {'mag':<7} {'tc_hit':<7} {'new_hit'}")
    print("  " + "-"*70)
    tc_hits = 0
    new_hits = 0
    n_tc = 0
    n_new = 0
    rng2 = random.Random(SEED + 1)
    for i, d in enumerate(sample):
        info = gt[d]
        truth = "UP" if (info["actual_return"] or 0) > 0 else "DOWN"
        tc_dir = "UP" if info["tc_direction"] == "LONG" else "DOWN"
        try:
            new_dir, meta = aggregate_to_direction(d, posts_by_date[d])
        except Exception as e:
            print(f"  {d:<12} ERR: {e}")
            continue
        # 映射 new -> UP/DOWN/NEUTRAL
        if new_dir == "bullish":
            new_up = "UP"
        elif new_dir == "bearish":
            new_up = "DOWN"
        else:
            new_up = "NEUTRAL"
        tc_hit = (tc_dir == truth)
        if new_up != "NEUTRAL":
            n_new += 1
            new_hit = (new_up == truth)
            if new_hit: new_hits += 1
            new_hit_str = "✓" if new_hit else "✗"
        else:
            new_hit_str = "·neutral"
        n_tc += 1
        if tc_hit: tc_hits += 1
        tc_hit_str = "✓" if tc_hit else "✗"
        print(f"  {d:<12} {truth:<7} {tc_dir:<5} {new_up:<9} {meta.get('magnitude',''):<7} "
              f"{tc_hit_str:<7} {new_hit_str}")

    print()
    print("-"*72)
    tc_rate = tc_hits / n_tc * 100 if n_tc else 0
    new_rate = new_hits / n_new * 100 if n_new else 0
    print(f"  trump-code  hit rate: {tc_hits}/{n_tc} = {tc_rate:.1f}%")
    print(f"  new (CLI)   hit rate: {new_hits}/{n_new} = {new_rate:.1f}%  (排除 neutral 后)")
    print()
    if new_rate >= tc_rate or n_new < 5:
        print(f"  ✓ 不退化（new {new_rate:.1f}% ≥ tc {tc_rate:.1f}%）" if n_new >= 5
              else f"  ⚠ 样本太少 (n={n_new})，无法判定退化与否")
    else:
        print(f"  ✗ 退化（new {new_rate:.1f}% < tc {tc_rate:.1f}%）—— 需要调阈值或回滚")


if __name__ == "__main__":
    main()
