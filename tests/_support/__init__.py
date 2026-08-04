"""Static test fixtures for functualize integration and CLI tests.

This directory contains committed project layouts, config files, and job
modules that tests reference by path. Use these for complex scenarios that
multiple tests share. For simple/dynamic cases, prefer the `project_tree`
fixture factory in conftest.py.

Layout:
    projects/       — complete project directory trees
    configs/        — XDG global config variants
    jobs/           — standalone job modules (no project context)
"""
