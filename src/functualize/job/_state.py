"""The `State` capability — re-exported from its canonical location.

`FreshStore` used to be a second public name for a second class. There is one
class now (ADR-021), and it is durable; see
`functualize._engine.capabilities.state`.
"""

from functualize._engine.capabilities.state import State

__all__ = ["State"]
