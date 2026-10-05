"""Words that appear unusually often beside a category's searched terms.

The score is log-likelihood. Nothing here uses a downloaded language model.
"""

import math
import re
from collections import Counter

from corpus import check_stop, report_status
from terms import (
    _is_decimal_point,
    find_matches,
    flatten,
    phrase_spans,
    covering_rule,
    rules_for_category,
    terms_by_category,
)

# Ordinary English function words. Content words such as "system" stay available.
FUNCTION_WORDS = frozenset(
    """
    a about above after again against all am an and any are aren't as at be because been
    before being below between both but by can can't cannot could couldn't did didn't do
    does doesn't doing don't down during each few for from further had hadn't has hasn't
    have haven't having he he'd he'll he's her here here's hers herself him himself his
    how how's i i'd i'll i'm i've if in into is isn't it it's its itself let's me more
    most my myself no nor not of off on once only or other our ours ourselves out over
    own same she she'd she'll she's should shouldn't so some such than that that's the
    their theirs them themselves then there there's these they they'd they'll they're
    they've this those through to too under until up very was wasn't we we'd we'll we're
    we've were weren't what what's when when's where where's which while who who's whom
    why why's with won't would wouldn't you you'd you'll you're you've your yours
    yourself yourselves
    """.split()
)

TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[-'’][A-Za-z0-9]+)*")
SENTENCE_END = set(".!?。！？\n")
TOO_FEW = "Too few sentences with these terms to find context words"
CONTEXT_COLUMNS = [
    "category",
    "word_or_phrase",
    "score",
    "times_with_terms",
    "times_elsewhere",
]
CONTEXT_NOTE = (
    "Context words: context_words.csv lists up to 30 words and two-word phrases per category "
    "that appear unusually often in the same sentence as that category's searched terms, "
    "scored by log-likelihood against the rest of the documents used for the counts. "
    "Common words and the category's own terms are left out. "
    "A word must appear at least 5 times with the terms. "
    "A category with fewer than 10 such sentences gets a note instead of a list."
)
CONTEXT_SKIPPED_NOTE = (
    "Context words: not listed for this run, because "
    "“Also list words found near the terms” was unticked."
)


def fold_token(token):
    return token.casefold().replace("’", "'")


def is_function_word(token):
    word = fold_token(token)
    return word in FUNCTION_WORDS or word.replace("'", "") in FUNCTION_WORDS


def is_content_word(token):
    word = fold_token(token)
    if len(word) < 2 or is_function_word(word):
        return False
    return any(character.isalpha() for character in word)


def normalize_phrase(text):
    text = fold_token(text).replace("_", " ").replace("-", " ")
    return " ".join(text.split())


def iter_sentences(text):
    start = 0
    for index, character in enumerate(text):
        if character in SENTENCE_END and not (character == "." and _is_decimal_point(text, index)):
            chunk = flatten(text[start : index + 1])
            if chunk and chunk.split():
                yield chunk
            start = index + 1
    tail = flatten(text[start:])
    if tail and tail.split():
        yield tail


def tokenize(text):
    return [(match.group().casefold(), match.start(), match.end()) for match in TOKEN_RE.finditer(text)]


def log_likelihood(focus_count, rest_count, focus_total, rest_total):
    """Dunning's log-likelihood. Higher means more common beside the terms."""
    if focus_count <= 0 or focus_total <= 0 or rest_total <= 0:
        return 0.0
    rest_count = max(0, rest_count)
    absent_focus = focus_total - focus_count
    absent_rest = rest_total - rest_count
    if absent_focus < 0 or absent_rest < 0:
        return 0.0
    observed = (focus_count, rest_count, absent_focus, absent_rest)
    total = float(sum(observed))
    if total <= 0:
        return 0.0
    row_focus = focus_count + absent_focus
    row_rest = rest_count + absent_rest
    col_present = focus_count + rest_count
    col_absent = absent_focus + absent_rest
    expected = (
        row_focus * col_present / total,
        row_rest * col_present / total,
        row_focus * col_absent / total,
        row_rest * col_absent / total,
    )
    score = 0.0
    for seen, predict in zip(observed, expected):
        if seen > 0 and predict > 0:
            score += seen * math.log(seen / predict)
    return 2.0 * score


def _document_sentences(document):
    text = "\n".join(part.get("text") or "" for part in document.parts)
    sentences = []
    for sentence in iter_sentences(text):
        sentences.append((sentence, tokenize(sentence)))
    return sentences


def _too_few(category):
    return {
        "category": category,
        "word_or_phrase": TOO_FEW,
        "score": "",
        "times_with_terms": "",
        "times_elsewhere": "",
    }


def _counted_hits(text, terms, rules):
    hits = find_matches(text, terms)
    if not rules or not hits:
        return hits
    spans = phrase_spans(text, rules)
    return [hit for hit in hits if covering_rule(hit, spans) is None]


def _category_rows(sentences, category, terms, rules=None):
    blocked = {normalize_phrase(term.term) for term in terms}
    focus_uni = Counter()
    focus_bi = Counter()
    focus_uni_total = 0
    focus_bi_total = 0
    focus_sentences = 0
    is_focus = []

    for text, tokens in sentences:
        hits = _counted_hits(text, terms, rules)
        is_focus.append(bool(hits))
        if not hits:
            continue
        focus_sentences += 1
        skip = set()
        for token_index, (_word, start, end) in enumerate(tokens):
            if any(start < hit.end and hit.start < end for hit in hits):
                skip.add(token_index)
        content_at = []
        for token_index, (word, _start, _end) in enumerate(tokens):
            if token_index in skip or not is_content_word(word):
                continue
            content_at.append(token_index)
            focus_uni[word] += 1
            focus_uni_total += 1
        for left, right in zip(content_at, content_at[1:]):
            if right != left + 1:
                continue
            phrase = tokens[left][0] + " " + tokens[right][0]
            focus_bi[phrase] += 1
            focus_bi_total += 1

    if focus_sentences < 10:
        return [_too_few(category)]

    def keep(counter):
        return {
            word: count
            for word, count in counter.items()
            if count >= 5 and normalize_phrase(word) not in blocked
        }

    uni_candidates = keep(focus_uni)
    bi_candidates = keep(focus_bi)
    rest_uni = Counter()
    rest_bi = Counter()
    rest_uni_total = 0
    rest_bi_total = 0
    for focus, (_text, tokens) in zip(is_focus, sentences):
        if focus:
            continue
        words = [word for word, _start, _end in tokens]
        content = [word for word in words if is_content_word(word)]
        rest_uni_total += len(content)
        for word in content:
            if word in uni_candidates:
                rest_uni[word] += 1
        for left, right in zip(words, words[1:]):
            if not is_content_word(left) or not is_content_word(right):
                continue
            rest_bi_total += 1
            phrase = left + " " + right
            if phrase in bi_candidates:
                rest_bi[phrase] += 1

    scored = []
    for word, count in uni_candidates.items():
        if focus_uni_total <= 0 or rest_uni_total <= 0:
            continue
        if count / focus_uni_total <= rest_uni[word] / rest_uni_total:
            continue
        scored.append(
            (
                log_likelihood(count, rest_uni[word], focus_uni_total, rest_uni_total),
                count,
                rest_uni[word],
                word,
            )
        )
    for phrase, count in bi_candidates.items():
        if focus_bi_total <= 0 or rest_bi_total <= 0:
            continue
        if count / focus_bi_total <= rest_bi[phrase] / rest_bi_total:
            continue
        scored.append(
            (
                log_likelihood(count, rest_bi[phrase], focus_bi_total, rest_bi_total),
                count,
                rest_bi[phrase],
                phrase,
            )
        )
    scored.sort(key=lambda item: (-item[0], -item[1], item[3]))
    rows = []
    for score, count, elsewhere, word in scored[:30]:
        rows.append(
            {
                "category": category,
                "word_or_phrase": word,
                "score": f"{score:.1f}",
                "times_with_terms": count,
                "times_elsewhere": elsewhere,
            }
        )
    return rows


def context_rows(documents, terms, status=None, should_stop=None, exclusions=None):
    """One block of rows per category, in category order."""
    grouped = terms_by_category(terms)
    order = []
    for term in terms:
        if term.category not in order:
            order.append(term.category)
    sentences = []
    total_docs = len(documents)
    for index, document in enumerate(documents, start=1):
        check_stop(should_stop)
        if index == 1 or index == total_docs or index % 250 == 0:
            report_status(
                status,
                f"Finding context words: reading {index:,} of {total_docs:,}",
                index,
                total_docs,
            )
        sentences.extend(_document_sentences(document))
    rows = []
    total = len(order)
    for index, category in enumerate(order, start=1):
        check_stop(should_stop)
        report_status(
            status,
            f"Finding context words: {category}",
            index,
            total,
        )
        category_terms = grouped.get(category, [])
        if category_terms:
            rows.extend(
                _category_rows(
                    sentences,
                    category,
                    category_terms,
                    rules_for_category(exclusions or [], category),
                )
            )
    return rows
