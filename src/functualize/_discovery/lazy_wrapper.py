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
import sys
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from functualize._primitives.config_class_detection import detect_config_class
from functualize._types.class_job import ClassJobMethod
from functualize._types.errors import JobMaterializationError

if TYPE_CHECKING:
    from functualize._types.descriptors import JobDescriptor

#: Mutual exclusion over the ``sys.path`` insert → import → remove region
#: of :func:`_import_real_function`, process-wide.
#:
#: This is a lock, not state, so the Constitution's "global mutable state
#: / module-level singletons" ban does not reach it: it holds no data, has
#: no observable value, is never reset between tests, and resolves through
#: no DI registry — the two reasons that rule gives cannot arise. What it
#: guards *is* interpreter-global (``sys.path``/``sys.modules``, like the
#: module locks CPython's own import machinery holds). It also guards the
#: first-materialization state of every ``LazyJobFunction``. A second proxy
#: lock would create an opposite-order cycle when imported module code
#: materializes another proxy on a different thread. No instance-scoped owner
#: spans every caller (the entry-point provider and tests call
#: ``_import_real_function`` with no proxy in sight); the one owner that
#: spans all of them is this module.
#:
#: Re-entrant deliberately: module import may materialize another proxy on
#: the same thread. All proxies acquire this lock before their first import,
#: so no thread can hold a proxy lock while waiting for it.
_IMPORT_LOCK = threading.RLock()


def _detect_config_class(func: Callable[..., Any]) -> type | None:
    """The warm-boot entry point to the one config-class rule.

    Delegates to ``_primitives.config_class_detection``. This used to be a
    third copy of the rule and it had drifted twice over: it iterated the
    hints mapping's *values* (so a pydantic return annotation was taken as
    config) and resolved hints without ``include_extras=True`` (so
    ``Annotated[Envelope, FromJob(...)]`` collapsed to bare ``Envelope`` and
    was taken as config too). A job that ran cold therefore failed warm.

    The name is kept: ``_app/boot.py`` and ``app/adapters/lazy_command.py``
    import it.
    """
    return detect_config_class(func)


def _import_real_function(descriptor: JobDescriptor) -> Callable[..., Any]:
    """Import a descriptor's module and resolve its real job function.

    For descriptors backed by a real source file, temporarily inserts the
    module's directory into sys.path and handles sys.modules collisions
    (a same-named module loaded from a different file is re-executed from
    the descriptor's source file). That whole insert → import → remove
    region is serialised process-wide by ``_IMPORT_LOCK`` — concurrent
    first materialisation of same-module jobs (a warm-cache
    ``invoke.parallel`` batch) would otherwise race on sys.path and read
    half-initialized modules. For synthetic sources
    (``<entry_point>``/``<dynamic>``), falls back to a plain import of
    ``module_path`` outside the lock.

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
        # Every source-backed helper call holds this region until import is
        # complete. It also protects direct callers without a lazy proxy;
        # proxies take the same re-entrant lock before checking their state.
        with _IMPORT_LOCK:
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

    if descriptor.owner_class is not None:
        return _resolve_class_method(descriptor, module)

    attribute = descriptor.attribute_name
    real_fn = getattr(module, attribute, None)
    if real_fn is None or not callable(real_fn):
        raise AttributeError(
            f"Module '{module_path}' has no callable named '{attribute}'"
        )
    if isinstance(real_fn, type):
        # A class is callable, so the test above accepts it — but a class is
        # not a job. Handing it on would describe the class as one job, and
        # `_build_descriptor` accepts a class for exactly this reason: its
        # `func = obj if callable(obj) else lambda: None` never sees the
        # problem. A class that should have been enumerated reached here
        # because its source could not be read (a compiled or zipped
        # distribution), so the class is visible for the first time and there
        # is nothing to hand dispatch.
        raise _not_a_job_class_error(descriptor, real_fn)
    result: Callable[..., Any] = real_fn
    return result


def _resolve_class_method(descriptor: JobDescriptor, module: Any) -> ClassJobMethod:
    """Resolve ``owner_class``'s method and wrap it as the registered callable.

    The proxy is built from the descriptor's own declaration, never from the
    method's ``@job``: 3.1 merged the class's identity and tags into the
    descriptor, and every cold-run reader of ``__functualize_job__`` expects
    that merged object. Recomputing it here would give a warm run a different
    declaration from the cold one.
    """
    class_name = descriptor.owner_class
    assert class_name is not None  # guarded by the caller
    method_name = descriptor.attribute_name
    job_class = getattr(module, class_name, None)
    if not isinstance(job_class, type):
        raise AttributeError(
            f"Module '{descriptor.module_path}' has no job class named '{class_name}'"
        )
    method = getattr(job_class, method_name, None)
    if method is None or not callable(method):
        raise AttributeError(
            f"Job class '{class_name}' in module '{descriptor.module_path}' has "
            f"no method named '{method_name}'"
        )
    if descriptor.declaration is None:
        raise AttributeError(
            f"Job class '{class_name}' in module '{descriptor.module_path}' "
            f"carries no @job declaration for '{method_name}'"
        )
    return ClassJobMethod(job_class, method_name, declaration=descriptor.declaration)


def _not_a_job_class_error(
    descriptor: JobDescriptor, job_class: type
) -> JobMaterializationError:
    """The materialisation error for a class found where a job was expected.

    Built at the raise site and relabelled through ``args``: the constructor's
    message is about an import that failed, and this import succeeded. Same
    pattern as ``_primitives/di.py:relabel`` — the error's identity and
    attributes are the right ones, only the rendered text would be wrong.
    """
    error = JobMaterializationError(
        descriptor.name, descriptor.module_path, descriptor.source_file
    )
    # Relabelled through ``args``: the constructor's message is about an import
    # that failed, and this import succeeded.
    error.args = (
        f"Job '{descriptor.name}': entry point '{descriptor.name}' in module "
        f"'{descriptor.module_path}' names the job class "
        f"'{job_class.__name__}' where a job function was expected. A job "
        "class names its own jobs and is enumerated by reading its module's "
        "source, which this descriptor's entry point does not allow (a "
        "compiled or zipped distribution).",
    )
    return error


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

    def materialize(self) -> tuple[Callable[..., Any], type | None]:
        """Import the module (once) and return (real_fn, config_class).

        Idempotent and thread-safe (double-checked import lock). Uses the
        descriptor's attached live function when present (cold boot /
        static providers) instead of importing.

        Raises:
            JobMaterializationError: If the module import or function
                resolution fails; chains the original exception.
        """
        if self._real_fn is not None:
            return self._real_fn, self.config_class
        # One lock guards both proxy publication and the process-wide import
        # region. Import runs arbitrary module code, which may materialize a
        # second proxy; a separate per-proxy lock would permit a cross-thread
        # lock-order cycle.
        with _IMPORT_LOCK:
            if self._real_fn is not None:
                return self._real_fn, self.config_class
            attached = getattr(self.descriptor, "function", None)
            if attached is not None and callable(attached):
                real_fn = attached
            else:
                try:
                    real_fn = _import_real_function(self.descriptor)
                except JobMaterializationError:
                    # Already names the job and says what is wrong; the generic
                    # wrap below would trade that for "failed to import".
                    raise
                except Exception as exc:
                    raise JobMaterializationError(
                        self.descriptor.name,
                        self.descriptor.module_path,
                        self.descriptor.source_file,
                    ) from exc
            # A class job's config class *is* its job class: the proxy holds it,
            # and detecting one from a proxy would read the method's return
            # annotation. Detection is a function-only question.
            if self.descriptor.owner_class is not None:
                self.config_class = real_fn.job_class
            else:
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
