"""Offline instrument that measures pre-context skill selection.

Rules for this package:

- It measures skill selection over a frozen corpus and a frozen catalog; the
  numbers it produces are evidence about a routing strategy, never product
  behaviour.
- Nothing in the product imports this package, and it imports public
  ``functualize`` modules only (``functualize.app``, ``functualize.app.utils``,
  ``functualize.plugin``, ``functualize.types``, ``functualize.workflow``),
  never an underscore-prefixed module.
- Offline tests never touch the network, spawn a process or sleep.
- Live runs are commands (``replay``, ``select``, ``report``) that write their
  output outside the repository; measured numbers are never committed.
"""
