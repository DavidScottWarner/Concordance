"""The window where a run is set up."""

import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from variant_window import (
    SameCheck,
    bind_text_zoom,
    copyable_text,
    fit_copyable,
    WheelScroller,
    scroll_canvas_by_pixels,
    set_copyable,
)

from corpus import discover_header_fields, list_sources
from settings_store import (
    DEFAULT_TEXT_SIZE,
    RunConfig,
    clamp_text_size,
    expand_path,
    font_for,
    load_settings,
    save_settings,
)
from terms import categories_in_order, load_terms

NOTE_COLOR = "#767676"
RUN_COLOR = "#1f77b4"
RUN_COLOR_ACTIVE = "#155a8a"

LANGUAGE_CHOICES = [
    "All languages",
    "English",
    "Chinese",
    "Spanish",
    "French",
    "German",
    "Portuguese",
    "Japanese",
    "Korean",
    "Arabic",
    "Russian",
]


class AccentButton(tk.Frame):
    """A colored Run button. Standard Mac buttons ignore a background color."""

    def __init__(self, parent, text, command):
        super().__init__(parent, bg=RUN_COLOR, padx=18, pady=8, cursor="hand2")
        self._command = command
        self._enabled = True
        self.label = tk.Label(
            self,
            text=text,
            bg=RUN_COLOR,
            fg="white",
            font=font_for("run", DEFAULT_TEXT_SIZE),
            cursor="hand2",
        )
        self.label.pack()
        self._bind_click()
        for widget in (self, self.label):
            widget.bind("<Enter>", lambda _event: self._paint(RUN_COLOR_ACTIVE))
            widget.bind("<Leave>", lambda _event: self._paint(RUN_COLOR if self._enabled else "#9bb8d3"))

    def _paint(self, color):
        self.configure(bg=color)
        self.label.configure(bg=color)

    def _bind_click(self):
        self.bind("<Button-1>", self._click)
        self.label.bind("<Button-1>", self._click)

    def _click(self, _event):
        if self._enabled:
            self._command()

    def config(self, **kwargs):
        state = kwargs.pop("state", None)
        if state is not None:
            self._enabled = str(state) != "disabled"
            self._paint(RUN_COLOR if self._enabled else "#9bb8d3")
            self.label.configure(fg="white" if self._enabled else "#f4f4f4")
            self.configure(cursor="hand2" if self._enabled else "arrow")
            self.label.configure(cursor="hand2" if self._enabled else "arrow")
        if kwargs:
            super().config(**kwargs)

    configure = config

    def set_font(self, font):
        self.label.configure(font=font)


def _parse_integer(text, message):
    """A whole number, including negatives. Returns (number, error)."""
    raw = (text or "").strip()
    if raw.startswith("-"):
        digits = raw[1:]
        negative = True
    else:
        digits = raw
        negative = False
    if not digits.isdigit():
        return None, message
    number = int(digits)
    return (-number if negative else number), None


def _parse_nonnegative(text, invalid_message, negative_message):
    number, error = _parse_integer(text, invalid_message)
    if error:
        return None, error
    if number < 0:
        return None, negative_message
    return number, None


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Concordance")
        self.root.minsize(700, 560)
        self.root.geometry("900x720")
        self.header_vars = {}
        self.saved = load_settings()
        self.text_size = clamp_text_size(self.saved.text_size)
        self._open_variant = None
        self._busy = None
        self._stop_requested = threading.Event()
        self._ignore_progress = False
        self._progress_mode = None
        self._progress_lock = threading.Lock()
        self._progress_queued = False
        self._pending_progress = ("Ready.", None, None)
        self._build()
        self._apply(self.saved)
        self._fit_window()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.bind_all("<Button-1>", self._clear_typing_focus, add="+")
        bind_text_zoom(self.root.bind_all, self.zoom_text)
        for class_name in ("Entry", "TEntry", "TCombobox"):
            bind_text_zoom(
                lambda sequence, func, class_name=class_name: self.root.bind_class(
                    class_name, sequence, func
                ),
                self.zoom_text,
            )

    def _build(self):
        self._text_roles = []
        self._fitting_text = False
        self._saved_path_column = ""
        self._saved_group_column = ""
        self._applying_settings = False
        outer = ttk.Frame(self.root, padding=(16, 12))
        outer.pack(fill=tk.BOTH, expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)
        self._outer = outer
        outer.bind("<Configure>", self._on_resize)

        canvas = tk.Canvas(outer, highlightthickness=0, bg=self.root.cget("bg"), borderwidth=0)
        scroll = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        body = ttk.Frame(canvas)
        body_id = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _event: self._refresh_scroll())
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(body_id, width=event.width))
        self._form_canvas = canvas
        self._scroll_body = body

        self.corpus_var = tk.StringVar()
        self.term_var = tk.StringVar()
        self.exclusion_var = tk.StringVar()
        self.metadata_var = tk.StringVar()
        self.path_column_var = tk.StringVar()
        self.group_column_var = tk.StringVar(value="(none)")
        self.results_var = tk.StringVar()
        self.strip_var = tk.BooleanVar(value=True)
        self.headers_var = tk.BooleanVar(value=False)
        self.short_var = tk.StringVar(value="50")
        self.sample_size_var = tk.StringVar(value="100")
        self.sample_seed_var = tk.StringVar(value="1")
        self.language_var = tk.StringVar(value="All languages")
        self.category_var = tk.StringVar(value="All categories")
        self.context_var = tk.BooleanVar(value=True)

        documents = self._add_section(body, "1. Documents", first=True)
        self._fill_documents(documents)
        self._add_section_gap(body)
        terms = self._add_section(body, "2. Search terms")
        self._fill_terms(terms)
        self._add_section_gap(body)
        options = self._add_section(body, "3. Options")
        self._fill_options(options)
        self._add_section_gap(body)
        results = self._add_section(body, "4. Results")
        self._fill_results(results)

        bar = ttk.Frame(outer)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Separator(bar, orient="horizontal").pack(fill="x", pady=(0, 12))
        actions = ttk.Frame(bar)
        actions.pack(anchor="w")
        self.run_button = AccentButton(actions, "Run", self.on_run)
        self.run_button.pack(side="left")
        self.stop_button = ttk.Button(
            actions, text="Stop", command=self.on_stop, state="disabled"
        )
        self.stop_button.pack(side="left", padx=(8, 0))

        self.progress = ttk.Progressbar(bar, mode="determinate", maximum=1, value=0)
        self._results_folder = ""
        self.open_results_button = ttk.Button(
            bar,
            text="Open results folder",
            command=self.open_results_folder,
        )
        self.status_var = tk.StringVar(value="Ready.")
        status = copyable_text(
            bar, "Ready.", font_for("body", self.text_size), "#333", self.root.cget("bg")
        )
        status._zoom = self.zoom_text
        status.pack(anchor="w", fill="x", pady=(10, 0))
        self._status_label = status
        self._text_roles.append((status, "body"))
        self.status_var.trace_add("write", self._sync_status_text)
        self.root.after_idle(lambda: fit_copyable(self._status_label))

        self.term_var.trace_add("write", lambda *_args: self.refresh_categories())
        self.metadata_var.trace_add("write", lambda *_args: self.refresh_metadata_columns())
        self.path_column_var.trace_add("write", lambda *_args: self._remember_column_choice("path"))
        self.group_column_var.trace_add("write", lambda *_args: self._remember_column_choice("group"))
        self._form_scroller = WheelScroller(self.root, lambda pixels: scroll_canvas_by_pixels(canvas, pixels))
        self._bind_wheel(body)
        self._bind_wheel(canvas)
        self._bind_wheel(scroll)
        self._apply_fonts()

    def _add_section(self, parent, title, first=False):
        block = ttk.Frame(parent)
        block.pack(fill="x", pady=(0 if first else 0, 0))
        self._selectable(block, title, "heading", "#222", wrap=True).pack(anchor="w", fill="x")
        fields = ttk.Frame(block)
        fields.pack(fill="x", pady=(8, 0))
        fields.columnconfigure(0, weight=1)
        return fields

    def _add_section_gap(self, parent):
        gap = ttk.Frame(parent)
        gap.pack(fill="x", pady=(8, 8))
        ttk.Separator(gap, orient="horizontal").pack(fill="x")

    def _fill_documents(self, parent):
        row = self._path_row(parent, 0, "Corpus folder", self.corpus_var, self.browse_corpus)
        row = self._path_row(parent, row, "Metadata file", self.metadata_var, self.browse_metadata)
        self._note(
            parent,
            row,
            "Optional. Leave this blank to read every supported file in the corpus folder, including subfolders.",
        )
        row += 1
        self._field_label(parent, "Column with the file path").grid(
            row=row, column=0, sticky="w", pady=(10, 2)
        )
        row += 1
        self.path_box = ttk.Combobox(parent, textvariable=self.path_column_var, state="readonly")
        self.path_box.grid(row=row, column=0, sticky="ew")
        row += 1
        self._note(
            parent,
            row,
            "If you chose a metadata file, pick the column that says where each document's file is, so each document is matched to its row.",
        )
        row += 1
        self._field_label(parent, "Group results by").grid(row=row, column=0, sticky="w", pady=(10, 2))
        row += 1
        self.group_box = ttk.Combobox(parent, textvariable=self.group_column_var, state="readonly")
        self.group_box.grid(row=row, column=0, sticky="ew")

    def _fill_terms(self, parent):
        row = self._path_row(parent, 0, "Term list", self.term_var, self.browse_terms)
        row = self._path_row(
            parent, row, "Exclusion list", self.exclusion_var, self.browse_exclusions
        )
        self._note(
            parent,
            row,
            "Optional. A CSV with category and phrase. A blank category applies to every category.",
        )
        row += 1
        self._field_label(parent, "Category to run").grid(row=row, column=0, sticky="w", pady=(10, 2))
        self.category_box = ttk.Combobox(
            parent,
            textvariable=self.category_var,
            state="readonly",
        )
        self.category_box.grid(row=row + 1, column=0, sticky="ew")
        word_actions = ttk.Frame(parent)
        word_actions.grid(row=row + 2, column=0, sticky="w", pady=(8, 0))
        self.review_button = ttk.Button(
            word_actions,
            text="Review word choices",
            command=self.on_review,
        )
        self.review_button.pack(side="left")

    def _fill_options(self, parent):
        background = self.root.cget("bg")
        SameCheck(
            parent,
            self.strip_var,
            text="Remove formatting marks and web addresses before searching",
            background=background,
        ).grid(row=0, column=0, sticky="w")
        SameCheck(
            parent,
            self.headers_var,
            text="Documents begin with header lines such as title: and url:, then a blank line",
            command=self.toggle_headers,
            background=background,
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))

        self.header_section = ttk.Frame(parent)
        self.header_section.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.find_headers_button = ttk.Button(
            self.header_section,
            text="Find header fields",
            command=self.on_find_headers,
        )
        self.find_headers_button.pack(anchor="w", pady=(0, 4))
        header_note = self._selectable(
            self.header_section,
            "Tick the header fields to search. The rest of the document is always searched.",
            "note",
            NOTE_COLOR,
            wrap=True,
        )
        header_note.pack(anchor="w", fill="x")
        self.header_box = ttk.Frame(self.header_section)
        self.header_box.pack(fill="x", pady=(4, 0))

        self._field_label(parent, "Flag documents shorter than").grid(
            row=3, column=0, sticky="w", pady=(10, 2)
        )
        cutoff = ttk.Frame(parent)
        cutoff.grid(row=4, column=0, sticky="w")
        ttk.Entry(cutoff, textvariable=self.short_var, width=6).pack(side="left")
        self._selectable(cutoff, "words", "body", "#222").pack(side="left", padx=(8, 0))

        self._field_label(parent, "Language used for the counts").grid(
            row=5, column=0, sticky="w", pady=(10, 2)
        )
        self.language_box = ttk.Combobox(
            parent,
            textvariable=self.language_var,
            values=LANGUAGE_CHOICES,
            width=24,
        )
        self.language_box.grid(row=6, column=0, sticky="w")
        self._note(parent, 7, "Counts include only documents in this language.")
        self._field_label(parent, "Coding sample size per category").grid(
            row=8, column=0, sticky="w", pady=(10, 2)
        )
        ttk.Entry(parent, textvariable=self.sample_size_var, width=8).grid(
            row=9, column=0, sticky="w"
        )
        self._note(
            parent,
            10,
            "Use 0 to code every match in the counts. Otherwise each category gets a sample of this size.",
        )
        self._field_label(parent, "Sample seed").grid(
            row=11, column=0, sticky="w", pady=(10, 2)
        )
        ttk.Entry(parent, textvariable=self.sample_seed_var, width=8).grid(
            row=12, column=0, sticky="w"
        )
        self._note(parent, 13, "The same seed draws the same sample again.")
        SameCheck(
            parent,
            self.context_var,
            text="Also list words found near the terms",
            background=background,
        ).grid(row=14, column=0, sticky="w", pady=(10, 0))

    def _fill_results(self, parent):
        self._path_row(parent, 0, "Results folder", self.results_var, self.browse_results)

    def _text_bg(self):
        if not hasattr(self, "_label_bg"):
            probe = tk.Label(self.root)
            self._label_bg = probe.cget("bg")
            probe.destroy()
        return self._label_bg

    def _selectable(self, parent, text, role, fg, wrap=False):
        width = min(max(len(text), 8), 48) if wrap else max(len(text), 4)
        widget = copyable_text(
            parent, text, font_for(role, self.text_size), fg, self._text_bg(), width=width
        )
        widget._zoom = self.zoom_text
        self._text_roles.append((widget, role))
        return widget

    def _field_label(self, parent, text):
        return self._selectable(parent, text, "label", "#222")

    def _path_row(self, parent, row, label, variable, command):
        top = 4 if row == 0 else 10
        self._field_label(parent, label).grid(row=row, column=0, sticky="w", pady=(top, 2))
        line = ttk.Frame(parent)
        line.grid(row=row + 1, column=0, sticky="ew")
        line.columnconfigure(0, weight=1)
        ttk.Entry(line, textvariable=variable).grid(row=0, column=0, sticky="ew")
        ttk.Button(line, text="Browse…", command=command).grid(row=0, column=1, padx=(8, 0))
        return row + 2

    def _note(self, parent, row, text):
        label = self._selectable(parent, text, "note", NOTE_COLOR, wrap=True)
        label.grid(row=row, column=0, sticky="ew", pady=(4, 0))
        return label

    def _bind_wheel(self, widget):
        widget.bind("<MouseWheel>", self._on_form_wheel, add="+")
        for child in widget.winfo_children():
            self._bind_wheel(child)

    def _refresh_scroll(self):
        self._form_canvas.update_idletasks()
        self._form_canvas.configure(scrollregion=self._form_canvas.bbox("all"))

    def _fit_window(self):
        self.root.update_idletasks()
        self._refresh_scroll()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        width = min(980, max(860, screen_w - 80))
        for _ in range(2):
            self.root.update()
            self._refresh_scroll()
            region = self._form_canvas.cget("scrollregion").split()
            body_h = int(float(region[3]) - float(region[1])) if len(region) == 4 else self._scroll_body.winfo_reqheight()
            height = min(body_h + 190, screen_h - 40)
            self.root.geometry(f"{width}x{max(height, 640)}")
        self.root.minsize(780, 560)
        self._refresh_scroll()

    def _on_form_wheel(self, event):
        return self._form_scroller.on_wheel(event)

    def zoom_text(self, delta):
        if delta == 0:
            self.set_text_size(DEFAULT_TEXT_SIZE)
        else:
            self.set_text_size(self.text_size + delta)
        return "break"

    def set_text_size(self, size):
        size = clamp_text_size(size)
        changed = size != self.text_size
        self.text_size = size
        self._apply_fonts()
        if self._open_variant is not None:
            self._open_variant.apply_text_size(size)
        if changed:
            self._persist_text_size()

    def _register_variant(self, dialog):
        self._open_variant = dialog

    def _apply_fonts(self):
        for widget, role in self._text_roles:
            widget.configure(font=font_for(role, self.text_size))
            fit_copyable(widget)
        self.run_button.set_font(font_for("run", self.text_size))
        style = ttk.Style(self.root)
        body = font_for("body", self.text_size)
        for name in ("TCheckbutton", "TButton", "TLabel", "TEntry", "TCombobox"):
            style.configure(name, font=body)
        self._refresh_scroll()

    def _persist_text_size(self):
        config, _problem = self.read_config()
        self._keep_saved_numbers(config)
        try:
            save_settings(config)
        except OSError:
            pass

    def _on_resize(self, event):
        if event.widget is not self._outer or self._fitting_text:
            return
        self._fit_selectable()

    def _fit_selectable(self):
        if self._fitting_text:
            return
        self._fitting_text = True
        try:
            self.root.update_idletasks()
            for widget, _role in self._text_roles:
                fit_copyable(widget)
        finally:
            self._fitting_text = False

    def _apply(self, config):
        self._applying_settings = True
        self._saved_path_column = (config.path_column or "").strip()
        self._saved_group_column = (config.group_column or "").strip()
        if self._saved_path_column:
            self.path_column_var.set(self._saved_path_column)
        if self._saved_group_column:
            self.group_column_var.set(self._saved_group_column)
        else:
            self.group_column_var.set("(none)")
        self.corpus_var.set(config.corpus_folder)
        self.term_var.set(config.term_list)
        self.exclusion_var.set(getattr(config, "exclusion_list", "") or "")
        self.metadata_var.set(config.metadata_file)
        self.results_var.set(config.results_folder)
        self.strip_var.set(config.strip_formatting)
        self.headers_var.set(config.use_headers)
        self.short_var.set(str(config.short_word_limit))
        self.sample_size_var.set(str(config.sample_size))
        self.sample_seed_var.set(str(config.sample_seed))
        self.language_var.set(config.count_language or "All languages")
        self.category_var.set(config.category or "All categories")
        self.context_var.set(bool(config.context_words))
        self.show_header_fields(config.header_fields or ["title"], check_these=config.header_fields)
        self.toggle_headers()
        self.refresh_metadata_columns()
        self._choose_saved_columns()
        self.refresh_categories()
        self._applying_settings = False
        self.root.after_idle(self._choose_saved_columns)
        self.root.after_idle(self._fit_selectable)

    def read_config(self):
        raw_limit = self.short_var.get().strip() or "0"
        try:
            limit = int(raw_limit)
        except ValueError:
            limit = 50
            limit_error = "The short-document cutoff needs to be a whole number. Use 0 to flag nothing."
        else:
            if limit < 0:
                limit_error = "The short-document cutoff cannot be negative. Use 0 to flag nothing."
            else:
                limit_error = None
        sample_size, sample_error = _parse_nonnegative(
            self.sample_size_var.get(),
            "The coding sample size needs to be a whole number. Use 0 to code every match.",
            "The coding sample size cannot be negative. Use 0 to code every match.",
        )
        sample_seed, seed_error = _parse_integer(
            self.sample_seed_var.get(),
            "The sample seed needs to be a whole number, such as 1.",
        )
        group = self.group_column_var.get().strip()
        if group == "(none)":
            group = ""
        config = RunConfig(
            corpus_folder=expand_path(self.corpus_var.get()),
            term_list=expand_path(self.term_var.get()),
            exclusion_list=expand_path(self.exclusion_var.get()),
            metadata_file=expand_path(self.metadata_var.get()),
            path_column=self.path_column_var.get().strip(),
            group_column=group,
            results_folder=expand_path(self.results_var.get()),
            strip_formatting=bool(self.strip_var.get()),
            use_headers=bool(self.headers_var.get()),
            header_fields=self.checked_header_fields(),
            short_word_limit=limit,
            sample_size=100 if sample_size is None else sample_size,
            sample_seed=1 if sample_seed is None else sample_seed,
            count_language=self.language_var.get().strip() or "All languages",
            category=self.category_var.get().strip() or "All categories",
            text_size=self.text_size,
            context_words=bool(self.context_var.get()),
        )
        return config, limit_error or sample_error or seed_error

    def set_status(self, text):
        self.status_var.set(text)
        self.root.update()

    def _sync_status_text(self, *_args):
        set_copyable(self._status_label, self.status_var.get())

    def open_results_folder(self):
        folder = self._results_folder
        if folder and Path(folder).is_dir():
            subprocess.run(["open", folder], check=False)

    def _show_open_results(self, folder):
        self._results_folder = str(folder)
        if not self.open_results_button.winfo_ismapped():
            self.open_results_button.pack(anchor="w", pady=(8, 0), before=self._status_label)

    def _clear_typing_focus(self, event):
        widget = event.widget
        # A dropdown list can report its name as text instead of a widget.
        if isinstance(widget, str):
            try:
                widget = self.root.nametowidget(widget)
            except (KeyError, tk.TclError, AttributeError):
                return
        try:
            if widget.winfo_toplevel() is not self.root:
                return
            if widget.winfo_class() in {
                "Entry",
                "TEntry",
                "Text",
                "TCombobox",
                "Combobox",
                "Spinbox",
                "TSpinbox",
                "Listbox",
            }:
                return
        except (tk.TclError, AttributeError):
            return
        self.root.focus_set()

    def _set_busy(self, busy):
        self._busy = busy
        self.run_button.config(state="disabled" if busy else "normal")
        self.find_headers_button.config(state="disabled" if busy else "normal")
        self.review_button.config(state="disabled" if busy else "normal")
        self.stop_button.config(state="normal" if busy in {"run", "review"} else "disabled")

    def _show_progress_bar(self):
        if not self.progress.winfo_ismapped():
            self.progress.pack(fill="x", pady=(8, 0), before=self._status_label)

    def _apply_progress(self, message, current, total):
        if self._ignore_progress:
            return
        if self._stop_requested.is_set():
            message = "Stopping..."
        self.status_var.set(message)
        self._show_progress_bar()
        if total:
            if self._progress_mode != "determinate":
                self.progress.stop()
                self.progress.configure(mode="determinate")
                self._progress_mode = "determinate"
            self.progress.configure(maximum=max(int(total), 1), value=int(current or 0))
        elif self._progress_mode != "indeterminate":
            self.progress.configure(mode="indeterminate")
            self.progress.start(12)
            self._progress_mode = "indeterminate"

    def _flush_progress(self):
        with self._progress_lock:
            message, current, total = self._pending_progress
            self._progress_queued = False
        try:
            if self.root.winfo_exists():
                self._apply_progress(message, current, total)
        except tk.TclError:
            pass

    def _post_progress(self, message, current=None, total=None):
        with self._progress_lock:
            self._pending_progress = (message, current, total)
            if self._progress_queued:
                return
            self._progress_queued = True
        try:
            self.root.after(0, self._flush_progress)
        except tk.TclError:
            with self._progress_lock:
                self._progress_queued = False

    def _on_main(self, callback):
        try:
            if self.root.winfo_exists():
                self.root.after(0, callback)
        except tk.TclError:
            pass

    def _end_run(self, message, *, filled):
        try:
            if not self.root.winfo_exists():
                return
            self.progress.stop()
            self._progress_mode = "determinate"
            self.progress.configure(mode="determinate", maximum=1, value=1 if filled else 0)
            self._show_progress_bar()
            self.status_var.set(message)
            self._set_busy(None)
        except tk.TclError:
            return

    def browse_corpus(self):
        chosen = filedialog.askdirectory(
            title="Choose the corpus folder",
            initialdir=self._initial_dir(self.corpus_var.get()),
        )
        if chosen:
            self.corpus_var.set(chosen)

    def browse_terms(self):
        chosen = filedialog.askopenfilename(
            title="Choose the term list",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialdir=self._initial_dir(self.term_var.get()),
        )
        if chosen:
            self.term_var.set(chosen)

    def browse_exclusions(self):
        chosen = filedialog.askopenfilename(
            title="Choose the exclusion list",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialdir=self._initial_dir(self.exclusion_var.get() or self.term_var.get()),
        )
        if chosen:
            self.exclusion_var.set(chosen)

    def browse_metadata(self):
        chosen = filedialog.askopenfilename(
            title="Choose the metadata file",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialdir=self._initial_dir(self.metadata_var.get() or self.corpus_var.get()),
        )
        if chosen:
            self.metadata_var.set(chosen)

    def browse_results(self):
        chosen = filedialog.askdirectory(
            title="Choose the results folder",
            initialdir=self._initial_dir(self.results_var.get()),
        )
        if chosen:
            self.results_var.set(chosen)

    def _initial_dir(self, current):
        path = Path(current).expanduser() if current else None
        if path and path.is_dir():
            return str(path)
        if path and path.parent.is_dir():
            return str(path.parent)
        return str(Path.home())

    def refresh_categories(self):
        values = ["All categories"]
        path = Path(self.term_var.get().strip())
        current = self.category_var.get()
        if path.is_file():
            try:
                names = categories_in_order(load_terms(path))
                values.extend(sorted(names, key=str.casefold))
            except RuntimeError:
                pass
        self.category_box["values"] = values
        if current in values:
            self.category_var.set(current)
        else:
            self.category_var.set("All categories")

    def _remember_column_choice(self, which):
        if self._applying_settings:
            return
        if which == "path":
            path = self.path_column_var.get().strip()
            if path:
                self._saved_path_column = path
            return
        group = self.group_column_var.get().strip()
        if group and group != "(none)":
            self._saved_group_column = group
        elif group == "(none)":
            self._saved_group_column = ""

    def _choose_saved_columns(self):
        self._keep_column(self.path_box, self.path_column_var, self._saved_path_column, "")
        self._keep_column(
            self.group_box,
            self.group_column_var,
            self._saved_group_column,
            "(none)",
        )

    def _keep_column(self, box, variable, saved, blank):
        choices = [str(item) for item in box["values"]]
        current = (variable.get() or "").strip()
        saved = (saved or "").strip()
        if saved == blank:
            saved = ""
        if current and current != blank and (not choices or current in choices):
            chosen = current
        elif saved and (not choices or saved in choices):
            chosen = saved
        elif current in choices:
            chosen = current or blank
        elif not choices:
            chosen = current or saved or blank
        else:
            chosen = blank
        variable.set(chosen or blank)
        if chosen and chosen in choices:
            box.current(choices.index(chosen))

    def refresh_metadata_columns(self):
        columns = []
        loaded = False
        path = Path(self.metadata_var.get().strip()) if self.metadata_var.get().strip() else None
        if path and path.is_file():
            try:
                from corpus import read_csv_table

                columns, _rows = read_csv_table(path)
                loaded = True
            except (OSError, UnicodeError):
                columns = []
        self.path_box["values"] = columns
        self.group_box["values"] = ["(none)"] + columns if loaded or not path else ["(none)"]
        if loaded or not path:
            self._choose_saved_columns()
        else:
            if self._saved_path_column:
                self.path_column_var.set(self._saved_path_column)
            if self._saved_group_column:
                self.group_column_var.set(self._saved_group_column)

    def toggle_headers(self):
        if self.headers_var.get():
            self.header_section.grid()
        else:
            self.header_section.grid_remove()
        if hasattr(self, "_form_canvas"):
            self._refresh_scroll()

    def checked_header_fields(self):
        return [name for name, variable in self.header_vars.items() if variable.get()]

    def show_header_fields(self, fields, check_these=None):
        previously = set(self.checked_header_fields())
        if check_these is not None:
            previously = {item.casefold() for item in check_these}
        else:
            previously = {item.casefold() for item in previously}
        for child in self.header_box.winfo_children():
            child.destroy()
        self.header_vars = {}
        for index, field in enumerate(fields):
            checked = field.casefold() in previously or (
                not previously and field.casefold() == "title"
            )
            variable = tk.BooleanVar(value=checked)
            self.header_vars[field] = variable
            SameCheck(
                self.header_box,
                variable,
                text=field,
                background=self.root.cget("bg"),
            ).grid(row=index // 3, column=index % 3, sticky="w", padx=(0, 16), pady=2)
        self.header_box.unbind("<MouseWheel>")
        self._bind_wheel(self.header_box)
        self._refresh_scroll()

    def on_find_headers(self):
        config, problem = self.read_config()
        if problem:
            messagebox.showerror("Concordance", problem, parent=self.root)
            return
        if not config.corpus_folder or not Path(config.corpus_folder).is_dir():
            messagebox.showerror("Concordance", "Choose a corpus folder first.", parent=self.root)
            return
        if self._busy:
            return
        self._set_busy("headers")
        self.status_var.set("Scanning…")
        self.root.update_idletasks()

        def work():
            try:
                sources = list_sources(config)
                paths = [resolved for resolved, _display, _metadata in sources if resolved]
                fields = discover_header_fields(paths)
            except Exception as error:
                self._on_main(lambda error=error: self._headers_failed(error))
                return
            self._on_main(lambda fields=fields: self._headers_finished(fields))

        threading.Thread(target=work, daemon=True).start()

    def _headers_failed(self, error):
        self._set_busy(None)
        self.status_var.set(str(error))
        messagebox.showerror("Concordance", str(error), parent=self.root)

    def _headers_finished(self, fields):
        self._set_busy(None)
        if not fields:
            self.status_var.set("No header fields were found.")
            messagebox.showinfo(
                "Concordance",
                "No header lines were found. These documents may not use that format.",
                parent=self.root,
            )
            return
        self.show_header_fields(fields)
        self.status_var.set(f"Found {len(fields)} header fields. Tick the ones to search.")

    def on_review(self):
        from corpus import RunStopped
        from terms import load_terms, select_terms
        from variants import (
            decision_ticks,
            gather_category_words,
            load_latest_decisions,
        )

        config, _problem = self.read_config()
        category = self.category_var.get().strip()
        if not category or category == "All categories":
            messagebox.showinfo(
                "Concordance",
                "Choose one category in the Category menu, then review its word choices.",
                parent=self.root,
            )
            return
        corpus = Path(config.corpus_folder) if config.corpus_folder else None
        if corpus is None or not corpus.is_dir():
            messagebox.showerror("Concordance", "Choose a corpus folder.", parent=self.root)
            return
        if not config.term_list or not Path(config.term_list).is_file():
            messagebox.showerror("Concordance", "Choose a term list first.", parent=self.root)
            return
        if self._busy:
            return
        try:
            terms = select_terms(load_terms(config.term_list), category)
        except RuntimeError as error:
            messagebox.showerror("Concordance", str(error), parent=self.root)
            return
        label = terms[0].category
        stems = [term.stem.strip() for term in terms if term.stem.strip()]
        if not stems:
            messagebox.showinfo(
                "Concordance",
                f"{label} has no stem, so there are no word choices to review.",
                parent=self.root,
            )
            return
        saved = decision_ticks(load_latest_decisions(config.term_list)).get(label.casefold(), {})
        listed = {term.term.casefold() for term in terms}
        self._ignore_progress = False
        self._stop_requested.clear()
        self._set_busy("review")
        self._apply_progress("Gathering words...", None, None)

        def work():
            try:
                rows = gather_category_words(
                    config,
                    label,
                    stems[0],
                    saved,
                    listed,
                    status=self._post_progress,
                    should_stop=self._stop_requested.is_set,
                )
            except RunStopped:
                self._on_main(self._finish_stopped)
                return
            except Exception as error:
                self._on_main(lambda error=error: self._review_failed(error))
                return
            if self._stop_requested.is_set():
                self._on_main(self._finish_stopped)
                return
            self._on_main(
                lambda rows=rows: self._show_review(config, label, stems[0], rows, terms)
            )

        threading.Thread(target=work, daemon=True).start()

    def _review_failed(self, error):
        self._stop_requested.clear()
        self._set_busy(None)
        self.progress.stop()
        self._progress_mode = "determinate"
        text = str(error).strip() or "Something went wrong."
        self.status_var.set(text)
        messagebox.showerror("Concordance", text, parent=self.root)

    def _show_review(self, config, category, stem, rows, terms):
        from terms import category_definitions
        from variant_window import show_variant_window
        from variants import apply_choices

        if self._stop_requested.is_set():
            self._finish_stopped()
            return
        self.progress.stop()
        self._progress_mode = "determinate"
        self.progress.configure(mode="determinate", maximum=1, value=0)
        self._set_busy("review-open")
        self._ignore_progress = True
        self.status_var.set("Ready.")
        choices = show_variant_window(
            self.root,
            category,
            stem,
            rows,
            text_size=self.text_size,
            on_text_size=self.set_text_size,
            register=self._register_variant,
            definition=category_definitions(terms).get(category, ""),
        )
        self._set_busy(None)
        if choices is None:
            self.status_var.set("Word choices were left as they are.")
            return
        try:
            apply_choices(
                config.term_list,
                str(config.corpus_folder),
                category,
                stem,
                choices,
                terms,
            )
        except OSError as error:
            self.status_var.set(str(error))
            messagebox.showerror("Concordance", str(error), parent=self.root)
            return
        self.status_var.set(f"Saved word decisions for {category}.")

    def on_stop(self):
        if self._busy not in {"run", "review"}:
            return
        self._stop_requested.set()
        self.stop_button.config(state="disabled")
        self.status_var.set("Stopping...")

    def _finish_stopped(self):
        self._ignore_progress = True
        self._stop_requested.clear()
        self._end_run("Stopped. No results were saved.", filled=False)

    def on_run(self):
        from concordance import RunCancelled, execute
        from corpus import RunStopped
        from variant_window import show_variant_window

        config, problem = self.read_config()
        if problem:
            messagebox.showerror("Concordance", problem, parent=self.root)
            return
        if self._busy:
            return
        try:
            save_settings(config)
        except OSError as error:
            messagebox.showerror("Concordance", str(error), parent=self.root)
            return
        self._ignore_progress = False
        self._stop_requested.clear()
        self._set_busy("run")
        self._apply_progress("Starting...", None, None)

        def prompter(category, stem, suggestions, related, definition="", position=None):
            holder = {}
            done = threading.Event()

            def show():
                try:
                    holder["value"] = show_variant_window(
                        self.root,
                        category,
                        stem,
                        suggestions,
                        related,
                        text_size=self.text_size,
                        on_text_size=self.set_text_size,
                        register=self._register_variant,
                        stop_check=self._stop_requested.is_set,
                        definition=definition,
                        position=position,
                    )
                except Exception as error:
                    holder["error"] = error
                finally:
                    done.set()

            try:
                if self.root.winfo_exists():
                    self.root.after(0, show)
                else:
                    return None
            except tk.TclError:
                return None
            done.wait()
            if "error" in holder:
                raise holder["error"]
            return holder.get("value")

        def work():
            try:
                folder = execute(
                    config,
                    status=self._post_progress,
                    parent=self.root,
                    prompter=prompter,
                    should_stop=self._stop_requested.is_set,
                )
            except RunStopped:
                self._on_main(self._finish_stopped)
            except RunCancelled as cancelled:
                self._on_main(lambda cancelled=cancelled: self._run_cancelled(cancelled))
            except Exception as error:
                self._on_main(lambda error=error: self._run_failed(error))
            else:
                self._on_main(lambda folder=folder: self._run_finished(folder))

        threading.Thread(target=work, daemon=True).start()

    def _run_cancelled(self, cancelled):
        self._end_run(str(cancelled), filled=False)
        messagebox.showinfo("Concordance", str(cancelled), parent=self.root)

    def _run_failed(self, error):
        text = str(error).strip() or "Something went wrong."
        self._end_run(text, filled=False)
        messagebox.showerror("Concordance", text, parent=self.root)

    def _run_finished(self, folder):
        self._show_open_results(folder)
        self._end_run(f"Done. Results saved to {folder}.", filled=True)
        messagebox.showinfo("Concordance", f"Saved results to:\n{folder}", parent=self.root)

    def on_close(self):
        config, _problem = self.read_config()
        self._keep_saved_numbers(config)
        try:
            save_settings(config)
        except OSError:
            pass
        self.root.destroy()

    def _keep_saved_numbers(self, config):
        """A half-typed number is not saved over the number already remembered."""
        raw_limit = self.short_var.get().strip()
        if raw_limit and not raw_limit.isdigit():
            config.short_word_limit = self.saved.short_word_limit
        if _parse_nonnegative(self.sample_size_var.get(), "", "")[0] is None:
            config.sample_size = self.saved.sample_size
        if _parse_integer(self.sample_seed_var.get(), "")[0] is None:
            config.sample_seed = self.saved.sample_seed
