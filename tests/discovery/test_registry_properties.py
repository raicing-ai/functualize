"""Property-based tests for Job Discovery and Registration.

Tests Properties 6, 7, and 8 from the design document using Hypothesis.
Validates Requirements 4.1, 4.2, 4.3, 4.4, 4.5.
"""

import inspect
import keyword
import os
import shutil
import sys
import tempfile

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from functualize._app.state import AppState
from functualize._discovery.registry import JobRegistry
from functualize._types.naming import normalize_segment
from functualize.app.adapters.click_params import (
    create_job_command as _create_job_command,
)
from functualize.app.core import FunctualizeApp
from functualize.job.context import RunContext

# --- Strategies ---

# Python keywords and builtins that cannot be used as function/variable names
_RESERVED_NAMES = (
    set(keyword.kwlist) | set(dir(__builtins__))
    if isinstance(__builtins__, dict)
    else set(keyword.kwlist) | set(dir(__builtins__))
)

# Valid Python identifiers for function names (public, no underscore prefix, not keywords)
public_func_names = st.from_regex(r"[a-z][a-z0-9_]{0,20}", fullmatch=True).filter(
    lambda s: (
        s.isidentifier()
        and not s.startswith("_")
        and not keyword.iskeyword(s)
        and s not in ("None", "True", "False")
    )
)

# Names must be unique in *canonical* space wherever they are registered
# together: `foo` and `foo_` both normalize to `foo`, and registering both is
# a collision the registry rejects by design, not two jobs.

# Private function names (underscore-prefixed)
private_func_names = st.from_regex(r"_[a-z][a-z0-9_]{0,20}", fullmatch=True).filter(
    lambda s: s.isidentifier()
)

# Valid module names (not keywords, not stdlib modules)
module_names = st.from_regex(r"[a-z][a-z0-9_]{0,15}", fullmatch=True).filter(
    lambda s: (
        s.isidentifier()
        and s not in sys.stdlib_module_names
        and not keyword.iskeyword(s)
    )
)

# JOB_GROUP values (simple lowercase identifiers, not keywords)
job_name_values = st.from_regex(r"[a-z][a-z0-9_]{0,15}", fullmatch=True).filter(
    lambda s: s.isidentifier() and not keyword.iskeyword(s)
)


def _make_function_source(name: str, has_runcontext: bool = False) -> str:
    """Generate source code for a simple function."""
    if has_runcontext:
        return f"def {name}(value: str = 'default', rc: 'RunContext' = None) -> str:\n    return value\n"
    return f"def {name}(value: str = 'default') -> str:\n    return value\n"


def _make_private_function_source(name: str) -> str:
    """Generate source code for a private function."""
    return f"def {name}() -> str:\n    return 'private'\n"


def _make_module_source(
    public_funcs: list[str],
    private_funcs: list[str],
    job_name: str | None = None,
    has_import: bool = False,
    has_runcontext: bool = False,
) -> str:
    """Generate a complete module source with given functions."""
    lines = []
    if has_import:
        lines.append("from os.path import join\n")
    if job_name is not None:
        lines.append(f'JOB_GROUP = "{job_name}"\n')
    for func_name in public_funcs:
        lines.append(_make_function_source(func_name, has_runcontext=has_runcontext))
    for func_name in private_funcs:
        lines.append(_make_private_function_source(func_name))
    # Add a non-callable attribute to verify it's skipped
    lines.append("MY_CONSTANT = 42\n")
    return "\n".join(lines)


def _setup_appstate():
    """Set up AppState for tests."""
    AppState.reset()
    AppState.set("config_directory", ".")
    AppState.set("environment", "DEV")


def _create_jobs_dir(tmp_path: str, modules: dict[str, str]) -> str:
    """Create a temporary jobs directory with module files."""
    jobs_dir = os.path.join(tmp_path, "jobs")
    os.makedirs(jobs_dir, exist_ok=True)
    for name, source in modules.items():
        filepath = os.path.join(jobs_dir, f"{name}.py")
        with open(filepath, "w") as f:
            f.write(source)
    return jobs_dir


# --- Property 6: Job Discovery Registers Public Functions ---
# Feature: functualize, Property 6: Job Discovery Registers Public Functions


@given(
    public_funcs=st.lists(
        public_func_names, min_size=1, max_size=5, unique_by=normalize_segment
    ),
    private_funcs=st.lists(private_func_names, min_size=0, max_size=3, unique=True),
    mod_name=module_names,
)
def test_property_6_registers_only_public_defined_callable_functions(
    public_funcs, private_funcs, mod_name
):
    """For any set of Python module files in a jobs directory, the JobRegistry SHALL
    register exactly those functions that are (a) not prefixed with underscore,
    (b) defined within the module (not imported), and (c) are callable — skipping all others.

    **Validates: Requirements 4.1, 4.2**
    """
    _setup_appstate()

    # Ensure no name collisions between public and private
    assume(not set(public_funcs) & set(private_funcs))

    tmp_dir = tempfile.mkdtemp()
    try:
        # Create module with public funcs, private funcs, an import, and a constant
        source = _make_module_source(
            public_funcs=public_funcs,
            private_funcs=private_funcs,
            job_name=None,
            has_import=True,
        )

        jobs_dir = _create_jobs_dir(tmp_dir, {mod_name: source})

        registry = JobRegistry()
        registry.scan_and_register(None, [jobs_dir])

        # Property: exactly the public functions defined in the module are registered
        registered_names = {
            key.split("::")[1]
            for key in registry._registered_commands
            if key.startswith("__top__::")
        }

        assert registered_names == set(public_funcs), (
            f"Expected {set(public_funcs)}, got {registered_names}. "
            f"Private funcs: {private_funcs}"
        )

        # Verify imported functions are NOT registered
        assert "__top__::join" not in registry._registered_commands

        # Verify non-callable attributes are NOT registered
        assert "__top__::MY_CONSTANT" not in registry._registered_commands
    finally:
        # Cleanup: remove module from sys.modules to avoid cross-test pollution
        if mod_name in sys.modules:
            del sys.modules[mod_name]
        shutil.rmtree(tmp_dir, ignore_errors=True)


# --- Property 7: JOB_GROUP Grouping ---
# Feature: functualize, Property 7: JOB_GROUP Grouping


@given(
    public_funcs=st.lists(
        public_func_names, min_size=1, max_size=4, unique_by=normalize_segment
    ),
    job_name=job_name_values,
    mod_name=module_names,
)
def test_property_7_job_group_groups_functions_under_subcommand(
    public_funcs, job_name, mod_name
):
    """For any job module, if it defines a JOB_GROUP module-level variable, all its
    registerable functions SHALL be grouped under a sub-command named by that variable.

    **Validates: Requirements 4.3, 4.4**
    """
    _setup_appstate()

    # Ensure module name doesn't collide with job_name
    assume(mod_name != job_name)

    tmp_dir = tempfile.mkdtemp()
    try:
        source = _make_module_source(
            public_funcs=public_funcs,
            private_funcs=[],
            job_name=job_name,
        )

        jobs_dir = _create_jobs_dir(tmp_dir, {mod_name: source})

        registry = JobRegistry()
        registry.scan_and_register(None, [jobs_dir])

        # Property: all public functions are grouped under JOB_GROUP
        for func_name in public_funcs:
            registry_key = f"{job_name}::{func_name}"
            assert registry_key in registry._registered_commands, (
                f"Expected '{registry_key}' in registered commands. "
                f"Got: {list(registry._registered_commands.keys())}"
            )

        # Property: no functions registered at top level
        top_level_keys = [
            key for key in registry._registered_commands if key.startswith("__top__::")
        ]
        assert len(top_level_keys) == 0, (
            f"Expected no top-level commands when JOB_GROUP is set, "
            f"but found: {top_level_keys}"
        )

        # Property: sub-Typer was created for the JOB_GROUP
        # Note: _sub_typers was removed when CLI routing was decoupled from
        # Typer internals. Group routing is validated by the registry keys above.
    finally:
        # Cleanup
        if mod_name in sys.modules:
            del sys.modules[mod_name]
        shutil.rmtree(tmp_dir, ignore_errors=True)


@given(
    public_funcs=st.lists(
        public_func_names, min_size=1, max_size=4, unique_by=normalize_segment
    ),
    mod_name=module_names,
)
def test_property_7_no_job_group_registers_at_top_level(public_funcs, mod_name):
    """For any job module, if it does not define JOB_GROUP, all its registerable
    functions SHALL be registered as top-level commands.

    **Validates: Requirements 4.3, 4.4**
    """
    _setup_appstate()

    tmp_dir = tempfile.mkdtemp()
    try:
        source = _make_module_source(
            public_funcs=public_funcs,
            private_funcs=[],
            job_name=None,
        )

        jobs_dir = _create_jobs_dir(tmp_dir, {mod_name: source})

        registry = JobRegistry()
        registry.scan_and_register(None, [jobs_dir])

        # Property: all public functions are at top level
        for func_name in public_funcs:
            registry_key = f"__top__::{func_name}"
            assert registry_key in registry._registered_commands, (
                f"Expected '{registry_key}' in registered commands. "
                f"Got: {list(registry._registered_commands.keys())}"
            )

        # Property: no sub-Typers created
        # Note: _sub_typers was removed when CLI routing was decoupled from
        # Typer internals. Ungrouped behavior is validated by top-level keys above.
    finally:
        # Cleanup
        if mod_name in sys.modules:
            del sys.modules[mod_name]
        shutil.rmtree(tmp_dir, ignore_errors=True)


# --- Property 8: RunContext Parameter Exclusion ---
# Feature: functualize, Property 8: RunContext Parameter Exclusion


@given(
    func_name=public_func_names,
    param_names=st.lists(
        st.from_regex(r"[a-z][a-z0-9_]{0,10}", fullmatch=True).filter(
            lambda s: (
                s.isidentifier()
                and s != "rc"
                and not keyword.iskeyword(s)
                and s not in ("return", "None", "True", "False")
            )
        ),
        min_size=1,
        max_size=4,
        unique=True,
    ),
)
def test_property_8_runcontext_excluded_from_cli_signature(func_name, param_names):
    """For any function whose last parameter is annotated with the RunContext type,
    the generated CLI command SHALL NOT expose that parameter as a CLI option or argument.

    **Validates: Requirements 4.5**
    """
    _setup_appstate()

    # Dynamically create a function with the given params + RunContext as last param
    param_str = ", ".join(f"{p}: str = 'default'" for p in param_names)
    func_source = f"def {func_name}({param_str}, rc: 'RunContext' = None) -> str:\n    return 'ok'\n"

    # Execute the source to create the function object
    local_ns: dict = {}
    exec(func_source, {"RunContext": RunContext}, local_ns)
    func = local_ns[func_name]

    # Annotate the rc parameter with the actual RunContext type
    hints = func.__annotations__
    hints["rc"] = RunContext

    registry = JobRegistry(
        cli_wiring_factory={"create_job_command": _create_job_command}
    )
    wrapped = registry.create_job_command(func_name, func)

    # Property: RunContext parameter is NOT in the wrapped signature
    sig = inspect.signature(wrapped)
    wrapped_param_names = list(sig.parameters.keys())

    assert "rc" not in wrapped_param_names, (
        f"RunContext param 'rc' should be excluded from CLI signature. "
        f"Got params: {wrapped_param_names}"
    )

    # Property: all other parameters ARE in the wrapped signature
    for p in param_names:
        assert p in wrapped_param_names, (
            f"Parameter '{p}' should be in CLI signature. "
            f"Got params: {wrapped_param_names}"
        )


@settings(deadline=5000)
@given(
    func_name=public_func_names,
    param_names=st.lists(
        st.from_regex(r"[a-z][a-z0-9_]{0,10}", fullmatch=True).filter(
            lambda s: (
                s.isidentifier()
                and s != "rc"
                and not keyword.iskeyword(s)
                and s not in ("return", "None", "True", "False")
            )
        ),
        min_size=0,
        max_size=3,
        unique=True,
    ),
)
def test_property_8_runcontext_injected_at_invocation(func_name, param_names):
    """For any function whose last parameter is annotated with the RunContext type,
    the generated CLI command SHALL inject a constructed RunContext instance at
    invocation time.

    **Validates: Requirements 4.5**
    """
    _setup_appstate()

    # Build a function that captures the RunContext it receives
    captured_rc = []

    param_str = ", ".join(f"{p}: str = 'default'" for p in param_names)
    if param_str:
        full_param_str = f"{param_str}, rc: 'RunContext' = None"
    else:
        full_param_str = "rc: 'RunContext' = None"

    func_source = (
        f"def {func_name}({full_param_str}) -> None:\n    captured_rc.append(rc)\n"
    )

    local_ns: dict = {"captured_rc": captured_rc, "RunContext": RunContext}
    exec(func_source, local_ns)
    func = local_ns[func_name]

    # Annotate rc with actual RunContext type
    func.__annotations__["rc"] = RunContext

    app = FunctualizeApp(name="testapp")
    registry = JobRegistry(
        app=app, cli_wiring_factory={"create_job_command": _create_job_command}
    )
    wrapped = registry.create_job_command(func_name, func)

    # Invoke the wrapped function with default values for all params
    kwargs = {p: "test_value" for p in param_names}
    wrapped(**kwargs)

    # Property: RunContext was injected
    assert len(captured_rc) == 1, "RunContext should be injected exactly once"
    assert isinstance(captured_rc[0], RunContext), (
        f"Injected value should be RunContext, got {type(captured_rc[0])}"
    )
    # Property: RunContext has the correct job name
    assert captured_rc[0].name == func_name
