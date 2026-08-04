"""Global snippets — simulates ~/.config/functualize/jobs/snippets.py.

Merged into the job list via extra_directories (see pyproject.toml). These
play the role of personal utility jobs available in every project. Note that
discovery filters apply to extra directories too: enable the "job_" prefix
filter and the snippets vanish from the listing.
"""

from datetime import datetime


def snippet_hello(name: str = "World") -> str:
    """Quick hello utility."""
    print(msg := f"Hello, {name}!")
    return msg


def snippet_date() -> str:
    """Show the current date."""
    print(msg := datetime.now().strftime("%Y-%m-%d"))
    return msg
