#!/usr/bin/env python3
"""
Test script for MindWriter to verify pagination with more than 10 notes.
"""

import os
import tempfile
from pathlib import Path
import sys
import subprocess

def create_test_notes(test_dir, num_notes=15):
    """Create dummy notes for testing."""
    notes_dir = test_dir / "notes"
    notes_dir.mkdir(exist_ok=True)

    for i in range(1, num_notes + 1):
        note_content = f"""---
title: Test Note {i}
created: 2026-03-17T{i:02d}:00:00Z
modified: 2026-03-17T{i:02d}:30:00Z
tags: [test, pagination]
author: TestUser
---

# Test Note {i}

This is a test note number {i} for testing pagination in MindWriter.
"""
        note_file = notes_dir / f"test-note-{i:02d}.md"
        with open(note_file, 'w') as f:
            f.write(note_content)

    return notes_dir

def test_pagination():
    """Test that list_notes shows only 10 notes per page."""
    print("Testing MindWriter pagination...")

    # Create temporary directory
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        test_notes_dir = create_test_notes(temp_path, 15)

        print(f"Created {len(list(test_notes_dir.glob('*.md')))} test notes")

        # Run the list command with 'q' input to quit immediately
        mindwriter_path = Path(__file__).parent.parent / "mindwriter.py"

        cmd = [sys.executable, str(mindwriter_path), 'list']
        env = os.environ.copy()
        env['NOTES_DIR'] = str(test_notes_dir.parent)
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env
        )

        # Send 'q' to quit immediately
        stdout, stderr = process.communicate(input='q\n')

        # Check the output
        output_lines = stdout.split('\n')

        # Count how many notes are listed (look for lines starting with number)
        note_count = 0
        for line in output_lines:
            if line.strip() and line[0].isdigit() and '. ' in line:
                note_count += 1

        print(f"Output shows {note_count} notes on first page")

        if note_count == 10:
            print("✓ Pagination works correctly - shows exactly 10 notes per page")
        else:
            print(f"✗ Expected 10 notes, got {note_count}")
            return False

        # Check if it mentions "Page 1 of 2"
        page_info_found = any("Page 1 of 2" in line for line in output_lines)
        if page_info_found:
            print("✓ Page information shows correctly (Page 1 of 2)")
        else:
            print("✗ Page information not found")
            return False

        print("All tests passed!")
        return True

if __name__ == "__main__":
    success = test_pagination()
    sys.exit(0 if success else 1)