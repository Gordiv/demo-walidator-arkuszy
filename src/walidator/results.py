"""Statistics collected during a check, used by the CLI summary, the GUI and the HTML report."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from walidator.model import ColumnRule, ColumnType
from walidator.readers import SourceInfo

MAX_FIX_EXAMPLES = 4
MAX_PROBLEMS = 500
MAX_DISTINCT_TRACKED = 50_000
MAX_NEAR_DUPLICATE_GROUPS = 100  # kept in the result and listed in the report


@dataclass(slots=True)
class Problem:
    row: int
    column: str
    value: str
    reason: str
    category: str


@dataclass(slots=True)
class ColumnStats:
    rule: ColumnRule
    filled: int = 0
    empty: int = 0
    invalid: int = 0
    fixed: int = 0
    minimum: object = None
    maximum: object = None
    fix_examples: list[tuple[str, str]] = field(default_factory=list)
    _distinct: set[str] = field(default_factory=set)
    distinct_overflow: bool = False

    @property
    def name(self) -> str:
        return self.rule.name

    @property
    def distinct(self) -> int:
        return len(self._distinct)

    @property
    def valid_share(self) -> float:
        """Share of filled cells that are valid (1.0 for a column with no data)."""
        return 1.0 if not self.filled else (self.filled - self.invalid) / self.filled

    def record_value(self, text: str, value: object) -> None:
        if not self.distinct_overflow:
            self._distinct.add(text)
            self.distinct_overflow = len(self._distinct) >= MAX_DISTINCT_TRACKED
        if self.rule.type in {ColumnType.INTEGER, ColumnType.DECIMAL, ColumnType.DATE}:
            if self.minimum is None or value < self.minimum:  # type: ignore[operator]
                self.minimum = value
            if self.maximum is None or value > self.maximum:  # type: ignore[operator]
                self.maximum = value

    def record_fix(self, before: str, after: str) -> None:
        self.fixed += 1
        example = (before, after)
        if len(self.fix_examples) < MAX_FIX_EXAMPLES and example not in self.fix_examples:
            self.fix_examples.append(example)


@dataclass(slots=True)
class NearDuplicateGroup:
    column: str
    rows: list[tuple[int, str]]


@dataclass(slots=True)
class OutputPaths:
    clean: Path
    rejected: Path
    report: Path | None


@dataclass(slots=True)
class RunResult:
    source: SourceInfo
    columns: list[ColumnStats]
    outputs: OutputPaths
    started_at: datetime
    rules_source: str | None = None
    similarity_key: str | None = None
    total: int = 0
    fixed: int = 0
    rejected: int = 0
    duplicates: int = 0
    elapsed: float = 0.0
    categories: Counter[str] = field(default_factory=Counter)
    problems: list[Problem] = field(default_factory=list)
    problems_total: int = 0
    near_duplicates: list[NearDuplicateGroup] = field(default_factory=list)
    near_duplicate_rows: int = 0
    near_duplicate_groups: int = 0
    warnings: list[str] = field(default_factory=list)

    def add_problem(self, problem: Problem) -> None:
        """Counts every problem but keeps only the first ones for the report."""
        self.problems_total += 1
        if len(self.problems) < MAX_PROBLEMS:
            self.problems.append(problem)

    @property
    def accepted(self) -> int:
        return self.total - self.rejected

    @property
    def unchanged(self) -> int:
        return self.accepted - self.fixed

    @property
    def rows_per_second(self) -> float:
        return self.total / self.elapsed if self.elapsed else 0.0
