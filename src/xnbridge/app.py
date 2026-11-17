from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from pathlib import Path

from .approval import ApprovalService
from .artifacts import ArtifactStore
from .config import Settings, load_settings
from .evidence import EvidenceService
from .executions import ExecutionService
from .registry import Registry
from .security import RiskClassifier
from .spec import DomainRegistry
from .store import Store
from .workflow import WorkflowEngine


@dataclass
class Bridge:
    settings: Settings
    store: Store
    artifacts: ArtifactStore
    evidence: EvidenceService
    approvals: ApprovalService
    domains: DomainRegistry
    engine: WorkflowEngine
    classifier: RiskClassifier
    executions: ExecutionService
    registry: Registry


def build(home: Path | None = None, *, domains: bool = True) -> Bridge:
    settings = load_settings(home)
    settings.ensure_dirs()
    store = Store(settings.db_path)
    artifacts = ArtifactStore(settings, store)
    evidence = EvidenceService(settings, store, artifacts)
    approvals = ApprovalService(settings, store, artifacts)
    registry_domains = DomainRegistry()
    if domains:
        from .domains import register_all

        register_all(registry_domains)
    engine = WorkflowEngine(settings, store, registry_domains)
    classifier = RiskClassifier(settings.policy)
    executions = ExecutionService(settings, store, engine, approvals, evidence, classifier)
    registry = Registry(settings, store, classifier)
    return Bridge(settings, store, artifacts, evidence, approvals, registry_domains, engine, classifier, executions, registry)


def configure_logging(settings: Settings, level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger("xnbridge")
    if logger.handlers:
        return logger
    logger.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    stderr_h = logging.StreamHandler(sys.stderr)
    stderr_h.setFormatter(fmt)
    logger.addHandler(stderr_h)
    try:
        settings.logs_dir.mkdir(parents=True, exist_ok=True)
        file_h = logging.FileHandler(settings.logs_dir / "bridge.log", encoding="utf-8")
        file_h.setFormatter(fmt)
        logger.addHandler(file_h)
    except OSError:
        pass
    logger.propagate = False
    return logger
