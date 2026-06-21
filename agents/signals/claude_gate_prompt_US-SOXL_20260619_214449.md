You are the final pre-trade risk gate for this local trading system.

Task:
- Review ONLY the rule_decision below. Do not create a new trade idea.
- Return APPROVE only if the proposed action is internally consistent, timely,
  and risk is acceptable for the current window.
- Return HOLD if data is stale, conflicted, weak, or the proposed order should
  not be sent.
- Return CAUTION if the signal is notable but should be recorded as no-order.
- Be conservative. If unsure, choose HOLD.

Output JSON only, with this schema:
{"verdict":"APPROVE|HOLD|CAUTION","confidence":1-10,"reason":"short reason","risk_flags":["..."]}

Decision packet:
{
  "timestamp_local": "2026-06-19T21:44:49",
  "ticker": "US.SOXL",
  "window": "pre-market",
  "market": {
    "ticker": "SOXL",
    "ts": "2026-06-19 21:44",
    "price": 279.29,
    "pct_chg": 19.43,
    "rsi_14": 56.7,
    "cci_20": 149.9,
    "cci_zone": "overbought",
    "ma20": 224.22,
    "ma50": 165.04,
    "vol_ratio": 0.79,
    "is_new_52w_high": false,
    "dist_from_high": -2.4,
    "trend": "up",
    "ma_stack": "bull",
    "rsi_zone": "neutral",
    "vol_zone": "shrink",
    "pct_chg_zone": "surge",
    "pre_price": 265.82,
    "pre_pct": 13.666,
    "pre_volume": 5745912.0,
    "pre_date": "2026-06-19",
    "pre_label": "今日盘前(进行中)",
    "after_price": 281.15,
    "after_pct": 0.665,
    "after_volume": 1848390.0,
    "after_date": "2026-06-18",
    "after_label": "昨日盘后(已结束)",
    "overnight_price": 255.7,
    "overnight_pct": 9.338,
    "overnight_volume": 2109890.0,
    "overnight_date": "2026-06-18",
    "overnight_label": "昨夜夜盘(已结束)",
    "now_et": "2026-06-19 08:44 ET",
    "prev_session": {
      "date": "2026-06-16",
      "open": 267.13,
      "close": 226.19,
      "high": 274.93,
      "low": 226.0,
      "pct": -15.33
    },
    "prev_pct": -15.33,
    "today_session": null,
    "today_not_yet_opened": "2026-06-19 今日尚未开盘（距 9:30 ET 还有 0h46m）",
    "ma_cross": "none",
    "rsi_cross": "none",
    "cci_cross": "up_100",
    "bb_pct": 0.904,
    "bb_zone": "normal",
    "bb_upper": 292.42,
    "bb_lower": 156.02,
    "psar_trend": 1,
    "psar_signal": "none",
    "macd_dif": 23.274,
    "macd_dea": 22.822,
    "macd_hist": 0.451,
    "macd_zone": "bull",
    "macd_signal": "golden",
    "adx_14": 15.8,
    "adx_zone": "weak"
  },
  "events": {
    "ts": "2026-06-19 21:43",
    "next_event": "NFP Release (2026-07-03)",
    "next_event_name": "NFP Release",
    "next_event_date": "2026-07-03",
    "next_event_impact": "critical",
    "event_verify_src": "",
    "days_to_event": 14,
    "breaking_news": false,
    "breaking_evidence": "",
    "top_headlines": [
      {
        "title": "If You'd Invested $10,000 in QQQ 10 Years Ago, Here's How Much You'd Have Today",
        "url": "https://www.fool.com/investing/2026/06/19/you-invested-10000-in-qqq-10-years-ago-how-much/?.tsrc=rss",
        "source": null
      },
      {
        "title": "ARKK’s 0.75% Fee Quietly Costs You $55 a Year on Every $10,000 Invested",
        "url": "https://247wallst.com/investing/2026/06/18/arkks-0-75-fee-quietly-costs-you-55-a-year-on-every-10000-invested/?.tsrc=rss",
        "source": null
      }
    ],
    "risk_level": "normal",
    "trump_signal": {
      "direction": "bullish",
      "magnitude": "extreme",
      "score": 81,
      "tariff_alert": false,
      "silence_signal": false,
      "posts_count": 13,
      "n_signals_medium_plus": 4,
      "fallback": false
    },
    "options_risk": {
      "ts": "2026-06-19T21:44:25.168319",
      "witching": {
        "is_witching_day": true,
        "days_to_witching": 0,
        "phase": "today",
        "next_witching_date": "2026-06-19"
      },
      "per_ticker": {
        "TQQQ": {
          "gex": {
            "direction": "neutral",
            "cp_oi_ratio": "1.07",
            "weighted_max_pain_pct": "-2.26",
            "strength": "weak"
          },
          "spot": 82.87,
          "walls_n": 2,
          "underlying_adjusted": [
            "{'proxy': 'QQQ', 'label': 'QQQ underlying', 'proxy_spot': 740.62, 'leveraged_ticker': 'TQQQ', 'leveraged_spot': 82.87, 'leverage': 3.0, 'gex': {'direction': 'neutral', 'cp_oi_ratio': 0.71, 'weighted_max_pain_pct': -0.37, 'strength': 'weak'}, 'walls': [{'expiry': '2026-06-22', 'category': 'weekly', 'days': 3, 'call_wall': {'proxy_strike': 740.0, 'proxy_pct': -0.08, 'leveraged_level': 82.66, 'leveraged_pct': -0.25, 'volume': 44976}, 'put_wall': {'proxy_strike': 735.0, 'proxy_pct': -0.76, 'leveraged_level': 80.98, 'leveraged_pct': -2.28, 'volume': 31521}, 'max_pain': {'proxy_strike': 738.0, 'proxy_pct': -0.35, 'leveraged_level': 81.99, 'leveraged_pct': -1.06}, 'total_call_vol': 322485, 'total_put_vol': 461623, 'cp_ratio': 0.7}, {'expiry': '2026-06-23', 'category': 'weekly', 'days': 4, 'call_wall': {'proxy_strike': 752.0, 'proxy_pct': 1.54, 'leveraged_level': 86.69, 'leveraged_pct': 4.61, 'volume': 5911}, 'put_wall': {'proxy_strike': 733.0, 'proxy_pct': -1.03, 'leveraged_level': 80.31, 'leveraged_pct': -3.09, 'volume': 8226}, 'max_pain': {'proxy_strike': 737.0, 'proxy_pct': -0.49, 'leveraged_level': 81.65, 'leveraged_pct': -1.47}, 'total_call_vol': 59549, 'total_put_vol': 73199, 'cp_ratio': 0.81}, {'expiry': '2026-07-17', 'category': 'monthly', 'days': 28, 'call_wall': {'proxy_strike': 800.0, 'proxy_pct': 8.02, 'leveraged_level': 102.8, 'leveraged_pct': 24.05, 'volume': 8485}, 'put_wall': {'proxy_strike': 740.0, 'proxy_pct': -0.08, 'leveraged_level': 82.66, 'leveraged_pct': -0.25, 'volume': 12238}, 'max_pain': {'proxy_strike': 739.0, 'proxy_pct': -0.22, 'leveraged_level': 82.33, 'leveraged_pct': -0.66}, 'total_call_vol': 82977, 'total_put_vol': 90630, 'cp_ratio': 0.92}]}"
          ]
        },
        "SOXL": {
          "gex": {
            "direction": "neutral",
            "cp_oi_ratio": "1.19",
            "weighted_max_pain_pct": "-4.22",
            "strength": "weak"
          },
          "spot": 279.29,
          "walls_n": 2,
          "underlying_adjusted": [
            "{'proxy': 'SOXX', 'label': 'SOXX underlying', 'proxy_spot': 639.45, 'leveraged_ticker': 'SOXL', 'leveraged_spot': 279.29, 'leverage': 3.0, 'gex': {'direction': 'negative_squeeze', 'cp_oi_ratio': 0.45, 'weighted_max_pain_pct': -2.26, 'strength': 'medium'}, 'walls': [{'expiry': '2026-06-26', 'category': 'weekly', 'days': 7, 'call_wall': {'proxy_strike': 680.0, 'proxy_pct': 6.34, 'leveraged_level': 332.42, 'leveraged_pct': 19.02, 'volume': 952}, 'put_wall': {'proxy_strike': 570.0, 'proxy_pct': -10.86, 'leveraged_level': 188.29, 'leveraged_pct': -32.58, 'volume': 893}, 'max_pain': {'proxy_strike': 625.0, 'proxy_pct': -2.26, 'leveraged_level': 260.36, 'leveraged_pct': -6.78}, 'total_call_vol': 2966, 'total_put_vol': 6598, 'cp_ratio': 0.45}, {'expiry': '2026-07-17', 'category': 'monthly', 'days': 28, 'call_wall': {'proxy_strike': 605.0, 'proxy_pct': -5.39, 'leveraged_level': 234.15, 'leveraged_pct': -16.16, 'volume': 767}, 'put_wall': {'proxy_strike': 560.0, 'proxy_pct': -12.42, 'leveraged_level': 175.19, 'leveraged_pct': -37.27, 'volume': 2648}, 'max_pain': {'proxy_strike': 600.0, 'proxy_pct': -6.17, 'leveraged_level': 227.6, 'leveraged_pct': -18.51}, 'total_call_vol': 2578, 'total_put_vol': 6375, 'cp_ratio': 0.4}]}",
            "{'proxy': 'SMH', 'label': 'SMH liquid proxy', 'proxy_spot': 659.88, 'leveraged_ticker': 'SOXL', 'leveraged_spot': 279.29, 'leverage': 3.0, 'gex': {'direction': 'negative_squeeze', 'cp_oi_ratio': 0.45, 'weighted_max_pain_pct': -1.12, 'strength': 'medium'}, 'walls': [{'expiry': '2026-06-26', 'category': 'weekly', 'days': 7, 'call_wall': {'proxy_strike': 690.0, 'proxy_pct': 4.56, 'leveraged_level': 317.53, 'leveraged_pct': 13.69, 'volume': 1850}, 'put_wall': {'proxy_strike': 600.0, 'proxy_pct': -9.07, 'leveraged_level': 203.26, 'leveraged_pct': -27.22, 'volume': 5183}, 'max_pain': {'proxy_strike': 652.5, 'proxy_pct': -1.12, 'leveraged_level': 269.92, 'leveraged_pct': -3.36}, 'total_call_vol': 16226, 'total_put_vol': 36448, 'cp_ratio': 0.45}, {'expiry': '2026-07-17', 'category': 'monthly', 'days': 28, 'call_wall': {'proxy_strike': 640.0, 'proxy_pct': -3.01, 'leveraged_level': 254.05, 'leveraged_pct': -9.04, 'volume': 21818}, 'put_wall': {'proxy_strike': 595.0, 'proxy_pct': -9.83, 'leveraged_level': 196.91, 'leveraged_pct': -29.5, 'volume': 2276}, 'max_pain': {'proxy_strike': 640.0, 'proxy_pct': -3.01, 'leveraged_level': 254.05, 'leveraged_pct': -9.04}, 'total_call_vol': 43976, 'total_put_vol': 18611, 'cp_ratio': 2.36}]}"
          ]
        },
        "DRAM": {
          "gex": {
            "direction": "positive_pin",
            "cp_oi_ratio": "2.09",
            "weighted_max_pain_pct": "-5.49",
            "strength": "medium"
          },
          "spot": 76.71,
          "walls_n": 2,
          "underlying_adjusted": [
            "{'proxy': 'MU', 'label': 'MU memory proxy', 'proxy_spot': 1133.99, 'leveraged_ticker': 'DRAM', 'leveraged_spot': 76.71, 'leverage': 1.0, 'gex': {'direction': 'neutral', 'cp_oi_ratio': 1.12, 'weighted_max_pain_pct': -3.0, 'strength': 'weak'}, 'walls': [{'expiry': '2026-06-26', 'category': 'weekly', 'days': 7, 'call_wall': {'proxy_strike': 1200.0, 'proxy_pct': 5.82, 'leveraged_level': 81.18, 'leveraged_pct': 5.82, 'volume': 10683}, 'put_wall': {'proxy_strike': 1000.0, 'proxy_pct': -11.82, 'leveraged_level': 67.65, 'leveraged_pct': -11.82, 'volume': 21457}, 'max_pain': {'proxy_strike': 1100.0, 'proxy_pct': -3.0, 'leveraged_level': 74.41, 'leveraged_pct': -3.0}, 'total_call_vol': 67032, 'total_put_vol': 59924, 'cp_ratio': 1.12}, {'expiry': '2026-07-17', 'category': 'monthly', 'days': 28, 'call_wall': {'proxy_strike': 1200.0, 'proxy_pct': 5.82, 'leveraged_level': 81.18, 'leveraged_pct': 5.82, 'volume': 6683}, 'put_wall': {'proxy_strike': 1000.0, 'proxy_pct': -11.82, 'leveraged_level': 67.65, 'leveraged_pct': -11.82, 'volume': 1066}, 'max_pain': {'proxy_strike': 1050.0, 'proxy_pct': -7.41, 'leveraged_level': 71.03, 'leveraged_pct': -7.41}, 'total_call_vol': 25287, 'total_put_vol': 6581, 'cp_ratio': 3.84}]}"
          ]
        },
        "SPY": {
          "gex": {
            "direction": "neutral",
            "cp_oi_ratio": "0.92",
            "weighted_max_pain_pct": "-0.1",
            "strength": "weak"
          },
          "spot": 746.74,
          "walls_n": 3
        },
        "QQQ": {
          "gex": {
            "direction": "neutral",
            "cp_oi_ratio": "0.71",
            "weighted_max_pain_pct": "-0.37",
            "strength": "weak"
          },
          "spot": 740.62,
          "walls_n": 3
        }
      },
      "summary": {
        "max_risk": "high",
        "reason": "三巫日（gamma 集中到期）"
      }
    }
  },
  "macro": {
    "vix": 17.149999618530273,
    "fg_score": 37,
    "t10y2y": 0.27,
    "t10yie": 2.25,
    "fedfunds": 3.63
  },
  "rule_decision": {
    "action": "WATCH_BUY",
    "confidence": 9,
    "reason": "bullish trend + momentum",
    "stop_ref": null,
    "score_breakdown": {
      "tech": 4,
      "macro": 0,
      "event": 0,
      "quant": 0,
      "boost": 3
    },
    "engine": "rules",
    "regime": "bull_pulling",
    "quant": {
      "buy_hits": [],
      "sell_hits": [],
      "buy_score": 0,
      "sell_score": 0,
      "n_rules": 0,
      "regime_bucket": "bull",
      "ts": null
    },
    "trump_boost": true,
    "session": "pre-market",
    "confluence": {
      "bull_signals": [
        "价格站上MA20(价格279.29 > MA20=224.22)",
        "均线多排(MA20=224.22 > MA50=165.04)",
        "当日暴涨(+19.4%，>+5%)  ⚠超买风险",
        "[2026-06-19 今日盘前(进行中)] 涨+13.67%  → 开盘大概率跳空高开"
      ],
      "bear_signals": [
        "CCI超买(CCI=150，中性区间-100~+100，当前高于+100)",
        "CCI进入超买(近3日上穿+100，当前=150)"
      ],
      "bull_count": 4,
      "bear_count": 2,
      "net": 2,
      "strength": "多头共振",
      "stars": "★★"
    },
    "h1_context": "最新K线@17:00  趋势:向下  RSI:37.2  近期死叉",
    "m15_context": "[最新15m K线@2026-06-18 06:00:00] 短线信号弱(信号数 2，方向不明): 突破6h高点 $260.70 · RSI极度超买(15m RSI=82)",
    "m15_direction": "mixed"
  }
}
