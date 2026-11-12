"""Painter's window (PySide6). Install with `pip install -e .[gui]`, run
`painter-gui`.

The window calls the same services as the command line: a request in, a
result out, progress through a QueueReporter drained on the GUI thread.
Nothing here talks to Canvas directly, and nothing outside this package
imports Qt (tests/test_layering.py).
"""
