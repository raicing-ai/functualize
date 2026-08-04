"""Tests for standalone job and file-based plugin templates.

Validates: Requirements R1-AC2, R1-AC3, R2-AC2
"""

import ast

from jinja2 import Environment, PackageLoader


def _render_template(template_name: str, context: dict) -> str:
    """Render a scaffold template with the given context."""
    env = Environment(
        loader=PackageLoader("functualize._cli.scaffold", "templates"),
        keep_trailing_newline=True,
    )
    template = env.get_template(template_name)
    return template.render(**context)


class TestStandaloneJobTemplate:
    """Tests for standalone_job.py.j2 template (R1-AC2, R1-AC3)."""

    def test_renders_valid_python(self) -> None:
        """Rendered standalone job template produces valid Python."""
        source = _render_template(
            "standalone_job.py.j2",
            {"job_name": "data_sync"},
        )
        # ast.parse raises SyntaxError if source is not valid Python
        tree = ast.parse(source)
        assert tree is not None

    def test_contains_public_function(self) -> None:
        """Rendered standalone job has at least one public function (R1-AC3)."""
        source = _render_template(
            "standalone_job.py.j2",
            {"job_name": "data_sync"},
        )
        tree = ast.parse(source)
        public_functions = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
        ]
        assert len(public_functions) >= 1

    def test_public_function_uses_run_context(self) -> None:
        """Rendered standalone job's public function has RunContext in signature."""
        source = _render_template(
            "standalone_job.py.j2",
            {"job_name": "data_sync"},
        )
        tree = ast.parse(source)
        public_functions = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
        ]
        # At least one public function should accept an 'rc' parameter
        # with RunContext annotation
        found_rc_param = False
        for func in public_functions:
            for arg in func.args.args:
                if (
                    arg.annotation
                    and isinstance(arg.annotation, ast.Name)
                    and arg.annotation.id == "RunContext"
                ):
                    found_rc_param = True
                    break
        assert found_rc_param, "No public function with RunContext parameter found"

    def test_imports_run_context(self) -> None:
        """Rendered standalone job imports RunContext."""
        source = _render_template(
            "standalone_job.py.j2",
            {"job_name": "my_job"},
        )
        assert "from functualize.job.context import RunContext" in source

    def test_job_name_substituted(self) -> None:
        """Template correctly substitutes the job_name variable."""
        source = _render_template(
            "standalone_job.py.j2",
            {"job_name": "process_data"},
        )
        assert "process_data" in source


class TestFilePluginTemplate:
    """Tests for file_plugin.py.j2 template (R2-AC2)."""

    def test_renders_valid_python(self) -> None:
        """Rendered file plugin template produces valid Python."""
        source = _render_template(
            "file_plugin.py.j2",
            {"plugin_name": "my_logger", "class_name": "MyLogger"},
        )
        # ast.parse raises SyntaxError if source is not valid Python
        tree = ast.parse(source)
        assert tree is not None

    def test_contains_callable_class(self) -> None:
        """Rendered file plugin has a class with __call__ method."""
        source = _render_template(
            "file_plugin.py.j2",
            {"plugin_name": "my_logger", "class_name": "MyLogger"},
        )
        tree = ast.parse(source)

        classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        assert len(classes) >= 1

        # At least one class must have a __call__ method
        found_callable = False
        for cls in classes:
            for item in cls.body:
                if isinstance(item, ast.FunctionDef) and item.name == "__call__":
                    found_callable = True
                    break
        assert found_callable, "No callable class (with __call__) found"

    def test_class_has_name_attribute(self) -> None:
        """Rendered file plugin's class has a `name` attribute."""
        source = _render_template(
            "file_plugin.py.j2",
            {"plugin_name": "my_logger", "class_name": "MyLogger"},
        )
        tree = ast.parse(source)

        classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        assert len(classes) >= 1

        # At least one class must have a `name` class-level attribute
        found_name_attr = False
        for cls in classes:
            for item in cls.body:
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name) and target.id == "name":
                            found_name_attr = True
                            break
        assert found_name_attr, "No class with 'name' attribute found"

    def test_plugin_name_substituted(self) -> None:
        """Template correctly substitutes the plugin_name variable."""
        source = _render_template(
            "file_plugin.py.j2",
            {"plugin_name": "my_logger", "class_name": "MyLogger"},
        )
        assert "my_logger" in source
        assert "MyLogger" in source

    def test_class_name_is_pascal_case(self) -> None:
        """Template uses the provided class_name for the class definition."""
        source = _render_template(
            "file_plugin.py.j2",
            {"plugin_name": "event_tracker", "class_name": "EventTracker"},
        )
        tree = ast.parse(source)

        classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        class_names = [cls.name for cls in classes]
        assert "EventTrackerPlugin" in class_names
