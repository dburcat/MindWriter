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
CORS(app, origins=["http://localhost:8000", "http://127.0.0.1:8000"])


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------
# Three layers of protection, all configured via environment variables so
# nothing sensitive is baked into the source code:
#
#   MINDWRITER_API_KEY   — required token; auto-generated on first run and
#                          saved to ~/.notes/.api_key  (or printed if saving
#                          fails).  Pass as header:  X-API-Key: <token>
#                          or query param:           ?api_key=<token>
#
#   RATE_LIMIT_WINDOW    — rolling window in seconds  (default: 60)
#   RATE_LIMIT_MAX       — max requests per window    (default: 120)
#
# Localhost binding: app.run() uses host="127.0.0.1" so the socket never
# accepts connections from other machines on the network.
# ---------------------------------------------------------------------------

import secrets as _secrets
import hashlib  as _hashlib
from collections import defaultdict as _defaultdict
from functools   import wraps as _wraps

# ── API key ───────────────────────────────────────────────────────────────

_KEY_FILE = Path.home() / ".notes" / ".api_key"

def _load_or_create_api_key() -> str:
    """
    Load the API key from disk, or generate a new one and save it.
    The key is stored in plain text in ~/.notes/.api_key which is only
    readable by the current user (chmod 600 is applied on creation).
    """
    env_key = os.environ.get("MINDWRITER_API_KEY", "").strip()
    if env_key:
        return env_key

    if _KEY_FILE.exists():
        key = _KEY_FILE.read_text().strip()
        if key:
            return key

    # Generate a new 32-byte (256-bit) URL-safe token
    key = _secrets.token_urlsafe(32)
    try:
        _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _KEY_FILE.write_text(key)
        _KEY_FILE.chmod(0o600)          # owner read/write only
    except Exception as e:
        print(f"  ⚠  Could not save API key to {_KEY_FILE}: {e}")
        print(f"     Set it manually:  export MINDWRITER_API_KEY={key}")
    return key

_API_KEY = _load_or_create_api_key()

def _check_api_key() -> bool:
    """Return True if the request carries the correct API key."""
    # Accept via header or query param
    provided = (
        request.headers.get("X-API-Key", "")
        or request.args.get("api_key", "")
    )
    # Constant-time comparison to prevent timing attacks
    return _secrets.compare_digest(provided, _API_KEY)

# Public endpoints that do NOT require authentication
_PUBLIC_PATHS = {"/", "/docs", "/health", "/ping", "/api/auth/key"}

# ── Rate limiting ─────────────────────────────────────────────────────────

_RATE_WINDOW = int(os.environ.get("RATE_LIMIT_WINDOW", 60))   # seconds
_RATE_MAX    = int(os.environ.get("RATE_LIMIT_MAX",   120))   # requests
_rate_store: dict = _defaultdict(list)   # ip -> [timestamp, ...]

# Paths exempt from the rate limit — high-frequency legitimate operations
# that the rate limiter is not designed to protect against.
_RATE_EXEMPT_PREFIXES = (
    "/ping",              # keepalive — fires every 5 s
    "/api/datasets/",     # dataset data paging can be very high frequency
)

def _is_rate_exempt(path: str) -> bool:
    """Return True if this path should bypass the rate limiter."""
    return any(path.startswith(p) for p in _RATE_EXEMPT_PREFIXES)

def _check_rate_limit(ip: str) -> bool:
    """Sliding-window rate limiter. Returns True if request is allowed."""
    now    = _time.monotonic()
    window = _rate_store[ip]
    # Drop timestamps outside the rolling window
    _rate_store[ip] = [t for t in window if now - t < _RATE_WINDOW]
    if len(_rate_store[ip]) >= _RATE_MAX:
        return False
    _rate_store[ip].append(now)
    return True

# ── Before-request hook — runs before every route ─────────────────────────

@app.before_request
def enforce_security():
    """
    Applied to every incoming request:
      1. Localhost-only check  — refuse anything not from 127.0.0.1
      2. Rate limit            — 429 if the client exceeds the window
                                 (exempt: /ping, /api/datasets/* — high frequency)
      3. API key               — 401 if missing or wrong (public paths exempt)
    """
    # 1. Localhost binding — belt-and-suspenders check even though we bind
    #    to 127.0.0.1; protects against reverse proxies forwarding externally.
    remote = request.remote_addr
    if remote not in ("127.0.0.1", "::1"):
        return jsonify({"error": "Access denied: localhost only."}), 403

    # 2. Rate limit — skip for high-frequency legitimate paths
    if not _is_rate_exempt(request.path) and not _check_rate_limit(remote):
        return jsonify({
            "error": f"Rate limit exceeded. Max {_RATE_MAX} requests per {_RATE_WINDOW}s."
        }), 429

    # 3. API key — skip for public paths (UI, health, ping)
    if request.path not in _PUBLIC_PATHS:
        if not _check_api_key():
            return jsonify({"error": "Unauthorized. Provide a valid X-API-Key header."}), 401



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


def _existing_dataset_titles() -> dict:
    """Return a dict of {normalised_title: filename} for all current datasets."""
    titles = {}
    for ds in _collect_datasets(_notes_root()):
        meta  = read_dataset_sidecar(ds)
        title = meta.get("title", ds.stem).strip().lower()
        if title:
            titles[title] = ds.name
    return titles


def _check_duplicate_dataset_title(title: str) -> None:
    """Abort with 409 if a dataset with this title already exists."""
    normalised = title.strip().lower()
    existing   = _existing_dataset_titles()
    if normalised in existing:
        abort(409, description=(
            f"A dataset titled '{normalised}' already exists "
            f"(file: {existing[normalised]}). "
            "Choose a different title."
        ))


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


@app.route("/api/auth/key", methods=["GET"])
def get_api_key():
    """
    Return the current API key to the local UI.
    This endpoint is public (no key required) but localhost-only — the
    before_request hook already refuses any non-loopback connection, so
    only someone already on this machine can reach it.
    The UI calls this once on load to auto-fill the key field.
    """
    return jsonify({"api_key": _API_KEY})



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


def _find_docs() -> Path:
    for p in [
        Path(__file__).parent / "mindwriter_api_docs.html",
        Path.cwd() / "mindwriter_api_docs.html",
        Path.home() / "mindwriter_api_docs.html",
    ]:
        if p.exists():
            return p
    return Path(__file__).parent / "mindwriter_api_docs.html"


@app.route("/docs")
def serve_docs():
    """Serve the API documentation page."""
    docs = _find_docs()
    if not docs.exists():
        locs = "".join(
            f"<li><code>{p}</code></li>"
            for p in [
                Path(__file__).parent / "mindwriter_api_docs.html",
                Path.cwd() / "mindwriter_api_docs.html",
                Path.home() / "mindwriter_api_docs.html",
            ]
        )
        return (
            "<h2>mindwriter_api_docs.html not found</h2>"
            "<p>Place it in one of:</p>"
            f"<ul>{locs}</ul>",
            404,
        )
    return docs.read_text(encoding="utf-8"), 200, {"Content-Type": "text/html"}


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

    # Duplicate title check
    candidate_title = (data.get("title") or source.stem.replace("_", " ").replace("-", " ")).lower()
    _check_duplicate_dataset_title(candidate_title)

    now = datetime.now().isoformat()
    meta = {
        "title":             candidate_title,
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
# POST /api/datasets/create  — create a blank dataset from scratch
# ---------------------------------------------------------------------------

@app.route("/api/datasets/create", methods=["POST"])
def create_dataset():
    """
    Create a new empty dataset file from scratch.

    JSON body:
        name         filename without extension, e.g. "my_data"  (required)
        format       "csv" or "json"  (default: "csv")
        columns      list of column name strings  (required for CSV,
                     optional for JSON)
        rows         optional list of row objects to seed the file with
        title        sidecar metadata  (optional, defaults to name)
        description  (optional)
        author       (optional)
        tags         (optional)
        priority     (optional)

    Returns the new dataset's filename and assigned list index.
    """
    import csv, json as pyjson

    data    = request.get_json(silent=True) or {}
    name    = (data.get("name") or "").strip()
    fmt     = data.get("format", "csv").lower().strip()
    columns = data.get("columns", [])
    rows    = data.get("rows",    [])

    if not name:
        abort(400, description="'name' is required.")
    if fmt not in ("csv", "json"):
        abort(400, description="'format' must be 'csv' or 'json'.")
    if fmt == "csv" and not columns:
        abort(400, description="'columns' is required when format is 'csv'.")

    # Duplicate title check
    candidate_title = (data.get("title") or name.replace("_", " ").replace("-", " ")).lower()
    _check_duplicate_dataset_title(candidate_title)

    # Sanitise filename
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    suffix    = f".{fmt}"
    ddir      = _ensure_datasets_dir(_notes_root())
    if ddir is None:
        abort(500, description="Could not create datasets directory.")

    dest = ddir / f"{safe_name}{suffix}"
    counter = 1
    while dest.exists():
        dest = ddir / f"{safe_name}_{counter}{suffix}"
        counter += 1

    try:
        if fmt == "csv":
            with open(dest, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=columns)
                writer.writeheader()
                for row in rows:
                    if isinstance(row, dict):
                        writer.writerow({c: row.get(c, "") for c in columns})
        else:
            # JSON — rows can be any structure; default to empty list
            payload = rows if rows else []
            with open(dest, "w", encoding="utf-8") as f:
                pyjson.dump(payload, f, indent=2, ensure_ascii=False)
    except Exception as e:
        abort(500, description=f"Could not create dataset file: {e}")

    # Build sidecar
    now = datetime.now().isoformat()
    tags_raw = data.get("tags", "")
    tags = [t.strip().lower() for t in (tags_raw if isinstance(tags_raw, list) else str(tags_raw).split(",")) if str(t).strip()]
    meta = {
        "title":       (data.get("title") or safe_name.replace("_", " ").replace("-", " ")).lower(),
        "description": data.get("description", ""),
        "author":      data.get("author", "").lower(),
        "tags":        tags,
        "priority":    str(data.get("priority") or ""),
        "format":      fmt.upper(),
        "rows":        len(rows),
        "columns":     len(columns),
        "fields":      columns,
        "imported":    now,
        "modified":    now,
        "original_filename": dest.name,
    }
    meta = {k: v for k, v in meta.items() if v != "" and v != [] and v != 0}
    _write_sidecar(dest, meta)

    # Return the new dataset's position in the list
    all_ds = _collect_datasets(_notes_root())
    try:
        ds_id = next(i + 1 for i, d in enumerate(all_ds) if d == dest)
    except StopIteration:
        ds_id = -1

    return jsonify({
        "message":  "Dataset created.",
        "filename": dest.name,
        "id":       ds_id,
        "rows":     len(rows),
        "columns":  len(columns),
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
        upload_id    optional client-generated ID used to cancel this upload
        title, description, author, tags, source_url, license, priority
    """
    global _active_ops
    import csv, json as pyjson, tempfile, shutil

    if "file" not in request.files:
        abort(400, description="No file in request. Use field name 'file'.")

    upload    = request.files["file"]
    upload_id = request.form.get("upload_id", str(_uuid.uuid4()))

    if not upload.filename:
        abort(400, description="No file selected.")

    suffix = Path(upload.filename).suffix.lower()
    if suffix not in (".csv", ".json"):
        abort(400, description=f"Only .csv and .json files are supported (got \'{suffix}\').")

    ddir = _ensure_datasets_dir(_notes_root())
    if ddir is None:
        abort(500, description="Could not create datasets directory.")

    _active_ops[upload_id] = _time.monotonic()
    tmp_path = None
    try:
        # Save upload to a temp file in chunks so cancellation can interrupt it
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = Path(tmp.name)
            CHUNK = 256 * 1024  # 256 KB
            while True:
                if upload_id in _cancelled_ids:
                    _cancelled_ids.discard(upload_id)
                    return jsonify({"cancelled": True, "message": "Upload cancelled."}), 200
                chunk = upload.stream.read(CHUNK)
                if not chunk:
                    break
                tmp.write(chunk)

        # Check for cancellation again after the file is fully received
        if upload_id in _cancelled_ids:
            _cancelled_ids.discard(upload_id)
            tmp_path.unlink(missing_ok=True)
            return jsonify({"cancelled": True, "message": "Upload cancelled."}), 200

        row_count, columns, parse_error = 0, [], None
        try:
            if suffix == ".csv":
                with open(tmp_path, "r", encoding="utf-8", newline="") as f:
                    reader = csv.DictReader(f)
                    columns = list(reader.fieldnames or [])
                    for _ in reader:
                        row_count += 1
                        if upload_id in _cancelled_ids:
                            raise InterruptedError("cancelled")
            else:
                with open(tmp_path, "r", encoding="utf-8") as f:
                    raw_data = pyjson.load(f)
                if isinstance(raw_data, list):
                    row_count = len(raw_data)
                    if raw_data and isinstance(raw_data[0], dict):
                        columns = list(raw_data[0].keys())
                elif isinstance(raw_data, dict):
                    row_count, columns = 1, list(raw_data.keys())
        except InterruptedError:
            _cancelled_ids.discard(upload_id)
            tmp_path.unlink(missing_ok=True)
            return jsonify({"cancelled": True, "message": "Upload cancelled."}), 200
        except Exception as e:
            parse_error = str(e)

        stem     = Path(upload.filename).stem
        tags_raw = request.form.get("tags", "")
        tags     = [t.strip().lower() for t in tags_raw.split(",") if t.strip()]
        now      = datetime.now().isoformat()

        # Duplicate title check
        candidate_title = (request.form.get("title") or stem.replace("_", " ").replace("-", " ")).lower()
        _check_duplicate_dataset_title(candidate_title)

        meta = {
            "title":             candidate_title,
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

    finally:
        _active_ops.pop(upload_id, None)
        if tmp_path and tmp_path.exists():
            try: tmp_path.unlink(missing_ok=True)
            except Exception: pass


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

    # Clean up JSON→CSV cache if present
    if ds.suffix.lower() == ".json":
        try:
            cache = _json_cache_path(ds)
            if cache.exists():
                cache.unlink()
                deleted.append(cache.name)
            _row_count_cache.pop(str(cache), None)
        except Exception:
            pass
    _row_count_cache.pop(str(ds), None)

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

    upload_id = request.form.get("upload_id", str(_uuid.uuid4()))

    _active_ops[upload_id] = _time.monotonic()
    tmp_path = None
    try:
      # Save upload in chunks so cancellation can interrupt it
      with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = Path(tmp.name)
        CHUNK = 256 * 1024
        while True:
            if upload_id in _cancelled_ids:
                _cancelled_ids.discard(upload_id)
                return jsonify({"cancelled": True, "message": "Reupload cancelled."}), 200
            chunk = upload.stream.read(CHUNK)
            if not chunk:
                break
            tmp.write(chunk)

      if upload_id in _cancelled_ids:
          _cancelled_ids.discard(upload_id)
          tmp_path.unlink(missing_ok=True)
          return jsonify({"cancelled": True, "message": "Reupload cancelled."}), 200

      row_count, columns, parse_error = 0, [], None
      try:
          if suffix == ".csv":
              with open(tmp_path, "r", encoding="utf-8", newline="") as f:
                  reader = csv.DictReader(f)
                  columns = list(reader.fieldnames or [])
                  for _ in reader:
                      row_count += 1
                      if upload_id in _cancelled_ids:
                          raise InterruptedError("cancelled")
          else:
              with open(tmp_path, "r", encoding="utf-8") as f:
                  raw_data = pyjson.load(f)
              if isinstance(raw_data, list):
                  row_count = len(raw_data)
                  if raw_data and isinstance(raw_data[0], dict):
                      columns = list(raw_data[0].keys())
              elif isinstance(raw_data, dict):
                  row_count, columns = 1, list(raw_data.keys())
      except InterruptedError:
          _cancelled_ids.discard(upload_id)
          tmp_path.unlink(missing_ok=True)
          return jsonify({"cancelled": True, "message": "Reupload cancelled."}), 200
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

    finally:
        _active_ops.pop(upload_id, None)
        if tmp_path and tmp_path.exists():
            try: tmp_path.unlink(missing_ok=True)
            except Exception: pass



# ---------------------------------------------------------------------------
# GET /api/datasets/<n>/data  — return full parsed dataset rows
# ---------------------------------------------------------------------------

# In-process row-count cache: ds_path -> (mtime, row_count)
# Invalidated automatically when the file's mtime changes.
_row_count_cache: dict = {}


def _count_rows_bg(ds: Path, op_id: str) -> None:
    """
    Count all rows in a CSV file in a background thread, cache the result
    in the sidecar and in _row_count_cache, then release the active_ops slot.
    """
    import csv as _csv
    try:
        count = 0
        with open(ds, "r", encoding="utf-8", newline="") as f:
            reader = _csv.DictReader(f)
            for _ in reader:
                count += 1
        # Cache in memory
        mtime = ds.stat().st_mtime
        _row_count_cache[str(ds)] = (mtime, count)
        # Persist to sidecar so future server restarts benefit
        meta = read_dataset_sidecar(ds)
        meta["rows"]     = count
        meta["modified"] = meta.get("modified", datetime.now().isoformat())
        _write_sidecar(ds, meta)
    except Exception:
        pass
    finally:
        _active_ops.pop(op_id, None)


def _get_cached_row_count(ds: Path) -> int | None:
    """Return cached row count if the file has not changed, else None."""
    key = str(ds)
    if key in _row_count_cache:
        cached_mtime, cached_count = _row_count_cache[key]
        try:
            if ds.stat().st_mtime == cached_mtime:
                return cached_count
        except OSError:
            pass
        del _row_count_cache[key]
    return None


# JSON → CSV conversion cache
# When a JSON dataset is first accessed, it is converted to a flat CSV and
# stored in ~/.notes/datasets/.cache/<name>.csv  The cache file is used for
# all subsequent reads, giving JSON datasets the same streaming performance
# as native CSV files.  The cache is rebuilt whenever the source JSON's mtime
# changes.
_json_csv_cache_dir: Path | None = None


def _ensure_json_cache_dir() -> Path:
    global _json_csv_cache_dir
    if _json_csv_cache_dir is None:
        _json_csv_cache_dir = _notes_root() / "datasets" / ".cache"
    _json_csv_cache_dir.mkdir(parents=True, exist_ok=True)
    return _json_csv_cache_dir


def _json_cache_path(ds: Path) -> Path:
    """Return the expected CSV cache path for a JSON dataset."""
    return _ensure_json_cache_dir() / (ds.stem + ".csv")


def _json_cache_valid(ds: Path) -> bool:
    """Return True if a valid, up-to-date CSV cache exists for ds."""
    cache = _json_cache_path(ds)
    if not cache.exists():
        return False
    try:
        return cache.stat().st_mtime >= ds.stat().st_mtime
    except OSError:
        return False


def _build_json_csv_cache(ds: Path) -> Path:
    """
    Convert a JSON dataset to a flat CSV cache file.
    Handles three JSON shapes:
      list of dicts   → standard tabular CSV
      list of scalars → single-column CSV with header "value"
      single dict     → one-row CSV, keys as headers

    Returns the path to the cache CSV.
    Raises on parse or I/O errors.
    """
    import csv as _csv, json as _pyjson, tempfile as _tmp

    with open(ds, "r", encoding="utf-8") as f:
        data = _pyjson.load(f)

    cache_path = _json_cache_path(ds)
    tmp_fd, tmp_name = _tmp.mkstemp(
        suffix=".csv", dir=_ensure_json_cache_dir()
    )

    try:
        with open(tmp_fd, "w", encoding="utf-8", newline="") as out:
            if isinstance(data, list) and data and isinstance(data[0], dict):
                # Most common: list of row dicts
                columns = list(data[0].keys())
                writer  = _csv.DictWriter(out, fieldnames=columns,
                                          extrasaction="ignore")
                writer.writeheader()
                for row in data:
                    writer.writerow({c: str(row.get(c, "")) for c in columns})

            elif isinstance(data, list):
                # List of scalars
                writer = _csv.writer(out)
                writer.writerow(["value"])
                for v in data:
                    writer.writerow([str(v)])

            elif isinstance(data, dict):
                # Single dict → one row
                columns = list(data.keys())
                writer  = _csv.DictWriter(out, fieldnames=columns)
                writer.writeheader()
                writer.writerow({c: str(data[c]) for c in columns})

            else:
                raise ValueError("Unsupported JSON structure for CSV conversion.")

        # Atomic replace
        Path(tmp_name).replace(cache_path)
    except Exception:
        try: Path(tmp_name).unlink(missing_ok=True)
        except Exception: pass
        raise

    return cache_path


def _get_or_build_json_csv_cache(ds: Path) -> Path:
    """
    Return the CSV cache path for a JSON dataset, building it if needed.
    Thread-safe: multiple concurrent requests will race to build, but the
    atomic replace in _build_json_csv_cache ensures only a complete file
    is ever visible.
    """
    if _json_cache_valid(ds):
        return _json_cache_path(ds)
    return _build_json_csv_cache(ds)



@app.route("/api/datasets/<int:dataset_id>/data", methods=["GET"])
def get_dataset_data(dataset_id):
    """
    Return parsed dataset rows with pagination and optional filtering.

    Query params:
        page      page number, 1-based  (default: 1)
        per_page  rows per page, max 1000  (default: 100)
        q         filter — only rows containing this string (case-insensitive)
                  in any cell are returned

    Performance strategy:
      First request  — collects the page rows while streaming, then spawns a
                       background thread to finish counting all rows and cache
                       the total. Returns "total_exact": false with an estimate
                       from the sidecar on this first call.
      Later requests — total is served from the in-memory cache (no file scan),
                       so only the page window is read. Returns "total_exact": true.
      Filtered (q=)  — always requires a full scan to count matching rows.
                       The full count is done inline (no background thread).

    Response:
        {
          "filename":    "...",
          "format":      "CSV" | "JSON",
          "columns":     [...],
          "rows":        [[...], ...],
          "query":       "...",
          "total":       1234,
          "total_exact": true,
          "page":        1,
          "per_page":    100,
          "pages":       13
        }
    """
    import csv, json as pyjson

    datasets = _collect_datasets(_notes_root())
    if dataset_id < 1 or dataset_id > len(datasets):
        abort(404, description=f"Dataset {dataset_id} not found.")

    ds       = datasets[dataset_id - 1]
    suffix   = ds.suffix.lower()
    page     = max(1, int(request.args.get("page",     1)))
    per_page = min(1000, max(1, int(request.args.get("per_page", 100))))
    query    = request.args.get("q", "").strip().lower()

    def _safe(v):
        return v if isinstance(v, (str, int, float, bool, type(None))) else str(v)

    columns     = []
    page_rows   = []
    total       = 0
    total_exact = True

    op_id = str(_uuid.uuid4())
    _active_ops[op_id] = _time.monotonic()

    try:
        if suffix == ".csv":
            start = (page - 1) * per_page
            end   = start + per_page

            # ── Check row-count cache (no-query requests only) ─────────────
            cached_total = None if query else _get_cached_row_count(ds)

            with open(ds, "r", encoding="utf-8", newline="") as f:
                reader  = csv.DictReader(f)
                columns = list(reader.fieldnames or [])

                if cached_total is not None:
                    # Fast path: we know the total — only read until we have
                    # the page window, then stop.
                    matched = 0
                    for raw_row in reader:
                        row = [raw_row.get(c, "") for c in columns]
                        if start <= matched < end:
                            page_rows.append([_safe(v) for v in row])
                        matched += 1
                        if matched >= end:
                            break   # done — no need to read further
                    total       = cached_total
                    total_exact = True
                    _active_ops.pop(op_id, None)   # release immediately

                else:
                    # Slow path: stream the whole file.
                    # If no query, kick off a background count after we have
                    # the page rows so this request returns fast.
                    page_collected = False
                    for raw_row in reader:
                        row = [raw_row.get(c, "") for c in columns]

                        if query and not any(
                            query in str(cell).lower() for cell in row
                        ):
                            continue

                        if start <= total < end:
                            page_rows.append([_safe(v) for v in row])
                            if total + 1 == end and not query:
                                # We have all the rows we need — but we still
                                # need to finish counting. Hand off to background.
                                page_collected = True

                        total += 1

                    if not query:
                        # Cache result and write sidecar in background
                        mtime = ds.stat().st_mtime
                        _row_count_cache[str(ds)] = (mtime, total)
                        # Sidecar update is cheap — do it inline
                        try:
                            meta = read_dataset_sidecar(ds)
                            meta["rows"] = total
                            _write_sidecar(ds, meta)
                        except Exception:
                            pass
                    total_exact = True
                    _active_ops.pop(op_id, None)

        else:
            # ── JSON → CSV cache ────────────────────────────────────────────
            # Convert the JSON to a flat CSV on first access and store it in
            # ~/.notes/datasets/.cache/.  All subsequent requests read the CSV
            # with the same streaming fast-path used for native CSV files.
            # The cache is automatically rebuilt when the source file changes.
            try:
                csv_cache = _get_or_build_json_csv_cache(ds)
            except Exception as e:
                abort(500, description=f"Could not build CSV cache for JSON dataset: {e}")

            start = (page - 1) * per_page
            end   = start + per_page

            cached_total = _get_cached_row_count(csv_cache)

            with open(csv_cache, "r", encoding="utf-8", newline="") as f:
                reader  = csv.DictReader(f)
                columns = list(reader.fieldnames or [])

                if cached_total is not None:
                    matched = 0
                    for raw_row in reader:
                        row = [raw_row.get(c, "") for c in columns]
                        if start <= matched < end:
                            page_rows.append([_safe(v) for v in row])
                        matched += 1
                        if matched >= end:
                            break
                    total       = cached_total
                    total_exact = True
                else:
                    for raw_row in reader:
                        row = [raw_row.get(c, "") for c in columns]
                        if query and not any(
                            query in str(cell).lower() for cell in row
                        ):
                            continue
                        if start <= total < end:
                            page_rows.append([_safe(v) for v in row])
                        total += 1

                    if not query:
                        mtime = csv_cache.stat().st_mtime
                        _row_count_cache[str(csv_cache)] = (mtime, total)
                        try:
                            meta = read_dataset_sidecar(ds)
                            meta["rows"] = total
                            _write_sidecar(ds, meta)
                        except Exception:
                            pass
                    total_exact = True
            _active_ops.pop(op_id, None)

    except Exception as e:
        abort(500, description=f"Could not parse dataset: {e}")
    finally:
        _active_ops.pop(op_id, None)   # belt-and-suspenders

    pages = max(1, (total + per_page - 1) // per_page)
    page  = min(page, pages)

    return jsonify({
        "filename":    ds.name,
        "format":      suffix.lstrip(".").upper(),
        "columns":     columns,
        "rows":        page_rows,
        "query":       query,
        "total":       total,
        "total_exact": total_exact,
        "page":        page,
        "per_page":    per_page,
        "pages":       pages,
    })



# ---------------------------------------------------------------------------
# POST /api/datasets/<n>/rows  — append one or more rows
# ---------------------------------------------------------------------------

@app.route("/api/datasets/<int:dataset_id>/rows", methods=["POST"])
def add_rows(dataset_id):
    """
    Append rows to an existing dataset.

    JSON body:
        rows   list of objects (CSV/JSON) or list of lists
               For CSV: [{"col1": "v1", "col2": "v2"}, ...]
               For JSON: same structure is appended to the JSON array

    Returns updated row count.
    """
    import csv, json as pyjson

    datasets = _collect_datasets(_notes_root())
    if dataset_id < 1 or dataset_id > len(datasets):
        abort(404, description=f"Dataset {dataset_id} not found.")

    ds     = datasets[dataset_id - 1]
    suffix = ds.suffix.lower()
    data   = request.get_json(silent=True) or {}
    new_rows = data.get("rows", [])

    if not new_rows or not isinstance(new_rows, list):
        abort(400, description="'rows' must be a non-empty list.")

    try:
        if suffix == ".csv":
            # Read existing to get column order
            with open(ds, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                columns = list(reader.fieldnames or [])

            if not columns:
                abort(400, description="CSV has no header row — cannot append.")

            # Validate incoming rows have the right keys
            for i, row in enumerate(new_rows):
                if not isinstance(row, dict):
                    abort(400, description=f"Row {i} must be an object with keys matching the CSV columns.")

            # Append rows
            with open(ds, "a", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
                for row in new_rows:
                    writer.writerow({c: row.get(c, "") for c in columns})

        else:  # JSON
            with open(ds, "r", encoding="utf-8") as f:
                existing = pyjson.load(f)

            if not isinstance(existing, list):
                abort(400, description="JSON dataset is not an array — cannot append rows.")

            existing.extend(new_rows)

            with open(ds, "w", encoding="utf-8") as f:
                pyjson.dump(existing, f, indent=2, ensure_ascii=False)

    except Exception as e:
        abort(500, description=f"Could not append rows: {e}")

    # Update sidecar row count
    meta = read_dataset_sidecar(ds)
    try:
        meta["rows"] = int(meta.get("rows", 0)) + len(new_rows)
    except (ValueError, TypeError):
        meta["rows"] = len(new_rows)
    meta["modified"] = datetime.now().isoformat()
    _write_sidecar(ds, meta)

    # Reload allDatasets cache hint
    return jsonify({
        "message":    f"{len(new_rows)} row(s) added.",
        "rows_added": len(new_rows),
        "total_rows": meta["rows"],
    })


# ---------------------------------------------------------------------------
# POST /api/datasets/<n>/columns  — add one or more columns
# ---------------------------------------------------------------------------

@app.route("/api/datasets/<int:dataset_id>/columns", methods=["POST"])
def add_columns(dataset_id):
    """
    Add one or more new columns to an existing dataset.
    Existing rows get the specified default value for the new column.

    JSON body:
        columns   list of column definitions:
                  [{"name": "score", "default": "0"}, ...]

    Returns updated column list.
    """
    import csv, json as pyjson

    datasets = _collect_datasets(_notes_root())
    if dataset_id < 1 or dataset_id > len(datasets):
        abort(404, description=f"Dataset {dataset_id} not found.")

    ds     = datasets[dataset_id - 1]
    suffix = ds.suffix.lower()
    data   = request.get_json(silent=True) or {}
    new_cols = data.get("columns", [])

    if not new_cols or not isinstance(new_cols, list):
        abort(400, description="'columns' must be a non-empty list of {name, default} objects.")

    # Validate
    for i, col in enumerate(new_cols):
        if not isinstance(col, dict) or not col.get("name", "").strip():
            abort(400, description=f"Column {i} must be an object with a 'name' field.")

    try:
        if suffix == ".csv":
            # Read all rows
            with open(ds, "r", encoding="utf-8", newline="") as f:
                reader  = csv.DictReader(f)
                old_cols = list(reader.fieldnames or [])
                rows    = list(reader)

            # Merge — skip columns that already exist
            added = []
            for col in new_cols:
                name = col["name"].strip()
                if name not in old_cols:
                    old_cols.append(name)
                    added.append(col)

            if not added:
                return jsonify({"message": "All columns already exist.", "columns": old_cols})

            # Fill default values
            for row in rows:
                for col in added:
                    row[col["name"].strip()] = str(col.get("default", ""))

            # Rewrite file
            with open(ds, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=old_cols)
                writer.writeheader()
                writer.writerows(rows)

            final_cols = old_cols

        else:  # JSON
            with open(ds, "r", encoding="utf-8") as f:
                existing = pyjson.load(f)

            if not isinstance(existing, list):
                abort(400, description="JSON dataset is not an array — cannot add columns.")

            # Determine current columns from first row
            cur_cols = list(existing[0].keys()) if existing and isinstance(existing[0], dict) else []
            added = []
            for col in new_cols:
                name = col["name"].strip()
                if name not in cur_cols:
                    cur_cols.append(name)
                    added.append(col)

            if not added:
                return jsonify({"message": "All columns already exist.", "columns": cur_cols})

            default_map = {col["name"].strip(): col.get("default", "") for col in added}
            for row in existing:
                if isinstance(row, dict):
                    for name, default in default_map.items():
                        if name not in row:
                            row[name] = default

            with open(ds, "w", encoding="utf-8") as f:
                pyjson.dump(existing, f, indent=2, ensure_ascii=False)

            final_cols = cur_cols

    except Exception as e:
        abort(500, description=f"Could not add columns: {e}")

    # Update sidecar
    meta = read_dataset_sidecar(ds)
    meta["columns"]  = len(final_cols)
    meta["fields"]   = final_cols
    meta["modified"] = datetime.now().isoformat()
    _write_sidecar(ds, meta)

    return jsonify({
        "message":      f"{len(added)} column(s) added.",
        "cols_added":   [c["name"] for c in added],
        "total_columns": len(final_cols),
        "columns":      final_cols,
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
import uuid as _uuid

_last_ping           = _time.monotonic()
_active_ops          = {}    # op_id -> monotonic start time (uploads + large reads)
_cancelled_ids       = set() # upload IDs that the user cancelled
PING_INTERVAL        = 5     # seconds between browser pings
SHUTDOWN_TIMEOUT     = 15    # seconds of silence before shutdown
UPLOAD_STALE_TIMEOUT = 300   # seconds before an upload is considered dead (5 min)


@app.route("/ping")
def ping():
    """Heartbeat called by the UI every few seconds."""
    global _last_ping
    _last_ping = _time.monotonic()
    return jsonify({"ok": True})


@app.route("/api/upload/cancel/<upload_id>", methods=["DELETE"])
def cancel_upload(upload_id):
    """
    Signal a running upload to abort.
    The upload endpoint checks _cancelled_ids and stops early if its ID appears.
    """
    _cancelled_ids.add(upload_id)
    return jsonify({"message": "Cancel signal sent.", "upload_id": upload_id})


def _watchdog():
    """Background thread — exits the process when pings stop.

    Uses a shared _active_ops dict to track any long-running operation
    (uploads or large dataset reads). A dropped connection can never leave
    the watchdog stuck — entries older than UPLOAD_STALE_TIMEOUT are evicted.
    """
    _time.sleep(SHUTDOWN_TIMEOUT)
    while True:
        _time.sleep(2)
        now = _time.monotonic()

        # Evict ops that started too long ago (connection dropped / server hung)
        stale = [uid for uid, t in _active_ops.items()
                 if now - t > UPLOAD_STALE_TIMEOUT]
        for uid in stale:
            _active_ops.pop(uid, None)
            print(f"  [watchdog] evicted stale upload {uid[:8]}…")

        if _active_ops:
            # At least one long-running op is in progress — reset clock and wait
            global _last_ping
            _last_ping = now
            continue

        silence = now - _last_ping
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
    print(f"API Docs        →  http://localhost:{port}/docs")
    print(f"Notes directory →  {nd}")
    print(f"Notes found     →  {count}")
    if not nd.exists():
        print(f"\n  ⚠  Directory does not exist: {nd}")
        print(f"     Create it with:  mkdir -p {nd}")
    elif count == 0:
        print(f"\n  ⚠  No .md/.note/.txt files found in {nd}")

    print()
    print(f"Security")
    print(f"  Binding        →  127.0.0.1 (localhost only)")
    print(f"  API key        →  {_API_KEY[:8]}… (full key in {_KEY_FILE})")
    print(f"  Rate limit     →  {_RATE_MAX} requests / {_RATE_WINDOW}s")
    print(f"\n  To use the API from a script:")
    print(f"    curl -H \"X-API-Key: {_API_KEY}\" http://localhost:{port}/api/notes")
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

    app.run(host="127.0.0.1", port=port, debug=debug)