#!/usr/bin/env python3
"""Build deterministic cause/effect evidence links for timeline data points.

Outputs:
  - data/evidence_data.json

This script gathers:
  - Academic paper candidates (OpenAlex API)
  - News/article candidates (Crossref works endpoint with relation weighting)
Then generates rule-based summaries using tools/rule_based_summary_parser.py.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from rule_based_summary_parser import summarize_article


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
TIMELINE_FILE = DATA_DIR / "timeline_data.json"
OUTPUT_FILE = DATA_DIR / "evidence_data.json"
USER_AGENT = "johnfiron-collapse-dashboard/1.0 (research index builder)"


DATA_POINT_CONFIG = {
    "creditSpreadProxyBAA10Y": {
        "label": "Credit spread proxy (BAA-10Y)",
        "queries": [
            "credit spreads recession risk transmission financial stress",
            "corporate bond spread macroeconomic downturn evidence",
        ],
        "cause": "credit risk repricing",
        "effect": "higher funding costs and tighter financial conditions",
    },
    "vix": {
        "label": "Equity volatility (VIX)",
        "queries": [
            "VIX volatility macro uncertainty downturn evidence",
            "equity implied volatility financial crisis transmission",
        ],
        "cause": "uncertainty shock",
        "effect": "de-risking and lower risk-asset demand",
    },
    "stlfsi": {
        "label": "St. Louis financial stress index",
        "queries": [
            "financial stress index recession forecasting evidence",
            "systemic stress index growth slowdown transmission",
        ],
        "cause": "system-wide funding and risk stress",
        "effect": "reduced credit creation and weaker activity",
    },
    "nfci": {
        "label": "Chicago Fed NFCI",
        "queries": [
            "national financial conditions index growth forecasting",
            "tight financial conditions and economic slowdown evidence",
        ],
        "cause": "tight financial conditions",
        "effect": "slower investment and hiring",
    },
    "unrate": {
        "label": "Unemployment rate",
        "queries": [
            "unemployment rise recession dynamics evidence",
            "labor market weakness consumption slowdown transmission",
        ],
        "cause": "labor market deterioration",
        "effect": "weaker income growth and softer demand",
    },
    "indproYoY": {
        "label": "Industrial production YoY",
        "queries": [
            "industrial production contraction recession signal",
            "manufacturing output decline macro cycle evidence",
        ],
        "cause": "real activity slowdown",
        "effect": "lower earnings momentum and rising stress",
    },
    "termSpread10y3m": {
        "label": "Term spread (10Y-3M)",
        "queries": [
            "yield curve inversion recession probability evidence",
            "term spread predictive power economic downturn",
        ],
        "cause": "inverted or flat term structure",
        "effect": "tighter credit channel and weaker future growth expectations",
    },
}

SUPPLEMENTAL_FED_FACTORS = [
    {
        "factorId": "bank-lending-standards",
        "label": "Bank lending standards (SLOOS channel)",
        "description": (
            "Tighter bank lending standards can slow credit growth even before headline stress "
            "indicators spike."
        ),
        "reportUrl": "https://www.federalreserve.gov/publications/financial-stability-report.htm",
        "queries": [
            "Federal Reserve bank lending standards financial stability report",
            "senior loan officer opinion survey lending standards recession",
        ],
        "relatedMetrics": ["creditSpreadProxyBAA10Y", "nfci", "unrate"],
        "notInStressScore": True,
    },
    {
        "factorId": "treasury-market-liquidity",
        "label": "Treasury market liquidity and basis pressure",
        "description": (
            "Treasury liquidity disruptions can transmit stress rapidly across funding and risk assets."
        ),
        "reportUrl": "https://www.federalreserve.gov/publications/financial-stability-report.htm",
        "queries": [
            "Federal Reserve Treasury market liquidity vulnerabilities",
            "Treasury basis trade leverage systemic risk report",
        ],
        "relatedMetrics": ["stlfsi", "vix", "termSpread10y3m"],
        "notInStressScore": True,
    },
    {
        "factorId": "private-credit-and-nonbank-leverage",
        "label": "Private credit and nonbank leverage risk",
        "description": (
            "Leverage in nonbank finance can amplify shocks through refinancing and forced deleveraging."
        ),
        "reportUrl": "https://www.federalreserve.gov/publications/financial-stability-report.htm",
        "queries": [
            "Federal Reserve nonbank leverage private credit vulnerabilities",
            "private credit refinancing risk macro financial stability",
        ],
        "relatedMetrics": ["creditSpreadProxyBAA10Y", "stlfsi", "nfci"],
        "notInStressScore": True,
    },
    {
        "factorId": "commercial-real-estate-refinancing",
        "label": "Commercial real estate refinancing risk",
        "description": (
            "Commercial real estate valuation and refinancing pressure can weaken lender balance sheets."
        ),
        "reportUrl": "https://www.federalreserve.gov/publications/financial-stability-report.htm",
        "queries": [
            "Federal Reserve commercial real estate refinancing risk report",
            "CRE refinancing risk bank balance sheet stress",
        ],
        "relatedMetrics": ["creditSpreadProxyBAA10Y", "unrate", "nfci"],
        "notInStressScore": True,
    },
]


@dataclass
class EvidenceItem:
    source_type: str
    title: str
    url: str
    year: Optional[int]
    abstract_or_excerpt: str
    score: float
    summary: str


def normalize_doi_url(value: str) -> str:
    if not value:
        return ""
    value = value.strip()
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if value.lower().startswith("doi.org/"):
        return "https://" + value
    return f"https://doi.org/{value}"


def compact_summary(title: str, text: str) -> str:
    summary = summarize_article(title, text, max_sentences=3, min_sentences=2)
    tokens = re.findall(r"[A-Za-z0-9']+", summary)
    if summary and len(tokens) >= 8:
        return summary
    fallback = summarize_article(title, title, max_sentences=1, min_sentences=1)
    if fallback:
        return fallback
    return "Summary unavailable from source metadata."


def http_json(url: str, timeout: int = 25) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def strip_html_tags(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def invert_openalex_index(abstract_index: Optional[dict]) -> str:
    if not abstract_index:
        return ""
    words: List[tuple[int, str]] = []
    for token, positions in abstract_index.items():
        for pos in positions:
            words.append((pos, token))
    words.sort(key=lambda x: x[0])
    return " ".join(token for _, token in words)


def score_record(text: str, query: str, year: Optional[int], now_year: int) -> float:
    text_tokens = set(re.findall(r"[a-z0-9]+", text.lower()))
    q_tokens = [t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 2]
    overlap = sum(1 for t in q_tokens if t in text_tokens)
    recency = 0.0
    if year is not None:
        recency = max(0.0, 1.0 - min(20, now_year - year) / 20.0)
    return overlap * 2.0 + recency


def fetch_openalex(query: str, per_page: int = 6) -> List[dict]:
    encoded = urllib.parse.quote(query)
    url = (
        "https://api.openalex.org/works?"
        f"search={encoded}&per-page={per_page}&select=display_name,publication_year,doi,id,abstract_inverted_index"
    )
    try:
        data = http_json(url)
        return data.get("results", [])
    except Exception:
        return []


def fetch_crossref(query: str, rows: int = 6) -> List[dict]:
    encoded = urllib.parse.quote(query)
    url = f"https://api.crossref.org/works?query={encoded}&rows={rows}"
    try:
        data = http_json(url)
        return data.get("message", {}).get("items", [])
    except Exception:
        return []


def build_evidence_for_metric(metric_key: str, cfg: dict) -> dict:
    now_year = dt.datetime.now(dt.timezone.utc).year
    items: List[EvidenceItem] = []
    query_status: List[dict] = []

    for query in cfg["queries"]:
        openalex_count = 0
        crossref_count = 0

        # Papers from OpenAlex
        for rec in fetch_openalex(query, per_page=5):
            title = (rec.get("display_name") or "").strip()
            year = rec.get("publication_year")
            doi = rec.get("doi")
            rec_id = rec.get("id")
            url = normalize_doi_url(doi) if doi else (rec_id or "")
            abstract = invert_openalex_index(rec.get("abstract_inverted_index"))
            if not title or not url:
                continue
            combined = f"{title}. {abstract}".strip()
            summary = compact_summary(title, combined)
            score = score_record(combined, query, year, now_year)
            items.append(
                EvidenceItem(
                    source_type="paper",
                    title=title,
                    url=url,
                    year=year,
                    abstract_or_excerpt=abstract[:1400],
                    score=score,
                    summary=summary,
                )
            )
            openalex_count += 1

        # Articles / reports from Crossref
        for rec in fetch_crossref(query, rows=5):
            titles = rec.get("title", [])
            title = (titles[0] if titles else "").strip()
            year = None
            issued = rec.get("issued", {}).get("date-parts", [])
            if issued and issued[0]:
                year = issued[0][0]
            url = rec.get("URL", "")
            abstract = strip_html_tags(rec.get("abstract", "") or "")
            container = (rec.get("container-title") or [""])[0]
            excerpt = f"{container}. {abstract}".strip()
            if not title or not url:
                continue
            combined = f"{title}. {excerpt}".strip()
            summary = compact_summary(title, combined)
            score = score_record(combined, query, year, now_year)
            items.append(
                EvidenceItem(
                    source_type="article",
                    title=title,
                    url=url,
                    year=year,
                    abstract_or_excerpt=excerpt[:1400],
                    score=score,
                    summary=summary,
                )
            )
            crossref_count += 1

        query_status.append(
            {
                "query": query,
                "openalexResults": openalex_count,
                "crossrefResults": crossref_count,
            }
        )

    # Deduplicate by URL/title and keep best score.
    best_by_key: Dict[str, EvidenceItem] = {}
    for item in items:
        key = (item.url or item.title).lower()
        if key not in best_by_key or item.score > best_by_key[key].score:
            best_by_key[key] = item

    ranked = sorted(best_by_key.values(), key=lambda x: x.score, reverse=True)[:6]
    paper_count = sum(1 for item in ranked if item.source_type == "paper")
    article_count = sum(1 for item in ranked if item.source_type == "article")
    related_fed_factors = [
        factor["factorId"]
        for factor in SUPPLEMENTAL_FED_FACTORS
        if metric_key in factor.get("relatedMetrics", [])
    ]

    return {
        "metricKey": metric_key,
        "label": cfg["label"],
        "causeHint": cfg["cause"],
        "effectHint": cfg["effect"],
        "queries": cfg["queries"],
        "queryStatus": query_status,
        "paperCount": paper_count,
        "articleCount": article_count,
        "relatedFedFactors": related_fed_factors,
        "evidence": [
            {
                "sourceType": item.source_type,
                "title": item.title,
                "url": item.url,
                "year": item.year,
                "score": round(item.score, 3),
                "summary": item.summary or "No clean summary available from source metadata.",
            }
            for item in ranked
        ],
    }


def build_contextual_month_links(timeline: List[dict]) -> List[dict]:
    """Attach a compact month-level mapping to help UI connect datapoints to evidence."""
    out: List[dict] = []
    for row in timeline[-36:]:
        # Keep last 3 years to limit payload size.
        inputs = row.get("inputs", {})
        out.append(
            {
                "date": row.get("date"),
                "phase": row.get("phase"),
                "stressScore": row.get("stressScore"),
                "availableDataPoints": [
                    key for key in DATA_POINT_CONFIG if inputs.get(key) is not None
                ],
            }
        )
    return out


def build_supplemental_fed_factors() -> List[dict]:
    now_year = dt.datetime.now(dt.timezone.utc).year
    output: List[dict] = []

    for factor in SUPPLEMENTAL_FED_FACTORS:
        items: List[EvidenceItem] = []
        query_status: List[dict] = []

        # Include direct Fed report reference as a fixed anchor.
        items.append(
            EvidenceItem(
                source_type="fed-report",
                title=f"Federal Reserve reference: {factor['label']}",
                url=factor["reportUrl"],
                year=now_year,
                abstract_or_excerpt=factor["description"],
                score=9.0,
                summary=factor["description"],
            )
        )

        for query in factor["queries"]:
            openalex_count = 0
            crossref_count = 0

            for rec in fetch_openalex(query, per_page=3):
                title = (rec.get("display_name") or "").strip()
                year = rec.get("publication_year")
                doi = rec.get("doi")
                rec_id = rec.get("id")
                url = normalize_doi_url(doi) if doi else (rec_id or "")
                abstract = invert_openalex_index(rec.get("abstract_inverted_index"))
                if not title or not url:
                    continue
                combined = f"{title}. {abstract}".strip()
                items.append(
                    EvidenceItem(
                        source_type="paper",
                        title=title,
                        url=url,
                        year=year,
                        abstract_or_excerpt=abstract[:1000],
                        score=score_record(combined, query, year, now_year),
                        summary=compact_summary(title, combined),
                    )
                )
                openalex_count += 1

            for rec in fetch_crossref(query, rows=3):
                titles = rec.get("title", [])
                title = (titles[0] if titles else "").strip()
                year = None
                issued = rec.get("issued", {}).get("date-parts", [])
                if issued and issued[0]:
                    year = issued[0][0]
                url = rec.get("URL", "")
                abstract = strip_html_tags(rec.get("abstract", "") or "")
                container = (rec.get("container-title") or [""])[0]
                excerpt = f"{container}. {abstract}".strip()
                if not title or not url:
                    continue
                combined = f"{title}. {excerpt}".strip()
                items.append(
                    EvidenceItem(
                        source_type="article",
                        title=title,
                        url=url,
                        year=year,
                        abstract_or_excerpt=excerpt[:1000],
                        score=score_record(combined, query, year, now_year),
                        summary=compact_summary(title, combined),
                    )
                )
                crossref_count += 1

            query_status.append(
                {
                    "query": query,
                    "openalexResults": openalex_count,
                    "crossrefResults": crossref_count,
                }
            )

        dedup: Dict[str, EvidenceItem] = {}
        for item in items:
            key = (item.url or item.title).lower()
            if key not in dedup or item.score > dedup[key].score:
                dedup[key] = item
        ranked = sorted(dedup.values(), key=lambda x: x.score, reverse=True)[:5]

        output.append(
            {
                "factorId": factor["factorId"],
                "label": factor["label"],
                "description": factor["description"],
                "notInStressScore": factor["notInStressScore"],
                "relatedMetrics": factor["relatedMetrics"],
                "queryStatus": query_status,
                "evidence": [
                    {
                        "sourceType": item.source_type,
                        "title": item.title,
                        "url": item.url,
                        "year": item.year,
                        "score": round(item.score, 3),
                        "summary": item.summary,
                    }
                    for item in ranked
                ],
            }
        )
    return output


def build() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    timeline_payload = json.loads(TIMELINE_FILE.read_text(encoding="utf-8"))
    timeline = timeline_payload.get("timeline", [])

    metric_evidence = []
    for key, cfg in DATA_POINT_CONFIG.items():
        metric_evidence.append(build_evidence_for_metric(key, cfg))
    supplemental_factors = build_supplemental_fed_factors()

    summary_stats = {
        "metrics": len(metric_evidence),
        "withEvidence": sum(1 for m in metric_evidence if m.get("evidence")),
        "totalItems": sum(len(m.get("evidence", [])) for m in metric_evidence),
        "totalPapers": sum(m.get("paperCount", 0) for m in metric_evidence),
        "totalArticles": sum(m.get("articleCount", 0) for m in metric_evidence),
        "supplementalFedFactors": len(supplemental_factors),
    }

    payload = {
        "meta": {
            "generatedAtUTC": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
            "description": (
                "Deterministic cause/effect evidence index for timeline metrics. "
                "Sources are searched dynamically and summarized with a rule-based parser."
            ),
            "sourceEngines": ["OpenAlex", "Crossref"],
            "summaryMethod": "rule_based_summary_parser.py (deterministic, no ML)",
            "stats": summary_stats,
        },
        "monthDataPointIndex": build_contextual_month_links(timeline),
        "metrics": metric_evidence,
        "supplementalFactors": supplemental_factors,
    }

    OUTPUT_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {OUTPUT_FILE}")


if __name__ == "__main__":
    build()
