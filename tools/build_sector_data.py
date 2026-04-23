#!/usr/bin/env python3
"""Build sector-relative datasets and combined macro/sector datasets.

Outputs:
  - data/sector_data.json
  - data/combined_data.json
"""

from __future__ import annotations

import csv
import datetime as dt
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
SECTOR_OUTPUT_FILE = DATA_DIR / "sector_data.json"
COMBINED_OUTPUT_FILE = DATA_DIR / "combined_data.json"
TIMELINE_FILE = DATA_DIR / "timeline_data.json"

BENCHMARK_SERIES = "SP500"
SECTOR_PROXY_SERIES = {
    "NASDAQ100": "Technology/Growth leadership proxy",
    "NASDAQCOM": "Broader technology-heavy market proxy",
    "DJIA": "Large-cap industrial/defensive proxy",
    "NASDAQNQUS500LCE": "S&P-style equal-weight proxy",
}


def fetch_fred(series_id: str) -> List[Tuple[dt.date, float]]:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    with urlopen(url, timeout=30) as resp:
        text = resp.read().decode("utf-8")
    rows = list(csv.DictReader(text.splitlines()))
    if not rows:
        return []
    date_key = "DATE" if "DATE" in rows[0] else "observation_date"
    out: List[Tuple[dt.date, float]] = []
    for row in rows:
        raw = row.get(series_id, ".")
        if raw == ".":
            continue
        try:
            out.append((dt.date.fromisoformat(row[date_key]), float(raw)))
        except ValueError:
            continue
    return out


def to_monthly_last(data: List[Tuple[dt.date, float]]) -> Dict[str, float]:
    by_month: Dict[Tuple[int, int], Tuple[dt.date, float]] = {}
    for d, v in data:
        by_month[(d.year, d.month)] = (d, v)
    out: Dict[str, float] = {}
    for (y, m), (_, v) in by_month.items():
        out[f"{y:04d}-{m:02d}-01"] = v
    return out


def pct_change(current: float, prior: Optional[float]) -> Optional[float]:
    if prior is None or prior == 0:
        return None
    return (current / prior - 1.0) * 100.0


def build() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    benchmark_daily = fetch_fred(BENCHMARK_SERIES)
    benchmark_monthly = to_monthly_last(benchmark_daily)
    dates = sorted(benchmark_monthly.keys())

    proxy_monthly: Dict[str, Dict[str, float]] = {}
    for sid in SECTOR_PROXY_SERIES:
        proxy_monthly[sid] = to_monthly_last(fetch_fred(sid))

    timeline: List[dict] = []
    for idx, d in enumerate(dates):
        bench_value = benchmark_monthly.get(d)
        if bench_value is None:
            continue
        prev_date_3m = dates[idx - 3] if idx >= 3 else None
        prev_date_12m = dates[idx - 12] if idx >= 12 else None
        prev_bench_3m = benchmark_monthly.get(prev_date_3m) if prev_date_3m else None
        prev_bench_12m = benchmark_monthly.get(prev_date_12m) if prev_date_12m else None
        bench_ret_3m = pct_change(bench_value, prev_bench_3m)
        bench_ret_12m = pct_change(bench_value, prev_bench_12m)

        sectors = {}
        for sid, label in SECTOR_PROXY_SERIES.items():
            val = proxy_monthly[sid].get(d)
            if val is None:
                continue
            prev_s_3m = proxy_monthly[sid].get(prev_date_3m) if prev_date_3m else None
            prev_s_12m = proxy_monthly[sid].get(prev_date_12m) if prev_date_12m else None
            s_ret_3m = pct_change(val, prev_s_3m)
            s_ret_12m = pct_change(val, prev_s_12m)
            rel_3m = (s_ret_3m - bench_ret_3m) if (s_ret_3m is not None and bench_ret_3m is not None) else None
            rel_12m = (s_ret_12m - bench_ret_12m) if (s_ret_12m is not None and bench_ret_12m is not None) else None
            sectors[sid] = {
                "label": label,
                "indexValue": val,
                "ret3mPct": None if s_ret_3m is None else round(s_ret_3m, 3),
                "ret12mPct": None if s_ret_12m is None else round(s_ret_12m, 3),
                "relative3mPct": None if rel_3m is None else round(rel_3m, 3),
                "relative12mPct": None if rel_12m is None else round(rel_12m, 3),
            }

        timeline.append(
            {
                "date": d,
                "sp500": {
                    "indexValue": bench_value,
                    "ret3mPct": None if bench_ret_3m is None else round(bench_ret_3m, 3),
                    "ret12mPct": None if bench_ret_12m is None else round(bench_ret_12m, 3),
                },
                "sectors": sectors,
            }
        )

    latest = timeline[-1] if timeline else None
    leadership = []
    if latest:
        for sid, payload in latest["sectors"].items():
            if payload["relative12mPct"] is None:
                continue
            leadership.append(
                {
                    "seriesId": sid,
                    "label": payload["label"],
                    "relative12mPct": payload["relative12mPct"],
                }
            )
        leadership.sort(key=lambda x: x["relative12mPct"], reverse=True)

    payload = {
        "meta": {
            "generatedAtUTC": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
            "benchmarkSeries": BENCHMARK_SERIES,
            "sectorSeries": SECTOR_PROXY_SERIES,
            "description": (
                "Sector-style performance proxies and relative strength versus S&P 500. "
                "Uses available broad FRED market internals where direct sector families are unavailable."
            ),
        },
        "leadershipLatest": leadership,
        "timeline": timeline,
    }
    SECTOR_OUTPUT_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {SECTOR_OUTPUT_FILE}")

    timeline_payload = json.loads(TIMELINE_FILE.read_text(encoding="utf-8"))
    macro_rows = {row["date"]: row for row in timeline_payload.get("timeline", [])}
    combined_rows = []
    for row in timeline:
        d = row["date"]
        macro = macro_rows.get(d)
        if not macro:
            continue
        combined_rows.append(
            {
                "date": d,
                "phase": macro["phase"],
                "phaseName": macro["phaseName"],
                "stressScore": macro["stressScore"],
                "sp500": row["sp500"],
                "sectors": row["sectors"],
            }
        )

    combined_payload = {
        "meta": {
            "generatedAtUTC": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
            "description": (
                "Combined macro phase and sector-proxy context for joint cycle/leadership analysis."
            ),
            "sectorSeries": SECTOR_PROXY_SERIES,
            "phaseMethodName": timeline_payload.get("meta", {}).get("method", {}).get("name"),
        },
        "timeline": combined_rows,
    }
    COMBINED_OUTPUT_FILE.write_text(json.dumps(combined_payload, indent=2), encoding="utf-8")
    print(f"Wrote {COMBINED_OUTPUT_FILE}")


if __name__ == "__main__":
    build()
