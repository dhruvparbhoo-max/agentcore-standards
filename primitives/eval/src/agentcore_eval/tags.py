"""Tags for a hill-climbing dataset.

Two axes, plus the topic you stratify on:

- ``behavior`` is ``capability`` (the climb) or ``regression`` (already true).
- ``split`` is ``optimization`` (you may read it while editing) or ``holdout``.
- ``categories`` are topic slugs such as ``tool_selection``. Each topic needs
  both splits before a climb. See ``docs/evals/hill-climbing.md``.

Ship-gate evals stay untagged. A climb case sets all three.
"""

import re
from collections.abc import Sequence
from enum import StrEnum

_CATEGORY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class BehaviorTag(StrEnum):
    """Whether the case is a climb target or a case that must keep passing."""

    CAPABILITY = "capability"
    REGRESSION = "regression"


class SplitTag(StrEnum):
    """Which side of the hill-climb split a case belongs to."""

    OPTIMIZATION = "optimization"
    HOLDOUT = "holdout"


class DatasetTags:
    """One climb case: behavior, split, and at least one topic slug."""

    def __init__(
        self,
        *,
        behavior: BehaviorTag,
        split: SplitTag,
        categories: Sequence[str],
    ) -> None:
        if not isinstance(behavior, BehaviorTag) or not isinstance(split, SplitTag):
            raise ValueError("behavior and split must be BehaviorTag and SplitTag")
        if isinstance(categories, str) or not isinstance(categories, Sequence):
            raise ValueError("categories must be a sequence of slugs")
        slugs = tuple(categories)
        if not slugs:
            raise ValueError("a climb eval needs at least one behavioral category")
        if len(slugs) != len(set(slugs)):
            raise ValueError("categories must be unique")
        for slug in slugs:
            if not isinstance(slug, str) or _CATEGORY_RE.fullmatch(slug) is None:
                raise ValueError(f"category must be a slug, got {slug!r}")
        self.behavior = behavior
        self.split = split
        self.categories = tuple(sorted(slugs))

    def as_dict(self) -> dict[str, object]:
        return {
            "behavior": self.behavior.value,
            "categories": list(self.categories),
            "split": self.split.value,
        }
