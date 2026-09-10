"""What the *app* wired up, that this job can look up — `rc.wiring`.

Extracted from :class:`~functualize._engine.capabilities.runcontext.RunContext`
(engine-sealed-construction/T8). Two lookups with one shape: a plugin's resolved
config section, and a named resource the host provided. Neither is about *this*
run — they are about the application the run happens inside, which is what makes
them a group rather than four unrelated members on the object every job holds.

Both raise `KeyError` naming what **is** available rather than returning `None`.
A missing plugin section or resource is a wiring mistake, and a wiring mistake
that answers `None` is discovered later, somewhere else, as an `AttributeError`
about a different object.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from pydantic import BaseModel

    from functualize._engine.capabilities.runcontext import RunContext

T = TypeVar("T")

__all__ = ["WiringFacade"]


class WiringFacade:
    """`rc.wiring` — the plugin configs and resources this app provides."""

    __slots__ = ("_rc",)

    def __init__(self, rc: RunContext) -> None:
        self._rc = rc

    # --- Plugin config ---

    @property
    def plugin_configs(self) -> MappingProxyType[str, BaseModel]:
        """Every resolved plugin config section, read-only."""
        if self._rc._plugin_configs is None:
            self._rc._plugin_configs = {}
        return MappingProxyType(self._rc._plugin_configs)

    def get_plugin_config(self, section: str) -> BaseModel:
        """The resolved config for ``section``.

        Raises:
            KeyError: No such section, naming the ones that exist.
        """
        configs = self._rc._plugin_configs
        if configs is None or section not in configs:
            available = list((configs or {}).keys())
            raise KeyError(
                f"No plugin config for section '{section}'. Available: {available}"
            )
        return configs[section]

    def with_plugin_config(self, section: str, **overrides: Any) -> RunContext:
        """A **new** `RunContext` with ``section`` overridden.

        Returns the context, not the facade: the caller wants something to run a
        job with, and handing back a facade would make them reach for its owner.
        """
        from functualize._engine.capabilities.runcontext import RunContext

        rc = self._rc
        current = self.get_plugin_config(section)
        model_class = type(current)
        new_config = model_class(**{**current.model_dump(), **overrides})
        new_configs = dict(rc._plugin_configs or {})
        new_configs[section] = new_config
        return RunContext(
            name=rc._name,
            config=rc._config,
            logger=rc._logger,
            metadata=rc._metadata,
            plugin_configs=new_configs,
            state_store=rc._state_store,
            resources=rc._resources,
            perf_timeline=rc._perf_timeline,
            _di_registry=rc._di_registry,
            _caps=rc._caps,
        )

    # --- Resources ---

    @property
    def resources(self) -> MappingProxyType[str, Any]:
        """Every named resource the host provided, read-only."""
        if self._rc._resources is None:
            self._rc._resources = {}
        return MappingProxyType(self._rc._resources)

    def get_resource(self, name: str, type_: type[T]) -> T:
        """The resource ``name``, checked against ``type_``.

        Raises:
            KeyError: No such resource, naming the ones that exist.
            TypeError: It exists and is not a ``type_``.
        """
        resources = self._rc._resources
        if resources is None or name not in resources:
            available = list((resources or {}).keys())
            raise KeyError(f"Resource '{name}' not found. Available: {available}")
        resource = resources[name]
        if not isinstance(resource, type_):
            raise TypeError(
                f"Resource '{name}': expected {type_.__name__}, "
                f"got {type(resource).__name__}"
            )
        return resource
