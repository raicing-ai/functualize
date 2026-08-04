"""InteractivityConfig mixin for job configs that declare an interactivity backend."""

from pydantic import BaseModel, Field


class InteractivityConfig(BaseModel):
    """Optional mixin for job config classes that declare an interactivity backend.

    Usage::

        class MyJobConfig(InteractivityConfig):
            timeout: int = 30

    When ``interactivity_backend`` is set, only the plugin with that name receives
    callbacks for this job. When omitted or empty, all active interactivity plugins
    receive callbacks. Set to ``'none'`` to disable all interactivity plugins.
    """

    interactivity_backend: str = Field(
        default="",
        description=(
            "Name of the interactivity plugin that handles UI for this job. "
            "Empty string = all active interactivity plugins. "
            "'none' = no interactivity plugin."
        ),
    )
