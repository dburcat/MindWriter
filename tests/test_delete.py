#!/usr/bin/env python3
"""
Test script for MindWriter delete functionality.
"""

import os
import tempfile
from pathlib import Path
import sys
import subprocess

def test_delete_note():
    """Test deleting a note."""
    print("Testing MindWriter delete functionality...")

    # Create a test note first
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        notes_dir = temp_path / "notes"
        notes_dir.mkdir()

        # Create a test note
        test_note = notes_dir / "test_delete.md"
        with open(test_note, 'w') as f:
            f.write("""---
title: Test Delete
created: 2026-03-17T12:00:00
modified: 2026-03-17T12:00:00
tags: [test]
author: testuser
---

Content to delete.
""")

        # Path to MindWriter.py
        mindwriter_path = Path(__file__).parent.parent / "mindwriter.py"

        # Run the delete command with 'y' confirmation
        cmd = [sys.executable, str(mindwriter_path), 'delete', 'test_delete.md']
        env = os.environ.copy()
        env['NOTES_DIR'] = str(temp_path)
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env
        )

        # Send 'y' to confirm deletion
        stdout, stderr = process.communicate(input='y\n')

        if process.returncode != 0:
            print(f"Command failed with return code {process.returncode}")
            print(f"stdout: {stdout}")
            print(f"stderr: {stderr}")
            return False

        # Check that the file is deleted
        if not test_note.exists():
            print("✓ Delete command successfully removed the file")
            return True
        else:
            print("✗ File still exists after delete")
            return False

if __name__ == "__main__":
    success = test_delete_note()
    sys.exit(0 if success else 1)