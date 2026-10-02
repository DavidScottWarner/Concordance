"""Write one dated results folder for a run."""

import csv
import re
import shutil
from datetime import datetime
from pathlib import Path

from terms import write_terms
from variants import DECISION_COLUMNS, decisions_path, read_decision_rows
from context_words import CONTEXT_COLUMNS, CONTEXT_NOTE, CONTEXT_SKIPPED_NOTE
from corpus import RunStopped, check_stop

RESERVED_COLUMNS = {
    "file_name",
    "file_path",
    "language",
    "short",
    "category",
    "term",
    "location",
    "sentence",
    "keep",
}


def include_in_counts(language, choice):
    choice = (choice or "").strip()
    if choice.casefold() in {"", "all", "all languages"}:
        return True
    return language.casefold() == choice.casefold()


def per_10000(matches, words):
    if words <= 0:
        return ""
    return f"{matches / words * 10000:.2f}"


def output_column_name(name):
    if name in RESERVED_COLUMNS:
        return f"metadata_{name}"
    return name


def metadata_columns(documents):
    columns = []
    for document in documents:
        for key in document.metadata:
            if key not in columns:
                columns.append(key)
    return columns


def group_value(document, column):
    if not column:
        return ""
    value = (document.metadata.get(column) or "").strip()
    return value or "(blank)"


def load_previous_keeps(results_folder):
    """Carry forward keep notes from earlier runs of the same match."""
    keeps = {}
    folder = Path(results_folder)
    if not folder.is_dir():
        return keeps
    for path in sorted(folder.glob("*/matches.csv")):
        try:
            with path.open(newline="", encoding="utf-8-sig") as handle:
                for row in csv.DictReader(handle):
                    note = (row.get("keep") or "").strip()
                    if not note:
                        continue
                    key = (
                        row.get("file_path", ""),
                        row.get("category", ""),
                        row.get("term", ""),
                        row.get("location", ""),
                        row.get("sentence", ""),
                    )
                    keeps[key] = note
        except (OSError, csv.Error):
            continue
    return keeps


def _write_rows(path, fieldnames, rows):
    with Path(path).open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _folder_category(category):
    name = (category or "").strip() or "All categories"
    if name.casefold() == "all categories":
        name = "All categories"
    cleaned = re.sub(r'[<>:"/\\|?*]+', "-", name).strip(" .")
    return cleaned or "category"


def _run_folder(results_root, category, when):
    """Date, minute, and category. Add the seconds only when that name is taken."""
    label = _folder_category(category)
    minute = when.strftime("%Y-%m-%d_%H-%M")
    destination = results_root / f"{minute}_{label}"
    if not destination.exists():
        return destination
    second = when.strftime("%Y-%m-%d_%H-%M-%S")
    destination = results_root / f"{second}_{label}"
    suffix = 2
    while destination.exists():
        destination = results_root / f"{second}_{label}-{suffix}"
        suffix += 1
    return destination


def _remove_unfinished_run(destination, results_root):
    """Delete one run folder that was still being written. Leave every other folder."""
    try:
        folder = destination.resolve()
        root = results_root.resolve()
    except OSError:
        return
    if folder == root or root not in folder.parents or not folder.is_dir():
        return
    shutil.rmtree(folder)


def write_run(
    config,
    corpus,
    matches,
    categories,
    terms,
    decision_categories=None,
    context_rows=None,
    should_stop=None,
):
    """Create a new dated folder and return its path. Older runs are left as they were."""
    results_root = Path(config.results_folder)
    results_root.mkdir(parents=True, exist_ok=True)
    check_stop(should_stop)
    destination = _run_folder(results_root, config.category, datetime.now())
    destination.mkdir()
    try:
        return _write_run_files(
            config,
            corpus,
            matches,
            categories,
            terms,
            destination,
            results_root,
            decision_categories,
            context_rows,
            should_stop,
        )
    except RunStopped:
        _remove_unfinished_run(destination, results_root)
        raise


def _write_run_files(
    config,
    corpus,
    matches,
    categories,
    terms,
    destination,
    results_root,
    decision_categories,
    context_rows,
    should_stop,
):
    check_stop(should_stop)
    keeps = load_previous_keeps(results_root)
    path_column = (config.path_column or "").strip()
    meta_columns = [
        column
        for column in metadata_columns(corpus.documents)
        if column != path_column
    ]
    renamed_meta = [(column, output_column_name(column)) for column in meta_columns]
    match_fields = (
        ["file_name", "file_path"]
        + [renamed for _original, renamed in renamed_meta]
        + ["language", "short", "category", "term", "location", "sentence", "keep"]
    )
    match_rows = []
    for match in matches:
        row = {
            "file_name": match["file_name"],
            "file_path": match["file_path"],
            "language": match["language"],
            "short": "yes" if match["short"] else "no",
            "category": match["category"],
            "term": match["term"],
            "location": match["location"],
            "sentence": match["sentence"],
        }
        for original, renamed in renamed_meta:
            row[renamed] = match["metadata"].get(original, "")
        key = (
            row["file_path"],
            row["category"],
            row["term"],
            row["location"],
            row["sentence"],
        )
        row["keep"] = keeps.get(key, "")
        match_rows.append(row)
    _write_rows(destination / "matches.csv", match_fields, match_rows)
    check_stop(should_stop)

    counted_matches = [
        match for match in matches if include_in_counts(match["language"], config.count_language)
    ]
    counted_documents = [
        document
        for document in corpus.documents
        if include_in_counts(document.language, config.count_language)
    ]
    grouping = (config.group_column or "").strip()
    _write_rows(
        destination / "counts_by_category.csv",
        ["category", "matches", "documents", "groups"],
        category_count_rows(categories, counted_matches, grouping),
    )
    if grouping:
        _write_rows(
            destination / "counts_by_group.csv",
            ["category", "group", "matches", "words", "matches_per_10000_words"],
            group_count_rows(categories, counted_matches, counted_documents, grouping),
        )
    check_stop(should_stop)

    write_terms(destination / "terms_used.csv", terms)
    names = categories if decision_categories is None else decision_categories
    wanted = {category.casefold() for category in names}
    decision_rows = [
        row
        for row in read_decision_rows(config.term_list)
        if (row.get("category") or "").casefold() in wanted
    ]
    _write_rows(destination / "word_decisions.csv", list(DECISION_COLUMNS), decision_rows)
    check_stop(should_stop)
    if getattr(config, "context_words", True):
        _write_rows(
            destination / "context_words.csv",
            CONTEXT_COLUMNS,
            context_rows or [],
        )
        context_note = CONTEXT_NOTE
    else:
        context_note = CONTEXT_SKIPPED_NOTE
    (destination / "run_settings.txt").write_text(
        run_record(config, corpus, destination, len(matches), len(counted_matches), context_note),
        encoding="utf-8",
    )
    return destination


def category_count_rows(categories, matches, grouping):
    rows = []
    for category in categories:
        chosen = [match for match in matches if match["category"] == category]
        documents = {match["file_path"] for match in chosen}
        if grouping:
            groups = {group_value_from_match(match, grouping) for match in chosen}
            group_count = len(groups)
        else:
            group_count = ""
        rows.append(
            {
                "category": category,
                "matches": len(chosen),
                "documents": len(documents),
                "groups": group_count,
            }
        )
    return rows


def group_value_from_match(match, column):
    value = (match["metadata"].get(column) or "").strip()
    return value or "(blank)"


def group_count_rows(categories, matches, documents, grouping):
    groups = []
    for document in documents:
        value = group_value(document, grouping)
        if value not in groups:
            groups.append(value)
    words_by_group = {value: 0 for value in groups}
    for document in documents:
        words_by_group[group_value(document, grouping)] += document.word_count

    rows = []
    for category in categories:
        chosen = [match for match in matches if match["category"] == category]
        for value in groups:
            count = sum(1 for match in chosen if group_value_from_match(match, grouping) == value)
            words = words_by_group[value]
            rows.append(
                {
                    "category": category,
                    "group": value,
                    "matches": count,
                    "words": words,
                    "matches_per_10000_words": per_10000(count, words),
                }
            )
    return rows


def _bullet_list(items, empty_note):
    if not items:
        return [empty_note]
    lines = []
    for item in items:
        if isinstance(item, tuple):
            lines.append(f"- {item[0]} ({item[1]})")
        else:
            lines.append(f"- {item}")
    return lines


def run_record(config, corpus, destination, match_count, counted_match_count, context_note):
    header_fields = ", ".join(config.header_fields) if config.header_fields else "none"
    grouping = config.group_column or "none"
    lines = [
        f"Results folder: {destination}",
        f"Corpus folder: {config.corpus_folder}",
        f"Term list: {config.term_list}",
        f"Word decisions file: {decisions_path(config.term_list)}",
        f"Metadata file: {config.metadata_file or 'none'}",
        f"File-path column: {config.path_column or 'none'}",
        f"Group column: {grouping}",
        f"Category: {config.category}",
        f"Remove formatting and web addresses: {'yes' if config.strip_formatting else 'no'}",
        f"Read opening header lines: {'yes' if config.use_headers else 'no'}",
        f"Header fields searched: {header_fields if config.use_headers else 'not used'}",
        f"Flag documents shorter than: {int(config.short_word_limit)} words",
        f"Language used for the counts: {config.count_language}",
        "",
        "The sentence file, matches.csv, includes every language.",
        "The count files include only the language chosen above.",
        "All languages means every document is included in the counts.",
        context_note,
        "Matches per 10,000 words uses the words in the text that was searched.",
        "A blank rate means that group had no words to divide by.",
        "The groups column is blank when no grouping column was chosen.",
        "",
        f"Documents read: {len(corpus.documents)}",
        f"Documents flagged as short: {sum(1 for document in corpus.documents if document.short)}",
        f"Matches in the sentence file: {match_count}",
        f"Matches included in the counts: {counted_match_count}",
        "",
        "Files listed in the metadata that could not be found:",
        *_bullet_list(corpus.missing, "- none"),
        "",
        "Files that could not be read:",
        *_bullet_list(corpus.unreadable, "- none"),
        "",
        "Files with no text, skipped:",
        *_bullet_list(corpus.empty, "- none"),
        "",
    ]
    return "\n".join(lines)
