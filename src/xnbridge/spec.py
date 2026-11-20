from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

RISKS = ("READ", "LOCAL_WRITE", "EXTERNAL_WRITE")


@dataclass(frozen=True)
class StageSpec:
    name: str
    goal: str
    capabilities: tuple[str, ...] = ()
    optional_capabilities: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    risk: str = "READ"
    optional: bool = False
    actions: tuple[str, ...] = ()


@dataclass(frozen=True)
class DomainSpec:
    name: str
    version: int
    skill: str | None
    stages: tuple[StageSpec, ...]
    description: str = ""

    def stage(self, name: str) -> StageSpec:
        for s in self.stages:
            if s.name == name:
                return s
        raise KeyError(name)

    def index(self, name: str) -> int:
        for i, s in enumerate(self.stages):
            if s.name == name:
                return i
        raise KeyError(name)

    @property
    def stage_names(self) -> tuple[str, ...]:
        return tuple(s.name for s in self.stages)


@dataclass
class ActionDef:
    domain: str
    name: str
    stage: str
    risk: str
    handler: Callable
    summary: str = ""
    payload_model: type | None = None
    needs_workflow: bool = True
    safe_when_pending: bool = False


class DomainRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, DomainSpec] = {}
        self._actions: dict[tuple[str, str], ActionDef] = {}

    def register(self, spec: DomainSpec, actions: list[ActionDef]) -> None:
        self._specs[spec.name] = spec
        for a in actions:
            self._actions[(a.domain, a.name)] = a

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))

    def specs(self) -> tuple[DomainSpec, ...]:
        return tuple(self._specs[n] for n in sorted(self._specs))

    def spec(self, name: str) -> DomainSpec:
        from .errors import NotFound

        if name not in self._specs:
            raise NotFound(f"unknown domain '{name}'", details={"known": sorted(self._specs)})
        return self._specs[name]

    def action(self, domain: str, name: str) -> ActionDef:
        from .errors import NotFound

        a = self._actions.get((domain, name))
        if a is None:
            raise NotFound(
                f"unknown action '{domain}.{name}'",
                details={"known": sorted(n for (d, n) in self._actions if d == domain)},
            )
        return a

    def domains(self) -> list[str]:
        return sorted(self._specs)

    def actions(self, domain: str) -> list[ActionDef]:
        return [a for (d, _), a in sorted(self._actions.items()) if d == domain]


@dataclass
class Ctx:
    bridge: Any
    workflow: dict | None

    @property
    def workflow_id(self) -> str:
        return self.workflow["id"] if self.workflow else ""
