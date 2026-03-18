#!/usr/bin/env python3
"""
Future Proof Notes Manager - MindWriter v0.1
A personal notes manager using text files with YAML headers.

Note indexing is handled entirely in-memory at runtime: every time notes are
collected they are sorted alphabetically and assigned a stable integer index
for that session.  No external index file is required.
"""

import sys
import os
from pathlib import Path
import mindwriter_shell
import slugify


def setup():
    """Initialize the notes application."""
    custom_notes_dir = os.environ.get('NOTES_DIR')
    if custom_notes_dir:
        notes_dir = Path(custom_notes_dir)
    else:
        notes_dir = Path.home() / ".notes"

    if not notes_dir.exists():
        pass

    return notes_dir


# ---------------------------------------------------------------------------
# In-memory index helpers
# ---------------------------------------------------------------------------

def build_index(note_files):
    """
    Given a sorted list of note Path objects return two lookup dicts:
      id_to_file  : {1: Path(...), 2: Path(...), ...}
      file_to_id  : {Path(...): 1, Path(...): 2, ...}

    Indices are 1-based and assigned in the order the list is provided
    (caller is responsible for sorting consistently).
    """
    id_to_file = {}
    file_to_id = {}
    for i, path in enumerate(note_files, start=1):
        id_to_file[i] = path
        file_to_id[path] = i
    return id_to_file, file_to_id


def collect_note_files(notes_dir):
    """Return a consistently sorted list of all note Path objects."""
    notes_subdir = notes_dir / "notes"
    search_dirs = [notes_subdir] if notes_subdir.exists() else [notes_dir]
    note_files = []
    for search_dir in search_dirs:
        note_files.extend(search_dir.glob("*.md"))
        note_files.extend(search_dir.glob("*.note"))
        note_files.extend(search_dir.glob("*.txt"))
    return sorted(note_files)


def resolve_to_path(notes_dir, identifier):
    """
    Resolve *identifier* (an integer index OR a filename string) to a Path.
    Returns the Path if found, otherwise None.

    Because the index is built from the live directory listing, it is always
    consistent with what is actually on disk — no stale index file to worry
    about.
    """
    note_files = collect_note_files(notes_dir)
    id_to_file, _ = build_index(note_files)

    # Try numeric index first
    try:
        idx = int(identifier)
        return id_to_file.get(idx)
    except ValueError:
        pass

    # Fall back to filename search
    notes_subdir = notes_dir / "notes"
    search_dirs = [notes_subdir] if notes_subdir.exists() else [notes_dir]
    for search_dir in search_dirs:
        candidate = search_dir / identifier
        if candidate.exists():
            return candidate
    return None


# ---------------------------------------------------------------------------
# YAML helper
# ---------------------------------------------------------------------------

def parse_yaml_header(file_path):
    """
    Parse YAML front matter from a note file.
    Returns a dictionary with metadata.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        if not lines or lines[0].strip() != '---':
            return {'title': file_path.name, 'file': file_path.name}

        yaml_end = -1
        for i in range(1, len(lines)):
            if lines[i].strip() == '---':
                yaml_end = i
                break

        if yaml_end == -1:
            return {'title': file_path.name, 'file': file_path.name}

        # Fields that are always normalised to lowercase
        LOWERCASE_FIELDS = {'title', 'author', 'tags'}

        metadata = {'file': file_path.name}
        for line in lines[1:yaml_end]:
            line = line.strip()
            if ':' in line:
                key, value = line.split(':', 1)
                key   = key.strip()
                value = value.strip()
                if key in LOWERCASE_FIELDS:
                    value = value.lower()
                metadata[key] = value

        return metadata

    except Exception as e:
        return {'title': file_path.name, 'file': file_path.name, 'error': str(e)}


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------

def read_note(notes_dir, identifier):
    """Read and display a note by index number or filename."""
    note_file = resolve_to_path(notes_dir, identifier)
    if not note_file:
        print(f"Error: Note '{identifier}' not found.")
        return False

    try:
        with open(note_file, 'r', encoding='utf-8') as f:
            content = f.read()
        print(f"\nContent of {note_file.name}:")
        print("=" * 60)
        print(content)
        input("Press Enter to return to list...")
        return True
    except Exception as e:
        print(f"Error reading note: {e}")
        return False


def create_note(notes_dir):
    """Create a new note by opening it in the default editor."""
    notes_subdir = notes_dir / "notes"
    if not notes_subdir.exists():
        try:
            notes_subdir.mkdir(parents=True)
            print(f"Created notes directory: {notes_subdir}")
        except Exception as e:
            print(f"Error creating notes directory: {e}")
            return False

    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    temp_file = notes_subdir / f"note_{timestamp}.md"

    template_content = f"""---
title: 
created: {datetime.now().isoformat()}
modified: {datetime.now().isoformat()}
tags: []
author: 
priority: 
---

# New Note

Write your note content here.
"""

    try:
        with open(temp_file, 'w', encoding='utf-8') as f:
            f.write(template_content)
    except Exception as e:
        print(f"Error creating note file: {e}")
        return False

    editor = os.environ.get('EDITOR', 'vi')
    os.system(f"{editor} {temp_file}")

    try:
        metadata = parse_yaml_header(temp_file)
        title = metadata.get('title', '').strip()
        if not title:
            print("Warning: No title provided. Keeping temporary filename.")
            final_file = temp_file
        else:
            filename = slugify.slugify(title) + ".md"
            final_file = notes_subdir / filename
            counter = 1
            while final_file.exists() and final_file != temp_file:
                base, ext = filename.rsplit('.', 1)
                filename = f"{base}_{counter}.{ext}"
                final_file = notes_subdir / filename
                counter += 1
            if final_file != temp_file:
                temp_file.rename(final_file)

        # Show the index the new note was assigned
        note_files = collect_note_files(notes_dir)
        _, file_to_id = build_index(note_files)
        assigned_id = file_to_id.get(final_file, "?")
        print(f"Note saved: {final_file.name}  [index: {assigned_id}]")
        return True
    except Exception as e:
        print(f"Error processing note: {e}")
        return False


def update_modified_timestamp(file_path):
    """
    Rewrite the 'modified' field in the YAML front matter to the current
    datetime.  If no 'modified' key exists in the header it is inserted on
    the line after 'created' (or just before the closing ---).
    If the file has no YAML front matter at all, the file is left unchanged
    and a warning is printed.
    """
    from datetime import datetime

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        print(f"Warning: could not read '{file_path.name}' to update timestamp: {e}")
        return

    # Must start with a YAML block
    if not lines or lines[0].strip() != '---':
        print(f"Warning: '{file_path.name}' has no YAML front matter — 'modified' not updated.")
        return

    # Locate closing ---
    yaml_end = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == '---':
            yaml_end = i
            break

    if yaml_end == -1:
        print(f"Warning: '{file_path.name}' YAML block is not closed — 'modified' not updated.")
        return

    now_iso = datetime.now().isoformat()
    new_modified_line = f"modified: {now_iso}\n"
    modified_found = False

    # Try to update an existing 'modified:' line inside the header
    for i in range(1, yaml_end):
        key = lines[i].split(':', 1)[0].strip() if ':' in lines[i] else ''
        if key == 'modified':
            lines[i] = new_modified_line
            modified_found = True
            break

    # If no 'modified' key existed, insert one before the closing ---
    if not modified_found:
        lines.insert(yaml_end, new_modified_line)

    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)
    except Exception as e:
        print(f"Warning: could not write updated timestamp to '{file_path.name}': {e}")


def edit_note(notes_dir, identifier):
    """Edit a note by index number or filename, then update its modified timestamp."""
    note_file = resolve_to_path(notes_dir, identifier)
    if not note_file:
        print(f"Error: Note '{identifier}' not found.")
        return False

    editor = os.environ.get('EDITOR', 'vi')
    os.system(f"{editor} {note_file}")

    # Update the modified timestamp in the YAML header after the editor closes
    update_modified_timestamp(note_file)
    print(f"Note edited: {note_file.name}")
    return True


def delete_note(notes_dir, identifier):
    """Delete a note (by index or filename) after confirmation."""
    note_file = resolve_to_path(notes_dir, identifier)
    if not note_file:
        print(f"Error: Note '{identifier}' not found.")
        return False

    confirm = input(f"Are you sure you want to delete '{note_file.name}'? (y/N): ").strip().lower()
    if confirm in ('y', 'yes'):
        try:
            note_file.unlink()
            print(f"Note deleted: {note_file.name}")
            return True
        except Exception as e:
            print(f"Error deleting note: {e}")
            return False
    else:
        print("Deletion cancelled.")
        return True


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search_notes(notes_dir, keywords):
    """
    Search all notes for one or more keywords (case-insensitive).

    Searches three areas independently for each keyword:
      - YAML header fields  (title, tags, author, priority, …)
      - Body content        (everything after the closing ---)
      - Filename            (the note's filename, minus extension)

    A note matches if *every* keyword appears in at least one of those areas.
    Results are printed with the global index, which fields matched, and up to
    two lines of context per keyword hit in the body.  The user can then open
    any result by typing its index number.
    """
    if not notes_dir.exists():
        print(f"Error: Notes directory does not exist: {notes_dir}", file=sys.stderr)
        return False

    if not keywords:
        print("Error: provide at least one keyword to search for.", file=sys.stderr)
        return False

    note_files = collect_note_files(notes_dir)
    if not note_files:
        print(f"No notes found in {notes_dir}")
        return True

    id_to_file, _ = build_index(note_files)
    kw_lower = [k.lower() for k in keywords]

    # ── helpers ──────────────────────────────────────────────────────────────

    def split_header_body(file_path):
        """Return (header_text, body_lines) for a note file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except Exception:
            return '', []

        if not lines or lines[0].strip() != '---':
            return '', lines

        yaml_end = -1
        for i in range(1, len(lines)):
            if lines[i].strip() == '---':
                yaml_end = i
                break

        if yaml_end == -1:
            return ''.join(lines), []

        header_text = ''.join(lines[1:yaml_end])
        body_lines  = lines[yaml_end + 1:]
        return header_text, body_lines

    def context_lines(body_lines, keyword, context=1):
        """Return brief context snippets around each line containing keyword."""
        snippets = []
        for i, line in enumerate(body_lines):
            if keyword in line.lower():
                start = max(0, i - context)
                end   = min(len(body_lines), i + context + 1)
                chunk = ''.join(body_lines[start:end]).strip()
                # Truncate very long lines for readability
                if len(chunk) > 120:
                    chunk = chunk[:117] + '…'
                snippets.append(chunk)
                if len(snippets) >= 2:   # show at most 2 snippets per keyword
                    break
        return snippets

    # ── scan every note ───────────────────────────────────────────────────────

    results = []   # list of (note_id, note_file, match_report)

    for note_id, note_file in id_to_file.items():
        metadata    = parse_yaml_header(note_file)
        header_text, body_lines = split_header_body(note_file)
        filename_stem = note_file.stem.lower()

        match_report = {}   # keyword -> {'locations': [...], 'snippets': [...]}

        for kw in kw_lower:
            locations = []
            snippets  = []

            # Check filename
            if kw in filename_stem:
                locations.append('filename')

            # Check every header field value
            for field, value in metadata.items():
                if field == 'file':
                    continue
                if kw in str(value).lower():
                    locations.append(f'header:{field}')

            # Check body
            body_snippets = context_lines(body_lines, kw)
            if body_snippets:
                locations.append('body')
                snippets = body_snippets

            if locations:
                match_report[kw] = {'locations': locations, 'snippets': snippets}

        # Note matches if ANY keyword was found (OR logic)
        if match_report:
            results.append((note_id, note_file, match_report))

    # ── display results ───────────────────────────────────────────────────────

    query_display = ' + '.join(f'"{k}"' for k in keywords)

    if not results:
        print(f"\nNo notes found matching {query_display}.")
        return True

    print(f"\nSearch results for {query_display}  —  {len(results)} note(s) found:")
    print("=" * 60)

    for note_id, note_file, match_report in results:
        metadata = parse_yaml_header(note_file)
        title    = metadata.get('title', note_file.name) or note_file.name
        print(f"[{note_id}] {note_file.name}")
        print(f"   Title: {title}")

        for kw, info in match_report.items():
            loc_str = ', '.join(info['locations'])
            print(f"   Keyword '{kw}' found in: {loc_str}")
            for snippet in info['snippets']:
                # Indent each snippet line for readability
                for sline in snippet.splitlines():
                    print(f"      │ {sline}")
        print()

    # ── interactive open ──────────────────────────────────────────────────────

    while True:
        prompt = input("Enter an index to open a note, or 'q' to quit: ").strip().lower()
        if prompt == 'q':
            break
        try:
            chosen_id = int(prompt)
            if any(r[0] == chosen_id for r in results):
                read_note(notes_dir, str(chosen_id))
            else:
                print(f"Index {chosen_id} is not in the result list above.")
        except ValueError:
            print("Invalid input. Enter a result index number or 'q'.")

    return True


# ---------------------------------------------------------------------------
# List / browse
# ---------------------------------------------------------------------------

def list_notes(notes_dir):
    """Interactively list and browse notes with pagination."""
    if not notes_dir.exists():
        print(f"Error: Notes directory does not exist: {notes_dir}", file=sys.stderr)
        print("Create it with: mkdir -p ~/.notes/notes", file=sys.stderr)
        return False

    note_files = collect_note_files(notes_dir)

    if not note_files:
        print(f"No notes found in {notes_dir}")
        return True

    # Build the session index once so display and selection are consistent
    id_to_file, _ = build_index(note_files)

    total_notes = len(note_files)
    items_per_page = 10
    total_pages = (total_notes + items_per_page - 1) // items_per_page
    current_page = 1

    while True:
        start_index = (current_page - 1) * items_per_page
        end_index = start_index + items_per_page
        # Slice using the ordered id list so page numbers match index numbers
        page_ids = list(id_to_file.keys())[start_index:end_index]

        print(f"\nNotes in {notes_dir} (Page {current_page} of {total_pages}):")
        print("=" * 60)
        for note_id in page_ids:
            note_file = id_to_file[note_id]
            metadata = parse_yaml_header(note_file)
            title    = metadata.get('title', note_file.name)
            created  = metadata.get('created', 'N/A')
            modified = metadata.get('modified', 'N/A')
            tags     = metadata.get('tags', '')
            author   = metadata.get('author', '')
            priority = metadata.get('priority', '')

            print(f"[{note_id}] {note_file.name}")
            print(f"   Title: {title}")
            if created != 'N/A':
                print(f"   Created: {created}")
            if modified != 'N/A':
                print(f"   Modified: {modified}")
            if tags:
                print(f"   Tags: {tags}")
            if author:
                print(f"   Author: {author}")
            if priority:
                print(f"   Priority: {priority}")
            print()

        print(f"Page {current_page}/{total_pages} — {len(page_ids)} shown, {total_notes} total")
        print("Enter an index number to read that note, 'n' next, 'p' previous, 'q' quit.")
        prompt = input("> ").strip().lower()

        if prompt == 'q':
            break
        elif prompt == 'n':
            if current_page < total_pages:
                current_page += 1
            else:
                print("Already on last page.")
        elif prompt == 'p':
            if current_page > 1:
                current_page -= 1
            else:
                print("Already on first page.")
        else:
            try:
                chosen_id = int(prompt)
                if chosen_id in id_to_file:
                    read_note(notes_dir, str(chosen_id))
                else:
                    print(f"No note with index {chosen_id}. Valid range: 1–{total_notes}")
            except ValueError:
                print("Invalid input. Enter a number, 'n', 'p', or 'q'.")

    return True


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def show_stats(notes_dir):
    """
    Scan all notes and display a rich summary covering:
      - Total note count and cumulative word / line counts
      - Breakdown by author
      - Breakdown by priority
      - Breakdown by tag  (supports comma-separated and bracket list formats)
      - Notes with no title / no tags / no author
      - The 5 most-recently modified notes
      - The 5 largest notes by word count
    """
    from collections import Counter
    from datetime import datetime

    if not notes_dir.exists():
        print(f"Error: Notes directory does not exist: {notes_dir}", file=sys.stderr)
        return False

    note_files = collect_note_files(notes_dir)
    if not note_files:
        print(f"No notes found in {notes_dir}")
        return True

    # ── accumulators ─────────────────────────────────────────────────────────
    total_words      = 0
    total_lines      = 0
    author_counter   = Counter()
    priority_counter = Counter()
    tag_counter      = Counter()
    no_title         = []
    no_tags          = []
    no_author        = []
    word_counts      = {}   # path -> int
    mod_dates        = {}   # path -> datetime | None

    def parse_tags(raw):
        """Normalise tag strings like '[work, python]' or 'work, python'."""
        raw = raw.strip().strip('[]')
        if not raw:
            return []
        return [t.strip().lower() for t in raw.split(',') if t.strip()]

    def count_words(file_path, yaml_end):
        """Count words in the body section only (below the YAML block)."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            body = lines[yaml_end + 1:] if yaml_end >= 0 else lines
            text = ' '.join(body)
            return len(text.split()), len(body)
        except Exception:
            return 0, 0

    def find_yaml_end(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            if not lines or lines[0].strip() != '---':
                return -1
            for i in range(1, len(lines)):
                if lines[i].strip() == '---':
                    return i
        except Exception:
            pass
        return -1

    # ── scan ─────────────────────────────────────────────────────────────────
    for note_file in note_files:
        meta     = parse_yaml_header(note_file)
        yaml_end = find_yaml_end(note_file)
        words, lines = count_words(note_file, yaml_end)

        total_words += words
        total_lines += lines
        word_counts[note_file] = words

        # Author
        author = meta.get('author', '').strip().lower()
        if author:
            author_counter[author] += 1
        else:
            no_author.append(note_file.name)

        # Priority
        priority = meta.get('priority', '').strip().lower()
        if priority:
            priority_counter[priority] += 1

        # Tags
        raw_tags = meta.get('tags', '').strip()
        tags = parse_tags(raw_tags)   # parse_tags already lowercases each tag
        if tags:
            for tag in tags:
                tag_counter[tag] += 1
        else:
            no_tags.append(note_file.name)

        # Title
        title = meta.get('title', '').strip().lower()
        if not title:
            no_title.append(note_file.name)

        # Modified date (for recency ranking)
        raw_mod = meta.get('modified', '').strip()
        parsed_mod = None
        if raw_mod:
            for fmt in ('%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
                try:
                    parsed_mod = datetime.strptime(raw_mod[:26], fmt)
                    break
                except ValueError:
                    continue
        mod_dates[note_file] = parsed_mod

    # ── helpers ───────────────────────────────────────────────────────────────
    def bar(count, total, width=20):
        """Simple ASCII progress bar."""
        filled = int(width * count / total) if total else 0
        return f"[{'█' * filled}{'░' * (width - filled)}]"

    def ranked_table(counter, total, label):
        """Print a sorted frequency table with bars."""
        if not counter:
            print(f"  (none recorded)")
            return
        for name, count in counter.most_common():
            pct = count / total * 100
            print(f"  {bar(count, total)} {count:>4}  ({pct:5.1f}%)  {name}")

    # ── display ───────────────────────────────────────────────────────────────
    total = len(note_files)
    W     = 60

    print()
    print("=" * W)
    print(" NOTE STATISTICS".center(W))
    print("=" * W)

    # Overview
    print(f"\n{'── Overview ':─<{W}}")
    print(f"  Total notes   : {total}")
    print(f"  Total words   : {total_words:,}")
    print(f"  Total lines   : {total_lines:,}")
    if total:
        print(f"  Avg words/note: {total_words // total:,}")

    # Authors
    print(f"\n{'── By Author ':─<{W}}")
    ranked_table(author_counter, total, 'author')
    if no_author:
        print(f"  No author set : {len(no_author)} note(s)")

    # Priorities — sort numerically if all values are numbers, else alphabetically
    print(f"\n{'── By Priority ':─<{W}}")
    if priority_counter:
        try:
            sorted_priorities = sorted(priority_counter.items(), key=lambda x: int(x[0]))
        except ValueError:
            sorted_priorities = sorted(priority_counter.items(), key=lambda x: x[0].lower())
        for name, count in sorted_priorities:
            pct = count / total * 100
            print(f"  {bar(count, total)} {count:>4}  ({pct:5.1f}%)  {name}")
    else:
        print("  (none recorded)")
    unset_pri = total - sum(priority_counter.values())
    if unset_pri:
        print(f"  No priority   : {unset_pri} note(s)")

    # Tags
    print(f"\n{'── By Tag ':─<{W}}")
    ranked_table(tag_counter, total, 'tag')
    if no_tags:
        print(f"  No tags set   : {len(no_tags)} note(s)")

    # Completeness
    print(f"\n{'── Completeness ':─<{W}}")
    def pct(n): return f"{n}/{total}  ({n/total*100:.0f}%)" if total else "0"
    print(f"  Have title    : {pct(total - len(no_title))}")
    print(f"  Have author   : {pct(total - len(no_author))}")
    print(f"  Have tags     : {pct(total - len(no_tags))}")

    # Recently modified
    print(f"\n{'── 5 Most Recently Modified ':─<{W}}")
    dated   = [(f, d) for f, d in mod_dates.items() if d]
    undated = [f for f, d in mod_dates.items() if not d]
    dated.sort(key=lambda x: x[1], reverse=True)
    for note_file, dt in dated[:5]:
        print(f"  {dt.strftime('%Y-%m-%d %H:%M')}  {note_file.name}")
    if undated and len(dated) < 5:
        for note_file in undated[:5 - len(dated)]:
            print(f"  (no date)            {note_file.name}")

    # Largest notes
    print(f"\n{'── 5 Largest Notes (by word count) ':─<{W}}")
    top_words = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    for note_file, wc in top_words:
        print(f"  {wc:>6} words  {note_file.name}")

    print()
    print("=" * W)
    return True


# ---------------------------------------------------------------------------
# Dataset import
# ---------------------------------------------------------------------------

DATASETS_SUBDIR = "datasets"


def datasets_dir(notes_dir):
    """Return the datasets subdirectory path."""
    return notes_dir / DATASETS_SUBDIR


def _ensure_datasets_dir(notes_dir):
    d = datasets_dir(notes_dir)
    if not d.exists():
        try:
            d.mkdir(parents=True)
        except Exception as e:
            print(f"Error creating datasets directory: {e}")
            return None
    return d


def _write_sidecar(data_file, meta):
    """
    Write a YAML sidecar file next to *data_file*.
    Sidecar name = data_file.stem + ".dataset.yaml"
    e.g.  sales.csv  ->  sales.csv.yaml
    """
    sidecar_path = data_file.parent / (data_file.stem + ".dataset.yaml")
    lines = ["---\n"]
    for key, value in meta.items():
        if isinstance(value, list):
            items = ", ".join(str(v) for v in value)
            lines.append(f"{key}: [{items}]\n")
        else:
            lines.append(f"{key}: {value}\n")
    lines.append("---\n")
    try:
        with open(sidecar_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        return sidecar_path
    except Exception as e:
        print(f"Warning: could not write sidecar: {e}")
        return None


def read_dataset_sidecar(data_file):
    """Read the YAML sidecar for *data_file*. Returns a dict (empty if missing)."""
    sidecar_path = data_file.parent / (data_file.stem + ".dataset.yaml")
    if not sidecar_path.exists():
        return {}
    meta = {}
    try:
        with open(sidecar_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if not lines or lines[0].strip() != "---":
            return {}
        yaml_end = -1
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                yaml_end = i
                break
        end = yaml_end if yaml_end != -1 else len(lines)
        for line in lines[1:end]:
            line = line.strip()
            if ":" in line:
                key, value = line.split(":", 1)
                meta[key.strip()] = value.strip()
    except Exception:
        pass
    return meta


def _collect_datasets(notes_dir):
    """Return sorted list of dataset Paths (csv + json) in the datasets dir."""
    d = datasets_dir(notes_dir)
    if not d.exists():
        return []
    return sorted(list(d.glob("*.csv")) + list(d.glob("*.json")))


def import_dataset(notes_dir, source_path_str):
    """
    Import a CSV or JSON file into the datasets directory, collect metadata
    interactively, then write a YAML sidecar alongside the copied file.
    The original file is copied — never moved or modified.
    """
    import shutil, csv, json
    from datetime import datetime

    source = Path(source_path_str)
    if not source.exists():
        print(f"Error: File not found: {source}")
        return False

    suffix = source.suffix.lower()
    if suffix not in (".csv", ".json"):
        print(f"Error: Only .csv and .json files are supported (got \'{suffix}\').")
        return False

    ddir = _ensure_datasets_dir(notes_dir)
    if ddir is None:
        return False

    # -- introspect the source file -------------------------------------------
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
                data = json.load(f)
            if isinstance(data, list):
                row_count = len(data)
                if data and isinstance(data[0], dict):
                    columns = list(data[0].keys())
            elif isinstance(data, dict):
                row_count, columns = 1, list(data.keys())
    except Exception as e:
        parse_error = str(e)

    print(f"\nImporting: {source.name}")
    print("=" * 60)
    if parse_error:
        print(f"  Warning: could not fully parse file -- {parse_error}")
    else:
        print(f"  Rows   : {row_count:,}")
        print(f"  Columns: {len(columns)}")
        if columns:
            col_preview = ", ".join(columns[:10]) + (" ..." if len(columns) > 10 else "")
            print(f"  Fields : {col_preview}")
    print()

    # -- collect metadata interactively ---------------------------------------
    def prompt(label, default=""):
        suffix_hint = f" [{default}]" if default else ""
        val = input(f"  {label}{suffix_hint}: ").strip()
        return val if val else default

    print("Enter metadata (press Enter to skip a field):")
    title       = prompt("Title",       source.stem.replace("_", " ").replace("-", " "))
    description = prompt("Description", "")
    author      = prompt("Author",      "").lower()
    tags_raw    = prompt("Tags (comma-separated)", "").lower()
    tags        = [t.strip() for t in tags_raw.split(",") if t.strip()]
    source_url  = prompt("Source URL",  "")
    license_    = prompt("License",     "")
    priority    = prompt("Priority",    "")

    now = datetime.now().isoformat()
    meta = {
        "title":             title.lower(),
        "description":       description,
        "author":            author,
        "tags":              tags,
        "source_url":        source_url,
        "license":           license_,
        "priority":          priority,
        "format":            suffix.lstrip(".").upper(),
        "rows":              row_count,
        "columns":           len(columns),
        "fields":            columns,
        "imported":          now,
        "modified":          now,
        "original_filename": source.name,
    }
    meta = {k: v for k, v in meta.items() if v != "" and v != [] and v != 0}

    # -- copy file to datasets dir --------------------------------------------
    dest = ddir / source.name
    counter = 1
    while dest.exists():
        dest = ddir / f"{source.stem}_{counter}{source.suffix}"
        counter += 1

    try:
        shutil.copy2(source, dest)
    except Exception as e:
        print(f"Error copying file: {e}")
        return False

    sidecar = _write_sidecar(dest, meta)
    print()
    print(f"Dataset saved  : {dest.name}")
    if sidecar:
        print(f"Sidecar written: {sidecar.name}")
    return True


def list_datasets(notes_dir):
    """List all imported datasets with their sidecar metadata."""
    if not notes_dir.exists():
        print(f"Error: Notes directory does not exist: {notes_dir}", file=sys.stderr)
        return False

    datasets = _collect_datasets(notes_dir)
    if not datasets:
        print("No datasets found. Use \'dataset-import <file>\' to add one.")
        return True

    print(f"\nDatasets ({len(datasets)} total):")
    print("=" * 60)
    for i, ds in enumerate(datasets, start=1):
        meta        = read_dataset_sidecar(ds)
        title       = meta.get("title", ds.stem)
        description = meta.get("description", "")
        author      = meta.get("author", "")
        tags        = meta.get("tags", "")
        fmt         = meta.get("format", ds.suffix.lstrip(".").upper())
        rows        = meta.get("rows", "?")
        cols        = meta.get("columns", "?")
        imported    = meta.get("imported", "")[:10]
        modified    = meta.get("modified", "")[:10]

        print(f"[{i}] {ds.name}  ({fmt})")
        print(f"   Title      : {title}")
        if description:
            print(f"   Description: {description}")
        if author:
            print(f"   Author     : {author}")
        if tags:
            print(f"   Tags       : {tags}")
        print(f"   Rows/Cols  : {rows} rows x {cols} columns")
        if imported:
            print(f"   Imported   : {imported}")
        if modified and modified != imported:
            print(f"   Modified   : {modified}")
        print()

    return True


# ---------------------------------------------------------------------------
# Help / finish
# ---------------------------------------------------------------------------

def show_help():
    help_text = """
Future Proof Notes Manager v0.1

Usage: python3 mindwriter.py [command]

Available commands:
  --help                     Display this help information
  create                     Create a new note (opens in default editor)
  list                       Interactively list and browse notes (paginated)
  read  <index|note-id>      Display a note by index number or filename
  edit  <index|note-id>      Edit a note by index number or filename
  delete <index|note-id>     Delete a note by index number or filename
  search <kw> [kw2 ...]      Search notes by keyword(s) — matches title, tags, body, filename
                             A note appears if ANY keyword matches (OR logic)
  stats                      Display statistics about your notes
  dataset-import <file>      Import a .csv or .json file and write a YAML sidecar
  dataset-list               List all imported datasets with their metadata
  shell                      Run interactive terminal shell

Index numbers are assigned alphabetically at runtime — use 'list' to see them.
They are stable within a session as long as no notes are added or removed.

Notes directory: {}
    """.format(Path.home() / ".notes")
    print(help_text.strip())


def finish(exit_code=0):
    sys.exit(exit_code)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    notes_dir = setup()

    if len(sys.argv) < 2:
        print("Error: No command provided.", file=sys.stderr)
        print("Usage: python3 mindwriter.py [command]", file=sys.stderr)
        print("Try 'python3 mindwriter.py help' for more information.", file=sys.stderr)
        finish(1)

    command = sys.argv[1].lower()

    if command in ("help", "--help"):
        show_help()
        finish(0)
    elif command == "list":
        finish(0 if list_notes(notes_dir) else 1)
    elif command == "read":
        if len(sys.argv) < 3:
            print("Error: read requires a note index or filename.", file=sys.stderr)
            finish(1)
        finish(0 if read_note(notes_dir, sys.argv[2]) else 1)
    elif command == "create":
        finish(0 if create_note(notes_dir) else 1)
    elif command == "edit":
        if len(sys.argv) < 3:
            print("Error: edit requires a note index or filename.", file=sys.stderr)
            finish(1)
        finish(0 if edit_note(notes_dir, sys.argv[2]) else 1)
    elif command == "delete":
        if len(sys.argv) < 3:
            print("Error: delete requires a note index or filename.", file=sys.stderr)
            finish(1)
        finish(0 if delete_note(notes_dir, sys.argv[2]) else 1)
    elif command == "stats":
        finish(0 if show_stats(notes_dir) else 1)
    elif command == "search":
        if len(sys.argv) < 3:
            print("Error: search requires at least one keyword.", file=sys.stderr)
            print("Usage: mindwriter.py search <keyword> [keyword2 ...]", file=sys.stderr)
            finish(1)
        keywords = sys.argv[2:]
        finish(0 if search_notes(notes_dir, keywords) else 1)
    elif command == "dataset-import":
        if len(sys.argv) < 3:
            print("Error: dataset-import requires a file path.", file=sys.stderr)
            print("Usage: mindwriter.py dataset-import <file.csv|file.json>", file=sys.stderr)
            finish(1)
        finish(0 if import_dataset(notes_dir, sys.argv[2]) else 1)
    elif command == "dataset-list":
        finish(0 if list_datasets(notes_dir) else 1)
    elif command == "shell":
        mindwriter_shell.main()
    else:
        print(f"Error: Unknown command '{command}'", file=sys.stderr)
        print("Try 'mindwriter.py help' for more information.", file=sys.stderr)
        finish(1)


if __name__ == "__main__":
    main()