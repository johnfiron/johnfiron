#!/usr/bin/env python3
"""Build timeline dataset for collapse-phase visualization.

Outputs:
  - data/timeline_data.json

Data sources are pulled from FRED public CSV endpoints at build time.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUTPUT_FILE = DATA_DIR / "timeline_data.json"
FRED_CSV_BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv?id="

# FRED daily/weekly/monthly core series used for regime scoring.
SERIES = {
    "BAA10Y": "Corporate bond spread proxy (BAA - 10Y Treasury, pct)",
    "VIXCLS": "Equity implied volatility (VIX)",
    "STLFSI4": "St. Louis Fed Financial Stress Index",
    "NFCI": "Chicago Fed National Financial Conditions Index",
    "UNRATE": "Unemployment rate",
    "USREC": "NBER recession indicator",
    "INDPRO": "Industrial production index",
    "TB3MS": "3-month Treasury bill",
    "GS10": "10-year Treasury constant maturity",
}


# Clear, beginner-friendly phase labels.
PHASE_INFO = {
    1: {
        "name": "Phase 1: Setup",
        "color": "#B7E4C7",
        "description": "Fragility may be building, but broad stress is not visible yet.",
    },
    2: {
        "name": "Phase 2: Stress Signals",
        "color": "#F7D6A1",
        "description": "Multiple systems show pressure (credit, volatility, liquidity, labor, activity).",
    },
    3: {
        "name": "Phase 3: Trigger Event",
        "color": "#F2A8A8",
        "description": "A catalyst hits while the system is already fragile.",
    },
    4: {
        "name": "Phase 4: Cascade",
        "color": "#7B7F8A",
        "description": "Forced de-risking and rapid repricing dominate.",
    },
}


# Collapse windows for overlays. 1920s/1930s segment explicitly estimated.
EVENT_WINDOWS = [
    {
        "id": "great-depression-est",
        "label": "Great Depression (estimated timeline)",
        "start": "1927-01-01",
        "trigger": "1929-10-01",
        "cascade": "1930-01-01",
        "end": "1933-03-01",
        "estimated": True,
        "notes": (
            "Estimated with available long-history proxies (BAA yields, industrial production, "
            "policy rates, recession chronology). Daily market-breadth/volatility inputs are unavailable."
        ),
    },
    {
        "id": "gfc",
        "label": "Global Financial Crisis",
        "start": "2007-06-01",
        "trigger": "2008-09-01",
        "cascade": "2008-10-01",
        "end": "2009-06-01",
        "estimated": False,
        "notes": "Lehman failure acted as trigger after broad stress buildup in credit/funding markets.",
    },
    {
        "id": "covid",
        "label": "COVID Crash",
        "start": "2020-01-01",
        "trigger": "2020-02-20",
        "cascade": "2020-03-01",
        "end": "2020-04-30",
        "estimated": False,
        "notes": "Fast shock with policy response and liquidity backstop following violent repricing.",
    },
]


@dataclass
class Point:
    date: dt.date
    value: float


@dataclass
class FetchResult:
    series_id: str
    url: str
    points: List[Point]
    status: str
    error: Optional[str] = None


def fetch_fred_series(series_id: str) -> FetchResult:
    """Fetch a FRED series with graceful error handling."""
    url = f"{FRED_CSV_BASE}{series_id}"
    try:
        with urlopen(url, timeout=30) as resp:
            payload = resp.read().decode("utf-8")
        rows = list(csv.DictReader(payload.splitlines()))
        if not rows:
            return FetchResult(series_id=series_id, url=url, points=[], status="empty")
        date_key = "DATE" if "DATE" in rows[0] else "observation_date"
        points: List[Point] = []
        for row in rows:
            raw = row.get(series_id, ".")
            if raw == ".":
                continue
            try:
                points.append(Point(dt.date.fromisoformat(row[date_key]), float(raw)))
            except ValueError:
                continue
        status = "ok" if points else "empty"
        return FetchResult(series_id=series_id, url=url, points=points, status=status)
    except Exception as exc:  # pragma: no cover - network edge cases
        return FetchResult(series_id=series_id, url=url, points=[], status="error", error=str(exc))


def to_monthly(series: List[Point]) -> Dict[dt.date, float]:
    """Convert a series to month-end points (last observation in month)."""
    monthly: Dict[Tuple[int, int], Point] = {}
    for p in series:
        key = (p.date.year, p.date.month)
        monthly[key] = p
    out: Dict[dt.date, float] = {}
    for (_, _), p in monthly.items():
        out[dt.date(p.date.year, p.date.month, 1)] = p.value
    return out


def month_range(start: dt.date, end: dt.date) -> Iterable[dt.date]:
    cur = dt.date(start.year, start.month, 1)
    stop = dt.date(end.year, end.month, 1)
    while cur <= stop:
        yield cur
        if cur.month == 12:
            cur = dt.date(cur.year + 1, 1, 1)
        else:
            cur = dt.date(cur.year, cur.month + 1, 1)


def percentile(values: List[float], x: float) -> float:
    """Simple percentile rank in [0, 1]."""
    if not values:
        return 0.5
    less = sum(1 for v in values if v < x)
    equal = sum(1 for v in values if v == x)
    return (less + 0.5 * equal) / len(values)


def zscore(values: List[float], x: float) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / max(1, len(values) - 1)
    std = math.sqrt(var) if var > 0 else 1.0
    return (x - mean) / std


def build() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fetched = {sid: fetch_fred_series(sid) for sid in SERIES}
    fetch_manifest = []
    for sid, result in fetched.items():
        first_date = result.points[0].date.isoformat() if result.points else None
        last_date = result.points[-1].date.isoformat() if result.points else None
        fetch_manifest.append(
            {
                "seriesId": sid,
                "label": SERIES[sid],
                "url": result.url,
                "status": result.status,
                "points": len(result.points),
                "firstDate": first_date,
                "lastDate": last_date,
                "error": result.error,
            }
        )

    # Convert all to monthly first.
    monthly = {sid: to_monthly(result.points) for sid, result in fetched.items()}

    # Determine available date window intersection, but keep broad history where possible.
    starts = [min(m.keys()) for m in monthly.values() if m]
    ends = [max(m.keys()) for m in monthly.values() if m]
    if not starts or not ends:
        raise RuntimeError("No input series could be fetched. See data request manifest for errors.")
    global_start = min(starts)
    global_end = max(ends)

    # Build aligned records with missing values allowed.
    records: List[Dict[str, Optional[float]]] = []
    for d in month_range(global_start, global_end):
        row: Dict[str, Optional[float]] = {"date": d.isoformat()}
        for sid in SERIES:
            row[sid] = monthly[sid].get(d)
        records.append(row)

    # Historical baselines (post-1971 for stability; fallback to full).
    def collect_non_null(key: str, since_year: int = 1971) -> List[float]:
        vals = [r[key] for r in records if r[key] is not None and int(r["date"][:4]) >= since_year]
        if vals:
            return [float(v) for v in vals]
        return [float(r[key]) for r in records if r[key] is not None]

    baseline = {
        "BAA10Y": collect_non_null("BAA10Y"),
        "VIXCLS": collect_non_null("VIXCLS", since_year=1990),
        "STLFSI4": collect_non_null("STLFSI4", since_year=1994),
        "NFCI": collect_non_null("NFCI", since_year=1971),
        "UNRATE": collect_non_null("UNRATE", since_year=1948),
    }

    # Build phase scores and classify each month.
    timeline: List[Dict[str, object]] = []
    prev_phase = 1
    for r in records:
        date = r["date"]
        year = int(date[:4])

        # Inputs with safe defaults if unavailable in early history.
        baa10y = float(r["BAA10Y"]) if r["BAA10Y"] is not None else None
        vix = float(r["VIXCLS"]) if r["VIXCLS"] is not None else None
        stlfsi = float(r["STLFSI4"]) if r["STLFSI4"] is not None else None
        nfci = float(r["NFCI"]) if r["NFCI"] is not None else None
        unrate = float(r["UNRATE"]) if r["UNRATE"] is not None else None
        usrec = int(float(r["USREC"])) if r["USREC"] is not None else 0
        indpro = float(r["INDPRO"]) if r["INDPRO"] is not None else None
        tb3 = float(r["TB3MS"]) if r["TB3MS"] is not None else None
        gs10 = float(r["GS10"]) if r["GS10"] is not None else None

        # Term spread when available.
        term_spread = (gs10 - tb3) if (gs10 is not None and tb3 is not None) else None

        # 12m industrial production change.
        indpro_12m = None
        if indpro is not None:
            prior = next(
                (
                    rr["INDPRO"]
                    for rr in records
                    if rr["date"] == f"{year - 1}-{date[5:7]}-01" and rr["INDPRO"] is not None
                ),
                None,
            )
            if prior:
                indpro_12m = (indpro / float(prior) - 1.0) * 100.0

        # Stress components scaled roughly into 0..1.
        credit_score = percentile(baseline["BAA10Y"], baa10y) if baa10y is not None else 0.5
        vol_score = percentile(baseline["VIXCLS"], vix) if vix is not None else 0.5
        liq_stress = 0.0
        if stlfsi is not None:
            liq_stress = max(liq_stress, percentile(baseline["STLFSI4"], stlfsi))
        if nfci is not None:
            liq_stress = max(liq_stress, percentile(baseline["NFCI"], nfci))
        if liq_stress == 0.0:
            liq_stress = 0.5
        labor_score = percentile(baseline["UNRATE"], unrate) if unrate is not None else 0.5

        growth_stress = 0.0
        if indpro_12m is not None:
            if indpro_12m < -8:
                growth_stress = 1.0
            elif indpro_12m < -3:
                growth_stress = 0.75
            elif indpro_12m < 0:
                growth_stress = 0.5
            else:
                growth_stress = 0.2
        else:
            growth_stress = 0.5

        curve_stress = 0.0
        if term_spread is not None:
            if term_spread < -1.0:
                curve_stress = 1.0
            elif term_spread < -0.3:
                curve_stress = 0.75
            elif term_spread < 0.2:
                curve_stress = 0.5
            else:
                curve_stress = 0.25
        else:
            curve_stress = 0.5

        # Composite stress score.
        stress_score = (
            0.28 * credit_score
            + 0.20 * vol_score
            + 0.20 * liq_stress
            + 0.15 * labor_score
            + 0.10 * growth_stress
            + 0.07 * curve_stress
        )

        phase = 1
        # A simple, transparent transition logic that non-experts can understand.
        if stress_score >= 0.58 or (credit_score >= 0.7 and (liq_stress >= 0.7 or vol_score >= 0.7)):
            phase = 2
        if phase >= 2 and usrec == 1 and (stress_score >= 0.66 or growth_stress >= 0.75):
            phase = 3
        if usrec == 1 and (stress_score >= 0.75 or growth_stress >= 1.0 or (vol_score >= 0.9 and credit_score >= 0.8)):
            phase = 4

        # Hysteresis to reduce flicker month to month.
        if prev_phase >= 2 and phase == 1 and stress_score >= 0.50:
            phase = 2
        if prev_phase >= 3 and phase == 2 and stress_score >= 0.68:
            phase = 3

        prev_phase = phase

        timeline.append(
            {
                "date": date,
                "phase": phase,
                "phaseName": PHASE_INFO[phase]["name"],
                "stressScore": round(stress_score, 4),
                "inputs": {
                    "creditSpreadProxyBAA10Y": baa10y,
                    "vix": vix,
                    "stlfsi": stlfsi,
                    "nfci": nfci,
                    "unrate": unrate,
                    "usrec": usrec,
                    "indproYoY": None if indpro_12m is None else round(indpro_12m, 3),
                    "termSpread10y3m": None if term_spread is None else round(term_spread, 3),
                },
                "confidence": "estimated" if year <= 1933 else "observed",
                "inputsAvailable": sum(1 for sid in SERIES if r[sid] is not None),
            }
        )

    payload = {
        "meta": {
            "title": "Collapse Cycle Phase Timeline",
            "generatedAtUTC": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
            "description": (
                "Monthly phase classification from historical and current macro-financial stress indicators. "
                "Early-history sections (including 1920s/1930s) are estimated due to limited high-frequency market microstructure data."
            ),
            "series": SERIES,
            "dataRequests": fetch_manifest,
            "phaseInfo": PHASE_INFO,
            "method": {
                "name": "Convergence model (proxy implementation)",
                "logicSummary": [
                    "Phase 1: low composite stress and no broad recession confirmation.",
                    "Phase 2: multiple stress components elevated simultaneously.",
                    "Phase 3: elevated stress with recession/trigger confirmation.",
                    "Phase 4: severe stress and cascade conditions.",
                ],
                "limitations": [
                    "FRED S&P 500 begins in 2016 for this endpoint; long equity drawdown context is represented via event overlays and macro proxies.",
                    "Pre-1948 unemployment and pre-1990 volatility are sparse or unavailable in modern formats.",
                    "Great Depression segment is explicitly marked estimated.",
                ],
            },
        },
        "events": EVENT_WINDOWS,
        "timeline": timeline,
    }

    OUTPUT_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {OUTPUT_FILE}")


if __name__ == "__main__":
    build()
