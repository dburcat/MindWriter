#!/usr/bin/env python3
"""
Future Proof Notes Manager - Version Zero
A personal notes manager using text files with YAML headers.
"""

import os
import sys
from pathlib import Path
import mindwriter


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
            metadata = mindwriter.parse_yaml_header(note_file)
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
            mindwriter.create_note(notes_dir)
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
                            mindwriter.read_note(notes_dir, selected_id)
                            break
                        elif action == 'e':
                            mindwriter.edit_note(notes_dir, selected_id)
                            break
                        elif action == 'd':
                            mindwriter.delete_note(notes_dir, selected_id)
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
            elif command == "help" or command == "h":
                show_help()
            elif command == "list" or command == "l":
                list_notes(notes_dir)
            elif command == "read" or command == "r":
                note_id = input("note-id> ")
                mindwriter.read_note(notes_dir, note_id)
            elif command == "edit" or command == "e":
                note_id = input("note-id> ")
                mindwriter.edit_note(notes_dir, note_id)
            elif command == "delete" or command == "d":
                note_id = input("note-id> ")
                mindwriter.delete_note(notes_dir, note_id)
            elif command == "search" or command == "s":
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
    os.system('clear')
    # Setup
    notes_dir = mindwriter.setup()
    print("Type 'help' for available commands")

    # Command loop
    command_loop(notes_dir)

    # Finish
    finish()


if __name__ == "__main__":
    main()
