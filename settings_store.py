"""Remember the choices from the window, outside the corpus folder."""

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
LEGACY_SETTINGS_PATH = PROJECT_DIR / "settings.json"
DEFAULT_TERM_LIST = PROJECT_DIR / "dao_ideals.csv"
DEFAULT_TEXT_SIZE = 12
MIN_TEXT_SIZE = 8
MAX_TEXT_SIZE = 24


def clamp_text_size(value):
    try:
        size = int(value)
    except (TypeError, ValueError):
        size = DEFAULT_TEXT_SIZE
    return max(MIN_TEXT_SIZE, min(MAX_TEXT_SIZE, size))


def font_for(role, size):
    """Point sizes for the window. The default is a step larger than the first version."""
    size = clamp_text_size(size)
    if role == "heading":
        return ("TkDefaultFont", size + 4, "bold")
    if role == "label":
        return ("TkDefaultFont", size + 2, "bold")
    if role == "run":
        return ("TkDefaultFont", size + 3, "bold")
    return ("TkDefaultFont", size)


@dataclass
class RunConfig:
    corpus_folder: str = ""
    term_list: str = ""
    metadata_file: str = ""
    path_column: str = ""
    group_column: str = ""
    results_folder: str = ""
    strip_formatting: bool = True
    use_headers: bool = False
    header_fields: list = field(default_factory=lambda: ["title"])
    short_word_limit: int = 50
    count_language: str = "All languages"
    category: str = "All categories"
    text_size: int = DEFAULT_TEXT_SIZE
    context_words: bool = True
    exclusion_list: str = ""
    sample_size: int = 100
    sample_seed: int = 1


def preferred_settings_path():
    """A place that is not the project folder and not a document corpus."""
    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "Tool 4 Concordance"
            / "settings.json"
        )
    return Path.home() / ".tool4-concordance" / "settings.json"


def settings_path(corpus_folder=""):
    """Return where settings are stored, never inside the corpus folder."""
    candidates = [
        preferred_settings_path(),
        LEGACY_SETTINGS_PATH,
        Path.home() / ".tool4-concordance-settings.json",
    ]
    if not corpus_folder:
        return candidates[0]
    for path in candidates:
        if not is_inside(path, corpus_folder):
            return path
    raise OSError(
        "The settings file would be inside the corpus folder. Choose a different corpus folder."
    )


def expand_path(value):
    value = (value or "").strip()
    if not value:
        return ""
    return str(Path(value).expanduser())


def _read_settings_file():
    for path in (preferred_settings_path(), LEGACY_SETTINGS_PATH):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            return data
    return {}


def load_settings():
    config = RunConfig()
    data = _read_settings_file()
    if data:
        config.corpus_folder = expand_path(data.get("corpus_folder") or "")
        config.term_list = expand_path(data.get("term_list") or "")
        config.metadata_file = expand_path(data.get("metadata_file") or "")
        config.path_column = str(data.get("path_column") or "")
        config.group_column = str(data.get("group_column") or "")
        config.results_folder = expand_path(data.get("results_folder") or "")
        config.strip_formatting = bool(data.get("strip_formatting", True))
        config.use_headers = bool(data.get("use_headers", False))
        fields = data.get("header_fields")
        if isinstance(fields, list):
            config.header_fields = [str(item) for item in fields if str(item).strip()]
        config.count_language = str(data.get("count_language") or "All languages")
        config.category = str(data.get("category") or "All categories")
        try:
            config.short_word_limit = max(0, int(data.get("short_word_limit", 50)))
        except (TypeError, ValueError):
            config.short_word_limit = 50
        config.text_size = clamp_text_size(data.get("text_size", DEFAULT_TEXT_SIZE))
        if "context_words" in data:
            config.context_words = bool(data.get("context_words"))
        if "exclusion_list" in data:
            config.exclusion_list = expand_path(data.get("exclusion_list") or "")
        try:
            config.sample_size = int(data.get("sample_size", 100))
        except (TypeError, ValueError):
            config.sample_size = 100
        if config.sample_size < 0:
            config.sample_size = 100
        try:
            config.sample_seed = int(data.get("sample_seed", 1))
        except (TypeError, ValueError):
            config.sample_seed = 1
    if not config.term_list and DEFAULT_TERM_LIST.is_file():
        config.term_list = str(DEFAULT_TERM_LIST)
    return config


def save_settings(config):
    payload = asdict(config)
    payload["header_fields"] = list(config.header_fields)
    path = settings_path(config.corpus_folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def is_inside(path, folder):
    """True when path is the folder itself or something inside it."""
    try:
        Path(path).resolve().relative_to(Path(folder).resolve())
    except (OSError, ValueError):
        return False
    return True


def validate_config(config):
    """Return a plain-language error, or None when the choices can be run."""
    corpus = Path(config.corpus_folder) if config.corpus_folder else None
    if corpus is None or not corpus.is_dir():
        return "Choose a corpus folder."

    term_list = Path(config.term_list) if config.term_list else None
    if term_list is None or not term_list.is_file():
        return "Choose a term list. It is a CSV file with columns for category, term, and stem."
    if is_inside(term_list, corpus):
        return (
            "Keep the term list outside the corpus folder. "
            "The tool saves word decisions next to it and must not change the corpus."
        )

    if config.exclusion_list:
        exclusion_list = Path(config.exclusion_list)
        if not exclusion_list.is_file():
            return "The exclusion list could not be found."

    if not config.results_folder:
        return "Choose a folder where the results should be saved."
    results = Path(config.results_folder)
    if results.exists() and not results.is_dir():
        return "The results location needs to be a folder."
    if is_inside(results, corpus):
        return (
            "The results folder is inside the corpus folder. "
            "Choose a different place so the tool does not change your documents."
        )

    if config.metadata_file:
        metadata = Path(config.metadata_file)
        if not metadata.is_file():
            return "The metadata file could not be found."
        if not config.path_column:
            return "Choose which metadata column contains the file path."

    try:
        limit = int(config.short_word_limit)
    except (TypeError, ValueError):
        return "The short-document cutoff needs to be a whole number. Use 0 to flag nothing."
    if limit < 0:
        return "The short-document cutoff cannot be negative. Use 0 to flag nothing."
    try:
        sample_size = int(config.sample_size)
    except (TypeError, ValueError):
        return "The coding sample size needs to be a whole number. Use 0 to code every match."
    if sample_size < 0:
        return "The coding sample size cannot be negative. Use 0 to code every match."
    try:
        int(config.sample_seed)
    except (TypeError, ValueError):
        return "The sample seed needs to be a whole number, such as 1."
    return None
