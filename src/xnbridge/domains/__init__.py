from __future__ import annotations

from ..spec import DomainRegistry


def register_all(registry: DomainRegistry) -> None:
    from . import career, data, research, social

    registry.register(research.SPEC, research.actions())
    registry.register(career.SPEC, career.actions())
    registry.register(social.SPEC, social.actions())
    registry.register(data.SPEC, {})
