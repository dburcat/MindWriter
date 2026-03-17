# MindWriter Tests

This directory contains tests for the MindWriter notes manager.

## Running Tests

To run the pagination test:

```bash
cd /Users/david/Projects/MindWriter
python3 tests/test_pagination.py
```

To run the create and edit tests:

```bash
cd /Users/david/Projects/MindWriter
python3 tests/test_create.py
```

To run the delete test:

```bash
cd /Users/david/Projects/MindWriter
python3 tests/test_delete.py
```

## Test Descriptions

- `test_pagination.py`: Tests that the interactive list command correctly paginates notes, showing exactly 10 notes per page when there are more than 10 notes available.
- `test_create.py`: Tests note creation and editing functionality, ensuring proper YAML headers and editor integration.
- `test_delete.py`: Tests note deletion with confirmation.

## Test Descriptions

- `test_pagination.py`: Tests that the interactive list command correctly paginates notes, showing exactly 10 notes per page when there are more than 10 notes available.