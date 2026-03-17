#!/usr/bin/env python3
"""
Test script for MindWriter create functionality.
"""

import os
import tempfile
from pathlib import Path
import sys
import subprocess

def test_create_note():
    """Test creating a note."""
    print("Testing MindWriter create functionality...")

    # Create temporary directory
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        notes_dir = temp_path / "notes"
        notes_dir.mkdir()

        # Path to MindWriter.py
        mindwriter_path = Path(__file__).parent.parent / "mindwriter.py"

        # Input for create command
        input_data = "Test Create Note\npython, create\ntestauthor\n2\nThis is content for the create test.\n"

        # Run the create command
        cmd = [sys.executable, str(mindwriter_path), 'create']
        env = os.environ.copy()
        env['NOTES_DIR'] = str(temp_path)
        env['EDITOR'] = 'true'  # Use 'true' as editor to exit immediately
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env
        )

        # Wait for completion
        stdout, stderr = process.communicate()

        if process.returncode != 0:
            print(f"Command failed with return code {process.returncode}")
            print(f"stdout: {stdout}")
            print(f"stderr: {stderr}")
            return False

        if process.returncode != 0:
            print(f"Command failed with return code {process.returncode}")
            print(f"stdout: {stdout}")
            print(f"stderr: {stderr}")
            return False

        # Check if note was created
        note_files = list(notes_dir.glob("*.md"))
        if len(note_files) == 1:
            print("✓ Note file created successfully")
            
            # Check content
            with open(note_files[0], 'r') as f:
                content = f.read()
            
            if 'title:' in content:
                print("✓ YAML header contains title field")
            else:
                print("✗ YAML header missing title field")
                return False
                
            if 'created:' in content:
                print("✓ Created timestamp included")
            else:
                print("✗ Created timestamp missing")
                return False
                
            if 'tags: []' in content:
                print("✓ Tags field included")
            else:
                print("✗ Tags field missing")
                return False
                
            if '# New Note' in content:
                print("✓ Template content included")
            else:
                print("✗ Template content missing")
                return False
                
        else:
            print(f"✗ Expected 1 note file, found {len(note_files)}")
            return False

        print("All create tests passed!")
        return True

if __name__ == "__main__":
    success = test_create_note()
    sys.exit(0 if success else 1)