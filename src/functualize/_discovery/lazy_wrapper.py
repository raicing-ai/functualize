"""CLI-free lazy job machinery for warm boot.

Provides LazyJobFunction (deferred-import stand-in registered into the
execution engine), the module-import helper it uses, and Pydantic config
class detection. Module import is deferred until first materialization.

The CLI command construction (make_lazy_command and the click-parameter
reconstruction from FieldDescriptor data) lives in
``functualize.app.adapters.lazy_command`` and ``.click_params`` — internal
packages stay import-light (no click).
"""

from __future__ import annotations

import importlib
import inspect
import sys
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from functualize._types.descriptors import JobDescriptor


def _detect_config_class(func: Callable[..., Any]) -> type | None:
    """Detect the Pydantic BaseModel config class from a function's signature.

    Inspects the function's parameters for a type annotation that is a
    subclass of pydantic.BaseModel (but not BaseModel itself). Uses
    typing.get_type_hints() to resolve string annotations from
    `from __future__ import annotations`.

    Args:
        func: The job function to inspect.

    Returns:
        The config class if found, None otherwise.
    """
    import typing

    from pydantic import BaseModel

    from functualize._primitives.group_options_detection import (
        is_group_options_subclass,
    )

    try:
        hints = typing.get_type_hints(func)
    except Exception:
        # Fall back to inspect.signature for cases where get_type_hints fails
        try:
            sig = inspect.signature(func)
        except (ValueError, TypeError):
            return None

        for param in sig.parameters.values():
            annotation = param.annotation
            if annotation is inspect.Parameter.empty:
                continue
            if (
                isinstance(annotation, type)
                and issubclass(annotation, BaseModel)
                and annotation is not BaseModel
                and not is_group_options_subclass(annotation)
            ):
                return annotation
        return None

    for annotation in hints.values():
        if (
            isinstance(annotation, type)
            and issubclass(annotation, BaseModel)
            and annotation is not BaseModel
            # A GroupOptions parameter carries the *group's* flags, not this
            # job's config fields (see _discovery/sync.py). This is the
            # warm-boot path, so missing it here leaks the group's fields into
            # the job's own `--help` even when the eager paths are correct.
            and not is_group_options_subclass(annotation)
        ):
            return annotation

    return None


def _import_real_function(descriptor: JobDescriptor) -> Callable[..., Any]:
    """Import a descriptor's module and resolve its real job function.

    For descriptors backed by a real source file, temporarily inserts the
    module's directory into sys.path and handles sys.modules collisions
    (a same-named module loaded from a different file is re-executed from
    the descriptor's source file). For synthetic sources
    (``<entry_point>``/``<dynamic>``), falls back to a plain import of
    ``module_path``.

    Args:
        descriptor: A JobDescriptor with module_path, func_name, source_file.

    Returns:
        The real, callable job function.

    Raises:
        ImportError: If the module cannot be imported.
        AttributeError: If the module lacks a callable named func_name.
    """
    from pathlib import Path

    source_file = descriptor.source_file
    module_path = descriptor.module_path

    if source_file and source_file != "<entry_point>" and source_file != "<dynamic>":
        module_dir = str(Path(source_file).parent)
        path_added = False
        if module_dir not in sys.path:
            sys.path.insert(0, module_dir)
            path_added = True
        try:
            existing = sys.modules.get(module_path)
            if existing is not None:
                existing_file = getattr(existing, "__file__", None)
                if existing_file and str(Path(existing_file).resolve()) != str(
                    Path(source_file).resolve()
                ):
                    import importlib.util as _importlib_util

                    spec = _importlib_util.spec_from_file_location(
                        module_path, source_file
                    )
                    if spec and spec.loader:
                        module = _importlib_util.module_from_spec(spec)
                        spec.loader.exec_module(module)
                        sys.modules[module_path] = module
                    else:
                        module = importlib.import_module(module_path)
                else:
                    module = existing
            else:
                module = importlib.import_module(module_path)
        finally:
            if path_added and module_dir in sys.path:
                sys.path.remove(module_dir)
    else:
        module = importlib.import_module(module_path)

    attribute = descriptor.attribute_name
    real_fn = getattr(module, attribute, None)
    if real_fn is None or not callable(real_fn):
        raise AttributeError(
            f"Module '{module_path}' has no callable named '{attribute}'"
        )
    result: Callable[..., Any] = real_fn
    return result


class LazyJobFunction:
    """Deferred-import stand-in for a job function.

    Construction does NOT import the job module. The real function is
    resolved on first ``materialize()`` (or first call), after which
    ``__wrapped__`` points at it. The execution engine detects instances
    via the ``__functualize_lazy__`` marker and swaps the registry entry
    to the real function before any signature introspection, so
    resolution-plan and validator caches key on the real function.
    """

    __functualize_lazy__: bool = True

    def __init__(self, descriptor: JobDescriptor) -> None:
        import threading

        self.descriptor = descriptor
        self.config_class: type | None = None
        # The stand-in mimics the *function*, so it carries the function's
        # own name — matching what materialization will resolve, and what
        # `inspect` reports for the real callable once it arrives.
        self.__name__ = descriptor.attribute_name
        self.__qualname__ = descriptor.attribute_name
        self.__module__ = descriptor.module_path
        self.__doc__ = descriptor.docstring or ""
        self._real_fn: Callable[..., Any] | None = None
        self._lock = threading.Lock()

    def materialize(self) -> tuple[Callable[..., Any], type | None]:
        """Import the module (once) and return (real_fn, config_class).

        Idempotent and thread-safe (double-checked lock). Uses the
        descriptor's attached live function when present (cold boot /
        static providers) instead of importing.

        Raises:
            JobMaterializationError: If the module import or function
                resolution fails; chains the original exception.
        """
        if self._real_fn is not None:
            return self._real_fn, self.config_class
        with self._lock:
            if self._real_fn is not None:
                return self._real_fn, self.config_class
            attached = getattr(self.descriptor, "function", None)
            if attached is not None and callable(attached):
                real_fn = attached
            else:
                try:
                    real_fn = _import_real_function(self.descriptor)
                except Exception as exc:
                    from functualize._types.errors import JobMaterializationError

                    raise JobMaterializationError(
                        self.descriptor.name,
                        self.descriptor.module_path,
                        self.descriptor.source_file,
                    ) from exc
            self.config_class = _detect_config_class(real_fn)
            self.__wrapped__ = real_fn
            self.__doc__ = real_fn.__doc__ or self.__doc__
            self._real_fn = real_fn
        return self._real_fn, self.config_class

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        real_fn, _ = self.materialize()
        return real_fn(*args, **kwargs)

    def __repr__(self) -> str:
        state = "materialized" if self._real_fn is not None else "deferred"
        return (
            f"<LazyJobFunction {self.descriptor.module_path}."
            f"{self.descriptor.func_name} ({state})>"
        )
