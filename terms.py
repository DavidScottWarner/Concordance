"""Load a term list and find whole-word matches."""

import csv
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

MAX_SENTENCE_WORDS = 80
CONTEXT_WORDS = 40
TERM_COLUMNS = ("category", "term", "stem")


@dataclass
class Term:
    category: str
    term: str
    stem: str
    definition: str = ""


@dataclass
class Exclusion:
    """A phrase that removes term matches falling inside it. A blank category applies to every category."""

    category: str
    phrase: str


@dataclass
class Hit:
    start: int
    end: int
    term: str


def load_terms(path):
    """Read a term list. Blank rows are ignored."""
    path = Path(path)
    try:
        handle = path.open(newline="", encoding="utf-8-sig")
    except OSError as error:
        raise RuntimeError(f"The term list could not be opened: {path}") from error

    with handle:
        reader = csv.DictReader(handle)
        fieldnames = [name.strip().lower() for name in (reader.fieldnames or []) if name]
        missing = [name for name in TERM_COLUMNS if name not in fieldnames]
        if missing:
            raise RuntimeError(
                "The term list needs columns named category, term, and stem. "
                f"This one is missing: {', '.join(missing)}."
            )
        terms = []
        for row in reader:
            lowered = {
                (key or "").strip().lower(): (value or "").strip()
                for key, value in row.items()
                if key
            }
            category = lowered.get("category", "")
            term = lowered.get("term", "")
            stem = lowered.get("stem", "")
            definition = lowered.get("definition", "")
            if category and term:
                terms.append(
                    Term(category=category, term=term, stem=stem, definition=definition)
                )
    if not terms:
        raise RuntimeError("The term list has no terms.")
    return terms


def write_terms(path, terms):
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(TERM_COLUMNS))
        writer.writeheader()
        for term in terms:
            writer.writerow(
                {"category": term.category, "term": term.term, "stem": term.stem}
            )


def load_exclusions(path):
    """Read an exclusion list. The file is not changed. A blank category applies to every category."""
    path = Path(path)
    try:
        handle = path.open(newline="", encoding="utf-8-sig")
    except OSError as error:
        raise RuntimeError(f"The exclusion list could not be opened: {path}") from error

    with handle:
        reader = csv.DictReader(handle)
        fieldnames = [name.strip().lower() for name in (reader.fieldnames or []) if name]
        missing = [name for name in ("category", "phrase") if name not in fieldnames]
        if missing:
            raise RuntimeError(
                "The exclusion list needs columns named category and phrase. "
                f"This one is missing: {', '.join(missing)}."
            )
        rules = []
        seen = set()
        for row in reader:
            lowered = {
                (key or "").strip().lower(): (value or "").strip()
                for key, value in row.items()
                if key
            }
            phrase = lowered.get("phrase", "")
            category = lowered.get("category", "")
            if not phrase:
                continue
            key = (category.casefold(), phrase.casefold())
            if key in seen:
                continue
            seen.add(key)
            rules.append(Exclusion(category=category, phrase=phrase))
    return rules


def category_definitions(terms):
    """The first non-blank definition for each category, in file order."""
    found = {}
    for term in terms:
        text = (term.definition or "").strip()
        if text and term.category not in found:
            found[term.category] = text
    return found


def rules_for_category(rules, category):
    """Phrases for this category, plus phrases whose category is blank."""
    return [
        rule
        for rule in rules
        if not rule.category or rule.category.casefold() == category.casefold()
    ]


def categories_in_order(terms):
    ordered = []
    for term in terms:
        if term.category not in ordered:
            ordered.append(term.category)
    return ordered


def select_terms(terms, category):
    """Keep every term, or only one category. Capitalization does not matter."""
    if not category or category.casefold() == "all categories":
        return list(terms)
    chosen = [term for term in terms if term.category.casefold() == category.casefold()]
    if not chosen:
        raise RuntimeError(f"The term list has no category named {category}.")
    return chosen


def terms_by_category(terms):
    grouped = {}
    for term in terms:
        grouped.setdefault(term.category, []).append(term)
    return grouped


@lru_cache(maxsize=None)
def compile_term(term):
    """Treat a hyphen and a space as the same between the words of a phrase."""
    parts = [part for part in re.split(r"[-\s]+", term.strip()) if part]
    if not parts:
        return None
    body = r"[\s-]+".join(re.escape(part) for part in parts)
    # Letters and digits mark a word. Punctuation and other scripts, such as
    # Chinese characters, do not, so an English word beside them still matches.
    return re.compile(
        rf"(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])",
        re.IGNORECASE,
    )


def find_matches(text, terms):
    """Return non-overlapping hits. The longest term wins when they overlap."""
    if not text:
        return []
    hits = []
    for term in terms:
        pattern = compile_term(term.term)
        if pattern is None:
            continue
        for match in pattern.finditer(text):
            hits.append(Hit(start=match.start(), end=match.end(), term=term.term))
    return keep_longest(hits)


def phrase_spans(text, rules):
    """Where each exclusion phrase occurs. Matching follows the same rules as terms."""
    spans = []
    if not text:
        return spans
    for rule in rules:
        pattern = compile_term(rule.phrase)
        if pattern is None:
            continue
        for match in pattern.finditer(text):
            spans.append((match.start(), match.end(), rule))
    return spans


def covering_rule(hit, spans):
    """The exclusion phrase that contains this match, when one does."""
    containers = [
        span for span in spans if span[0] <= hit.start and hit.end <= span[1]
    ]
    if not containers:
        return None
    containers.sort(
        key=lambda span: (
            -(span[1] - span[0]),
            span[0],
            span[2].phrase.casefold(),
        )
    )
    return containers[0][2]


def split_matches(text, terms, rules):
    """Term hits, split into counted matches and hits that fall inside an exclusion phrase."""
    hits = find_matches(text, terms)
    spans = phrase_spans(text, rules)
    kept = []
    excluded = []
    for hit in hits:
        rule = covering_rule(hit, spans)
        if rule is None:
            kept.append(hit)
        else:
            excluded.append((hit, rule))
    return kept, excluded


def keep_longest(hits):
    """Each stretch of text counts once. A longer term is kept over a shorter one."""
    ordered = sorted(
        hits,
        key=lambda hit: (-(hit.end - hit.start), hit.start, hit.term.casefold()),
    )
    kept = []
    for hit in ordered:
        if any(hit.start < earlier.end and earlier.start < hit.end for earlier in kept):
            continue
        kept.append(hit)
    kept.sort(key=lambda hit: (hit.start, hit.end))
    return kept


def flatten(text):
    return re.sub(r"\s+", " ", text).strip()


def word_count(text):
    if not text:
        return 0
    return len(text.split())


def _is_decimal_point(text, index):
    if text[index] != ".":
        return False
    before = text[index - 1] if index > 0 else ""
    after = text[index + 1] if index + 1 < len(text) else ""
    return before.isdigit() and after.isdigit()


def sentence_bounds(text, start, end):
    """The sentence runs up to a full stop or a new line on either side of the match."""
    start = max(0, min(start, len(text)))
    end = max(start, min(end, len(text)))
    sentence_start = 0
    index = start - 1
    while index >= 0:
        character = text[index]
        if character in ".!?。！？\n" and not _is_decimal_point(text, index):
            sentence_start = index + 1
            break
        index -= 1

    sentence_end = len(text)
    index = max(end, sentence_start)
    while index < len(text):
        character = text[index]
        if character in ".!?。！？\n" and not _is_decimal_point(text, index):
            sentence_end = index + 1
            break
        index += 1
    if sentence_end < end:
        sentence_end = end
    return sentence_start, sentence_end


def context_snippet(text, start, end):
    """Return the sentence, or 40 words on each side when it is longer than 80 words."""
    if not text:
        return ""
    sentence_start, sentence_end = sentence_bounds(text, start, end)
    sentence = text[sentence_start:sentence_end]
    words = list(re.finditer(r"\S+", sentence))
    if len(words) <= MAX_SENTENCE_WORDS:
        return flatten(sentence)

    local_start = max(0, start - sentence_start)
    local_end = max(local_start, end - sentence_start)
    overlapping = [
        index
        for index, word in enumerate(words)
        if word.end() > local_start and word.start() < local_end
    ]
    if overlapping:
        first = overlapping[0]
        last = overlapping[-1]
    else:
        first = last = 0

    before = max(0, first - CONTEXT_WORDS)
    after = min(len(words), last + 1 + CONTEXT_WORDS)
    piece = sentence[words[before].start() : words[after - 1].end()]
    snippet = flatten(piece)
    if before > 0:
        snippet = "... " + snippet
    if after < len(words):
        snippet = snippet + " ..."
    return snippet
