"""Turning a fetched page into the text an agent reads.

A page arrives as markdown far longer than an agent can be handed: a run reads
dozens, across researchers working in parallel. Two steps make the part it gets
count:

- ``clean`` drops what is never worth reading: images, and link targets too long
  to be anything but tracking (an Indeed results page spent half its length on
  ``pagead/clk?...`` URLs). A short link keeps its target, so a listing still
  leads somewhere.
- ``excerpt`` picks the passages that bear on what the agent says it is looking
  for, rather than whatever comes first. The top of a page is mostly its
  navigation and intro; the answer is wherever it is.
"""

import math
import re
import unicodedata
from collections import Counter

LINK_TARGET_MAX = 100  # chars; a longer URL is tracking, not a place to go
CHUNK_CHARS = 600  # a passage: small enough to skip, big enough to make sense
_GAP = "\n\n[...]\n\n"

_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_BLANK_RUNS = re.compile(r"\n{3,}")
_WORD = re.compile(r"\w+")


def clean(markdown: str) -> str:
    """The page without images and without link targets too long to follow."""
    text = _IMAGE.sub("", markdown)
    text = _LINK.sub(
        lambda m: m.group(0) if len(m.group(2)) <= LINK_TARGET_MAX else m.group(1),
        text,
    )
    return _BLANK_RUNS.sub("\n\n", text).strip()


def excerpt(text: str, focus: str, limit: int) -> str:
    """At most ``limit`` chars of ``text``: all of it when it fits, else the
    passages that best match ``focus``, in page order, with the gaps marked.
    With no focus, or none of its words on the page, it is the head of the
    page."""
    if len(text) <= limit:
        return text
    chunks = _chunks(text)
    scores = _bm25(chunks, focus)
    picked: set[int] = set()
    used = 0
    for i in sorted(range(len(chunks)), key=lambda i: -scores[i]):
        if scores[i] <= 0 or used + len(chunks[i]) + len(_GAP) > limit:
            continue
        picked.add(i)
        used += len(chunks[i]) + len(_GAP)
    if not picked:
        return text[:limit] + "\n\n[...truncated]"
    out = "[...]\n\n" if 0 not in picked else ""
    last = None
    for i in sorted(picked):
        if last is not None:
            out += "\n" if i == last + 1 else _GAP
        out += chunks[i]
        last = i
    return out + ("" if last == len(chunks) - 1 else "\n\n[...]")


def _chunks(text: str) -> list[str]:
    """The page as consecutive passages of at most ``CHUNK_CHARS``, cut on line
    breaks. Not on paragraphs: a results page is often one "paragraph" of
    10,000 characters, too big to ever fit, so the listings it holds were the
    one part an agent could never be shown. Joined with newlines, the passages
    are the page (bar a line longer than a passage, which is cut in pieces)."""
    lines = [
        line[i : i + CHUNK_CHARS]
        for line in text.split("\n")
        for i in range(0, max(len(line), 1), CHUNK_CHARS)
    ]
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines:
        if current and size + len(line) > CHUNK_CHARS:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def _terms(text: str) -> list[str]:
    """Words folded for matching: lowercase, accents off, cut to a six-letter
    stem so "recrute" meets "recrutement" and "hiring" meets "hires"."""
    # ponytail: crude stemming, language-blind; a real stemmer if matches miss.
    folded = unicodedata.normalize("NFKD", text.lower())
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return [w[:6] for w in _WORD.findall(folded) if len(w) > 1]


def _bm25(
    chunks: list[str], query: str, k1: float = 1.5, b: float = 0.75
) -> list[float]:
    """Okapi BM25 of each chunk against the query, with the page as the corpus:
    a word on every passage (the site's name, "emploi" on a job board) counts
    for little, a word on few counts for a lot."""
    wanted = set(_terms(query))
    if not wanted:
        return [0.0] * len(chunks)
    docs = [Counter(_terms(c)) for c in chunks]
    avg = sum(sum(d.values()) for d in docs) / len(docs) or 1
    n = len(docs)
    idf = {
        t: math.log(1 + (n - df + 0.5) / (df + 0.5))
        for t in wanted
        if (df := sum(1 for d in docs if t in d))
    }
    scores = []
    for d in docs:
        size = sum(d.values())
        scores.append(
            sum(
                idf[t] * d[t] * (k1 + 1) / (d[t] + k1 * (1 - b + b * size / avg))
                for t in idf
                if t in d
            )
        )
    return scores
