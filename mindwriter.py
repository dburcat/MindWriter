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

        metadata = {'file': file_path.name}
        for line in lines[1:yaml_end]:
            line = line.strip()
            if ':' in line:
                key, value = line.split(':', 1)
                metadata[key.strip()] = value.strip()

        return metadata

    except Exception as e:
        return {'title': file_path.name, 'file': file_path.name, 'error': str(e)}


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
    """Edit a note by index number or filename."""
    note_file = resolve_to_path(notes_dir, identifier)
    if not note_file:
        print(f"Error: Note '{identifier}' not found.")
        return False

    editor = os.environ.get('EDITOR', 'vi')
    os.system(f"{editor} {note_file}")
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
  search "query"             Search notes for text (title, tags, content)
  stats                      Display statistics about your notes
  shell                      Run interactive terminal shell

Index numbers are assigned alphabetically at runtime — use 'list' to see them.
They are stable within a session as long as no notes are added or removed.

Notes directory: {}
    """.format(Path.home() / ".notes")
    print(help_text.strip())


def finish(exit_code=0):
    sys.exit(exit_code)


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
    elif command == "shell":
        mindwriter_shell.main()
    else:
        print(f"Error: Unknown command '{command}'", file=sys.stderr)
        print("Try 'mindwriter.py help' for more information.", file=sys.stderr)
        finish(1)


if __name__ == "__main__":
    main()