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
  "timestamp_local": "2026-06-19T01:11:43",
  "ticker": "US.TQQQ",
  "window": "midday",
  "market": {
    "ticker": "TQQQ",
    "ts": "2026-06-19 01:11",
    "price": 82.57,
    "pct_chg": 6.49,
    "rsi_14": 48.9,
    "cci_20": 40.8,
    "cci_zone": "neutral",
    "ma20": 80.06,
    "ma50": 70.31,
    "vol_ratio": 0.52,
    "is_new_52w_high": false,
    "dist_from_high": -6.27,
    "trend": "up",
    "ma_stack": "bull",
    "rsi_zone": "neutral",
    "vol_zone": "shrink",
    "pct_chg_zone": "surge",
    "pre_price": 81.99,
    "pre_pct": 5.738,
    "pre_volume": 2759510.0,
    "pre_date": "2026-06-18",
    "pre_label": "今日盘前(已结束)",
    "after_price": 79.86,
    "after_pct": 2.992,
    "after_volume": 2398739.0,
    "after_date": "2026-06-17",
    "after_label": "昨日盘后(已结束)",
    "overnight_price": 80.98,
    "overnight_pct": 4.436,
    "overnight_volume": 1918529.0,
    "overnight_date": "2026-06-17",
    "overnight_label": "昨夜夜盘(已结束)",
    "now_et": "2026-06-18 12:11 ET",
    "prev_session": {
      "date": "2026-06-16",
      "open": 84.19,
      "close": 79.93,
      "high": 84.83,
      "low": 79.86,
      "pct": -5.06
    },
    "prev_pct": -5.06,
    "today_session": {
      "date": "2026-06-18",
      "open": 82.0,
      "current": 82.57,
      "pct": 0.69,
      "status": "盘中进行中"
    },
    "today_not_yet_opened": null,
    "ma_cross": "golden",
    "rsi_cross": "none",
    "cci_cross": "none",
    "bb_pct": 0.623,
    "bb_zone": "normal",
    "bb_upper": 90.24,
    "bb_lower": 69.87,
    "psar_trend": 1,
    "psar_signal": "none",
    "macd_dif": 2.4,
    "macd_dea": 2.997,
    "macd_hist": -0.597,
    "macd_zone": "bull",
    "macd_signal": "none",
    "adx_14": 23.4,
    "adx_zone": "moderate"
  },
  "events": {
    "ts": "2026-06-19 01:10",
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
        "title": "Pre-Markets Bounce Back, Philly Fed & Jobless Claims Up",
        "url": "https://finance.yahoo.com/economy/articles/pre-markets-bounce-back-philly-142800629.html?.tsrc=rss",
        "source": null
      },
      {
        "title": "Exchange-Traded Funds, Equity Futures Higher Pre-Bell Thursday as Interim US-Iran Deal Lifts Risk Sentiment",
        "url": "https://finance.yahoo.com/markets/stocks/articles/exchange-traded-funds-equity-futures-125723601.html?.tsrc=rss",
        "source": null
      }
    ],
    "risk_level": "normal",
    "trump_signal": {
      "direction": "bullish",
      "magnitude": "large",
      "score": 40,
      "tariff_alert": false,
      "silence_signal": false,
      "posts_count": 23,
      "n_signals_medium_plus": 2,
      "fallback": false
    },
    "options_risk": {
      "ts": "2026-06-19T01:11:42.421063",
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
            "cp_oi_ratio": "1.45",
            "weighted_max_pain_pct": "-1.05",
            "strength": "weak"
          },
          "spot": 82.6,
          "walls_n": 3,
          "underlying_adjusted": [
            "{'proxy': 'QQQ', 'label': 'QQQ underlying', 'proxy_spot': 738.65, 'leveraged_ticker': 'TQQQ', 'leveraged_spot': 82.6, 'leverage': 3.0, 'gex': {'direction': 'neutral', 'cp_oi_ratio': 0.86, 'weighted_max_pain_pct': -0.36, 'strength': 'weak'}, 'walls': [{'expiry': '2026-06-18', 'category': '0DTE', 'days': -1, 'call_wall': {'proxy_strike': 740.0, 'proxy_pct': 0.18, 'leveraged_level': 83.05, 'leveraged_pct': 0.55, 'volume': 186553}, 'put_wall': {'proxy_strike': 735.0, 'proxy_pct': -0.49, 'leveraged_level': 81.38, 'leveraged_pct': -1.48, 'volume': 143286}, 'max_pain': {'proxy_strike': 736.0, 'proxy_pct': -0.36, 'leveraged_level': 81.71, 'leveraged_pct': -1.08}, 'total_call_vol': 1295625, 'total_put_vol': 1499800, 'cp_ratio': 0.86}, {'expiry': '2026-06-22', 'category': 'weekly', 'days': 3, 'call_wall': {'proxy_strike': 737.0, 'proxy_pct': -0.22, 'leveraged_level': 82.05, 'leveraged_pct': -0.67, 'volume': 18910}, 'put_wall': {'proxy_strike': 736.0, 'proxy_pct': -0.36, 'leveraged_level': 81.71, 'leveraged_pct': -1.08, 'volume': 14383}, 'max_pain': {'proxy_strike': 736.0, 'proxy_pct': -0.36, 'leveraged_level': 81.71, 'leveraged_pct': -1.08}, 'total_call_vol': 136641, 'total_put_vol': 158431, 'cp_ratio': 0.86}, {'expiry': '2026-07-17', 'category': 'monthly', 'days': 28, 'call_wall': {'proxy_strike': 740.0, 'proxy_pct': 0.18, 'leveraged_level': 83.05, 'leveraged_pct': 0.55, 'volume': 5786}, 'put_wall': {'proxy_strike': 700.0, 'proxy_pct': -5.23, 'leveraged_level': 69.63, 'leveraged_pct': -15.7, 'volume': 9055}, 'max_pain': {'proxy_strike': 734.0, 'proxy_pct': -0.63, 'leveraged_level': 81.04, 'leveraged_pct': -1.89}, 'total_call_vol': 40302, 'total_put_vol': 43220, 'cp_ratio': 0.93}]}"
          ]
        },
        "SOXL": {
          "gex": {
            "direction": "neutral",
            "cp_oi_ratio": "1.33",
            "weighted_max_pain_pct": "-5.12",
            "strength": "weak"
          },
          "spot": 279.31,
          "walls_n": 3,
          "underlying_adjusted": [
            "{'proxy': 'SOXX', 'label': 'SOXX underlying', 'proxy_spot': 638.46, 'leveraged_ticker': 'SOXL', 'leveraged_spot': 279.31, 'leverage': 3.0, 'gex': {'direction': 'negative_squeeze', 'cp_oi_ratio': 0.65, 'weighted_max_pain_pct': -2.71, 'strength': 'medium'}, 'walls': [{'expiry': '2026-06-18', 'category': '0DTE', 'days': -1, 'call_wall': {'proxy_strike': 642.5, 'proxy_pct': 0.63, 'leveraged_level': 284.61, 'leveraged_pct': 1.9, 'volume': 1053}, 'put_wall': {'proxy_strike': 565.0, 'proxy_pct': -11.51, 'leveraged_level': 182.9, 'leveraged_pct': -34.52, 'volume': 1409}, 'max_pain': {'proxy_strike': 630.0, 'proxy_pct': -1.33, 'leveraged_level': 268.21, 'leveraged_pct': -3.98}, 'total_call_vol': 2090, 'total_put_vol': 4176, 'cp_ratio': 0.5}, {'expiry': '2026-06-26', 'category': 'weekly', 'days': 7, 'call_wall': {'proxy_strike': 700.0, 'proxy_pct': 9.64, 'leveraged_level': 360.08, 'leveraged_pct': 28.92, 'volume': 423}, 'put_wall': {'proxy_strike': 572.5, 'proxy_pct': -10.33, 'leveraged_level': 192.74, 'leveraged_pct': -30.99, 'volume': 322}, 'max_pain': {'proxy_strike': 600.0, 'proxy_pct': -6.02, 'leveraged_level': 228.83, 'leveraged_pct': -18.07}, 'total_call_vol': 1398, 'total_put_vol': 1218, 'cp_ratio': 1.15}, {'expiry': '2026-07-17', 'category': 'monthly', 'days': 28, 'call_wall': {'proxy_strike': 720.0, 'proxy_pct': 12.77, 'leveraged_level': 386.33, 'leveraged_pct': 38.31, 'volume': 398}, 'put_wall': {'proxy_strike': 590.0, 'proxy_pct': -7.59, 'leveraged_level': 215.71, 'leveraged_pct': -22.77, 'volume': 1912}, 'max_pain': {'proxy_strike': 595.0, 'proxy_pct': -6.81, 'leveraged_level': 222.27, 'leveraged_pct': -20.42}, 'total_call_vol': 587, 'total_put_vol': 3594, 'cp_ratio': 0.16}]}",
            "{'proxy': 'SMH', 'label': 'SMH liquid proxy', 'proxy_spot': 658.04, 'leveraged_ticker': 'SOXL', 'leveraged_spot': 279.31, 'leverage': 3.0, 'gex': {'direction': 'negative_squeeze', 'cp_oi_ratio': 0.58, 'weighted_max_pain_pct': -1.22, 'strength': 'medium'}, 'walls': [{'expiry': '2026-06-18', 'category': '0DTE', 'days': -1, 'call_wall': {'proxy_strike': 650.0, 'proxy_pct': -1.22, 'leveraged_level': 269.07, 'leveraged_pct': -3.67, 'volume': 3012}, 'put_wall': {'proxy_strike': 630.0, 'proxy_pct': -4.26, 'leveraged_level': 243.6, 'leveraged_pct': -12.78, 'volume': 3152}, 'max_pain': {'proxy_strike': 650.0, 'proxy_pct': -1.22, 'leveraged_level': 269.07, 'leveraged_pct': -3.67}, 'total_call_vol': 10279, 'total_put_vol': 16037, 'cp_ratio': 0.64}, {'expiry': '2026-06-26', 'category': 'weekly', 'days': 7, 'call_wall': {'proxy_strike': 690.0, 'proxy_pct': 4.86, 'leveraged_level': 320.01, 'leveraged_pct': 14.57, 'volume': 1276}, 'put_wall': {'proxy_strike': 600.0, 'proxy_pct': -8.82, 'leveraged_level': 205.4, 'leveraged_pct': -26.46, 'volume': 2921}, 'max_pain': {'proxy_strike': 650.0, 'proxy_pct': -1.22, 'leveraged_level': 269.07, 'leveraged_pct': -3.67}, 'total_call_vol': 6197, 'total_put_vol': 12515, 'cp_ratio': 0.5}, {'expiry': '2026-07-17', 'category': 'monthly', 'days': 28, 'call_wall': {'proxy_strike': 690.0, 'proxy_pct': 4.86, 'leveraged_level': 320.01, 'leveraged_pct': 14.57, 'volume': 1170}, 'put_wall': {'proxy_strike': 585.0, 'proxy_pct': -11.1, 'leveraged_level': 186.3, 'leveraged_pct': -33.3, 'volume': 1816}, 'max_pain': {'proxy_strike': 645.0, 'proxy_pct': -1.98, 'leveraged_level': 262.71, 'leveraged_pct': -5.94}, 'total_call_vol': 4733, 'total_put_vol': 5303, 'cp_ratio': 0.89}]}"
          ]
        },
        "DRAM": {
          "gex": {
            "direction": "neutral",
            "cp_oi_ratio": "1.15",
            "weighted_max_pain_pct": "-4.13",
            "strength": "weak"
          },
          "spot": 77.05,
          "walls_n": 3,
          "underlying_adjusted": [
            "{'proxy': 'MU', 'label': 'MU memory proxy', 'proxy_spot': 1129.6, 'leveraged_ticker': 'DRAM', 'leveraged_spot': 77.05, 'leverage': 1.0, 'gex': {'direction': 'positive_pin', 'cp_oi_ratio': 1.54, 'weighted_max_pain_pct': -2.72, 'strength': 'medium'}, 'walls': [{'expiry': '2026-06-18', 'category': '0DTE', 'days': -1, 'call_wall': {'proxy_strike': 1150.0, 'proxy_pct': 1.81, 'leveraged_level': 78.44, 'leveraged_pct': 1.81, 'volume': 21984}, 'put_wall': {'proxy_strike': 1100.0, 'proxy_pct': -2.62, 'leveraged_level': 75.03, 'leveraged_pct': -2.62, 'volume': 11818}, 'max_pain': {'proxy_strike': 1100.0, 'proxy_pct': -2.62, 'leveraged_level': 75.03, 'leveraged_pct': -2.62}, 'total_call_vol': 150745, 'total_put_vol': 83662, 'cp_ratio': 1.8}, {'expiry': '2026-06-26', 'category': 'weekly', 'days': 7, 'call_wall': {'proxy_strike': 1200.0, 'proxy_pct': 6.23, 'leveraged_level': 81.85, 'leveraged_pct': 6.23, 'volume': 4931}, 'put_wall': {'proxy_strike': 1000.0, 'proxy_pct': -11.47, 'leveraged_level': 68.21, 'leveraged_pct': -11.47, 'volume': 19125}, 'max_pain': {'proxy_strike': 1095.0, 'proxy_pct': -3.06, 'leveraged_level': 74.69, 'leveraged_pct': -3.06}, 'total_call_vol': 33764, 'total_put_vol': 36310, 'cp_ratio': 0.93}, {'expiry': '2026-07-17', 'category': 'monthly', 'days': 28, 'call_wall': {'proxy_strike': 1200.0, 'proxy_pct': 6.23, 'leveraged_level': 81.85, 'leveraged_pct': 6.23, 'volume': 3055}, 'put_wall': {'proxy_strike': 1000.0, 'proxy_pct': -11.47, 'leveraged_level': 68.21, 'leveraged_pct': -11.47, 'volume': 409}, 'max_pain': {'proxy_strike': 1040.0, 'proxy_pct': -7.93, 'leveraged_level': 70.94, 'leveraged_pct': -7.93}, 'total_call_vol': 13459, 'total_put_vol': 2533, 'cp_ratio': 5.31}]}"
          ]
        },
        "SPY": {
          "gex": {
            "direction": "neutral",
            "cp_oi_ratio": "0.84",
            "weighted_max_pain_pct": "-0.04",
            "strength": "weak"
          },
          "spot": 746.25,
          "walls_n": 3
        },
        "QQQ": {
          "gex": {
            "direction": "neutral",
            "cp_oi_ratio": "0.86",
            "weighted_max_pain_pct": "-0.36",
            "strength": "weak"
          },
          "spot": 738.65,
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
    "vix": 16.920000076293945,
    "fg_score": 37,
    "t10y2y": 0.29,
    "t10yie": 2.26,
    "fedfunds": 3.63
  },
  "rule_decision": {
    "action": "WATCH_BUY",
    "confidence": 8,
    "reason": "uptrend + positive confluence",
    "stop_ref": null,
    "score_breakdown": {
      "tech": 4,
      "macro": 0,
      "event": 0,
      "quant": 0,
      "boost": 2
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
    "session": "open",
    "confluence": {
      "bull_signals": [
        "价格站上MA20(价格82.57 > MA20=80.06)",
        "均线多排(MA20=80.06 > MA50=70.31)",
        "均线金叉(MA5上穿MA20，近3日)",
        "当日暴涨(+6.5%，>+5%)  ⚠超买风险"
      ],
      "bear_signals": [],
      "bull_count": 4,
      "bear_count": 0,
      "net": 4,
      "strength": "强多头共振",
      "stars": "★★★"
    },
    "h1_context": "最新K线@17:00  趋势:向上  RSI:43.3",
    "m15_context": "[最新15m K线@2026-06-18 06:00:00] 短线信号弱(信号数 1，方向不明): RSI极度超买(15m RSI=76)",
    "m15_direction": "mixed"
  }
}
