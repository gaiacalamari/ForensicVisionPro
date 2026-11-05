"""Base comune dei parser di struttura. I parser leggono solo, con limiti espliciti."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.findings import Finding

MAX_NODES = 200_000


class ParseLimit(Exception):
    pass


@dataclass
class Node:
    name: str
    offset: int
    length: int
    fields: dict[str, Any] = field(default_factory=dict)
    children: list["Node"] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"name": self.name, "offset": self.offset, "length": self.length, "fields": self.fields,
                "children": [c.to_dict() for c in self.children]}

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


@dataclass
class ParseResult:
    format: str
    root: Node
    findings: list[Finding] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"format": self.format, "root": self.root.to_dict(), "extra": self.extra}
