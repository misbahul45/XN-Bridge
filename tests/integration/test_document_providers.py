"""Optional live local-provider test; no private CVs and no application submission."""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

import anyio
import pytest
from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client

from xnbridge.actions import dispatch_action
from xnbridge.app import build
from xnbridge.hosts import load_host_servers


@pytest.mark.providers
@pytest.mark.skipif(os.environ.get("XN_RUN_PROVIDER_TESTS") != "1", reason="set XN_RUN_PROVIDER_TESTS=1 for installed local document providers")
def test_actual_pdf_generation_extraction_and_profile_ingestion(tmp_path):
    specs = {s.name: s for s in load_host_servers("codex")}
    for name in ("document_generator", "markitdown"):
        assert name in specs and specs[name].transport == "stdio", f"missing local provider {name}"

    def params(name):
        s = specs[name]
        args = list(s.args)
        if Path(s.command).name in ("npx", "uvx"):
            args.insert(0, "--offline")
        return StdioServerParameters(command=s.command, args=args, env=s.env, cwd=str(tmp_path))

    text = "Education\nBachelor of Computer Science, Example University, expected graduation 2027.\nSkills\nPython, SQL, PostgreSQL, Git, Linux\nProjects\nBuilt a Python REST API with PostgreSQL.\nLanguages\nEnglish: professional."

    async def run():
        with tempfile.TemporaryFile(mode="w+") as errlog:
            async with Client(stdio_client(params("document_generator"), errlog=errlog), mode="legacy") as c:
                result = await c.call_tool("gerar_documento_pdf", {"nome_arquivo": "synthetic-cv", "titulo_documento": "Synthetic Candidate CV", "conteudo_principal": text})
                assert not result.is_error
                output = "\n".join(x.text for x in result.content if hasattr(x, "text"))
                match = re.search(r"PDF:\s*(.+\.pdf)", output)
                assert match, output
                path = Path(match.group(1).strip()).resolve()
                assert path.is_relative_to(tmp_path.resolve()) and path.read_bytes().startswith(b"%PDF")
            async with Client(stdio_client(params("markitdown"), errlog=errlog)) as c:
                result = await c.call_tool("convert_to_markdown", {"uri": path.as_uri()})
                assert not result.is_error
                extracted = (result.structured_content or {}).get("result") or "\n".join(x.text for x in result.content if hasattr(x, "text"))
        assert "Python" in extracted and "2027" in extracted
        b = build(tmp_path / "state")
        wf = b.engine.create("career")["id"]
        ev = b.evidence.register(workflow_id=wf, claim="Text extracted from the generated local PDF", origin="local_file", requested="VERIFIED", source_ref=str(path), content=extracted, provider="markitdown:convert_to_markdown")
        out = dispatch_action(b, "career", "profile.ingest", wf, {"text": extracted, "evidence_id": ev["id"], "extractor": "markitdown", "label": "synthetic-cv.pdf"}, "SUMMARY")
        assert {"python", "postgresql", "git"} <= set(out["skills"])
        assert out["evidence_id"] == ev["id"]
        assert b.evidence.get(ev["id"])["verification"] == "VERIFIED"
        assert b.store.integrity()["ok"]

    anyio.run(run)
