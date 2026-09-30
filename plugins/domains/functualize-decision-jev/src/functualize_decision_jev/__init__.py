"""Functualize decision provider backed by the Jev model service.

Experimental. ``JevPlugin`` is loaded through the ``functualize.plugins`` entry
point and registers the ``decision`` gate strategy, answered by
``JevDecisionProvider``; the provider needs ``OPENCODE_API_KEY`` at call time.
"""

from functualize_decision_jev._plugin import JevPlugin

__all__ = ["JevPlugin"]
