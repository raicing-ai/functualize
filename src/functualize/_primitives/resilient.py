"""Resilient iteration utility.

Only imports from _types/ and stdlib — zero third-party runtime dependencies.
"""

from __future__ import annotations

from collections.abc import Callable, Generator, Iterable
from typing import TypeVar

T = TypeVar("T")


def resilient(
    iterable: Iterable[T],
    on_error: Callable[[Exception], None],
) -> Generator[T, None, None]:
    """Yield each successfully-produced item from *iterable*.

    Catches exceptions raised during iteration of individual items,
    passes each caught exception to the *on_error* callback, and
    continues to the next item.

    Args:
        iterable: Any iterable whose iteration may raise exceptions.
        on_error: Callback invoked with each caught exception.

    Yields:
        Successfully produced items from the iterable.
    """
    iterator = iter(iterable)
    while True:
        try:
            item = next(iterator)
        except StopIteration:
            break
        except Exception as exc:  # noqa: BLE001
            on_error(exc)
        else:
            yield item
