#!/usr/bin/env python3
"""
Future Proof Notes Manager - MindWriter_v0.1
A personal notes manager using text files with YAML headers.
"""

import sys
import os
from pathlib import Path


def setup():
    """Initialize the notes application."""
    # Define the notes directory in HOME, or use custom path for testing
    custom_notes_dir = os.environ.get('NOTES_DIR')
    if custom_notes_dir:
        notes_dir = Path(custom_notes_dir)
    else:
        notes_dir = Path.home() / ".notes"

    # Check if notes directory exists
    if not notes_dir.exists():
        # For CLI version, we don't automatically create it
        pass

    return notes_dir


def parse_yaml_header(file_path):
    """
    Parse YAML front matter from a note file.
    Returns a dictionary with metadata and the content.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # Check if file starts with YAML front matter
        if not lines or lines[0].strip() != '---':
            return {'title': file_path.name, 'file': file_path.name}

        # Find the closing ---
        yaml_end = -1
        for i in range(1, len(lines)):
            if lines[i].strip() == '---':
                yaml_end = i
                break

        if yaml_end == -1:
            return {'title': file_path.name, 'file': file_path.name}

        # Parse YAML lines (simple parsing for basic key: value pairs)
        metadata = {'file': file_path.name}
        for line in lines[1:yaml_end]:
            line = line.strip()
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip()
                metadata[key] = value

        return metadata

    except Exception as e:
        return {'title': file_path.name, 'file': file_path.name, 'error': str(e)}


def read_note(notes_dir, note_id):
    """Read and display the content of a specific note."""
    # Find the note file
    notes_subdir = notes_dir / "notes"
    search_dirs = [notes_subdir] if notes_subdir.exists() else [notes_dir]

    note_file = None
    for search_dir in search_dirs:
        candidate = search_dir / note_id
        if candidate.exists():
            note_file = candidate
            break

    if not note_file:
        print(f"Error: Note '{note_id}' not found.")
        return False

    # Read and display the note
    try:
        with open(note_file, 'r', encoding='utf-8') as f:
            content = f.read()
        print(f"\nContent of {note_id}:")
        print("=" * 60)
        print(content)
        input("Press Enter to return to list...")
        return True
    except Exception as e:
        print(f"Error reading note: {e}")
        return False


def list_notes(notes_dir):
    """Interactively list and browse notes with pagination."""
    # Check if notes directory exists
    if not notes_dir.exists():
        print(f"Error: Notes directory does not exist: {notes_dir}", file=sys.stderr)
        print("Create it with: mkdir -p ~/.notes/notes", file=sys.stderr)
        print("Then copy test notes: cp test-notes/*.md ~/.notes/notes/", file=sys.stderr)
        return False

    # Look for notes in the notes directory (or directly in .notes)
    notes_subdir = notes_dir / "notes"
    search_dirs = [notes_subdir] if notes_subdir.exists() else [notes_dir]

    # Find all note files (*.md, *.note, *.txt)
    note_files = []
    for search_dir in search_dirs:
        note_files.extend(search_dir.glob("*.md"))
        note_files.extend(search_dir.glob("*.note"))
        note_files.extend(search_dir.glob("*.txt"))

    if not note_files:
        print(f"No notes found in {notes_dir}")
        print("Copy test notes with: cp test-notes/*.md ~/.notes/", file=sys.stderr)
        return True

    note_files = sorted(note_files)
    total_notes = len(note_files)
    items_per_page = 10
    total_pages = (total_notes + items_per_page - 1) // items_per_page
    current_page = 1

    while True:
        # Display current page
        start_index = (current_page - 1) * items_per_page
        end_index = start_index + items_per_page
        page_notes = note_files[start_index:end_index]

        print(f"\nNotes in {notes_dir} (Page {current_page} of {total_pages}):")
        print("=" * 60)
        for i, note_file in enumerate(page_notes, start=1):
            metadata = parse_yaml_header(note_file)
            title = metadata.get('title', note_file.name)
            created = metadata.get('created', 'N/A')
            modified = metadata.get('modified', 'N/A')
            tags = metadata.get('tags', '')
            author = metadata.get('author', 'N/A')

            print(f"{i}. {note_file.name}")
            print(f"   Title: {title}")
            if created != 'N/A':
                print(f"   Created: {created}")
            if modified != 'N/A':
                print(f"   Modified: {modified}")
            if tags:
                print(f"   Tags: {tags}")
            if author:
                print(f"   Author: {author}")
            print()

        print(f"Page {current_page}/{total_pages} - {len(page_notes)} notes shown.")

        # Prompt for user input
        prompt = input("Enter number to read note, 'n' for next page, 'p' for previous, 'q' to quit: ").strip().lower()

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
                num = int(prompt)
                if 1 <= num <= len(page_notes):
                    selected_file = page_notes[num - 1]
                    read_note(notes_dir, selected_file.name)
                else:
                    print("Invalid number. Please enter a number between 1 and", len(page_notes))
            except ValueError:
                print("Invalid input. Please enter a number, 'n', 'p', or 'q'.")

    return True


def show_help():
    """Display help information."""
    help_text = """
Future Proof Notes Manager v0.1

Usage: python3 mindwriter.py [command]

Available commands:
--help                     # Display help information
create                     # Create a new note (opens in default editor)
list                       # Interactively list and browse notes (paginated, 10 per page)
read <note-id>             # Display a specific note
edit <note-id>             # Edit a specific note
delete <note-id>           # Delete a specific note, asks confirmation before removal
search "query"             # Search notes for text (title, tags, content)
stats                      # Display statistics about your notes

Notes directory: {}

    """.format(Path.home() / ".notes")
    print(help_text.strip())


def finish(exit_code=0):
    """Clean up and exit the application."""
    sys.exit(exit_code)


def main():
    """Main entry point for the notes CLI application."""
    # Setup
    notes_dir = setup()

    # Parse command-line arguments
    if len(sys.argv) < 2:
        # No command provided
        print("Error: No command provided.", file=sys.stderr)
        print("Usage: python3 mindwriter.py [command]", file=sys.stderr)
        print("Try 'python3 mindwriter.py help' for more information.", file=sys.stderr)
        finish(1)

    command = sys.argv[1].lower()

    # Process command
    if command == "help":
        show_help()
        finish(0)
    elif command == "list":
        success = list_notes(notes_dir)
        finish(0 if success else 1)
    elif command == "read":
        if len(sys.argv) < 3:
            print("Error: read requires a note-id.", file=sys.stderr)
            finish(1)
        note_id = sys.argv[2]
        success = read_note(notes_dir, note_id)
        finish(0 if success else 1)
    else:
        print(f"Error: Unknown command '{command}'", file=sys.stderr)
        print("Try 'mindwriter.py help' for more information.", file=sys.stderr)
        finish(1)


if __name__ == "__main__":
    main()
