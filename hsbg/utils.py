"""Utility functions."""
from __future__ import annotations
from typing import Iterable, List


def filter_minions(minions: Iterable[Minion], clone: bool = False, limit: Optional[int] = None,
                   **kwargs: dict) -> List[Minion]:
    """Find all the minions in the given iterable matching the given keyword arguments.
    Each keyword argument should be an attribute of the Minion class.

    Args:
        minions: An iterable of minions to filter.
        clone: Whether to clone the minions.
        limit: The maximum length of the returned list.
        **kwargs: Keyword arguments corresponding to minion attributes to match.
    """
    matches = []
    for minion in minions:
        if limit is not None and len(matches) == limit:
            break
        if any(getattr(minion, key) != value for key, value in kwargs.items()):
            continue

        if clone:
            matches.append(minion.clone())
        else:
            matches.append(minion)

    return matches