"""Find documents, clean their text, and record language and length."""

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

from readers import SUPPORTED_EXTENSIONS, read_beginning, read_document
from terms import word_count

# A header key is one word: letters, digits, or underscores. Spaces would let a
# sentence such as "this proposal completes rfp 15:" through.
HEADER_LINE = re.compile(r"^([A-Za-z0-9_]+):[ \t]*(.*)$")

_detector = None


@dataclass
class Document:
    absolute_path: str
    file_name: str
    metadata: dict
    parts: list
    language: str
    word_count: int
    short: bool


@dataclass
class LoadedCorpus:
    documents: list = field(default_factory=list)
    missing: list = field(default_factory=list)
    unreadable: list = field(default_factory=list)
    empty: list = field(default_factory=list)


def read_csv_table(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = []
        for row in reader:
            rows.append({key: (value or "") for key, value in row.items() if key})
        return fieldnames, rows


def iter_supported_files(folder):
    folder = Path(folder)
    found = []
    for path in folder.rglob("*"):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(folder).parts
        if any(part.startswith(".") for part in relative_parts):
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        found.append(path)
    found.sort(key=lambda path: str(path).casefold())
    return found


def resolve_document_path(raw_path, corpus_folder, metadata_file):
    """Find a metadata path inside the corpus, beside the metadata file, or one folder up."""
    raw_path = (raw_path or "").strip()
    if not raw_path:
        return None
    candidate = Path(raw_path)
    if candidate.is_absolute() and candidate.is_file():
        return candidate.resolve()
    corpus = Path(corpus_folder)
    places = [corpus / raw_path]
    if metadata_file:
        places.append(Path(metadata_file).parent / raw_path)
    places.append(corpus.parent / raw_path)
    for place in places:
        if place.is_file():
            return place.resolve()
    return None


def list_sources(config):
    """Return (resolved path or None, display path, metadata) for each document to read."""
    if config.metadata_file:
        columns, rows = read_csv_table(config.metadata_file)
        if config.path_column not in columns:
            raise RuntimeError(
                f"The metadata file has no column named {config.path_column}."
            )
        if config.group_column and config.group_column not in columns:
            raise RuntimeError(
                f"The metadata file has no column named {config.group_column}."
            )
        sources = []
        for row in rows:
            raw = row.get(config.path_column, "")
            resolved = resolve_document_path(raw, config.corpus_folder, config.metadata_file)
            sources.append((resolved, raw.strip(), row))
        return sources

    sources = []
    for path in iter_supported_files(config.corpus_folder):
        resolved = path.resolve()
        sources.append((resolved, str(resolved), {}))
    return sources


class RunStopped(Exception):
    """The user clicked Stop."""


def check_stop(should_stop):
    """Raise when the user has asked the current work to stop."""
    if should_stop is not None and should_stop():
        raise RunStopped()


def report_status(status, message, current=None, total=None):
    """Send a progress line. Older callbacks that only accept the message still work."""
    if status is None:
        return
    if current is None and total is None:
        status(message)
        return
    try:
        status(message, current=current, total=total)
    except TypeError:
        status(message)


def split_header(text):
    """Separate opening header lines from the title and the body.

    The opening block starts with a single-word key such as title: or
    scores_total:. Each key line before the first blank line is one header
    field. A line that is not a key continues the previous field, so a wrapped
    title or a wrapped choices list stays with that field. The body is
    everything after the blank line.

    Some files are only header lines and have no blank line at the end. Those
    lines are still the header, and the body is empty. Otherwise keys such as
    scores_total, state, and discussion would be counted as text. An underscore
    is not part of a word, so scores_total would be counted as "scores total".
    """
    lines = text.splitlines()
    if not lines or not HEADER_LINE.match(lines[0].strip("\ufeff").strip()):
        return {}, text
    header = {}
    last_key = None
    for index, line in enumerate(lines):
        if line.strip() == "":
            return header, "\n".join(lines[index + 1 :])
        match = HEADER_LINE.match(line.strip())
        if match:
            last_key = match.group(1).lower()
            header[last_key] = match.group(2).strip()
            continue
        if last_key is None:
            return {}, text
        header[last_key] = (header[last_key] + "\n" + line.strip()).strip()
    return header, ""


def clean_text(text):
    """Remove Markdown marks and web addresses. Link text is kept."""
    if not text:
        return ""
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<(https?://[^>\s]+)>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"https?://\S+", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bwww\.\S+", " ", text, flags=re.IGNORECASE)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = text.replace("*", "")
    text = re.sub(r"(?m)^[ \t]{0,3}#{1,6}[ \t]*", "", text)
    text = re.sub(r"(?m)^[ \t]*>[ \t]?", "", text)
    text = re.sub(r"(?<!\w)_|_(?!\w)", "", text)
    return text


def maybe_clean(text, enabled):
    return clean_text(text) if enabled else text


def discover_header_fields(paths, status=None):
    """Return header names in the order they first appear."""
    found = []
    total = len(paths)
    for index, path in enumerate(paths, start=1):
        if status and (index == 1 or index % 50 == 0 or index == total):
            report_status(
                status,
                f"Scanning… {index:,} of {total:,}",
                index,
                total,
            )
        try:
            header, _body = split_header(read_beginning(path))
        except Exception:
            continue
        for key in header:
            if key not in found:
                found.append(key)
    return found


def get_detector():
    global _detector
    if _detector is None:
        from lingua import LanguageDetectorBuilder

        # High accuracy. On this corpus it takes about three minutes, which is
        # acceptable because a wrong language would change the counts.
        _detector = LanguageDetectorBuilder.from_all_spoken_languages().build()
    return _detector


def detect_language(text):
    """Name the language of a document. Very short or unclear text is unknown."""
    snippet = (text or "").strip()
    compact = "".join(snippet.split())
    # Chinese and similar writing often have no spaces, so a short word count
    # is not enough to call a document too short to classify.
    if len(snippet.split()) < 5 and len(compact) < 30:
        return "unknown"
    sample = snippet[:4000]
    language = get_detector().detect_language_of(sample)
    if language is None:
        return "unknown"
    confidence = get_detector().compute_language_confidence(sample, language)
    if confidence < 0.35:
        return "unknown"
    return language.name.replace("_", " ").title()


def _searched_parts(raw_text, config):
    if config.use_headers:
        header, body = split_header(raw_text)
        parts = []
        wanted = {field.casefold() for field in config.header_fields}
        for key, value in header.items():
            if key.casefold() in wanted and value.strip():
                parts.append(
                    {"location": key, "text": maybe_clean(value, config.strip_formatting)}
                )
        parts.append({"location": "body", "text": maybe_clean(body, config.strip_formatting)})
        language_source = maybe_clean(body, config.strip_formatting).strip()
        if not language_source:
            language_source = "\n".join(part["text"] for part in parts)
        return parts, language_source
    text = maybe_clean(raw_text, config.strip_formatting)
    return [{"location": "body", "text": text}], text


def read_one_document(resolved, metadata, config):
    """Read one file the way a search would, without detecting its language.

    Returns None when the file is missing, unreadable, or empty.
    """
    if resolved is None or resolved.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return None
    try:
        raw_text = read_document(resolved)
    except Exception:
        return None
    if not raw_text or not raw_text.strip():
        return None
    parts, _language_source = _searched_parts(raw_text, config)
    return Document(
        absolute_path=str(resolved),
        file_name=resolved.name,
        metadata=dict(metadata),
        parts=parts,
        language="",
        word_count=0,
        short=False,
    )


def load_corpus(config, status=None, should_stop=None):
    """Read every selected document. Nothing in the corpus folder is changed."""
    status = status or (lambda message, current=None, total=None: None)
    sources = list_sources(config)
    loaded = LoadedCorpus()
    total = len(sources)
    if total == 0:
        return loaded

    limit = int(config.short_word_limit)
    pending = []
    for index, (resolved, display, metadata) in enumerate(sources, start=1):
        check_stop(should_stop)
        report_status(
            status,
            f"Reading documents: {index:,} of {total:,}",
            index,
            total,
        )
        if resolved is None:
            loaded.missing.append(display or "(blank path)")
            continue
        if resolved.suffix.lower() not in SUPPORTED_EXTENSIONS:
            loaded.unreadable.append(
                (display, "This file type is not one the tool can read.")
            )
            continue
        try:
            raw_text = read_document(resolved)
        except Exception as error:
            loaded.unreadable.append((display, str(error)))
            continue
        if not raw_text or not raw_text.strip():
            loaded.empty.append(display)
            continue
        parts, language_source = _searched_parts(raw_text, config)
        counted = sum(word_count(part["text"]) for part in parts)
        pending.append(
            (resolved, metadata, parts, language_source, counted, limit > 0 and counted < limit)
        )

    detect_total = len(pending)
    if detect_total:
        report_status(status, "Preparing language detection...")
        get_detector()
    for index, (resolved, metadata, parts, language_source, counted, short) in enumerate(
        pending, start=1
    ):
        check_stop(should_stop)
        report_status(
            status,
            f"Detecting languages: {index:,} of {detect_total:,}",
            index,
            detect_total,
        )
        loaded.documents.append(
            Document(
                absolute_path=str(resolved),
                file_name=resolved.name,
                metadata=dict(metadata),
                parts=parts,
                language=detect_language(language_source),
                word_count=counted,
                short=short,
            )
        )
    return loaded
