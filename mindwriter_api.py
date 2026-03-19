#!/usr/bin/env python3
"""
MindWriter API  —  v0.2
Flask REST API for the MindWriter notes manager.

All business logic is imported directly from mindwriter.py.
The API adds HTTP transport, JSON serialisation, and a served UI on top —
no logic is duplicated.

Install:
    pip install flask flask-cors

Run:
    python3 mindwriter_api.py
    NOTES_DIR=/custom/path python3 mindwriter_api.py
    PORT=8080 python3 mindwriter_api.py

Endpoints
─────────────────────────────────────────────────────────────────────────────
GET    /                               Serve the Vanilla JS UI
GET    /health                         Health check + resolved paths

Notes
GET    /api/notes                      List all notes (metadata)
                                         ?tag=   ?author=   ?sort=id|title|modified|created
GET    /api/notes/<id|filename>        Get one note (metadata + body)
POST   /api/notes                      Create a new note
                                         JSON body: {title, body, author, tags, priority}
PUT    /api/notes/<id|filename>        Edit / update a note's body and/or metadata
                                         JSON body: {title?, body?, author?, tags?, priority?}
DELETE /api/notes/<id|filename>        Delete a note
GET    /api/notes/search?q=kw&q=kw2   Search notes (OR — any keyword matches)
                                         Returns match locations and body snippets

Stats
GET    /api/stats                      Aggregate statistics across all notes

Datasets
GET    /api/datasets                   List all imported datasets
GET    /api/datasets/<n>               Get one dataset's sidecar metadata
POST   /api/datasets/import            Import a CSV or JSON file from a server-side path
                                         JSON body: {path, title?, description?, author?,
                                                     tags?, source_url?, license?, priority?}
"""

import os
import sys
import types
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

from flask import Flask, abort, jsonify, request
from flask_cors import CORS

# ---------------------------------------------------------------------------
# Stub out modules that mindwriter.py imports but the API never uses
# ---------------------------------------------------------------------------

_dummy_shell = types.ModuleType("mindwriter_shell")
_dummy_shell.main = lambda: None
sys.modules.setdefault("mindwriter_shell", _dummy_shell)

if "slugify" not in sys.modules:
    _slug = types.ModuleType("slugify")
    _slug.slugify = lambda s, **kw: s.lower().replace(" ", "-")
    sys.modules["slugify"] = _slug

_here = Path(__file__).parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

# ---------------------------------------------------------------------------
# Import everything from mindwriter.py
# ---------------------------------------------------------------------------

from mindwriter import (
    setup,
    build_index,
    collect_note_files,
    resolve_to_path,
    parse_yaml_header,
    update_modified_timestamp,
    _collect_datasets,
    read_dataset_sidecar,
    _write_sidecar,
    _ensure_datasets_dir,
    datasets_dir,
)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = Flask(__name__)
CORS(app)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _notes_dir() -> Path:
    """Return the resolved notes directory (~/.notes/notes or override)."""
    root = setup()
    sub  = root / "notes"
    return sub if sub.exists() else root


def _notes_root() -> Path:
    custom = os.environ.get("NOTES_DIR")
    return Path(custom) if custom else Path.home() / ".notes"


def _get_body(file_path: Path) -> str:
    """Return the note body — text below the closing YAML --- delimiter."""
    try:
        lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)
    except Exception:
        return ""
    if not lines or lines[0].strip() != "---":
        return "".join(lines)
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "".join(lines[i + 1:])
    return ""


def _parse_tags(raw: str) -> list:
    return [t.strip().lower() for t in raw.strip("[]").split(",") if t.strip()]


def _note_to_dict(note_id: int, note_file: Path, include_body: bool = False) -> dict:
    meta = parse_yaml_header(note_file)
    d = {
        "id":       note_id,
        "filename": note_file.name,
        "title":    (meta.get("title") or note_file.stem).strip(),
        "author":   meta.get("author", ""),
        "tags":     _parse_tags(meta.get("tags", "")),
        "priority": meta.get("priority", ""),
        "created":  meta.get("created", ""),
        "modified": meta.get("modified", ""),
    }
    if include_body:
        d["body"] = _get_body(note_file)
    return d


def _resolve(identifier: str) -> tuple:
    """
    Return (note_id, note_file) for a numeric id or filename.
    Aborts with 404 if not found.
    """
    nd         = _notes_dir()
    note_files = collect_note_files(nd)
    id_to_file, _ = build_index(note_files)

    try:
        nid = int(identifier)
        nf  = id_to_file.get(nid)
        if nf:
            return nid, nf
    except ValueError:
        for nid, nf in id_to_file.items():
            if nf.name == identifier:
                return nid, nf

    abort(404, description=f"Note '{identifier}' not found.")


def _write_yaml_header(file_path: Path, meta: dict, body: str):
    """Overwrite a note file with new YAML front matter and body."""
    now = datetime.now().isoformat()
    lines = ["---\n"]
    for key in ("title", "created", "modified", "tags", "author", "priority"):
        value = meta.get(key, "")
        lines.append(f"{key}: {value}\n")
    lines.append("---\n")
    lines.append("\n")
    lines.append(body)
    file_path.write_text("".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Serve the UI
# ---------------------------------------------------------------------------

def _find_ui() -> Path:
    for p in [
        Path(__file__).parent / "mindwriter_ui.html",
        Path.cwd() / "mindwriter_ui.html",
        Path.home() / "mindwriter_ui.html",
    ]:
        if p.exists():
            return p
    return Path(__file__).parent / "mindwriter_ui.html"


@app.route("/")
def serve_ui():
    ui = _find_ui()
    if not ui.exists():
        locs = "".join(
            f"<li><code>{p}</code></li>"
            for p in [
                Path(__file__).parent / "mindwriter_ui.html",
                Path.cwd() / "mindwriter_ui.html",
                Path.home() / "mindwriter_ui.html",
            ]
        )
        return (
            "<h2>mindwriter_ui.html not found</h2>"
            "<p>Place it in one of:</p>"
            f"<ul>{locs}</ul>",
            404,
        )
    return ui.read_text(encoding="utf-8"), 200, {"Content-Type": "text/html"}


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(400)
def bad_request(e):
    return jsonify({"error": str(e.description)}), 400

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": str(e.description)}), 404

@app.errorhandler(500)
def internal_error(e):
    return jsonify({"error": str(e.description)}), 500


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

@app.route("/health")
def health():
    nd    = _notes_dir()
    files = collect_note_files(nd)
    return jsonify({
        "status":           "ok",
        "notes_root":       str(_notes_root()),
        "notes_dir":        str(nd),
        "notes_dir_exists": nd.exists(),
        "note_count":       len(files),
    })


# ---------------------------------------------------------------------------
# GET /api/notes  — list all notes
# ---------------------------------------------------------------------------

@app.route("/api/notes", methods=["GET"])
def list_notes():
    """
    List all notes with metadata.
    Query params:
        tag     filter by tag  (exact, lowercase)
        author  filter by author (exact, lowercase)
        sort    id | title | modified | created  (default: id)
    """
    nd            = _notes_dir()
    note_files    = collect_note_files(nd)
    id_to_file, _ = build_index(note_files)

    tag    = request.args.get("tag",    "").lower().strip()
    author = request.args.get("author", "").lower().strip()
    sort   = request.args.get("sort",   "id")

    notes = [_note_to_dict(nid, nf) for nid, nf in id_to_file.items()]

    if tag:
        notes = [n for n in notes if tag in n["tags"]]
    if author:
        notes = [n for n in notes if author == n["author"]]

    if sort == "title":
        notes.sort(key=lambda n: n["title"].lower())
    elif sort == "modified":
        notes.sort(key=lambda n: n["modified"], reverse=True)
    elif sort == "created":
        notes.sort(key=lambda n: n["created"], reverse=True)

    return jsonify({"total": len(notes), "notes": notes})


# ---------------------------------------------------------------------------
# GET /api/notes/search  — search notes
# ---------------------------------------------------------------------------

@app.route("/api/notes/search", methods=["GET"])
def search_notes():
    """
    Search notes by keywords (OR logic).
    Query params:
        q   keyword — repeat for multiple: ?q=python&q=flask
            or comma-separated: ?q=python,flask
    Returns each matched note with:
        matched_keywords  list of keywords that hit
        match_report      per-keyword locations (filename/header:field/body)
                          and up to 2 body context snippets
    """
    raw      = request.args.getlist("q")
    keywords = [k.strip().lower() for r in raw for k in r.split(",") if k.strip()]
    if not keywords:
        abort(400, description="Provide at least one keyword via ?q=keyword")

    nd            = _notes_dir()
    note_files    = collect_note_files(nd)
    id_to_file, _ = build_index(note_files)
    results       = []

    for nid, nf in id_to_file.items():
        meta          = parse_yaml_header(nf)
        filename_stem = nf.stem.lower()

        # Split body into lines for snippet extraction
        try:
            raw_lines = nf.read_text(encoding="utf-8").splitlines(keepends=True)
        except Exception:
            raw_lines = []

        yaml_end = -1
        if raw_lines and raw_lines[0].strip() == "---":
            for i in range(1, len(raw_lines)):
                if raw_lines[i].strip() == "---":
                    yaml_end = i
                    break
        body_lines = raw_lines[yaml_end + 1:] if yaml_end != -1 else raw_lines

        match_report = {}

        for kw in keywords:
            locations = []
            snippets  = []

            if kw in filename_stem:
                locations.append("filename")

            for field, value in meta.items():
                if field == "file":
                    continue
                if kw in str(value).lower():
                    locations.append(f"header:{field}")

            for i, line in enumerate(body_lines):
                if kw in line.lower():
                    start = max(0, i - 1)
                    end   = min(len(body_lines), i + 2)
                    chunk = "".join(body_lines[start:end]).strip()
                    if len(chunk) > 120:
                        chunk = chunk[:117] + "…"
                    snippets.append(chunk)
                    locations.append("body")
                    if len(snippets) >= 2:
                        break

            if locations:
                match_report[kw] = {
                    "locations": list(dict.fromkeys(locations)),  # dedupe, keep order
                    "snippets":  snippets,
                }

        if match_report:
            d = _note_to_dict(nid, nf)
            d["matched_keywords"] = list(match_report.keys())
            d["match_report"]     = match_report
            results.append(d)

    return jsonify({"query": keywords, "total": len(results), "notes": results})


# ---------------------------------------------------------------------------
# GET /api/notes/<id>  — get one note
# ---------------------------------------------------------------------------

@app.route("/api/notes/<identifier>", methods=["GET"])
def get_note(identifier):
    """Get a single note by numeric id or filename — returns metadata + body."""
    nid, nf = _resolve(identifier)
    return jsonify(_note_to_dict(nid, nf, include_body=True))


# ---------------------------------------------------------------------------
# POST /api/notes  — create a note
# ---------------------------------------------------------------------------

@app.route("/api/notes", methods=["POST"])
def create_note():
    """
    Create a new note.
    JSON body:
        title       (required)
        body        note content  (default: "")
        author      (optional)
        tags        comma-separated string or list  (optional)
        priority    (optional)
    """
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        abort(400, description="'title' is required.")

    nd = _notes_dir()
    nd.mkdir(parents=True, exist_ok=True)

    # Build filename from title
    safe = "".join(c if c.isalnum() or c in "-_ " else "" for c in title.lower())
    slug = safe.strip().replace(" ", "-")
    filename = f"{slug}.md"
    dest = nd / filename
    counter = 1
    while dest.exists():
        dest = nd / f"{slug}-{counter}.md"
        counter += 1

    now = datetime.now().isoformat()

    tags_raw = data.get("tags", "")
    if isinstance(tags_raw, list):
        tags_str = ", ".join(tags_raw)
    else:
        tags_str = tags_raw

    meta = {
        "title":    title.lower(),
        "created":  now,
        "modified": now,
        "tags":     tags_str.lower(),
        "author":   (data.get("author") or "").lower(),
        "priority": str(data.get("priority") or ""),
    }
    body = data.get("body", "") or ""

    try:
        _write_yaml_header(dest, meta, body)
    except Exception as e:
        abort(500, description=f"Could not write note file: {e}")

    # Resolve the index assigned to the new note
    note_files    = collect_note_files(nd)
    _, file_to_id = build_index(note_files)
    assigned_id   = file_to_id.get(dest, -1)

    return jsonify({
        "message":  "Note created.",
        "id":       assigned_id,
        "filename": dest.name,
        "title":    meta["title"],
    }), 201


# ---------------------------------------------------------------------------
# PUT /api/notes/<id>  — update a note
# ---------------------------------------------------------------------------

@app.route("/api/notes/<identifier>", methods=["PUT"])
def update_note(identifier):
    """
    Update an existing note's body and/or metadata fields.
    JSON body (all optional — only supplied fields are changed):
        title, body, author, tags, priority
    The 'modified' timestamp is always refreshed automatically.
    """
    nid, nf = _resolve(identifier)
    data    = request.get_json(silent=True) or {}

    if not data:
        abort(400, description="Provide at least one field to update in the JSON body.")

    meta = parse_yaml_header(nf)
    body = _get_body(nf)

    if "title" in data:
        meta["title"]  = str(data["title"]).lower().strip()
    if "author" in data:
        meta["author"] = str(data["author"]).lower().strip()
    if "priority" in data:
        meta["priority"] = str(data["priority"]).strip()
    if "tags" in data:
        raw = data["tags"]
        meta["tags"] = (", ".join(raw) if isinstance(raw, list) else str(raw)).lower()
    if "body" in data:
        body = data["body"]

    meta["modified"] = datetime.now().isoformat()

    try:
        _write_yaml_header(nf, meta, body)
    except Exception as e:
        abort(500, description=f"Could not update note file: {e}")

    return jsonify({
        "message":  "Note updated.",
        "id":       nid,
        "filename": nf.name,
        "modified": meta["modified"],
    })


# ---------------------------------------------------------------------------
# DELETE /api/notes/<id>  — delete a note
# ---------------------------------------------------------------------------

@app.route("/api/notes/<identifier>", methods=["DELETE"])
def delete_note(identifier):
    """Delete a note by numeric id or filename."""
    nid, nf = _resolve(identifier)
    try:
        nf.unlink()
    except Exception as e:
        abort(500, description=f"Could not delete note: {e}")
    return jsonify({"message": f"Note '{nf.name}' deleted.", "id": nid})


# ---------------------------------------------------------------------------
# GET /api/stats
# ---------------------------------------------------------------------------

@app.route("/api/stats", methods=["GET"])
def stats():
    """Aggregate statistics across all notes."""
    from collections import Counter
    nd         = _notes_dir()
    note_files = collect_note_files(nd)

    total_words     = 0
    author_counts   = Counter()
    priority_counts = Counter()
    tag_counts      = Counter()
    no_title = no_author = no_tags = 0
    recent   = []   # (modified_iso, filename)

    for nf in note_files:
        meta = parse_yaml_header(nf)
        body = _get_body(nf)
        total_words += len(body.split())

        author = meta.get("author", "").strip().lower()
        if author:
            author_counts[author] += 1
        else:
            no_author += 1

        priority = meta.get("priority", "").strip()
        if priority:
            priority_counts[priority] += 1

        tags = _parse_tags(meta.get("tags", ""))
        if tags:
            for t in tags:
                tag_counts[t] += 1
        else:
            no_tags += 1

        if not meta.get("title", "").strip():
            no_title += 1

        mod = meta.get("modified", "")
        if mod:
            recent.append((mod, nf.name))

    total  = len(note_files)
    recent = sorted(recent, reverse=True)[:5]

    return jsonify({
        "total_notes":       total,
        "total_words":       total_words,
        "avg_words":         (total_words // total) if total else 0,
        "no_title":          no_title,
        "no_author":         no_author,
        "no_tags":           no_tags,
        "by_author":         dict(author_counts.most_common()),
        "by_priority":       dict(priority_counts.most_common()),
        "by_tag":            dict(tag_counts.most_common()),
        "recently_modified": [{"modified": m, "filename": f} for m, f in recent],
    })


# ---------------------------------------------------------------------------
# GET /api/datasets  — list datasets
# ---------------------------------------------------------------------------

@app.route("/api/datasets", methods=["GET"])
def list_datasets():
    """List all imported datasets with their sidecar metadata."""
    result = []
    for i, ds in enumerate(_collect_datasets(_notes_root()), start=1):
        meta = read_dataset_sidecar(ds)
        result.append({
            "id":          i,
            "filename":    ds.name,
            "title":       meta.get("title", ds.stem),
            "description": meta.get("description", ""),
            "author":      meta.get("author", ""),
            "tags":        _parse_tags(meta.get("tags", "")),
            "format":      meta.get("format", ds.suffix.lstrip(".").upper()),
            "rows":        meta.get("rows", ""),
            "columns":     meta.get("columns", ""),
            "fields":      meta.get("fields", ""),
            "source_url":  meta.get("source_url", ""),
            "license":     meta.get("license", ""),
            "imported":    meta.get("imported", "")[:10],
            "modified":    meta.get("modified", "")[:10],
        })
    return jsonify({"total": len(result), "datasets": result})


# ---------------------------------------------------------------------------
# GET /api/datasets/<n>  — get one dataset
# ---------------------------------------------------------------------------

@app.route("/api/datasets/<int:dataset_id>", methods=["GET"])
def get_dataset(dataset_id):
    """Get full sidecar metadata for a single dataset by list index."""
    datasets = _collect_datasets(_notes_root())
    if dataset_id < 1 or dataset_id > len(datasets):
        abort(404, description=f"Dataset {dataset_id} not found.")
    ds   = datasets[dataset_id - 1]
    meta = read_dataset_sidecar(ds)
    meta["id"]       = dataset_id
    meta["filename"] = ds.name
    return jsonify(meta)


# ---------------------------------------------------------------------------
# POST /api/datasets/import  — import a dataset from a server-side path
# ---------------------------------------------------------------------------

@app.route("/api/datasets/import", methods=["POST"])
def import_dataset():
    """
    Import a CSV or JSON file that already exists on the server's filesystem.
    JSON body:
        path         (required)  absolute or ~ path to the source file
        title        (optional)
        description  (optional)
        author       (optional)
        tags         (optional, comma-separated string or list)
        source_url   (optional)
        license      (optional)
        priority     (optional)
    """
    import shutil, csv, json as pyjson

    data = request.get_json(silent=True) or {}
    raw_path = (data.get("path") or "").strip()
    if not raw_path:
        abort(400, description="'path' is required.")

    source = Path(raw_path).expanduser().resolve()
    if not source.exists():
        abort(400, description=f"File not found: {source}")

    suffix = source.suffix.lower()
    if suffix not in (".csv", ".json"):
        abort(400, description=f"Only .csv and .json files are supported (got '{suffix}').")

    ddir = _ensure_datasets_dir(_notes_root())
    if ddir is None:
        abort(500, description="Could not create datasets directory.")

    # Introspect the file
    row_count, columns, parse_error = 0, [], None
    try:
        if suffix == ".csv":
            with open(source, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                columns = list(reader.fieldnames or [])
                for _ in reader:
                    row_count += 1
        else:
            with open(source, "r", encoding="utf-8") as f:
                raw_data = pyjson.load(f)
            if isinstance(raw_data, list):
                row_count = len(raw_data)
                if raw_data and isinstance(raw_data[0], dict):
                    columns = list(raw_data[0].keys())
            elif isinstance(raw_data, dict):
                row_count, columns = 1, list(raw_data.keys())
    except Exception as e:
        parse_error = str(e)

    # Build metadata
    tags_raw = data.get("tags", "")
    tags = [t.strip().lower() for t in (tags_raw if isinstance(tags_raw, list) else tags_raw.split(",")) if str(t).strip()]

    now = datetime.now().isoformat()
    meta = {
        "title":             (data.get("title") or source.stem.replace("_", " ").replace("-", " ")).lower(),
        "description":       data.get("description", ""),
        "author":            (data.get("author") or "").lower(),
        "tags":              tags,
        "source_url":        data.get("source_url", ""),
        "license":           data.get("license", ""),
        "priority":          str(data.get("priority") or ""),
        "format":            suffix.lstrip(".").upper(),
        "rows":              row_count,
        "columns":           len(columns),
        "fields":            columns,
        "imported":          now,
        "modified":          now,
        "original_filename": source.name,
    }
    meta = {k: v for k, v in meta.items() if v != "" and v != [] and v != 0}

    # Copy to datasets directory
    dest = ddir / source.name
    counter = 1
    while dest.exists():
        dest = ddir / f"{source.stem}_{counter}{source.suffix}"
        counter += 1

    try:
        shutil.copy2(source, dest)
    except Exception as e:
        abort(500, description=f"Could not copy file: {e}")

    sidecar = _write_sidecar(dest, meta)

    return jsonify({
        "message":       "Dataset imported.",
        "filename":      dest.name,
        "sidecar":       sidecar.name if sidecar else None,
        "rows":          row_count,
        "columns":       len(columns),
        "parse_error":   parse_error,
    }), 201


# ---------------------------------------------------------------------------
# POST /api/datasets/upload  — upload a file directly from the browser
# ---------------------------------------------------------------------------

@app.route("/api/datasets/upload", methods=["POST"])
def upload_dataset():
    """
    Accept a multipart file upload (CSV or JSON) plus optional metadata fields.
    Form fields:
        file         the .csv or .json file  (required)
        title, description, author, tags, source_url, license, priority
    """
    import csv, json as pyjson, tempfile, shutil

    if "file" not in request.files:
        abort(400, description="No file in request. Use field name 'file'.")

    upload = request.files["file"]
    if not upload.filename:
        abort(400, description="No file selected.")

    suffix = Path(upload.filename).suffix.lower()
    if suffix not in (".csv", ".json"):
        abort(400, description=f"Only .csv and .json files are supported (got \'{suffix}\').")

    ddir = _ensure_datasets_dir(_notes_root())
    if ddir is None:
        abort(500, description="Could not create datasets directory.")

    # Save upload to a temp file for introspection
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        upload.save(tmp.name)
        tmp_path = Path(tmp.name)

    row_count, columns, parse_error = 0, [], None
    try:
        if suffix == ".csv":
            with open(tmp_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                columns = list(reader.fieldnames or [])
                for _ in reader:
                    row_count += 1
        else:
            with open(tmp_path, "r", encoding="utf-8") as f:
                raw_data = pyjson.load(f)
            if isinstance(raw_data, list):
                row_count = len(raw_data)
                if raw_data and isinstance(raw_data[0], dict):
                    columns = list(raw_data[0].keys())
            elif isinstance(raw_data, dict):
                row_count, columns = 1, list(raw_data.keys())
    except Exception as e:
        parse_error = str(e)

    stem     = Path(upload.filename).stem
    tags_raw = request.form.get("tags", "")
    tags     = [t.strip().lower() for t in tags_raw.split(",") if t.strip()]
    now      = datetime.now().isoformat()

    meta = {
        "title":             (request.form.get("title") or stem.replace("_"," ").replace("-"," ")).lower(),
        "description":       request.form.get("description", ""),
        "author":            request.form.get("author", "").lower(),
        "tags":              tags,
        "source_url":        request.form.get("source_url", ""),
        "license":           request.form.get("license", ""),
        "priority":          request.form.get("priority", ""),
        "format":            suffix.lstrip(".").upper(),
        "rows":              row_count,
        "columns":           len(columns),
        "fields":            columns,
        "imported":          now,
        "modified":          now,
        "original_filename": upload.filename,
    }
    meta = {k: v for k, v in meta.items() if v != "" and v != [] and v != 0}

    # Move temp file into datasets dir
    dest = ddir / upload.filename
    counter = 1
    while dest.exists():
        dest = ddir / f"{stem}_{counter}{suffix}"
        counter += 1

    try:
        tmp_path.rename(dest)
    except Exception:
        shutil.copy2(tmp_path, dest)
        tmp_path.unlink(missing_ok=True)

    sidecar = _write_sidecar(dest, meta)

    return jsonify({
        "message":     "Dataset uploaded.",
        "filename":    dest.name,
        "sidecar":     sidecar.name if sidecar else None,
        "rows":        row_count,
        "columns":     len(columns),
        "parse_error": parse_error,
    }), 201


# ---------------------------------------------------------------------------
# DELETE /api/datasets/<n>  — delete dataset file + sidecar
# ---------------------------------------------------------------------------

@app.route("/api/datasets/<int:dataset_id>", methods=["DELETE"])
def delete_dataset(dataset_id):
    """Delete a dataset and its sidecar metadata file."""
    datasets = _collect_datasets(_notes_root())
    if dataset_id < 1 or dataset_id > len(datasets):
        abort(404, description=f"Dataset {dataset_id} not found.")

    ds      = datasets[dataset_id - 1]
    sidecar = ds.parent / (ds.stem + ".dataset.yaml")
    deleted = []

    try:
        ds.unlink()
        deleted.append(ds.name)
    except Exception as e:
        abort(500, description=f"Could not delete dataset file: {e}")

    if sidecar.exists():
        try:
            sidecar.unlink()
            deleted.append(sidecar.name)
        except Exception:
            pass  # sidecar deletion failure is non-fatal

    return jsonify({"message": "Dataset deleted.", "deleted": deleted})


# ---------------------------------------------------------------------------
# PUT /api/datasets/<n>/reupload  — replace file, keep or update metadata
# ---------------------------------------------------------------------------

@app.route("/api/datasets/<int:dataset_id>/reupload", methods=["PUT"])
def reupload_dataset(dataset_id):
    """
    Replace an existing dataset file with a new upload.
    The sidecar is updated with fresh row/column counts and a new 'modified'
    timestamp; all other metadata fields are preserved unless explicitly
    overridden via form fields.

    Form fields:
        file              (required) the replacement .csv or .json file
        title, description, author, tags, source_url, license, priority
                          (optional) override specific metadata fields
    """
    import csv, json as pyjson, tempfile, shutil

    datasets = _collect_datasets(_notes_root())
    if dataset_id < 1 or dataset_id > len(datasets):
        abort(404, description=f"Dataset {dataset_id} not found.")

    ds = datasets[dataset_id - 1]

    if "file" not in request.files:
        abort(400, description="No file in request. Use field name 'file'.")

    upload = request.files["file"]
    if not upload.filename:
        abort(400, description="No file selected.")

    suffix = Path(upload.filename).suffix.lower()
    if suffix not in (".csv", ".json"):
        abort(400, description=f"Only .csv and .json files are supported (got '{suffix}').")

    # Save upload to a temp file for introspection
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        upload.save(tmp.name)
        tmp_path = Path(tmp.name)

    row_count, columns, parse_error = 0, [], None
    try:
        if suffix == ".csv":
            with open(tmp_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                columns = list(reader.fieldnames or [])
                for _ in reader:
                    row_count += 1
        else:
            with open(tmp_path, "r", encoding="utf-8") as f:
                raw_data = pyjson.load(f)
            if isinstance(raw_data, list):
                row_count = len(raw_data)
                if raw_data and isinstance(raw_data[0], dict):
                    columns = list(raw_data[0].keys())
            elif isinstance(raw_data, dict):
                row_count, columns = 1, list(raw_data.keys())
    except Exception as e:
        parse_error = str(e)

    # Load existing sidecar metadata and apply any overrides from form
    meta = read_dataset_sidecar(ds)

    for field in ("title", "description", "source_url", "license", "priority"):
        val = request.form.get(field, "").strip()
        if val:
            meta[field] = val.lower() if field == "title" else val

    author = request.form.get("author", "").strip()
    if author:
        meta["author"] = author.lower()

    tags_raw = request.form.get("tags", "").strip()
    if tags_raw:
        meta["tags"] = [t.strip().lower() for t in tags_raw.split(",") if t.strip()]

    # Always update file-derived fields
    meta["format"]            = suffix.lstrip(".").upper()
    meta["rows"]              = row_count
    meta["columns"]           = len(columns)
    meta["fields"]            = columns
    meta["modified"]          = datetime.now().isoformat()
    meta["original_filename"] = upload.filename
    meta = {k: v for k, v in meta.items() if v != "" and v != [] and v != 0}

    # Replace the data file (keep same path)
    try:
        tmp_path.rename(ds)
    except Exception:
        shutil.copy2(tmp_path, ds)
        tmp_path.unlink(missing_ok=True)

    _write_sidecar(ds, meta)

    return jsonify({
        "message":     "Dataset reuploaded.",
        "filename":    ds.name,
        "rows":        row_count,
        "columns":     len(columns),
        "parse_error": parse_error,
    })



# ---------------------------------------------------------------------------
# GET /api/datasets/<n>/data  — return full parsed dataset rows
# ---------------------------------------------------------------------------

@app.route("/api/datasets/<int:dataset_id>/data", methods=["GET"])
def get_dataset_data(dataset_id):
    """
    Return the full parsed contents of a dataset as JSON rows.
    Query params:
        page      page number (default 1)
        per_page  rows per page (default 100, max 1000)

    Response:
        {
          "filename": "...",
          "format":   "CSV" | "JSON",
          "columns":  [...],
          "rows":     [[...], ...],   // array of arrays, values in column order
          "total":    1234,
          "page":     1,
          "per_page": 100,
          "pages":    13
        }
    """
    import csv, json as pyjson

    datasets = _collect_datasets(_notes_root())
    if dataset_id < 1 or dataset_id > len(datasets):
        abort(404, description=f"Dataset {dataset_id} not found.")

    ds     = datasets[dataset_id - 1]
    suffix = ds.suffix.lower()
    page     = max(1, int(request.args.get("page",     1)))
    per_page = min(1000, max(1, int(request.args.get("per_page", 100))))
    query    = request.args.get("q", "").strip().lower()

    columns = []
    all_rows = []

    try:
        if suffix == ".csv":
            with open(ds, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                columns = list(reader.fieldnames or [])
                for row in reader:
                    all_rows.append([row.get(c, "") for c in columns])
        else:
            with open(ds, "r", encoding="utf-8") as f:
                data = pyjson.load(f)
            if isinstance(data, list):
                if data and isinstance(data[0], dict):
                    columns = list(data[0].keys())
                    for row in data:
                        all_rows.append([row.get(c, "") for c in columns])
                else:
                    columns = ["value"]
                    all_rows = [[v] for v in data]
            elif isinstance(data, dict):
                columns = list(data.keys())
                all_rows = [[data.get(c, "") for c in columns]]
    except Exception as e:
        abort(500, description=f"Could not parse dataset: {e}")

    # Filter rows if a search query was provided
    # A row matches if the query string appears in any cell value (case-insensitive)
    if query:
        all_rows = [
            row for row in all_rows
            if any(query in str(cell).lower() for cell in row)
        ]

    total  = len(all_rows)
    pages  = max(1, (total + per_page - 1) // per_page)
    page   = min(page, pages)
    start  = (page - 1) * per_page
    rows   = all_rows[start:start + per_page]

    # Serialise any non-string values
    safe_rows = []
    for row in rows:
        safe_rows.append([str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v for v in row])

    return jsonify({
        "filename": ds.name,
        "format":   suffix.lstrip(".").upper(),
        "columns":  columns,
        "rows":     safe_rows,
        "query":    query,
        "total":    total,
        "page":     page,
        "per_page": per_page,
        "pages":    pages,
    })



# ---------------------------------------------------------------------------
# Browser keep-alive — shutdown when the tab/window closes
# ---------------------------------------------------------------------------
# The UI sends GET /ping every 5 seconds while it is open.
# A watchdog thread watches the timestamp of the last ping; if more than
# SHUTDOWN_TIMEOUT seconds pass with no ping the server calls os._exit(0).
# os._exit bypasses Python's normal shutdown so it works even inside Flask's
# Werkzeug dev server which catches SystemExit.

import time as _time

_last_ping    = _time.monotonic()
PING_INTERVAL = 5     # seconds between browser pings
SHUTDOWN_TIMEOUT = 15  # seconds of silence before shutdown


@app.route("/ping")
def ping():
    """Heartbeat called by the UI every few seconds."""
    global _last_ping
    _last_ping = _time.monotonic()
    return jsonify({"ok": True})


def _watchdog():
    """Background thread — exits the process when pings stop."""
    # Give the browser time to open and send its first ping
    _time.sleep(SHUTDOWN_TIMEOUT)
    while True:
        _time.sleep(2)
        silence = _time.monotonic() - _last_ping
        if silence > SHUTDOWN_TIMEOUT:
            print(f"\nNo ping for {silence:.0f}s — browser tab closed. Shutting down.")
            os._exit(0)



# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port  = int(os.environ.get("PORT", 8000))
    debug = os.environ.get("DEBUG", "false").lower() == "true"
    nd    = _notes_dir()
    count = len(collect_note_files(nd))

    print(f"\nMindWriter API  →  http://localhost:{port}")
    print(f"Notes directory →  {nd}")
    print(f"Notes found     →  {count}")
    if not nd.exists():
        print(f"\n  ⚠  Directory does not exist: {nd}")
        print(f"     Create it with:  mkdir -p {nd}")
    elif count == 0:
        print(f"\n  ⚠  No .md/.note/.txt files found in {nd}")
    print()

    def open_browser():
        import time
        time.sleep(1.0)
        webbrowser.open(f"http://localhost:{port}/")

    if not debug:
        threading.Thread(target=open_browser, daemon=True).start()

    # Start watchdog — shuts down when the browser tab closes
    threading.Thread(target=_watchdog, daemon=True).start()
    print(f"  Auto-shutdown after {SHUTDOWN_TIMEOUT}s with no browser activity.")
    print()

    app.run(host="0.0.0.0", port=port, debug=debug)