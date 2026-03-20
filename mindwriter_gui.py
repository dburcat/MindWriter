#!/usr/bin/env python3
"""
MindWriter GUI  —  Tkinter desktop application
Communicates with the MindWriter API (mindwriter_api.py).

Run:
    python3 mindwriter_gui.py
    python3 mindwriter_gui.py --api http://localhost:9000
"""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import urllib.request
import urllib.error
import urllib.parse
import json
import threading
import argparse
import sys
import os
from pathlib import Path

# ── Colour palette (matches the web UI) ───────────────────────────────────
C = {
    "bg":      "#0c0c0f",
    "surf":    "#121218",
    "surf2":   "#18181f",
    "border":  "#222230",
    "accent":  "#b8f050",
    "blue":    "#50c8f0",
    "muted":   "#50506a",
    "text":    "#d8d8e8",
    "dim":     "#8888a0",
    "danger":  "#f05858",
    "warn":    "#f0c850",
    "green":   "#50f0a0",
}

FONT_MONO  = ("JetBrains Mono", 10) if sys.platform != "win32" else ("Consolas", 10)
FONT_SANS  = ("DM Sans", 10)        if sys.platform != "win32" else ("Segoe UI", 10)
FONT_TITLE = ("DM Sans", 14, "bold") if sys.platform != "win32" else ("Segoe UI", 14, "bold")
FONT_SMALL = ("DM Sans", 9)          if sys.platform != "win32" else ("Segoe UI", 9)

# ── API client ─────────────────────────────────────────────────────────────

class APIClient:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip("/")
        self.api_key  = ""

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["X-API-Key"] = self.api_key
        return h

    def _request(self, method: str, path: str, data=None, form=None, timeout=15):
        url = self.base_url + path
        body = None
        headers = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        if data is not None:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
        elif form is not None:
            encoded = urllib.parse.urlencode(form).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            body = encoded
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())

    def get(self, path, timeout=15):
        return self._request("GET", path, timeout=timeout)

    def post(self, path, data=None, timeout=15):
        return self._request("POST", path, data=data, timeout=timeout)

    def put(self, path, data=None, timeout=15):
        return self._request("PUT", path, data=data, timeout=timeout)

    def delete(self, path, timeout=15):
        return self._request("DELETE", path, timeout=timeout)

    def health(self) -> bool:
        try:
            self._request("GET", "/health", timeout=3)
            return True
        except Exception:
            return False

    def fetch_key(self) -> str:
        try:
            d = self._request("GET", "/api/auth/key", timeout=3)
            return d.get("api_key", "")
        except Exception:
            return ""


api = APIClient()


# ── Utility helpers ─────────────────────────────────────────────────────────

def run_async(fn, *args, callback=None, err_callback=None):
    """Run fn(*args) in a thread; call callback(result) or err_callback(exc) on main thread."""
    def _worker():
        try:
            result = fn(*args)
            if callback:
                app.after(0, lambda: callback(result))
        except Exception as exc:
            if err_callback:
                app.after(0, lambda: err_callback(exc))
    threading.Thread(target=_worker, daemon=True).start()


def styled_frame(parent, **kw):
    kw.setdefault("bg", C["bg"])
    return tk.Frame(parent, **kw)


def styled_label(parent, text="", **kw):
    kw.setdefault("bg", C["bg"])
    kw.setdefault("fg", C["text"])
    kw.setdefault("font", FONT_SANS)
    return tk.Label(parent, text=text, **kw)


def styled_button(parent, text="", command=None, variant="accent", **kw):
    colours = {
        "accent":  (C["accent"],  "#0c0c0f"),
        "ghost":   (C["surf2"],   C["text"]),
        "danger":  (C["danger"],  C["bg"]),
        "muted":   (C["surf"],    C["muted"]),
    }
    bg, fg = colours.get(variant, colours["accent"])
    kw.setdefault("relief", "flat")
    kw.setdefault("cursor", "hand2")
    kw.setdefault("font", FONT_SANS)
    kw.setdefault("padx", 12)
    kw.setdefault("pady", 5)
    btn = tk.Button(parent, text=text, command=command, bg=bg, fg=fg,
                    activebackground=bg, activeforeground=fg,
                    highlightthickness=0, **kw)
    return btn


def styled_entry(parent, **kw):
    kw.setdefault("bg", C["surf2"])
    kw.setdefault("fg", C["text"])
    kw.setdefault("insertbackground", C["accent"])
    kw.setdefault("relief", "flat")
    kw.setdefault("font", FONT_SANS)
    kw.setdefault("highlightthickness", 1)
    kw.setdefault("highlightbackground", C["border"])
    kw.setdefault("highlightcolor", C["accent"])
    return tk.Entry(parent, **kw)


def styled_text(parent, **kw):
    kw.setdefault("bg", C["surf2"])
    kw.setdefault("fg", C["text"])
    kw.setdefault("insertbackground", C["accent"])
    kw.setdefault("relief", "flat")
    kw.setdefault("font", FONT_MONO)
    kw.setdefault("highlightthickness", 1)
    kw.setdefault("highlightbackground", C["border"])
    kw.setdefault("highlightcolor", C["accent"])
    kw.setdefault("wrap", "word")
    kw.setdefault("selectbackground", C["blue"])
    kw.setdefault("spacing3", 3)
    return tk.Text(parent, **kw)


def scrollable(parent, widget_class, **kw):
    """Wrap a widget in a frame with a scrollbar."""
    frame = styled_frame(parent)
    sb = tk.Scrollbar(frame, orient="vertical", bg=C["border"],
                      troughcolor=C["bg"], activebackground=C["muted"],
                      relief="flat", width=8)
    w = widget_class(frame, yscrollcommand=sb.set, **kw)
    sb.config(command=w.yview)
    w.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    return frame, w


# ── Main window ────────────────────────────────────────────────────────────

class MindWriterApp(tk.Tk):
    def __init__(self, api_url: str):
        super().__init__()
        api.base_url = api_url
        self.title("MindWriter")
        self.geometry("1100x700")
        self.minsize(820, 520)
        self.configure(bg=C["bg"])
        self._build_ui()
        self._auto_connect()

    # ── Top bar ──────────────────────────────────────────────────────────

    def _build_ui(self):
        self._build_topbar()
        body = styled_frame(self)
        body.pack(fill="both", expand=True)
        self._build_sidebar(body)
        self._content = styled_frame(body)
        self._content.pack(side="left", fill="both", expand=True)
        # Panels
        self._panels = {}
        for name, cls in [
            ("notes",    NotesPanel),
            ("search",   SearchPanel),
            ("stats",    StatsPanel),
            ("datasets", DatasetsPanel),
        ]:
            p = cls(self._content, self)
            p.place(relx=0, rely=0, relwidth=1, relheight=1)
            self._panels[name] = p
        self._show_panel("notes")

    def _build_topbar(self):
        bar = tk.Frame(self, bg=C["surf"], height=46)
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)

        styled_label(bar, text="✦ mindwriter", bg=C["surf"],
                     fg=C["accent"], font=(*FONT_MONO[:2], "bold")).pack(side="left", padx=18)

        # Nav buttons
        self._nav_btns = {}
        nav_frame = tk.Frame(bar, bg=C["surf"])
        nav_frame.pack(side="left", padx=4)
        for name in ("notes", "search", "stats", "datasets"):
            btn = tk.Button(nav_frame, text=name.capitalize(),
                            bg=C["surf"], fg=C["muted"], relief="flat",
                            font=FONT_SMALL, cursor="hand2", padx=10, pady=6,
                            activebackground=C["surf2"], activeforeground=C["text"],
                            highlightthickness=0,
                            command=lambda n=name: self._nav(n))
            btn.pack(side="left", padx=1)
            self._nav_btns[name] = btn

        # Right side: URL + status
        right = tk.Frame(bar, bg=C["surf"])
        right.pack(side="right", padx=14)

        self._status_dot = tk.Canvas(right, width=9, height=9,
                                      bg=C["surf"], highlightthickness=0)
        self._status_dot.pack(side="right", padx=(6, 0))
        self._dot_oval = self._status_dot.create_oval(1, 1, 8, 8, fill=C["muted"], outline="")

        styled_label(right, text="API", bg=C["surf"], fg=C["muted"],
                     font=FONT_SMALL).pack(side="left")
        self._url_var = tk.StringVar(value=api.base_url)
        url_entry = tk.Entry(right, textvariable=self._url_var,
                             bg=C["bg"], fg=C["text"], insertbackground=C["accent"],
                             relief="flat", font=FONT_MONO, width=22,
                             highlightthickness=1, highlightbackground=C["border"],
                             highlightcolor=C["accent"])
        url_entry.pack(side="left", padx=(4, 0))
        url_entry.bind("<Return>", lambda e: self._reconnect())

        styled_label(right, text="Key", bg=C["surf"], fg=C["muted"],
                     font=FONT_SMALL).pack(side="left", padx=(10, 0))
        self._key_var = tk.StringVar()
        key_entry = tk.Entry(right, textvariable=self._key_var, show="•",
                             bg=C["bg"], fg=C["text"], insertbackground=C["accent"],
                             relief="flat", font=FONT_MONO, width=14,
                             highlightthickness=1, highlightbackground=C["border"],
                             highlightcolor=C["accent"])
        key_entry.pack(side="left", padx=(4, 0))
        key_entry.bind("<Return>", lambda e: self._reconnect())

    def _build_sidebar(self, parent):
        sb = tk.Frame(parent, bg=C["surf"], width=160)
        sb.pack(side="left", fill="y")
        sb.pack_propagate(False)
        # vertical nav labels
        for name, icon in [("notes", "📝"), ("search", "🔍"),
                            ("stats", "📊"), ("datasets", "🗄")]:
            f = tk.Frame(sb, bg=C["surf"], cursor="hand2")
            f.pack(fill="x")
            f.bind("<Button-1>", lambda e, n=name: self._nav(n))
            tk.Label(f, text=icon + "  " + name.capitalize(),
                     bg=C["surf"], fg=C["muted"], font=FONT_SANS,
                     anchor="w", padx=16, pady=10).pack(fill="x")
            f.bind("<Enter>", lambda e, fr=f: fr.config(bg=C["surf2"]))
            f.bind("<Leave>", lambda e, fr=f: fr.config(bg=C["surf"]))
            self._nav_btns[f"side_{name}"] = f

    def _nav(self, name: str):
        # Update top nav highlight
        for n, btn in self._nav_btns.items():
            if not n.startswith("side_"):
                btn.config(fg=C["muted"], bg=C["surf"])
        self._nav_btns[name].config(fg=C["accent"],
                                     bg=C["surf2"] if name == name else C["surf"])
        self._show_panel(name)

    def _show_panel(self, name: str):
        for n, p in self._panels.items():
            p.lower()
        self._panels[name].lift()
        self._panels[name].on_show()

    # ── Connection ────────────────────────────────────────────────────────

    def _auto_connect(self):
        def _try():
            key = api.fetch_key()
            if key:
                self._key_var.set(key)
                api.api_key = key
            ok = api.health()
            self.after(0, lambda: self._set_status(ok))
            if ok:
                self.after(0, lambda: self._panels["notes"].load())
        threading.Thread(target=_try, daemon=True).start()

    def _reconnect(self):
        api.base_url = self._url_var.get().rstrip("/")
        api.api_key  = self._key_var.get().strip()
        self._set_status(None)
        def _try():
            if not api.api_key:
                key = api.fetch_key()
                if key:
                    api.api_key = key
                    self.after(0, lambda: self._key_var.set(key))
            ok = api.health()
            self.after(0, lambda: self._set_status(ok))
            if ok:
                self.after(0, lambda: self._panels["notes"].load())
        threading.Thread(target=_try, daemon=True).start()

    def _set_status(self, ok):
        if ok is None:
            colour = C["muted"]
        elif ok:
            colour = C["accent"]
        else:
            colour = C["danger"]
        self._status_dot.itemconfig(self._dot_oval, fill=colour)


# ── Notes Panel ────────────────────────────────────────────────────────────

class NotesPanel(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["bg"])
        self._app = app
        self._notes = []
        self._active_id = None
        self._mode = "view"   # view | edit | create
        self._build()

    def _build(self):
        # Left sidebar
        left = tk.Frame(self, bg=C["surf"], width=240)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        # Buttons
        btn_row = tk.Frame(left, bg=C["surf"])
        btn_row.pack(fill="x", padx=8, pady=8)
        styled_button(btn_row, "+ New", self._new_note, "accent").pack(side="left", fill="x", expand=True)
        tk.Frame(btn_row, width=6, bg=C["surf"]).pack(side="left")
        styled_button(btn_row, "⬆ Upload", self._upload_note, "ghost").pack(side="left", fill="x", expand=True)

        # Filter
        filter_frame = tk.Frame(left, bg=C["surf"])
        filter_frame.pack(fill="x", padx=8, pady=(0, 4))
        self._search_var = tk.StringVar()
        e = styled_entry(filter_frame, textvariable=self._search_var, width=20)
        e.pack(fill="x")
        e.insert(0, "Filter by tag or author…")
        e.config(fg=C["muted"])
        e.bind("<FocusIn>",  lambda ev: (e.delete(0, "end"), e.config(fg=C["text"])) if e.get() == "Filter by tag or author…" else None)
        e.bind("<FocusOut>", lambda ev: (e.insert(0, "Filter by tag or author…"), e.config(fg=C["muted"])) if not e.get() else None)
        e.bind("<Return>", lambda ev: self.load())

        # Sort
        sort_row = tk.Frame(left, bg=C["surf"])
        sort_row.pack(fill="x", padx=8, pady=(0, 6))
        styled_label(sort_row, "Sort:", bg=C["surf"], fg=C["muted"],
                     font=FONT_SMALL).pack(side="left")
        self._sort_var = tk.StringVar(value="id")
        for val, label in [("id", "ID"), ("title", "Title"), ("modified", "Modified")]:
            tk.Radiobutton(sort_row, text=label, variable=self._sort_var, value=val,
                           bg=C["surf"], fg=C["muted"], selectcolor=C["surf"],
                           activebackground=C["surf"], font=FONT_SMALL,
                           command=self.load).pack(side="left", padx=3)

        # Note list
        list_frame, self._listbox = scrollable(
            left, tk.Listbox,
            bg=C["surf"], fg=C["text"], selectbackground=C["surf2"],
            selectforeground=C["accent"], relief="flat", font=FONT_SMALL,
            borderwidth=0, highlightthickness=0, activestyle="none"
        )
        list_frame.pack(fill="both", expand=True, padx=0, pady=0)
        self._listbox.bind("<<ListboxSelect>>", self._on_select)

        # Right: reader + editor stacked
        self._right = tk.Frame(self, bg=C["bg"])
        self._right.pack(side="left", fill="both", expand=True)
        self._build_reader()
        self._build_editor()
        self._show_reader()

    def _build_reader(self):
        self._reader = tk.Frame(self._right, bg=C["bg"])
        # Header row
        hdr = tk.Frame(self._reader, bg=C["bg"])
        hdr.pack(fill="x", padx=28, pady=(24, 0))
        self._reader_title = styled_label(hdr, fg=C["text"], font=FONT_TITLE, anchor="w")
        self._reader_title.pack(side="left", fill="x", expand=True)
        btn_row = tk.Frame(hdr, bg=C["bg"])
        btn_row.pack(side="right")
        styled_button(btn_row, "✎ Edit",   self._edit_note,   "ghost").pack(side="left", padx=3)
        styled_button(btn_row, "✕ Delete", self._delete_note, "danger").pack(side="left")
        # Meta strip
        self._reader_meta = styled_label(self._reader, fg=C["dim"],
                                          font=FONT_SMALL, anchor="w", justify="left")
        self._reader_meta.pack(fill="x", padx=28, pady=(6, 0))
        tk.Frame(self._reader, bg=C["border"], height=1).pack(fill="x", padx=28, pady=10)
        # Body
        body_frame, self._reader_body = scrollable(
            self._reader, tk.Text,
            bg=C["bg"], fg=C["dim"], relief="flat", font=FONT_MONO,
            wrap="word", state="disabled", borderwidth=0,
            highlightthickness=0, padx=28, pady=0, spacing3=4
        )
        body_frame.pack(fill="both", expand=True, padx=0, pady=(0, 20))

        # Empty state
        self._empty = tk.Frame(self._right, bg=C["bg"])
        styled_label(self._empty, "◎", fg=C["muted"],
                     font=("DM Sans", 32)).pack(pady=(120, 6))
        styled_label(self._empty, "Select a note or create a new one",
                     fg=C["muted"], font=FONT_SMALL).pack()

    def _build_editor(self):
        self._editor = tk.Frame(self._right, bg=C["bg"])
        self._form_title_lbl = styled_label(self._editor, fg=C["accent"],
                                             font=(*FONT_SANS[:2], "bold"), anchor="w")
        self._form_title_lbl.pack(fill="x", padx=28, pady=(24, 8))

        def field(lbl, widget_fn, **kw):
            tk.Label(self._editor, text=lbl, bg=C["bg"], fg=C["blue"],
                     font=(*FONT_MONO[:2],), anchor="w").pack(fill="x", padx=28)
            w = widget_fn(self._editor, **kw)
            w.pack(fill="x" if widget_fn != styled_text else "both",
                   expand=widget_fn == styled_text, padx=28, pady=(2, 8))
            return w

        self._f_title    = field("TITLE *",    styled_entry)
        self._f_author   = field("AUTHOR",     styled_entry)
        row2 = tk.Frame(self._editor, bg=C["bg"])
        row2.pack(fill="x", padx=28)
        for lbl in ("PRIORITY", "TAGS"):
            sub = tk.Frame(row2, bg=C["bg"])
            sub.pack(side="left", fill="x", expand=True, padx=(0, 8) if lbl == "PRIORITY" else 0)
            tk.Label(sub, text=lbl, bg=C["bg"], fg=C["blue"], font=FONT_MONO, anchor="w").pack(fill="x")
            e = styled_entry(sub)
            e.pack(fill="x", pady=(2, 8))
            if lbl == "PRIORITY": self._f_priority = e
            else:                 self._f_tags = e

        tk.Label(self._editor, text="BODY", bg=C["bg"], fg=C["blue"],
                 font=FONT_MONO, anchor="w").pack(fill="x", padx=28)
        body_frame, self._f_body = scrollable(
            self._editor, tk.Text,
            bg=C["surf2"], fg=C["text"], insertbackground=C["accent"],
            relief="flat", font=FONT_MONO, wrap="word",
            highlightthickness=1, highlightbackground=C["border"],
            highlightcolor=C["accent"], padx=8, pady=8
        )
        body_frame.pack(fill="both", expand=True, padx=28, pady=(2, 0))

        # Actions
        act = tk.Frame(self._editor, bg=C["bg"])
        act.pack(fill="x", padx=28, pady=10)
        self._save_btn = styled_button(act, "Save Note", self._save_note, "accent")
        self._save_btn.pack(side="left", padx=(0, 8))
        styled_button(act, "Cancel", self._cancel_edit, "ghost").pack(side="left")
        self._form_msg = styled_label(act, fg=C["accent"], font=FONT_SMALL)
        self._form_msg.pack(side="left", padx=12)

    def _show_reader(self):
        self._empty.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._reader.place_forget()
        self._editor.place_forget()

    def _show_note_reader(self):
        self._empty.place_forget()
        self._editor.place_forget()
        self._reader.place(relx=0, rely=0, relwidth=1, relheight=1)

    def _show_editor(self):
        self._empty.place_forget()
        self._reader.place_forget()
        self._editor.place(relx=0, rely=0, relwidth=1, relheight=1)

    def on_show(self):
        if not self._notes:
            self.load()

    def load(self):
        fv = self._search_var.get()
        qs = f"?sort={self._sort_var.get()}"
        if fv and fv != "Filter by tag or author…":
            qs += f"&tag={urllib.parse.quote(fv)}&author={urllib.parse.quote(fv)}"
        def _do():
            return api.get(f"/api/notes{qs}")
        def _done(d):
            self._notes = d.get("notes", [])
            self._render_list()
        def _err(e):
            self._listbox.delete(0, "end")
            self._listbox.insert("end", f"  Error: {e}")
        run_async(_do, callback=_done, err_callback=_err)

    def _render_list(self):
        self._listbox.delete(0, "end")
        for n in self._notes:
            tag_str = ", ".join(n.get("tags", [])[:2])
            line = f"  #{n['id']}  {n['title'] or n['filename']}"
            self._listbox.insert("end", line)
            if n.get("id") == self._active_id:
                self._listbox.selection_set("end")

    def _on_select(self, event):
        sel = self._listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx >= len(self._notes):
            return
        note = self._notes[idx]
        self._active_id = note["id"]
        run_async(lambda: api.get(f"/api/notes/{note['id']}"),
                  callback=self._render_note,
                  err_callback=lambda e: None)

    def _render_note(self, n):
        self._active_note = n
        self._reader_title.config(text=(n.get("title") or n["filename"]).title())
        meta_parts = []
        if n.get("author"):   meta_parts.append(f"author: {n['author']}")
        if n.get("modified"): meta_parts.append(f"modified: {n['modified'][:10]}")
        if n.get("priority"): meta_parts.append(f"priority: {n['priority']}")
        if n.get("tags"):     meta_parts.append(f"tags: {', '.join(n['tags'])}")
        self._reader_meta.config(text="   ".join(meta_parts))
        body = n.get("body", "") or "(empty)"
        self._reader_body.config(state="normal")
        self._reader_body.delete("1.0", "end")
        self._reader_body.insert("1.0", body)
        self._reader_body.config(state="disabled")
        self._show_note_reader()

    def _new_note(self):
        self._mode = "create"
        self._form_title_lbl.config(text="+ New Note")
        self._save_btn.config(text="Save Note")
        self._clear_form()
        self._show_editor()
        self._f_title.focus()

    def _edit_note(self):
        if not hasattr(self, "_active_note"):
            return
        self._mode = "edit"
        n = self._active_note
        self._form_title_lbl.config(text="✎ Edit Note")
        self._save_btn.config(text="Update Note")
        self._clear_form()
        self._f_title.insert(0, n.get("title", ""))
        self._f_author.insert(0, n.get("author", ""))
        self._f_priority.insert(0, n.get("priority", ""))
        self._f_tags.insert(0, ", ".join(n.get("tags", [])))
        self._f_body.insert("1.0", n.get("body", ""))
        self._form_msg.config(text="")
        self._show_editor()
        self._f_title.focus()

    def _clear_form(self):
        for w in (self._f_title, self._f_author, self._f_priority, self._f_tags):
            w.delete(0, "end")
        self._f_body.delete("1.0", "end")
        self._form_msg.config(text="")

    def _save_note(self):
        title = self._f_title.get().strip()
        if not title:
            self._form_msg.config(text="Title is required.", fg=C["danger"])
            return
        body     = self._f_body.get("1.0", "end-1c")
        author   = self._f_author.get().strip()
        priority = self._f_priority.get().strip()
        tags     = self._f_tags.get().strip()
        data     = {"title": title, "body": body, "author": author,
                    "priority": priority, "tags": tags}
        self._save_btn.config(state="disabled", text="Saving…")
        if self._mode == "create":
            run_async(lambda: api.post("/api/notes", data),
                      callback=self._after_save,
                      err_callback=self._save_err)
        else:
            nid = self._active_note["id"]
            run_async(lambda: api.put(f"/api/notes/{nid}", data),
                      callback=self._after_save,
                      err_callback=self._save_err)

    def _after_save(self, result):
        self._save_btn.config(state="normal",
                               text="Save Note" if self._mode == "create" else "Update Note")
        self._form_msg.config(text="Saved!", fg=C["accent"])
        self.load()
        nid = result.get("id", self._active_id)
        if nid:
            self._active_id = nid
            self.after(500, lambda: run_async(
                lambda: api.get(f"/api/notes/{nid}"),
                callback=self._render_note
            ))
        self.after(600, self._show_note_reader)

    def _save_err(self, exc):
        self._save_btn.config(state="normal")
        self._form_msg.config(text=str(exc)[:60], fg=C["danger"])

    def _cancel_edit(self):
        if hasattr(self, "_active_note"):
            self._show_note_reader()
        else:
            self._show_reader()

    def _delete_note(self):
        if not hasattr(self, "_active_note"):
            return
        n = self._active_note
        if not messagebox.askyesno("Delete Note",
                                    f"Delete \"{n.get('title', n['filename'])}\"?\nThis cannot be undone."):
            return
        def _do():
            return api.delete(f"/api/notes/{n['id']}")
        def _done(_):
            self._active_id = None
            if hasattr(self, "_active_note"):
                del self._active_note
            self._show_reader()
            self.load()
        run_async(_do, callback=_done,
                  err_callback=lambda e: messagebox.showerror("Error", str(e)))

    def _upload_note(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="Upload Note",
            filetypes=[("Note files", "*.md *.txt *.note"), ("All files", "*.*")]
        )
        if not path:
            return
        overwrite = messagebox.askyesno("Overwrite?",
            "Replace existing note if filename already exists?")
        def _do():
            import urllib.request, urllib.parse
            url  = api.base_url + "/api/notes/upload"
            with open(path, "rb") as fh:
                file_data = fh.read()
            boundary = "MindWriterBoundary12345"
            fname    = os.path.basename(path)
            body  = (f"--{boundary}\r\n"
                     f"Content-Disposition: form-data; name=\"file\"; filename=\"{fname}\"\r\n"
                     f"Content-Type: text/plain\r\n\r\n").encode() + \
                    file_data + \
                    f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\n{'true' if overwrite else 'false'}\r\n--{boundary}--\r\n".encode()
            req = urllib.request.Request(url, data=body, method="POST")
            req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
            if api.api_key:
                req.add_header("X-API-Key", api.api_key)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        def _done(d):
            messagebox.showinfo("Uploaded", f"Note uploaded: {d.get('filename', '')}")
            self.load()
        run_async(_do, callback=_done,
                  err_callback=lambda e: messagebox.showerror("Upload failed", str(e)))


# ── Search Panel ───────────────────────────────────────────────────────────

class SearchPanel(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["bg"])
        self._app = app
        self._build()

    def _build(self):
        top = tk.Frame(self, bg=C["bg"])
        top.pack(fill="x", padx=28, pady=20)
        styled_label(top, "Search Notes", font=FONT_TITLE, fg=C["text"],
                     bg=C["bg"]).pack(side="left")

        bar = tk.Frame(self, bg=C["bg"])
        bar.pack(fill="x", padx=28, pady=(0, 12))
        self._q_var = tk.StringVar()
        e = styled_entry(bar, textvariable=self._q_var, width=40)
        e.pack(side="left", fill="x", expand=True, padx=(0, 8), ipady=4)
        e.bind("<Return>", lambda ev: self._search())
        styled_button(bar, "Search", self._search, "accent").pack(side="left")

        # Results
        frame, self._results = scrollable(
            self, tk.Text,
            bg=C["bg"], fg=C["text"], relief="flat", font=FONT_SANS,
            wrap="word", state="disabled", borderwidth=0,
            highlightthickness=0, padx=28, pady=8, cursor="arrow"
        )
        frame.pack(fill="both", expand=True)
        self._results.tag_config("title",   foreground=C["text"],   font=(*FONT_SANS[:2], "bold"))
        self._results.tag_config("match",   foreground=C["accent"], font=FONT_MONO)
        self._results.tag_config("snippet", foreground=C["dim"],    font=FONT_MONO)
        self._results.tag_config("meta",    foreground=C["muted"],  font=FONT_SMALL)
        self._results.tag_config("sep",     foreground=C["border"])

    def on_show(self): pass

    def _search(self):
        q = self._q_var.get().strip()
        if not q:
            return
        keywords = [k.strip() for k in q.split() if k.strip()]
        qs = "&".join(f"q={urllib.parse.quote(k)}" for k in keywords)
        def _do():
            return api.get(f"/api/notes/search?{qs}")
        def _done(d):
            self._render(d)
        run_async(_do, callback=_done,
                  err_callback=lambda e: self._show_error(str(e)))

    def _render(self, d):
        self._results.config(state="normal")
        self._results.delete("1.0", "end")
        notes = d.get("notes", [])
        if not notes:
            self._results.insert("end", "No results found.", "meta")
        for n in notes:
            self._results.insert("end", f"#{n['id']}  ", "meta")
            self._results.insert("end", (n.get("title") or n["filename"]).title() + "\n", "title")
            kws = ", ".join(n.get("matched_keywords", []))
            self._results.insert("end", f"  matched: {kws}\n", "match")
            for kw, info in n.get("match_report", {}).items():
                for snip in info.get("snippets", [])[:1]:
                    self._results.insert("end", f"  …{snip}…\n", "snippet")
            self._results.insert("end", "─" * 60 + "\n", "sep")
        self._results.config(state="disabled")

    def _show_error(self, msg):
        self._results.config(state="normal")
        self._results.delete("1.0", "end")
        self._results.insert("end", f"Error: {msg}", "meta")
        self._results.config(state="disabled")


# ── Stats Panel ────────────────────────────────────────────────────────────

class StatsPanel(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["bg"])
        self._app   = app
        self._loaded = False
        self._build()

    def _build(self):
        top = tk.Frame(self, bg=C["bg"])
        top.pack(fill="x", padx=28, pady=20)
        styled_label(top, "Stats", font=FONT_TITLE, fg=C["text"],
                     bg=C["bg"]).pack(side="left")
        styled_button(top, "↻ Refresh", self._load, "ghost").pack(side="left", padx=12)
        self._scroll_frame = tk.Frame(self, bg=C["bg"])
        self._scroll_frame.pack(fill="both", expand=True)
        self._canvas = tk.Canvas(self._scroll_frame, bg=C["bg"],
                                  highlightthickness=0)
        sb = tk.Scrollbar(self._scroll_frame, orient="vertical",
                           command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)
        self._inner = tk.Frame(self._canvas, bg=C["bg"])
        self._canvas_win = self._canvas.create_window((0, 0), window=self._inner,
                                                        anchor="nw")
        self._inner.bind("<Configure>", self._on_frame_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._msg = styled_label(self._inner, "Loading…", fg=C["muted"],
                                  font=FONT_SMALL)
        self._msg.pack(pady=40)

    def _on_frame_configure(self, event):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self._canvas.itemconfig(self._canvas_win, width=event.width)

    def on_show(self):
        if not self._loaded:
            self._load()

    def _load(self):
        self._loaded = False
        self._msg.config(text="Loading…")
        run_async(lambda: api.get("/api/stats"),
                  callback=self._render,
                  err_callback=lambda e: self._msg.config(text=f"Error: {e}"))

    def _render(self, s):
        for w in self._inner.winfo_children():
            w.destroy()

        # Stat cards
        cards_data = [
            (str(s.get("total_notes", 0)), "total notes"),
            (f"{s.get('total_words', 0):,}", "total words"),
            (f"{s.get('avg_words', 0):,}", "avg words/note"),
            (str(s.get("no_title", 0)),  "missing title"),
            (str(s.get("no_author", 0)), "missing author"),
            (str(s.get("no_tags", 0)),   "missing tags"),
        ]
        cards_row = tk.Frame(self._inner, bg=C["bg"])
        cards_row.pack(fill="x", padx=24, pady=(8, 20))
        for val, lbl in cards_data:
            card = tk.Frame(cards_row, bg=C["surf"],
                             highlightthickness=1, highlightbackground=C["border"])
            card.pack(side="left", fill="x", expand=True, padx=4)
            styled_label(card, val, bg=C["surf"], fg=C["accent"],
                         font=("DM Sans", 20, "bold")).pack(pady=(12, 2))
            styled_label(card, lbl, bg=C["surf"], fg=C["muted"],
                         font=FONT_SMALL).pack(pady=(0, 12))

        # Bar charts
        for section_title, data_key in [
            ("By Author", "by_author"),
            ("By Priority", "by_priority"),
            ("By Tag", "by_tag"),
        ]:
            data = s.get(data_key, {})
            if not data:
                continue
            sec = tk.Frame(self._inner, bg=C["bg"])
            sec.pack(fill="x", padx=28, pady=(0, 20))
            styled_label(sec, section_title, fg=C["blue"],
                         font=(*FONT_MONO[:2],), bg=C["bg"],
                         anchor="w").pack(fill="x", pady=(0, 6))
            tk.Frame(sec, bg=C["border"], height=1).pack(fill="x", pady=(0, 8))
            top10 = sorted(data.items(), key=lambda x: x[1], reverse=True)[:10]
            max_val = max(v for _, v in top10) if top10 else 1
            for name, count in top10:
                row = tk.Frame(sec, bg=C["bg"])
                row.pack(fill="x", pady=2)
                styled_label(row, name[:20], fg=C["text"], font=FONT_SMALL,
                             bg=C["bg"], width=18, anchor="w").pack(side="left")
                styled_label(row, str(count), fg=C["muted"], font=FONT_MONO,
                             bg=C["bg"], width=5, anchor="e").pack(side="left")
                track = tk.Frame(row, bg=C["border"], height=5)
                track.pack(side="left", fill="x", expand=True, padx=(8, 0), pady=4)
                fill_w = max(4, int(count / max_val * 200))
                tk.Frame(track, bg=C["accent"], height=5,
                          width=fill_w).place(x=0, y=0, height=5)
        self._loaded = True


# ── Datasets Panel ─────────────────────────────────────────────────────────

class DatasetsPanel(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["bg"])
        self._app      = app
        self._datasets = []
        self._active_ds = None
        self._page     = 1
        self._per_page = 100
        self._q        = ""
        self._build()

    def _build(self):
        # Left sidebar
        left = tk.Frame(self, bg=C["surf"], width=240)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        btn_row = tk.Frame(left, bg=C["surf"])
        btn_row.pack(fill="x", padx=8, pady=8)
        styled_button(btn_row, "↻ Refresh", self._load, "ghost").pack(fill="x")

        list_frame, self._ds_listbox = scrollable(
            left, tk.Listbox,
            bg=C["surf"], fg=C["text"], selectbackground=C["surf2"],
            selectforeground=C["accent"], relief="flat", font=FONT_SMALL,
            borderwidth=0, highlightthickness=0, activestyle="none"
        )
        list_frame.pack(fill="both", expand=True)
        self._ds_listbox.bind("<<ListboxSelect>>", self._on_ds_select)

        # Right content
        self._right = tk.Frame(self, bg=C["bg"])
        self._right.pack(side="left", fill="both", expand=True)

        self._empty = tk.Frame(self._right, bg=C["bg"])
        self._empty.place(relx=0, rely=0, relwidth=1, relheight=1)
        styled_label(self._empty, "◎", fg=C["muted"],
                     font=("DM Sans", 32)).pack(pady=(120, 6))
        styled_label(self._empty, "Select a dataset from the list",
                     fg=C["muted"], font=FONT_SMALL).pack()

        self._detail = tk.Frame(self._right, bg=C["bg"])
        self._build_detail()

    def _build_detail(self):
        # Header
        hdr = tk.Frame(self._detail, bg=C["bg"])
        hdr.pack(fill="x", padx=24, pady=(20, 0))
        self._ds_title_lbl = styled_label(hdr, font=FONT_TITLE, fg=C["text"],
                                           bg=C["bg"], anchor="w")
        self._ds_title_lbl.pack(side="left", fill="x", expand=True)
        self._ds_fmt_lbl = styled_label(hdr, fg=C["blue"], bg=C["bg"],
                                         font=FONT_MONO)
        self._ds_fmt_lbl.pack(side="right")

        self._ds_meta_lbl = styled_label(self._detail, fg=C["muted"],
                                          font=FONT_SMALL, bg=C["bg"],
                                          anchor="w", justify="left")
        self._ds_meta_lbl.pack(fill="x", padx=24, pady=(4, 0))

        tk.Frame(self._detail, bg=C["border"], height=1).pack(
            fill="x", padx=24, pady=10)

        # Search bar
        sbar = tk.Frame(self._detail, bg=C["bg"])
        sbar.pack(fill="x", padx=24, pady=(0, 8))
        self._ds_q_var = tk.StringVar()
        e = styled_entry(sbar, textvariable=self._ds_q_var, width=30)
        e.pack(side="left", padx=(0, 6), ipady=3)
        e.bind("<Return>", lambda ev: self._search_ds())
        styled_button(sbar, "Search", self._search_ds, "ghost").pack(side="left", padx=(0, 6))
        styled_button(sbar, "Clear", self._clear_search, "ghost").pack(side="left")

        # Table area
        self._tbl_frame = tk.Frame(self._detail, bg=C["bg"])
        self._tbl_frame.pack(fill="both", expand=True, padx=24)

        # Pagination
        pg_row = tk.Frame(self._detail, bg=C["bg"])
        pg_row.pack(fill="x", padx=24, pady=8)
        self._pg_first = styled_button(pg_row, "«", lambda: self._go_page(1), "ghost")
        self._pg_first.pack(side="left", padx=2)
        self._pg_prev  = styled_button(pg_row, "‹", lambda: self._go_page(self._page - 1), "ghost")
        self._pg_prev.pack(side="left", padx=2)
        self._pg_info  = styled_label(pg_row, "", fg=C["muted"], font=FONT_MONO, bg=C["bg"])
        self._pg_info.pack(side="left", padx=8)
        self._pg_next  = styled_button(pg_row, "›", lambda: self._go_page(self._page + 1), "ghost")
        self._pg_next.pack(side="left", padx=2)
        self._pg_last  = styled_button(pg_row, "»", lambda: self._go_page(self._total_pages), "ghost")
        self._pg_last.pack(side="left", padx=2)
        self._total_pages = 1

    def on_show(self):
        if not self._datasets:
            self._load()

    def _load(self):
        run_async(lambda: api.get("/api/datasets"),
                  callback=self._render_list,
                  err_callback=lambda e: None)

    def _render_list(self, d):
        self._datasets = d.get("datasets", [])
        self._ds_listbox.delete(0, "end")
        for ds in self._datasets:
            rows = f"  {ds['rows']} rows" if ds.get("rows") else ""
            self._ds_listbox.insert("end", f"  {ds['title'] or ds['filename']}{rows}")

    def _on_ds_select(self, event):
        sel = self._ds_listbox.curselection()
        if not sel or sel[0] >= len(self._datasets):
            return
        self._active_ds = self._datasets[sel[0]]
        self._page = 1
        self._q    = ""
        self._ds_q_var.set("")
        self._show_detail()
        self._load_data()

    def _show_detail(self):
        ds = self._active_ds
        self._ds_title_lbl.config(text=(ds.get("title") or ds["filename"]).title())
        self._ds_fmt_lbl.config(text=ds.get("format", ""))
        meta_parts = []
        if ds.get("rows"):    meta_parts.append(f"{ds['rows']} rows × {ds.get('columns', '?')} columns")
        if ds.get("author"):  meta_parts.append(f"author: {ds['author']}")
        if ds.get("imported"):meta_parts.append(f"imported: {ds['imported']}")
        self._ds_meta_lbl.config(text="   ".join(meta_parts))
        self._empty.place_forget()
        self._detail.place(relx=0, rely=0, relwidth=1, relheight=1)

    def _load_data(self):
        ds   = self._active_ds
        page = self._page
        q    = self._q
        qs   = f"?page={page}&per_page={self._per_page}"
        if q:
            qs += f"&q={urllib.parse.quote(q)}"
        run_async(lambda: api.get(f"/api/datasets/{ds['id']}/data{qs}"),
                  callback=self._render_table,
                  err_callback=lambda e: self._show_table_msg(str(e)))

    def _render_table(self, d):
        # Clear old table
        for w in self._tbl_frame.winfo_children():
            w.destroy()

        columns = d.get("columns", [])
        rows    = d.get("rows", [])
        self._page        = d.get("page", 1)
        self._total_pages = d.get("pages", 1)
        total   = d.get("total", 0)
        start   = (self._page - 1) * self._per_page + 1
        end     = min(self._page * self._per_page, total)

        if not columns:
            self._show_table_msg("No data found.")
            return

        # Build a ttk Treeview — much faster than a Text widget for tabular data
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Dark.Treeview",
                         background=C["surf"], foreground=C["text"],
                         fieldbackground=C["surf"], rowheight=22,
                         borderwidth=0, font=FONT_MONO)
        style.configure("Dark.Treeview.Heading",
                         background=C["surf2"], foreground=C["blue"],
                         relief="flat", font=(*FONT_MONO[:2], "bold"))
        style.map("Dark.Treeview", background=[("selected", C["surf2"])],
                  foreground=[("selected", C["accent"])])

        vsb = tk.Scrollbar(self._tbl_frame, orient="vertical", bg=C["border"],
                            troughcolor=C["bg"], activebackground=C["muted"],
                            relief="flat", width=8)
        hsb = tk.Scrollbar(self._tbl_frame, orient="horizontal", bg=C["border"],
                            troughcolor=C["bg"], relief="flat", width=8)

        tree = ttk.Treeview(self._tbl_frame, columns=columns, show="headings",
                             style="Dark.Treeview",
                             yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.config(command=tree.yview)
        hsb.config(command=tree.xview)

        col_w = max(80, min(200, 800 // max(len(columns), 1)))
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=col_w, minwidth=50, stretch=True)

        for row in rows:
            tree.insert("", "end", values=[str(v) if v is not None else "" for v in row])

        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        tree.pack(fill="both", expand=True)

        # Pagination controls
        self._pg_info.config(
            text=f"rows {start}–{end} of {total:,}  •  page {self._page}/{self._total_pages}"
        )
        self._pg_first.config(state="normal" if self._page > 1 else "disabled")
        self._pg_prev.config( state="normal" if self._page > 1 else "disabled")
        self._pg_next.config( state="normal" if self._page < self._total_pages else "disabled")
        self._pg_last.config( state="normal" if self._page < self._total_pages else "disabled")

    def _show_table_msg(self, msg):
        for w in self._tbl_frame.winfo_children():
            w.destroy()
        styled_label(self._tbl_frame, msg, fg=C["muted"],
                     font=FONT_SMALL, bg=C["bg"]).pack(pady=20)

    def _go_page(self, page):
        if page < 1 or page > self._total_pages:
            return
        self._page = page
        self._load_data()

    def _search_ds(self):
        self._q    = self._ds_q_var.get().strip()
        self._page = 1
        self._load_data()

    def _clear_search(self):
        self._q = ""
        self._ds_q_var.set("")
        self._page = 1
        self._load_data()


# ── Entry point ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="MindWriter GUI")
    parser.add_argument("--api", default="http://localhost:8000",
                        help="API base URL")
    args = parser.parse_args()

    global app
    app = MindWriterApp(args.api)
    app.mainloop()


if __name__ == "__main__":
    main()
