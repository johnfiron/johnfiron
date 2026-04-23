#!/usr/bin/env python3
"""Build static supplemental factor references used as fallback/context.

This intentionally does NOT pre-rank per-click metric evidence. That is fetched
dynamically in the browser at click time from OpenAlex/Crossref.
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
OUTPUT_FILE = DATA_DIR / "evidence_supplemental.json"
USER_AGENT = "johnfiron-collapse-dashboard/1.0 (supplemental references builder)"


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
    score: float
    summary: str


def http_json(url: str, timeout: int = 25) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def strip_html_tags(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def normalize_doi_url(value: str) -> str:
    if not value:
        return ""
    value = value.strip()
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if value.lower().startswith("doi.org/"):
        return "https://" + value
    return f"https://doi.org/{value}"


def score_record(text: str, query: str, year: Optional[int], now_year: int) -> float:
    text_tokens = set(re.findall(r"[a-z0-9]+", text.lower()))
    q_tokens = [t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 2]
    overlap = sum(1 for t in q_tokens if t in text_tokens)
    recency = 0.0
    if year is not None:
        recency = max(0.0, 1.0 - min(20, now_year - year) / 20.0)
    return overlap * 2.0 + recency


def compact_summary(title: str, text: str) -> str:
    summary = summarize_article(title, text, max_sentences=2, min_sentences=1)
    return summary or "Summary unavailable from source metadata."


def fetch_openalex(query: str, per_page: int = 4) -> List[dict]:
    encoded = urllib.parse.quote(query)
    url = (
        "https://api.openalex.org/works?"
        f"search={encoded}&per-page={per_page}&select=display_name,publication_year,doi,id,abstract_inverted_index"
    )
    try:
        return http_json(url).get("results", [])
    except Exception:
        return []


def fetch_crossref(query: str, rows: int = 4) -> List[dict]:
    encoded = urllib.parse.quote(query)
    url = f"https://api.crossref.org/works?query={encoded}&rows={rows}"
    try:
        return http_json(url).get("message", {}).get("items", [])
    except Exception:
        return []


def invert_openalex_index(abstract_index: Optional[dict]) -> str:
    if not abstract_index:
        return ""
    words: List[tuple[int, str]] = []
    for token, positions in abstract_index.items():
        for pos in positions:
            words.append((pos, token))
    words.sort(key=lambda x: x[0])
    return " ".join(token for _, token in words)


def build_supplemental_fed_factors() -> List[dict]:
    now_year = dt.datetime.now(dt.timezone.utc).year
    output: List[dict] = []

    for factor in SUPPLEMENTAL_FED_FACTORS:
        items: List[EvidenceItem] = [
            EvidenceItem(
                source_type="fed-report",
                title=f"Federal Reserve reference: {factor['label']}",
                url=factor["reportUrl"],
                year=now_year,
                score=9.0,
                summary=factor["description"],
            )
        ]
        query_status: List[dict] = []

        for query in factor["queries"]:
            o_count = 0
            c_count = 0

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
                        score=score_record(combined, query, year, now_year),
                        summary=compact_summary(title, combined),
                    )
                )
                o_count += 1

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
                        score=score_record(combined, query, year, now_year),
                        summary=compact_summary(title, combined),
                    )
                )
                c_count += 1

            query_status.append(
                {
                    "query": query,
                    "openalexResults": o_count,
                    "crossrefResults": c_count,
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
    supplemental_factors = build_supplemental_fed_factors()
    payload = {
        "meta": {
            "generatedAtUTC": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
            "description": (
                "Supplemental Fed-related factors outside core stress-score inputs. "
                "Used as context and fallback references."
            ),
            "summaryMethod": "rule_based_summary_parser.py (deterministic, no ML)",
            "stats": {
                "supplementalFedFactors": len(supplemental_factors),
                "totalItems": sum(len(f.get('evidence', [])) for f in supplemental_factors),
            },
        },
        "supplementalFactors": supplemental_factors,
    }
    OUTPUT_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {OUTPUT_FILE}")


if __name__ == "__main__":
    build()
