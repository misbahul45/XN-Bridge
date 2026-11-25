from ..spec import DomainSpec, StageSpec

SPEC = DomainSpec(
    name="data",
    version=1,
    skill="xn-bridge",
    description="Collect permitted browser datasets and work with local references",
    stages=(
        StageSpec("collect", "Resolve registered source scope and start collection", capabilities=("data.collect",), optional_capabilities=("data.source.read",), risk="LOCAL_WRITE"),
        StageSpec("query", "Read dataset records and coverage", capabilities=("data.dataset.query",), optional_capabilities=("social.workflow.status",)),
        StageSpec("export", "Write a local dataset export", capabilities=("data.dataset.export",), risk="LOCAL_WRITE", optional=True),
    ),
)
