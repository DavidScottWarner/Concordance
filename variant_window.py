"""The checkbox window for new words."""

import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from settings_store import DEFAULT_TEXT_SIZE, clamp_text_size, font_for, load_settings, save_settings

_NAVIGATION_KEYS = {
    "Left",
    "Right",
    "Up",
    "Down",
    "Home",
    "End",
    "Prior",
    "Next",
    "Shift_L",
    "Shift_R",
    "Control_L",
    "Control_R",
    "Meta_L",
    "Meta_R",
    "Alt_L",
    "Alt_R",
    "Super_L",
    "Super_R",
    "Caps_Lock",
    "Escape",
    "Tab",
}


def copyable_text(parent, text, font, fg, background, width=None):
    """A text line or paragraph that can be selected and copied, but not edited."""
    widget = tk.Text(
        parent,
        height=1,
        width=width if width is not None else max(len(text), 4),
        wrap="word",
        font=font,
        fg=fg,
        bg=background,
        borderwidth=0,
        highlightthickness=0,
        insertwidth=0,
        padx=0,
        pady=0,
        cursor="arrow",
        undo=False,
    )
    widget.insert("1.0", text)
    widget.bind("<Key>", _block_edits)
    widget.bind("<<Paste>>", lambda _event: "break")
    widget.bind("<<Cut>>", lambda _event: "break")
    fit_copyable(widget)
    return widget


def set_copyable(widget, text):
    widget.delete("1.0", "end")
    widget.insert("1.0", text)
    fit_copyable(widget)


def fit_copyable(widget):
    widget.update_idletasks()
    counted = widget.count("1.0", "end-1c", "displaylines")
    if isinstance(counted, tuple):
        lines = counted[0] if counted else 1
    else:
        lines = counted or 1
    widget.configure(height=max(int(lines), 1))


def _command_down(event):
    # The same modifier bits that let Command-C copy selected text.
    return bool(event.state & (0x4 | 0x8 | 0x10 | 0x20000))


def zoom_delta(event):
    """1 to grow, -1 to shrink, 0 to restore the default, or None."""
    if not _command_down(event):
        return None
    key = event.keysym
    if key in {"plus", "equal", "KP_Add"}:
        return 1
    if key in {"minus", "KP_Subtract"}:
        return -1
    if key in {"0", "KP_0"}:
        return 0
    return None


def _block_edits(event):
    delta = zoom_delta(event)
    if delta is not None:
        zoom = getattr(event.widget, "_zoom", None)
        if zoom is not None:
            zoom(delta)
        return "break"
    if event.keysym in _NAVIGATION_KEYS:
        return None
    if _command_down(event) and event.keysym.lower() in {"a", "c"}:
        return None
    return "break"


def match_phrase(count):
    """How a match count is written next to a word."""
    try:
        count = int(count)
    except (TypeError, ValueError):
        count = 0
    if count == 1:
        return "1 match"
    return f"{count} matches"


def sentence_parts(item):
    """The example text and its source. Older rows stored a plain string."""
    if isinstance(item, str):
        return item, ""
    return (item.get("text") or ""), (item.get("source") or "")


def sentence_line(item):
    text, source = sentence_parts(item)
    if source:
        return f"• {text} ({source})"
    return f"• {text}"


def copy_confirmation(count):
    """The note shown after Copy all."""
    if count == 1:
        return "Copied the full list: 1 word with its examples."
    return f"Copied the full list: {count} words with their examples."


class SameCheck(tk.Frame):
    """A tick box that uses one blue for every ticked box."""

    SIZE = 16
    BLUE = "#007AFF"
    BORDER = "#8E8E93"

    def __init__(self, parent, variable, text="", command=None, background=""):
        super().__init__(
            parent,
            bg=background or _widget_background(parent),
            highlightthickness=0,
            bd=0,
            cursor="arrow",
        )
        self._variable = variable
        self._command = command
        self._box = tk.Canvas(
            self,
            width=self.SIZE,
            height=self.SIZE,
            highlightthickness=0,
            borderwidth=0,
            bg=self.cget("bg"),
            cursor="arrow",
        )
        self._box.grid(row=0, column=0)
        self._label = None
        if text:
            self._label = ttk.Label(self, text=text, cursor="arrow")
            self._label.grid(row=0, column=1, sticky="w", padx=(6, 0))
            self._label.bind("<Button-1>", self._toggle)
        self._box.bind("<Button-1>", self._toggle)
        self._trace = variable.trace_add("write", self._redraw)
        self.bind("<Destroy>", self._on_destroy)
        self._draw()

    def _toggle(self, _event=None):
        self._variable.set(not bool(self._variable.get()))
        if self._command is not None:
            self._command()
        return "break"

    def _redraw(self, *_args):
        if self.winfo_exists():
            self._draw()

    def _on_destroy(self, event):
        if event.widget is not self:
            return
        try:
            self._variable.trace_remove("write", self._trace)
        except tk.TclError:
            pass

    def _draw(self):
        box = self._box
        box.delete("all")
        if self._variable.get():
            box.create_rectangle(1, 1, 15, 15, fill=self.BLUE, outline=self.BLUE)
            box.create_line(
                4, 8, 7, 12, 12, 4,
                fill="white",
                width=2,
                capstyle="round",
                joinstyle="round",
            )
        else:
            box.create_rectangle(1, 1, 15, 15, outline=self.BORDER, width=1)

    def tick_color(self):
        """The fill of a ticked box, or an empty string when it is unticked."""
        if not self._variable.get():
            return ""
        for item in self._box.find_all():
            fill = self._box.itemcget(item, "fill")
            if fill == self.BLUE:
                return fill
        return ""


def _widget_background(widget):
    for option in ("background", "bg"):
        try:
            value = widget.cget(option)
        except tk.TclError:
            continue
        if value:
            return str(value)
    try:
        return str(widget.winfo_toplevel().cget("bg"))
    except tk.TclError:
        return "#ffffff"


class WheelScroller:
    """Scrolling that follows a Mac trackpad or a mouse wheel.

    A slow swipe moves a short way. A fast swipe keeps moving after the
    fingers lift. One notch of a mouse wheel moves about three lines.
    """

    def __init__(self, widget, scroll):
        self.widget = widget
        self.scroll = scroll
        self.last = 0.0
        self.velocity = 0.0
        self.coast_job = None
        self.notch_job = None
        self.pending_notch = 0

    def on_wheel(self, event):
        raw = getattr(event, "delta", 0) or 0
        try:
            raw = int(raw)
        except (TypeError, ValueError):
            return "break"
        if raw == 0:
            return "break"
        # One notch on Windows and some mice is 120.
        if abs(raw) >= 120:
            self.stop()
            self.scroll(int(-raw / 120 * 50))
            return "break"
        now = time.perf_counter()
        gap = now - self.last if self.last else 1.0
        self.last = now
        direction = -1 if raw > 0 else 1
        amount = abs(raw)
        if gap >= 0.07:
            # A notch, or the first moment of a swipe. Move a little now.
            self._stop_coast()
            self.scroll(direction * amount * 10)
            self.pending_notch = direction * max(0, 45 - amount * 10)
            self._arm_notch()
        else:
            # Events close together are a trackpad. Faster means farther.
            self._cancel_notch()
            rate = 1.0 / max(gap, 0.004)
            gain = 1.0 + min(rate, 220.0) / 55.0
            pixels = direction * amount * 11 * gain
            pixels = max(-125, min(125, pixels))
            self.scroll(int(pixels))
            self.velocity = pixels / max(gap, 0.008)
            self._arm_coast()
        return "break"

    def stop(self):
        self.velocity = 0.0
        self.pending_notch = 0
        self._cancel_notch()
        self._stop_coast()

    def _arm_notch(self):
        if self.notch_job is not None:
            try:
                self.widget.after_cancel(self.notch_job)
            except tk.TclError:
                pass
            self.notch_job = None
        if self.pending_notch:
            self.notch_job = self.widget.after(70, self._finish_notch)

    def _finish_notch(self):
        self.notch_job = None
        extra = self.pending_notch
        self.pending_notch = 0
        if extra:
            self.scroll(int(extra))

    def _cancel_notch(self):
        self.pending_notch = 0
        if self.notch_job is not None:
            try:
                self.widget.after_cancel(self.notch_job)
            except tk.TclError:
                pass
            self.notch_job = None

    def _arm_coast(self):
        self._stop_coast()
        self.coast_job = self.widget.after(16, self._coast)

    def _coast(self):
        self.coast_job = None
        if abs(self.velocity) < 65:
            self.velocity = 0.0
            return
        step = max(-100, min(100, self.velocity * 0.016))
        self.scroll(int(step))
        self.velocity *= 0.86
        self._arm_coast()

    def _stop_coast(self):
        if self.coast_job is not None:
            try:
                self.widget.after_cancel(self.coast_job)
            except tk.TclError:
                pass
            self.coast_job = None


def scroll_canvas_by_pixels(canvas, pixels):
    """Move a canvas by pixels. Tk on this Mac cannot scroll a canvas by pixels directly."""
    if not pixels:
        return
    region = (canvas.cget("scrollregion") or "").split()
    if len(region) != 4:
        return
    height = float(region[3]) - float(region[1])
    visible = canvas.winfo_height()
    if height <= 1 or visible <= 1 or height <= visible:
        return
    first, _last = canvas.yview()
    top = first * height
    limit = height - visible
    new_top = min(max(top + pixels, 0), limit)
    canvas.yview_moveto(new_top / height)


def bind_text_zoom(binder, callback):
    """binder is widget.bind, widget.bind_all, or a bind_class wrapper."""

    def handler(delta):
        def inner(_event, delta=delta):
            callback(delta)
            return "break"

        return inner

    for sequence in ("<Command-plus>", "<Command-equal>", "<Command-KP_Add>"):
        binder(sequence, handler(1))
    for sequence in ("<Command-minus>", "<Command-KP_Subtract>"):
        binder(sequence, handler(-1))
    for sequence in ("<Command-0>", "<Command-KP_0>"):
        binder(sequence, handler(0))


def _remember_text_size(size):
    config = load_settings()
    config.text_size = clamp_text_size(size)
    try:
        save_settings(config)
    except OSError:
        pass


def show_variant_window(
    parent,
    category,
    stem,
    suggestions,
    related_suggestions=None,
    text_size=None,
    on_text_size=None,
    register=None,
    stop_check=None,
):
    """Show the words and wait until Save or Cancel. Cancel returns None."""
    if text_size is None:
        text_size = load_settings().text_size
    dialog = VariantDialog(
        parent,
        category,
        stem,
        suggestions,
        related_suggestions or [],
        text_size=text_size,
        on_text_size=on_text_size,
        stop_check=stop_check,
    )
    if register is not None:
        register(dialog)
    try:
        parent.wait_window(dialog.window)
    finally:
        if register is not None:
            register(None)
    return dialog.result


class VariantDialog:
    def __init__(
        self,
        parent,
        category,
        stem,
        suggestions,
        related_suggestions,
        text_size=None,
        on_text_size=None,
        stop_check=None,
    ):
        self.result = None
        self.rows = []
        self._drag_job = None
        self._drag_dir = 0
        self._drag_xy = (0, 0)
        self.category = category
        self.on_text_size = on_text_size
        self.text_size = clamp_text_size(
            DEFAULT_TEXT_SIZE if text_size is None else text_size
        )
        self.window = tk.Toplevel(parent)
        self.window.title(f"New words for {category}")
        self.window.geometry("900x720")
        self.window.minsize(700, 560)
        self.window.resizable(True, True)
        self.window.transient(parent)
        self.stop_check = stop_check
        self._stop_job = None
        if stop_check is None:
            self.window.grab_set()
        else:
            self.window.lift()
            self._stop_job = self.window.after(200, self._watch_stop)
        self.window.protocol("WM_DELETE_WINDOW", self.cancel)
        self._background = self.window.cget("bg")

        intro = ttk.Frame(self.window, padding=8)
        intro.pack(fill="x")
        buttons = ttk.Frame(intro)
        buttons.pack(anchor="w", pady=4)
        ttk.Button(buttons, text="Check all", command=self.check_all).grid(
            row=0, column=0, padx=4, pady=2
        )
        ttk.Button(buttons, text="Uncheck all", command=self.uncheck_all).grid(
            row=0, column=1, padx=4, pady=2
        )
        ttk.Button(buttons, text="Copy all", command=self.copy_all).grid(
            row=0, column=2, padx=4, pady=2
        )
        self.copy_var = tk.StringVar(value="")
        self.copy_note = ttk.Label(
            buttons, textvariable=self.copy_var, style="VariantConfirm.TLabel"
        )
        self.copy_note.grid(row=1, column=0, columnspan=3, sticky="w", padx=4, pady=(4, 0))

        list_frame = ttk.Frame(self.window, padding=(8, 0))
        list_frame.pack(fill=tk.BOTH, expand=True)
        self.body = tk.Text(
            list_frame,
            wrap="word",
            font=font_for("body", self.text_size),
            fg="#222",
            bg=self._background,
            borderwidth=0,
            highlightthickness=0,
            insertwidth=0,
            padx=4,
            pady=4,
            cursor="xterm",
            undo=False,
        )
        scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.body.yview)
        self.body.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.body.pack(side="left", fill=tk.BOTH, expand=True)
        self._scroller = WheelScroller(
            self.body, lambda pixels: self.body.yview_scroll(int(pixels), "pixels")
        )
        self.body.bind("<Key>", _block_edits)
        self.body.bind("<<Paste>>", lambda _event: "break")
        self.body.bind("<<Cut>>", lambda _event: "break")
        self.body.bind("<MouseWheel>", self._on_wheel)
        scroll.bind("<MouseWheel>", self._on_wheel)
        self.body.bind("<B1-Motion>", self._on_drag_motion, add="+")
        self.body.bind("<ButtonRelease-1>", self._on_drag_release, add="+")
        self.body.bind("<B1-Leave>", self._on_drag_leave, add="+")
        self.body._zoom = self.change_text_size

        self.apply_text_size(self.text_size)
        self._write(
            f"Words for {category}",
            "heading",
        )
        self._write(
            (
                f"These words start with “{stem}”. "
                "Checked words will be searched. Uncheck a word to leave it out. "
                "A word from your term list is marked “(from your term list)”. "
                "A word with no saved decision yet is marked “new”."
            ),
            "note",
        )
        self._write("", "gap")
        self._add_section("Words from the stem", suggestions)
        if related_suggestions:
            self._add_section("Related words", related_suggestions)
        self.body.mark_set("insert", "1.0")
        self.body.see("1.0")

        footer = ttk.Frame(self.window, padding=8)
        footer.pack(fill="x", pady=(8, 0))
        ttk.Button(footer, text="Save", command=self.save).pack(side="left", padx=(0, 8))
        ttk.Button(footer, text="Cancel", command=self.cancel).pack(side="left")
        self.window.bind("<Escape>", lambda _event: self.cancel())
        bind_text_zoom(self.window.bind, self.change_text_size)

    def _watch_stop(self):
        self._stop_job = None
        try:
            if not self.window.winfo_exists():
                return
        except tk.TclError:
            return
        if self.stop_check and self.stop_check():
            self.cancel()
            return
        self._stop_job = self.window.after(200, self._watch_stop)

    def _clear_stop_watch(self):
        if self._stop_job is not None:
            try:
                self.window.after_cancel(self._stop_job)
            except tk.TclError:
                pass
            self._stop_job = None

    def apply_text_size(self, size):
        self.text_size = clamp_text_size(size)
        if not self.window.winfo_exists():
            return
        style = ttk.Style(self.window)
        style.configure("TCheckbutton", font=font_for("body", self.text_size))
        style.configure("TButton", font=font_for("body", self.text_size))
        style.configure(
            "VariantConfirm.TLabel",
            font=font_for("note", self.text_size),
            foreground="#767676",
        )
        self.body.configure(font=font_for("body", self.text_size))
        self.body.tag_configure(
            "heading",
            font=font_for("heading", self.text_size),
            foreground="#222",
            spacing1=10,
            spacing3=4,
        )
        self.body.tag_configure(
            "note",
            font=font_for("note", self.text_size),
            foreground="#767676",
            spacing3=8,
        )
        self.body.tag_configure(
            "source",
            font=font_for("note", self.text_size),
            foreground="#767676",
        )
        self.body.tag_configure(
            "entry",
            font=font_for("label", self.text_size),
            foreground="#222",
            spacing1=14,
        )
        self.body.tag_configure(
            "word",
            font=font_for("body", self.text_size),
            foreground="#222",
        )
        left, hang = self._sentence_margins()
        self.body.tag_configure(
            "sentence",
            font=font_for("body", self.text_size),
            foreground="#333",
            lmargin1=left,
            lmargin2=hang,
            spacing3=3,
        )
        self.body.tag_configure("gap", font=font_for("body", self.text_size), spacing1=8)
        self.body.tag_raise("source")

    def _sentence_margins(self):
        """The bullet line starts indented; wrapped lines start after the bullet."""
        left = 36
        measure = tkfont.Font(font=font_for("body", self.text_size), root=self.body)
        return left, left + measure.measure("• ")

    def change_text_size(self, delta):
        if delta == 0:
            size = DEFAULT_TEXT_SIZE
        else:
            size = clamp_text_size(self.text_size + delta)
        if self.on_text_size is not None:
            self.on_text_size(size)
        else:
            self.apply_text_size(size)
            _remember_text_size(size)

    def _write(self, text, tag):
        if text:
            self.body.insert("end", text, tag)
        self.body.insert("end", "\n", tag)

    def _add_section(self, heading, suggestions):
        if self.rows:
            self._write("", "gap")
        self._write(heading, "heading")
        if not suggestions:
            self._write("No new words.", "word")
            return
        for suggestion in suggestions:
            stored = dict(suggestion)
            stored["section"] = heading
            variable = tk.BooleanVar(value=bool(suggestion.get("checked")))
            self.rows.append((stored, variable))
            box = SameCheck(
                self.body,
                variable,
                background=self.body.cget("bg"),
            )
            box.bind("<MouseWheel>", self._on_wheel)
            box._box.bind("<MouseWheel>", self._on_wheel)
            self.body.window_create("end", window=box, padx=2, pady=1)
            self.body.insert("end", f"  {suggestion['word']}", "entry")
            self.body.insert("end", f"   {match_phrase(suggestion['count'])}", "word")
            if suggestion.get("from_term_list"):
                self.body.insert("end", "   (from your term list)", "source")
            if suggestion.get("new"):
                self.body.insert("end", "   new", "source")
            self.body.insert("end", "\n", "entry")
            for item in suggestion.get("sentences") or []:
                text, source = sentence_parts(item)
                self.body.insert("end", f"• {text}", "sentence")
                if source:
                    self.body.insert("end", f"  ({source})", ("sentence", "source"))
                self.body.insert("end", "\n", "sentence")

    def _on_wheel(self, event):
        return self._scroller.on_wheel(event)

    def _on_drag_motion(self, event):
        """Keep extending a selection when the pointer sits at the top or bottom."""
        self._drag_xy = (event.x, event.y)
        height = self.body.winfo_height()
        margin = 28
        if event.y < margin:
            self._drag_dir = -1
            self._drag_speed = 8 + int(margin - event.y)
        elif event.y > height - margin:
            self._drag_dir = 1
            self._drag_speed = 8 + int(event.y - (height - margin))
        else:
            self._drag_dir = 0
            self._stop_drag_scroll()
            return
        if self._drag_job is None:
            self._drag_job = self.body.after(30, self._drag_scroll)

    def _on_drag_release(self, _event):
        self._drag_dir = 0
        self._stop_drag_scroll()

    def _on_drag_leave(self, _event):
        # Once the pointer leaves the list, the usual window autoscroll takes over.
        self._drag_dir = 0
        self._stop_drag_scroll()

    def _drag_scroll(self):
        self._drag_job = None
        if not self._drag_dir or not self.body.winfo_exists():
            return
        step = max(6, min(36, self._drag_speed))
        self.body.yview_scroll(self._drag_dir * step, "pixels")
        self._extend_drag_selection()
        self._drag_job = self.body.after(30, self._drag_scroll)

    def _extend_drag_selection(self):
        x, y = self._drag_xy
        height = max(1, self.body.winfo_height())
        y = max(0, min(height - 1, y))
        x = max(0, x)
        try:
            self.body.tk.call("::tk::TextSelectTo", self.body, x, y)
        except tk.TclError:
            pass

    def _stop_drag_scroll(self):
        if self._drag_job is not None:
            try:
                self.body.after_cancel(self._drag_job)
            except tk.TclError:
                pass
            self._drag_job = None

    def copy_all(self):
        lines = [f"Words for {self.category}", ""]
        section = None
        for suggestion, variable in self.rows:
            if suggestion.get("section") != section:
                section = suggestion.get("section")
                if section:
                    lines.append(section)
            ticked = "ticked" if variable.get() else "not ticked"
            line = f"{suggestion['word']}  {match_phrase(suggestion['count'])}"
            if suggestion.get("from_term_list"):
                line += "  (from your term list)"
            if suggestion.get("new"):
                line += "  new"
            line += f"  {ticked}"
            lines.append(line)
            for item in suggestion.get("sentences") or []:
                lines.append(sentence_line(item))
            lines.append("")
        text = "\n".join(lines).rstrip() + "\n"
        self.window.clipboard_clear()
        self.window.clipboard_append(text)
        self.window.update_idletasks()
        self.copy_var.set(copy_confirmation(len(self.rows)))

    def check_all(self):
        for _suggestion, variable in self.rows:
            variable.set(True)

    def uncheck_all(self):
        for _suggestion, variable in self.rows:
            variable.set(False)

    def save(self):
        self._clear_stop_watch()
        self._scroller.stop()
        self._stop_drag_scroll()
        self.result = []
        for suggestion, variable in self.rows:
            self.result.append(
                {
                    "word": suggestion["word"],
                    "count": suggestion["count"],
                    "included": bool(variable.get()),
                }
            )
        self.window.destroy()

    def cancel(self):
        self._clear_stop_watch()
        self._scroller.stop()
        self._stop_drag_scroll()
        self.result = None
        self.window.destroy()
