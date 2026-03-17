#!/usr/bin/env python3
"""
Future Proof Notes Manager - Version Zero
A personal notes manager using text files with YAML headers.
"""

import os
import sys
from pathlib import Path


def setup():
    """Initialize the notes application."""
    os.system('clear')
    print("MindWriter Notes Manager v0.1")
    print("=" * 40)

    # Define the notes directory in HOME
    notes_dir = Path.home() / ".notes"

    # Check if notes directory exists
    if not notes_dir.exists():
        print(f"Notes directory not found at {notes_dir}")
        print("Run 'notes init' to create it.")
    else:
        print(f"Notes directory: {notes_dir}")

    print()
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


def create_note(notes_dir):
    """Create a new note by opening it in the default editor."""
    # Ensure notes directory exists
    notes_subdir = notes_dir / "notes"
    if not notes_subdir.exists():
        try:
            notes_subdir.mkdir(parents=True)
            print(f"Created notes directory: {notes_subdir}")
        except Exception as e:
            print(f"Error creating notes directory: {e}")
            return False

    # Generate filename with timestamp
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    temp_filename = f"note_{timestamp}.md"
    temp_file = notes_subdir / temp_filename

    # Create template content
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

    # Write the template file
    try:
        with open(temp_file, 'w', encoding='utf-8') as f:
            f.write(template_content)
    except Exception as e:
        print(f"Error creating note file: {e}")
        return False

    # Open in default editor
    editor = os.environ.get('EDITOR', 'vi')
    try:
        os.system(f"{editor} {temp_file}")
    except Exception as e:
        print(f"Error opening editor: {e}")
        return False

    # After editing, read the title and rename the file
    try:
        metadata = parse_yaml_header(temp_file)
        title = metadata.get('title', '').strip()
        if not title:
            print("Warning: No title provided. Keeping temporary filename.")
            final_file = temp_file
        else:
            # Sanitize title for filename
            import re
            filename = re.sub(r'[^\w\-_\.]', '_', title.lower().replace(' ', '_'))
            filename = f"{filename}.md"
            final_file = notes_subdir / filename

            # Check if file already exists
            counter = 1
            while final_file.exists() and final_file != temp_file:
                base, ext = filename.rsplit('.', 1)
                filename = f"{base}_{counter}.{ext}"
                final_file = notes_subdir / filename
                counter += 1

            # Rename the file
            if final_file != temp_file:
                temp_file.rename(final_file)

        print(f"Note saved: {final_file}")
        return True
    except Exception as e:
        print(f"Error processing note: {e}")
        return False


def edit_note(notes_dir, note_id):
    """Edit an existing note by opening it in the default editor."""
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

    # Open in default editor
    editor = os.environ.get('EDITOR', 'vi')
    try:
        os.system(f"{editor} {note_file}")
        print(f"Note edited: {note_file}")
        return True
    except Exception as e:
        print(f"Error opening editor: {e}")
        return False


def delete_note(notes_dir, note_id):
    """Delete an existing note after confirmation."""
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

    # Ask for confirmation
    confirm = input(f"Are you sure you want to delete '{note_id}'? (y/N): ").strip().lower()
    if confirm == 'y' or confirm == 'yes':
        try:
            note_file.unlink()
            print(f"Note deleted: {note_id}")
            return True
        except Exception as e:
            print(f"Error deleting note: {e}")
            return False
    else:
        print("Deletion cancelled.")
        return True


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
    run = True
    while run is True:
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
            priority = metadata.get('priority', '')

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
            if priority:
                print(f"   Priority: {priority}")
            print()

        print(f"Page {current_page}/{total_pages} - {len(page_notes)} notes shown. {len(note_files)} Total notes in folder")

        # Prompt for user input
        prompt = input("Enter number to select note, 'n' for next page, 'p' for previous, 'c' to create note, 'q' to quit: ").strip().lower()

        if prompt == 'q':
            break
        elif prompt == 'c':
            create_note(notes_dir)
            run = False
            list_notes(notes_dir)
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
                    selected_id = selected_file.name
                    
                    # Submenu for selected note
                    while True:
                        action = input(f"Selected: {selected_id}\n(r)ead, (e)dit, (d)elete, (b)ack: ").strip().lower()
                        if action == 'r':
                            read_note(notes_dir, selected_id)
                            break
                        elif action == 'e':
                            edit_note(notes_dir, selected_id)
                            break
                        elif action == 'd':
                            delete_note(notes_dir, selected_id)
                            # After delete, refresh the list
                            break
                        elif action == 'b':
                            break
                        else:
                            print("Invalid option. Use r, e, d, or b.")
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
help                     # Display help information
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



def command_loop(notes_dir):
    """Main command loop for processing user input."""
    while True:
        try:
            # Get user input
            command = input("notes> ").strip().lower()

            # Handle empty input
            if not command:
                continue

            # Process commands
            if command == "quit" or command == "q":
                break
            elif command == "help":
                show_help()
            elif command == "list":
                list_notes(notes_dir)
            elif command == "read":
                note_id = input("note-id> ")
                read_note(notes_dir, note_id)
            elif command == "edit":
                note_id = input("note-id> ")
                edit_note(notes_dir, note_id)
            elif command == "delete":
                note_id = input("note-id> ")
                delete_note(notes_dir, note_id)
            elif command == "list":
                list_notes(notes_dir)
            elif command == "search":
                continue
            else:
                print(f"Unknown command: '{command}'")
                print("Type 'help' for available commands.")

        except EOFError:
            # Handle Ctrl+D
            print()
            break
        except KeyboardInterrupt:
            # Handle Ctrl+C
            print("\nUse 'quit' to exit.")


def finish():
    """Clean up and exit the application."""
    print("\nGoodbye!")
    sys.exit(0)


def main():
    """Main entry point for the notes application."""
    # Setup
    notes_dir = setup()

    # Command loop
    command_loop(notes_dir)

    # Finish
    finish()


if __name__ == "__main__":
    main()
