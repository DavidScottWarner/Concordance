"""Search a folder of documents for terms and count the matches.

Start the window with:
    ~/.venvs/tool4-concordance/bin/python concordance.py

Run one category from the saved choices:
    ~/.venvs/tool4-concordance/bin/python concordance.py --category "Trustlessness"

Forget the word decisions for one category:
    ~/.venvs/tool4-concordance/bin/python concordance.py --reset-category "Trustlessness"
"""

import argparse
import tkinter as tk
from tkinter import messagebox, ttk

from corpus import load_corpus, report_status, RunStopped, check_stop
from report import include_in_counts, write_run
from settings_store import (
    DEFAULT_TERM_LIST,
    load_settings,
    save_settings,
    validate_config,
)
from terms import (
    categories_in_order,
    category_definitions,
    context_snippet,
    load_exclusions,
    load_terms,
    rules_for_category,
    select_terms,
    split_matches,
    terms_by_category,
)
from context_words import context_rows
from variant_window import show_variant_window
from variants import (
    apply_choices,
    collect_stem_suggestions,
    date_column_name,
    decision_ticks,
    effective_search_terms,
    load_latest_decisions,
    related_word_suggestions,
    reset_category_decisions,
    reset_message,
)


class RunCancelled(Exception):
    """The word window was closed without saving."""


def _hit_row(document, part, category, hit, text):
    return {
        "file_name": document.file_name,
        "file_path": document.absolute_path,
        "metadata": document.metadata,
        "language": document.language,
        "short": document.short,
        "category": category,
        "term": hit.term,
        "location": part["location"],
        "start": hit.start,
        "sentence": context_snippet(text, hit.start, hit.end),
    }


def search_documents(documents, terms, status, should_stop=None, exclusions=None):
    grouped = terms_by_category(terms)
    order = categories_in_order(terms)
    exclusions = exclusions or []
    matches = []
    excluded = []
    total = len(documents)
    for index, document in enumerate(documents, start=1):
        check_stop(should_stop)
        report_status(status, f"Searching: {index:,} of {total:,}", index, total)
        for part in document.parts:
            text = part["text"]
            if not text:
                continue
            for category in order:
                rules = rules_for_category(exclusions, category)
                kept, dropped = split_matches(text, grouped.get(category, []), rules)
                for hit in kept:
                    matches.append(_hit_row(document, part, category, hit, text))
                for hit, rule in dropped:
                    row = _hit_row(document, part, category, hit, text)
                    row["phrase"] = rule.phrase
                    row["exclusion_category"] = rule.category
                    excluded.append(row)
    return matches, excluded


def stem_jobs(terms, saved_ticks):
    jobs = []
    for category in categories_in_order(terms):
        category_terms = [term for term in terms if term.category == category]
        stems = [term.stem.strip() for term in category_terms if term.stem.strip()]
        if not stems:
            continue
        listed = {term.term.casefold() for term in category_terms}
        saved = saved_ticks.get(category.casefold(), {})
        jobs.append((category, stems[0], saved, listed))
    return jobs


def execute(config, status=None, parent=None, prompter=None, should_stop=None):
    """Run a search. The prompter returns checkbox choices, or None if cancelled."""
    status = status or (lambda message: None)
    problem = validate_config(config)
    if problem:
        raise RuntimeError(problem)

    report_status(status, "Reading the term list...")
    selected = select_terms(load_terms(config.term_list), config.category)
    report_status(status, "Finding documents...")
    corpus = load_corpus(config, status, should_stop=should_stop)
    if not corpus.documents:
        detail = []
        if corpus.missing:
            detail.append(f"{len(corpus.missing)} listed files could not be found")
        if corpus.unreadable:
            detail.append(f"{len(corpus.unreadable)} files could not be read")
        if corpus.empty:
            detail.append(f"{len(corpus.empty)} files had no text")
        extra = f" ({'; '.join(detail)})." if detail else "."
        raise RuntimeError("No documents were found to search" + extra)

    definitions = category_definitions(selected)
    if prompter is None:
        def prompter(category, stem, suggestions, related, definition="", position=None):
            if parent is None:
                raise RuntimeError("Open the tool window to review new words.")
            return show_variant_window(
                parent,
                category,
                stem,
                suggestions,
                related,
                definition=definition,
                position=position,
            )

    saved_ticks = decision_ticks(load_latest_decisions(config.term_list))
    jobs = stem_jobs(selected, saved_ticks)
    suggestions = {}
    if jobs:
        suggestions = collect_stem_suggestions(
            corpus.documents,
            jobs,
            status,
            group_column=config.group_column or "",
            date_column=date_column_name(corpus.documents) if config.metadata_file else "",
            has_metadata=bool(config.metadata_file),
            should_stop=should_stop,
        )

    needing_window = [
        category
        for category, _stem, _saved, _listed in jobs
        if any(row.get("new") for row in suggestions.get(category, []))
    ]
    window_place = {
        category: index for index, category in enumerate(needing_window, start=1)
    }
    window_total = len(needing_window)

    for category, stem, _decided, _listed in jobs:
        check_stop(should_stop)
        rows = suggestions.get(category, [])
        if not rows:
            report_status(status, f"No new words for {category}.")
            continue
        if not any(row.get("new") for row in rows):
            report_status(status, f"Word choices for {category} are already saved.")
            continue
        report_status(status, f"Review new words for {category}.")
        related = related_word_suggestions(corpus.documents, category, stem)
        choices = prompter(
            category,
            stem,
            rows,
            related,
            definition=definitions.get(category, ""),
            position=(window_place[category], window_total),
        )
        if should_stop is not None and should_stop():
            raise RunStopped()
        if choices is None:
            raise RunCancelled(
                "The run was stopped before any results were written. "
                "Word decisions you already saved are kept."
            )
        apply_choices(
            config.term_list,
            str(config.corpus_folder),
            category,
            stem,
            choices,
            load_terms(config.term_list),
        )
        report_status(status, f"Saved word decisions for {category}.")

    listed = select_terms(load_terms(config.term_list), config.category)
    terms = effective_search_terms(listed, load_latest_decisions(config.term_list))
    categories = categories_in_order(terms)
    check_stop(should_stop)
    exclusion_path = (getattr(config, "exclusion_list", "") or "").strip()
    exclusion_rules = load_exclusions(exclusion_path) if exclusion_path else []
    matches, excluded = search_documents(
        corpus.documents,
        terms,
        status,
        should_stop=should_stop,
        exclusions=exclusion_rules,
    )
    rows = None
    if getattr(config, "context_words", True):
        counted_documents = [
            document
            for document in corpus.documents
            if include_in_counts(document.language, config.count_language)
        ]
        rows = context_rows(
            counted_documents,
            terms,
            status,
            should_stop=should_stop,
            exclusions=exclusion_rules,
        )
    check_stop(should_stop)
    report_status(status, "Writing the results...")
    return write_run(
        config,
        corpus,
        matches,
        categories,
        terms,
        decision_categories=categories_in_order(listed),
        context_rows=rows,
        should_stop=should_stop,
        excluded=excluded,
        exclusion_rules=exclusion_rules,
        definitions=definitions,
    )


def command_reset(category):
    config = load_settings()
    term_list = config.term_list
    if not term_list and DEFAULT_TERM_LIST.is_file():
        term_list = str(DEFAULT_TERM_LIST)
    if not term_list:
        print("Choose a term list in the window first.")
        return 1
    try:
        forgotten = reset_category_decisions(term_list, category)
    except OSError as error:
        print(f"The decisions file could not be updated: {error}")
        return 1
    print(reset_message(category, forgotten))
    return 0


def command_run(category):
    config = load_settings()
    config.category = category
    root = tk.Tk()
    root.title("Concordance")
    root.geometry("900x200")
    root.minsize(700, 160)
    message = tk.StringVar(value="Starting...")
    frame = ttk.Frame(root, padding=8)
    frame.pack(fill=tk.BOTH, expand=True)
    tk.Label(
        frame,
        textvariable=message,
        anchor="w",
        justify=tk.LEFT,
        wraplength=820,
        fg="#333",
        font=("TkDefaultFont", 10),
    ).pack(fill=tk.BOTH, expand=True)

    bar = ttk.Progressbar(frame, mode="determinate")
    bar.pack(fill="x", pady=(0, 8))

    def status(text, current=None, total=None):
        message.set(text)
        if total:
            bar.stop()
            bar.configure(mode="determinate", maximum=max(int(total), 1), value=int(current or 0))
        else:
            if str(bar.cget("mode")) != "indeterminate":
                bar.configure(mode="indeterminate")
                bar.start(12)
        root.update()

    def finish():
        try:
            folder = execute(config, status=status, parent=root)
        except RunCancelled as cancelled:
            messagebox.showinfo("Concordance", str(cancelled), parent=root)
            root.destroy()
            return
        except Exception as error:
            messagebox.showerror("Concordance", str(error), parent=root)
            root.destroy()
            return
        messagebox.showinfo("Concordance", f"Saved results to:\n{folder}", parent=root)
        root.destroy()

    root.after(200, finish)
    root.mainloop()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Search documents for terms and count the matches."
    )
    parser.add_argument("--category", help="Run only this category, using the saved choices.")
    parser.add_argument(
        "--reset-category",
        help="Forget saved word decisions for this category.",
    )
    args = parser.parse_args(argv)
    if args.category and args.reset_category:
        parser.error("Use either --category or --reset-category.")
    if args.reset_category:
        return command_reset(args.reset_category)
    if args.category:
        return command_run(args.category)

    from main_window import App

    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
