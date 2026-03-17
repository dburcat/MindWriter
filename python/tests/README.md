# MindWriter Tests

This directory contains tests for the MindWriter notes manager.

## Running Tests

To run the pagination test:

```bash
cd /Users/david/Projects/MindWriter/python
python3 tests/test_pagination.py
```

## Test Descriptions

- `test_pagination.py`: Tests that the interactive list command correctly paginates notes, showing exactly 10 notes per page when there are more than 10 notes available.