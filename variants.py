"""Find words that belong with a stem, and remember choices already made.

related_word_suggestions is the place for a later Word2Vec section.
It returns nothing for now, and the word window hides that section until it has rows.
"""

import csv
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from corpus import check_stop, list_sources, read_one_document, report_status
from terms import Hit, Term, compile_term, context_snippet, keep_longest

DECISION_COLUMNS = [
    "datetime",
    "corpus_folder",
    "category",
    "stem",
    "word",
    "count",
    "included",
]
# "added" stays in the decisions file only. Run folders do not need it.
DECISION_FILE_COLUMNS = DECISION_COLUMNS + ["added"]

# A word in the Latin alphabet, with an optional internal hyphen or apostrophe.
# Very long tokens are usually leftover addresses or hashes.
WORD_PATTERN = re.compile(r"[A-Za-z0-9]{1,40}(?:[-'’][A-Za-z0-9]{1,40})*")


def decisions_path(term_list_path):
    """One decisions file per term list, in a Decisions folder beside that list.

    An older file that sat next to the term list is moved, so saved choices are kept.
    """
    path = Path(term_list_path)
    folder = path.parent / "Decisions"
    new_path = folder / f"{path.stem}_decisions.csv"
    old_path = path.with_name(new_path.name)
    if old_path.is_file() and old_path.resolve() != new_path.resolve() and not new_path.exists():
        folder.mkdir(parents=True, exist_ok=True)
        old_path.replace(new_path)
    return new_path


def read_decision_rows(term_list_path):
    path = decisions_path(term_list_path)
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def stem_match(word, stem):
    """True when the word starts with the stem, including after non- or un-."""
    text = word.casefold()
    stem = stem.casefold().strip()
    if not stem or not text:
        return False
    if text.startswith(stem):
        return True
    parts = re.split(r"[-'’]", text)
    if len(parts) > 1 and any(part.startswith(stem) for part in parts):
        return True
    for prefix in ("non", "un"):
        if text.startswith(prefix) and text[len(prefix) :].startswith(stem):
            return True
    return False


def related_word_suggestions(documents, category, stem):
    """Placeholder for a later Word2Vec section. Nothing is suggested yet."""
    return []


def opening_tick(word, listed, saved):
    """How a word starts in the popup.

    A term-list word starts ticked unless a saved decision turned it off.
    Any other word starts unticked unless a saved decision turned it on.
    saved maps a lowercase word to True or False. A missing word has no decision.
    """
    if word in listed:
        return saved.get(word, True)
    return saved.get(word, False)


def date_column_name(documents):
    """The metadata column that holds a date, if there is one."""
    keys = []
    for document in documents:
        if document.metadata:
            keys = list(document.metadata.keys())
            break
    for key in keys:
        if key.casefold() == "date":
            return key
    for key in keys:
        if "date" in key.casefold():
            return key
    return ""


def format_suggestion_source(document, group_column="", date_column="", has_metadata=False):
    """Where an example sentence came from, for the word window."""
    if not has_metadata:
        return document.file_name
    parts = []
    if group_column:
        group = (document.metadata.get(group_column) or "").strip()
        if group:
            parts.append(group)
    if date_column:
        shown = _format_source_date(document.metadata.get(date_column) or "")
        if shown:
            parts.append(shown)
    if not parts:
        return document.file_name
    return ", ".join(parts)


def _format_source_date(value):
    value = (value or "").strip()
    if not value:
        return ""
    match = re.match(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", value)
    if match:
        year, month, day = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    return value


def collect_stem_suggestions(
    documents,
    jobs,
    status=None,
    group_column="",
    date_column="",
    has_metadata=False,
    should_stop=None,
):
    """Scan the corpus once for every category that may have new words.

    Each job is (category, stem, saved_ticks, terms_already_listed).
    saved_ticks maps a lowercase word to True or False.
    The listed set contains lowercase words from the term list.
    """
    counts = {category: defaultdict(int) for category, *_rest in jobs}
    samples = {category: defaultdict(list) for category, *_rest in jobs}

    total = len(documents)
    for index, document in enumerate(documents, start=1):
        check_stop(should_stop)
        report_status(
            status,
            f"Looking for new words: {index:,} of {total:,}",
            index,
            total,
        )
        for part in document.parts:
            text = part["text"]
            if not text:
                continue
            for match in WORD_PATTERN.finditer(text):
                word = match.group()
                lowered = word.casefold()
                for category, stem, _saved, _listed in jobs:
                    if not stem_match(word, stem):
                        continue
                    counts[category][lowered] += 1
                    bucket = samples[category][lowered]
                    if len(bucket) >= 3:
                        continue
                    sentence = context_snippet(text, match.start(), match.end())
                    if sentence and sentence not in bucket:
                        bucket.append(sentence)

    suggestions = {}
    for category, stem, saved, listed in jobs:
        found = counts[category]
        for word in listed:
            if stem_match(word, stem):
                found.setdefault(word, 0)
        if not found:
            suggestions[category] = []
            continue
        match_counts, match_samples = _count_like_search(
            documents,
            found,
            listed,
            lambda document: format_suggestion_source(
                document, group_column, date_column, has_metadata
            ),
            lambda document: _organization_name(document, group_column),
            should_stop=should_stop,
        )
        rows = []
        for word in found:
            rows.append(
                {
                    "word": word,
                    "count": match_counts[word],
                    "sentences": match_samples[word],
                    "checked": opening_tick(word, listed, saved),
                    "from_term_list": word in listed,
                    "new": word not in saved,
                }
            )
        rows.sort(key=lambda row: (not row["new"], -row["count"], row["word"]))
        suggestions[category] = rows
    return suggestions


def gather_category_words(
    config,
    category,
    stem,
    saved,
    listed,
    status=None,
    should_stop=None,
):
    """Collect one category's words, counts, and examples for the word window.

    Each file is read only to find those words. Languages are not detected,
    and nothing is written.
    """
    check_stop(should_stop)
    sources = list_sources(config)
    documents = []
    found = {}
    total = len(sources)
    for index, (resolved, _display, metadata) in enumerate(sources, start=1):
        check_stop(should_stop)
        report_status(
            status,
            f"Gathering words: {index:,} of {total:,}",
            index,
            total,
        )
        document = read_one_document(resolved, metadata, config)
        if document is None:
            continue
        documents.append(document)
        for part in document.parts:
            text = part["text"]
            if not text:
                continue
            for match in WORD_PATTERN.finditer(text):
                word = match.group().casefold()
                if stem_match(word, stem):
                    found.setdefault(word, 0)
    for word in listed:
        if stem_match(word, stem):
            found.setdefault(word, 0)
    if not found:
        return []
    group_column = config.group_column or ""
    date_column = date_column_name(documents) if config.metadata_file else ""
    has_metadata = bool(config.metadata_file)
    match_counts, match_samples = _count_like_search(
        documents,
        found,
        listed,
        lambda document: format_suggestion_source(
            document, group_column, date_column, has_metadata
        ),
        lambda document: _organization_name(document, group_column),
        status=status,
        should_stop=should_stop,
        progress_label="Counting words",
    )
    rows = []
    for word in found:
        rows.append(
            {
                "word": word,
                "count": match_counts[word],
                "sentences": match_samples[word],
                "checked": opening_tick(word, listed, saved),
                "from_term_list": word in listed,
                "new": word not in saved,
            }
        )
    rows.sort(key=lambda row: (not row["new"], -row["count"], row["word"]))
    return rows


def _organization_name(document, group_column):
    """The group this document belongs to, used to spread example sentences."""
    if not group_column:
        return ""
    return (document.metadata.get(group_column) or "").strip()


def _example_wanted(bucket, organization, limit=3):
    """True when this group might still change which examples are kept."""
    if len(bucket) < limit:
        return True
    org = (organization or "").casefold()
    orgs = [(item.get("organization") or "").casefold() for item in bucket]
    if not org or org in orgs:
        return False
    counts = {}
    for name in orgs:
        counts[name] = counts.get(name, 0) + 1
    return any((not name) or counts.get(name, 0) > 1 for name in orgs)


def place_example(bucket, item, limit=3):
    """Keep up to three examples, from different groups when the word has them."""
    text = item.get("text") or ""
    if not text:
        return
    if any((existing.get("text") or "") == text for existing in bucket):
        return
    org = (item.get("organization") or "").casefold()
    if len(bucket) < limit:
        bucket.append(item)
        return
    if not org:
        return
    orgs = [(existing.get("organization") or "").casefold() for existing in bucket]
    if org in orgs:
        return
    counts = {}
    for name in orgs:
        counts[name] = counts.get(name, 0) + 1
    for index in range(len(bucket) - 1, -1, -1):
        name = orgs[index]
        if not name or counts.get(name, 0) > 1:
            bucket[index] = item
            return


def _count_like_search(
    documents,
    found,
    listed,
    source_for=None,
    organization_for=None,
    status=None,
    should_stop=None,
    progress_label="Counting words",
):
    """Count each suggested word the way the search will count it.

    A hyphen and a space are the same, capital letters do not matter, and a
    longer term already in the list keeps an overlapping match.
    """
    listed_patterns = []
    for word in listed:
        pattern = compile_term(word)
        if pattern is not None:
            listed_patterns.append((word.casefold(), pattern))
    unlisted = []
    for word in found:
        if word.casefold() in listed:
            continue
        pattern = compile_term(word)
        if pattern is not None:
            unlisted.append((word.casefold(), pattern))

    match_counts = defaultdict(int)
    match_samples = defaultdict(list)

    def keep_sample(word, text, start, end, document):
        bucket = match_samples[word]
        organization = organization_for(document) if organization_for else ""
        if not _example_wanted(bucket, organization):
            return
        sentence = context_snippet(text, start, end)
        if not sentence:
            return
        source = source_for(document) if source_for else ""
        place_example(
            bucket,
            {"text": sentence, "source": source, "organization": organization},
        )

    for index, document in enumerate(documents, start=1):
        check_stop(should_stop)
        if status is not None:
            report_status(
                status,
                f"{progress_label}: {index:,} of {len(documents):,}",
                index,
                len(documents),
            )
        for part in document.parts:
            text = part["text"]
            if not text:
                continue
            listed_hits = []
            for word, pattern in listed_patterns:
                for match in pattern.finditer(text):
                    listed_hits.append(Hit(match.start(), match.end(), word))
            for hit in keep_longest(listed_hits):
                if hit.term not in found:
                    continue
                match_counts[hit.term] += 1
                keep_sample(hit.term, text, hit.start, hit.end, document)
            for word, pattern in unlisted:
                own = [
                    Hit(match.start(), match.end(), word)
                    for match in pattern.finditer(text)
                ]
                if not own:
                    continue
                for hit in keep_longest(own + listed_hits):
                    if hit.term != word:
                        continue
                    match_counts[word] += 1
                    keep_sample(word, text, hit.start, hit.end, document)
    return match_counts, match_samples


def load_latest_decisions(term_list_path):
    """The latest saved choice for each word, grouped by category.

    Keys are lowercase. A later row for the same word replaces an earlier one.
    """
    latest = defaultdict(dict)
    for row in read_decision_rows(term_list_path):
        category = (row.get("category") or "").strip()
        word = (row.get("word") or "").strip()
        if category and word:
            latest[category.casefold()][word.casefold()] = row
    return latest


def decision_ticks(latest):
    """category -> word -> True when that saved choice is ticked."""
    ticks = {}
    for category, words in latest.items():
        ticks[category] = {
            word: _yes(row.get("included")) for word, row in words.items()
        }
    return ticks


def _yes(value):
    return (value or "").strip().casefold() in {"yes", "y", "true", "1"}


def _write_decision_rows(path, rows):
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=DECISION_FILE_COLUMNS, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def append_decisions(term_list_path, corpus_folder, category, stem, choices):
    path = decisions_path(term_list_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if path.is_file():
        with path.open(newline="", encoding="utf-8-sig") as handle:
            existing = list(csv.DictReader(handle))
    replace = {
        (category.casefold(), (choice["word"] or "").strip().casefold())
        for choice in choices
    }
    existing = [
        row
        for row in existing
        if (
            (row.get("category") or "").strip().casefold(),
            (row.get("word") or "").strip().casefold(),
        )
        not in replace
    ]
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fresh = [
        {
            "datetime": timestamp,
            "corpus_folder": corpus_folder,
            "category": category,
            "stem": stem,
            "word": choice["word"],
            "count": choice["count"],
            "included": "yes" if choice["included"] else "no",
            "added": "yes" if choice.get("added") else "no",
        }
        for choice in choices
    ]
    _write_decision_rows(path, existing + fresh)


def reset_message(category, forgotten):
    if not forgotten:
        return f"No saved word decisions were found for {category}."
    return f"Forgot {forgotten} saved word decisions for {category}."


def reset_category_decisions(term_list_path, category):
    """Forget decisions for one category. The term list file is not changed."""
    path = decisions_path(term_list_path)
    if not path.is_file():
        return 0
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    wanted = category.casefold()
    kept = [
        row
        for row in rows
        if (row.get("category") or "").casefold() != wanted
    ]
    forgotten = len(rows) - len(kept)
    if forgotten:
        _write_decision_rows(path, kept)
    return forgotten


def effective_search_terms(terms, latest):
    """Terms to search: the term list, plus ticked variants, minus unticked term-list words.

    latest is the mapping from load_latest_decisions. terms are the term-list
    rows for this run. The term list file is not changed.
    """
    by_category = {}
    for term in terms:
        by_category.setdefault(term.category.casefold(), term.category)
    used = []
    seen = set()
    for term in terms:
        category = term.category.casefold()
        word = term.term.casefold()
        row = latest.get(category, {}).get(word)
        if row is not None and not _yes(row.get("included")):
            continue
        used.append(term)
        seen.add((category, word))
    for category, words in latest.items():
        if category not in by_category:
            continue
        for word, row in words.items():
            if (category, word) in seen or not _yes(row.get("included")):
                continue
            display = (row.get("word") or word).strip()
            stem = (row.get("stem") or "").strip()
            used.append(Term(category=by_category[category], term=display, stem=stem))
            seen.add((category, word))
    return used


def apply_choices(term_list_path, corpus_folder, category, stem, choices, terms):
    """Record popup choices in the decisions file. The term list file is not changed."""
    listed = {(term.category.casefold(), term.term.casefold()) for term in terms}
    recorded = []
    for choice in choices:
        key = (category.casefold(), choice["word"].casefold())
        recorded.append(
            {
                "word": choice["word"],
                "count": choice["count"],
                "included": choice["included"],
                "added": key not in listed,
            }
        )
    append_decisions(term_list_path, corpus_folder, category, stem, recorded)
