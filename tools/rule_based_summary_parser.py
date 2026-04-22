#!/usr/bin/env python3
"""Deterministic, rule-based summary parser (no ML/AI).

Pipeline:
1) Clean input
2) Split into sentences
3) Score sentences with transparent rules
4) Deduplicate by overlap
5) Emit concise plain-English summary
"""

from __future__ import annotations

import argparse
import html
import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, List, Sequence


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "for",
    "from",
    "has",
    "have",
    "he",
    "her",
    "his",
    "i",
    "in",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "she",
    "that",
    "the",
    "their",
    "they",
    "this",
    "to",
    "was",
    "we",
    "were",
    "will",
    "with",
    "you",
    "your",
}

TONE_MARKERS = (
    "in conclusion",
    "overall",
    "key",
    "important",
    "notably",
    "significant",
    "as a result",
    "therefore",
    "in summary",
)

CAUSE_EFFECT_MARKERS = (
    "because",
    "due to",
    "driven by",
    "led to",
    "leads to",
    "resulted in",
    "results in",
    "caused",
    "causes",
    "as a result",
)

JARGON_MAP = {
    "leverage": "use",
    "utilize": "use",
    "synergy": "cooperation",
    "paradigm": "model",
    "bandwidth": "capacity",
    "stakeholders": "groups involved",
    "robust": "strong",
    "optimize": "improve",
    "granular": "detailed",
    "methodology": "method",
}

SUBJECT_WORDS = {
    "company",
    "market",
    "government",
    "team",
    "report",
    "data",
    "results",
    "policy",
    "analysts",
    "investors",
    "managers",
    "industry",
    "economy",
    "it",
    "they",
    "we",
    "he",
    "she",
}

VERB_WORDS = {
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "grow",
    "grew",
    "fall",
    "fell",
    "rise",
    "rose",
    "increase",
    "decrease",
    "show",
    "shows",
    "reported",
    "report",
    "expect",
    "expects",
    "said",
    "say",
}


@dataclass
class SentenceCandidate:
    text: str
    index: int
    paragraph_index: int
    score: float
    token_set: set[str]


def tokenize(text: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9']+", text.lower())


def normalize_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return text


def strip_html_noise(text: str) -> str:
    text = html.unescape(text)
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"https?://\S+|www\.\S+", " ", text)
    # Remove emojis / high Unicode symbols that usually add noise in summaries.
    text = re.sub(r"[\U00010000-\U0010FFFF]", " ", text)
    return text


def merge_broken_lines(text: str) -> str:
    """Merge broken lines into coherent paragraphs."""
    lines = [ln.strip() for ln in text.split("\n")]
    paragraphs: List[str] = []
    current: List[str] = []

    for line in lines:
        if not line:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue

        if current and current[-1].endswith("-"):
            current[-1] = current[-1][:-1] + line
        else:
            current.append(line)

    if current:
        paragraphs.append(" ".join(current))

    return "\n\n".join(paragraphs)


def clean_input(raw_text: str) -> str:
    text = strip_html_noise(raw_text)
    text = normalize_whitespace(text)
    text = merge_broken_lines(text)
    # Keep sentence punctuation, remove most stray symbols.
    text = re.sub(r"[^A-Za-z0-9\s\.\,\!\?\:\;\-\%\$\n]", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def split_sentences(text: str) -> List[tuple[str, int]]:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    sentence_rows: List[tuple[str, int]] = []

    splitter = re.compile(r"(?<=[.!?])\s+")
    for p_idx, paragraph in enumerate(paragraphs):
        rough = splitter.split(paragraph)
        for part in rough:
            # Secondary split to break overly long semicolon chains.
            sub_parts = re.split(r"(?<=;)\s+", part)
            for sub in sub_parts:
                sentence = sub.strip()
                if sentence:
                    sentence_rows.append((sentence, p_idx))
    return sentence_rows


def has_subject_verb(sentence: str) -> bool:
    tokens = tokenize(sentence)
    if len(tokens) < 3:
        return False
    has_subject = any(tok in SUBJECT_WORDS for tok in tokens) or any(tok not in STOPWORDS for tok in tokens)
    has_verb = any(tok in VERB_WORDS for tok in tokens) or any(tok.endswith(("ed", "ing", "es")) for tok in tokens)
    return has_subject and has_verb


def frequency_weights(sentences: Sequence[str], top_k: int = 25) -> Counter[str]:
    all_tokens: List[str] = []
    for sentence in sentences:
        all_tokens.extend([t for t in tokenize(sentence) if t not in STOPWORDS and len(t) > 2])
    freq = Counter(all_tokens)
    return Counter(dict(freq.most_common(top_k)))


def title_keywords(title: str) -> set[str]:
    return {t for t in tokenize(title) if t not in STOPWORDS and len(t) > 2}


def low_signal_only(tokens: Sequence[str]) -> bool:
    signal = [t for t in tokens if t not in STOPWORDS and len(t) > 2]
    return len(signal) < 2


def score_sentence(
    sentence: str,
    idx: int,
    p_idx: int,
    total_sentences: int,
    paragraph_count: int,
    title_terms: set[str],
    freq_map: Counter[str],
) -> float:
    tokens = tokenize(sentence)
    token_set = set(tokens)
    score = 0.0

    # Keyword overlap with title.
    overlap = len(token_set & title_terms)
    score += overlap * 2.5

    # Frequency importance from repeated key terms.
    freq_score = sum(freq_map.get(t, 0) for t in token_set if t in freq_map)
    score += min(5.0, freq_score / 8.0)

    # Position rules: intro and conclusion emphasized.
    if idx <= 2:
        score += 2.0
    if idx >= max(0, total_sentences - 3):
        score += 2.0
    if p_idx == 0:
        score += 2.2
    if p_idx == max(0, paragraph_count - 1):
        score += 2.2

    # Numbers / statistics.
    if re.search(r"\d", sentence):
        score += 1.5
    if re.search(r"\d+(\.\d+)?\s*%|\$[\d,]+", sentence):
        score += 1.0

    # Tone markers.
    lowered = sentence.lower()
    score += sum(1.0 for marker in TONE_MARKERS if marker in lowered)
    score += sum(1.1 for marker in CAUSE_EFFECT_MARKERS if marker in lowered)

    # Penalties.
    length = len(tokens)
    if length < 5:
        score -= 2.5
    if length > 40:
        score -= 1.8
    if sentence.strip().endswith("?"):
        score -= 0.9
    if low_signal_only(tokens):
        score -= 2.2
    if not has_subject_verb(sentence):
        score -= 3.0

    return score


def overlap_ratio(a_tokens: set[str], b_tokens: set[str]) -> float:
    if not a_tokens or not b_tokens:
        return 0.0
    return len(a_tokens & b_tokens) / min(len(a_tokens), len(b_tokens))


def dedupe_candidates(candidates: Sequence[SentenceCandidate], threshold: float = 0.7) -> List[SentenceCandidate]:
    kept: List[SentenceCandidate] = []
    for cand in sorted(candidates, key=lambda c: c.score, reverse=True):
        if any(overlap_ratio(cand.token_set, prev.token_set) >= threshold for prev in kept):
            continue
        kept.append(cand)
    return kept


def simplify_jargon(text: str) -> str:
    out = text
    for src, tgt in JARGON_MAP.items():
        out = re.sub(rf"\b{re.escape(src)}\b", tgt, out, flags=re.IGNORECASE)
    return out


def normalize_sentence_output(sentence: str) -> str:
    sentence = sentence.strip()
    if not sentence:
        return ""
    sentence = simplify_jargon(sentence)
    sentence = re.sub(r"https?://\S+|www\.\S+", "", sentence)
    sentence = re.sub(r"[^A-Za-z0-9\s\.\,\!\?\:\;\-\%\$]", " ", sentence)
    sentence = re.sub(r"\s{2,}", " ", sentence).strip()
    sentence = re.sub(r"\(([^)]{36,})\)", "", sentence).strip()
    if sentence and sentence[0].islower():
        sentence = sentence[0].upper() + sentence[1:]
    # Keep readability near 8th-grade by trimming long lines.
    words = sentence.split()
    if len(words) > 34:
        sentence = " ".join(words[:34]).rstrip(",;:") + "."
    if sentence and sentence[-1] not in ".!?":
        sentence += "."
    return sentence


def score_readability(sentence: str) -> float:
    tokens = tokenize(sentence)
    if not tokens:
        return 0.0
    long_words = sum(1 for t in tokens if len(t) >= 11)
    comma_bonus = 0.2 if "," in sentence and len(tokens) >= 10 else 0.0
    # Favor concise, clear lines and penalize very dense wording.
    return max(0.0, 1.6 - long_words * 0.22 + comma_bonus)


def truncate_to_word_limit(sentence: str, word_limit: int = 28) -> str:
    words = sentence.split()
    if len(words) <= word_limit:
        return sentence
    clipped = " ".join(words[:word_limit]).rstrip(",;:")
    if clipped and clipped[-1] not in ".!?":
        clipped += "."
    return clipped


def summarize_article(
    title: str,
    raw_text: str,
    max_sentences: int = 5,
    min_sentences: int = 3,
) -> str:
    max_sentences = max(1, min(max_sentences, 7))
    min_sentences = max(1, min(min_sentences, max_sentences))
    cleaned = clean_input(raw_text)
    if not cleaned:
        return ""

    rows = split_sentences(cleaned)
    if not rows:
        return ""

    sentences = [s for s, _ in rows]
    para_count = max(p for _, p in rows) + 1 if rows else 1
    title_terms = title_keywords(title)
    freq_map = frequency_weights(sentences)

    candidates: List[SentenceCandidate] = []
    for idx, (sentence, p_idx) in enumerate(rows):
        score = score_sentence(
            sentence=sentence,
            idx=idx,
            p_idx=p_idx,
            total_sentences=len(rows),
            paragraph_count=para_count,
            title_terms=title_terms,
            freq_map=freq_map,
        )
        token_set = {t for t in tokenize(sentence) if t not in STOPWORDS}
        # Hard discard of obvious fragments before final output.
        if has_subject_verb(sentence):
            candidates.append(
                SentenceCandidate(
                    text=sentence,
                    index=idx,
                    paragraph_index=p_idx,
                    score=score,
                    token_set=token_set,
                )
            )

    if not candidates:
        return ""

    deduped = dedupe_candidates(candidates, threshold=0.7)
    # Blend structural score with readability to keep output plain-English.
    reranked = sorted(
        deduped,
        key=lambda c: (c.score + score_readability(c.text), -c.index),
        reverse=True,
    )
    selected = sorted(reranked[:max_sentences], key=lambda c: c.index)

    # Enforce minimum sentence output target where possible.
    if len(selected) < min_sentences:
        extras = [c for c in sorted(candidates, key=lambda c: c.score, reverse=True) if c not in selected]
        for cand in extras:
            selected.append(cand)
            if len(selected) >= min_sentences:
                break
        selected = sorted(selected, key=lambda c: c.index)

    output_sentences: List[str] = []
    for cand in selected[:6]:
        normalized = normalize_sentence_output(cand.text)
        normalized = truncate_to_word_limit(normalized, word_limit=28)
        if normalized:
            output_sentences.append(normalized)

    # Remove accidental repeated lines after normalization.
    unique_output: List[str] = []
    seen = set()
    for sentence in output_sentences:
        key = sentence.lower()
        if key in seen:
            continue
        seen.add(key)
        unique_output.append(sentence)

    return " ".join(unique_output[:6]).strip()


def _read_input_text(args: argparse.Namespace) -> str:
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            return f.read()
    if args.text:
        return args.text
    return input("Paste article text:\n")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dynamic rule-based summary parser (deterministic, no ML).")
    parser.add_argument("--title", default="", help="Article title (used for keyword overlap scoring).")
    parser.add_argument("--text", default="", help="Raw article text input.")
    parser.add_argument("--file", default="", help="Path to text file containing article text.")
    parser.add_argument(
        "--max-sentences",
        type=int,
        default=5,
        help="Target max sentences in summary (clamped to 3..7, final output capped at 6).",
    )
    parser.add_argument(
        "--min-sentences",
        type=int,
        default=3,
        help="Minimum output sentences when enough candidates exist (default: 3).",
    )
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    text = _read_input_text(args)
    summary = summarize_article(
        args.title,
        text,
        max_sentences=args.max_sentences,
        min_sentences=args.min_sentences,
    )
    print(summary if summary else "No usable summary could be generated from input.")


if __name__ == "__main__":
    main()
