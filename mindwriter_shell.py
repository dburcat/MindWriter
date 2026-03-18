#!/usr/bin/env python3
"""
Future Proof Notes Manager - Version Zero
A personal notes manager using text files with YAML headers.
"""

import os
import sys
from pathlib import Path
import mindwriter
import re

def list_notes(notes_dir):
    """Interactively list and browse notes with pagination."""
    if not notes_dir.exists():
        print(f"Error: Notes directory does not exist: {notes_dir}", file=sys.stderr)
        print("Create it with: mkdir -p ~/.notes/notes", file=sys.stderr)
        return False

    note_files = mindwriter.collect_note_files(notes_dir)

    if not note_files:
        print(f"No notes found in {notes_dir}")
        return True

    # Build the session index once so display and selection are consistent
    id_to_file, _ = mindwriter.build_index(note_files)

    total_notes = len(note_files)
    items_per_page = 10
    total_pages = (total_notes + items_per_page - 1) // items_per_page
    current_page = 1
    run = True
    while run is True:
        start_index = (current_page - 1) * items_per_page
        end_index = start_index + items_per_page
        # Slice using the ordered id list so page numbers match index numbers
        page_ids = list(id_to_file.keys())[start_index:end_index]

        print(f"\nNotes in {notes_dir} (Page {current_page} of {total_pages}):")
        print("=" * 60)
        for note_id in page_ids:
            note_file = id_to_file[note_id]
            metadata = mindwriter.parse_yaml_header(note_file)
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
        print("Enter an index number to read that note, 'n' next, 'p' previous, 'c' create note, 'q' quit.")
        prompt = input("> ").strip().lower()

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
                chosen_id = int(prompt)
                if chosen_id in id_to_file:
                    #mindwriter.read_note(notes_dir, str(chosen_id))
                    # Submenu for selected note
                    run_sub = True
                    while run_sub is True:
                        action = input(f"Selected: {id_to_file[chosen_id].name}\n(r)ead, (e)dit, (d)elete, (b)ack: ").strip().lower()
                        if action == 'r':
                            mindwriter.read_note(notes_dir, str(chosen_id))
                            break
                        elif action == 'e':
                            mindwriter.edit_note(notes_dir, str(chosen_id))
                            run = False
                            run_sub = False
                            list_notes(notes_dir)
                        elif action == 'd':
                            mindwriter.delete_note(notes_dir, str(chosen_id))
                            # After delete, refresh the list
                            run = False
                            run_sub = False
                            list_notes(notes_dir)
                        elif action == 'b':
                            break
                        else:
                            print("Invalid option. Use r, e, d, or b.")
                else:
                    print(f"No note with index {chosen_id}. Valid range: 1–{total_notes}")
            except ValueError:
                print("Invalid input. Enter a number, 'n', 'p', or 'q'.")

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
                note_id = input("note-id> ").strip().lower()
                mindwriter.read_note(notes_dir, note_id)
            elif command == "edit" or command == "e":
                note_id = input("note-id> ").strip().lower()
                mindwriter.edit_note(notes_dir, note_id)
            elif command == "delete" or command == "d":
                note_id = input("note-id> ").strip().lower()
                mindwriter.delete_note(notes_dir, note_id)
            elif command == "search" or command == "s":
                keywords = input("keywords> ").strip().lower()
                keywords = re.split(r'[,;\s]+', keywords)
                mindwriter.search_notes(notes_dir, keywords)
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
