"""Offline instrument that measures the hermetic router over a frozen corpus.

Rules for this package:

- It measures routing quality over a corpus frozen by a lock file; the numbers
  it produces are evidence about a candidate decision layer, never product
  behaviour.
- Nothing in the product imports this package, and it imports public
  ``functualize`` modules only (``functualize.app``, ``functualize.app.utils``,
  ``functualize.plugin``, ``functualize.types``, ``functualize.workflow``),
  never an underscore-prefixed module.
- Offline tests never touch the network, spawn a process or sleep.
- Live runs are the ``replay`` command, which writes its run directory outside
  the repository; measured numbers are never committed.
"""
