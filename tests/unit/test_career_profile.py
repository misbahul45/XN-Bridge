from __future__ import annotations

import pytest

from tests.career_helpers import FIX, act, confirm_all, ingest_cv, new_career
from xnbridge import entities
from xnbridge.errors import PolicyDenied, ValidationFailed


def profile_data(bridge, wf):
    from xnbridge.domains.career.profile import latest_profile

    with bridge.store.read() as con:
        return latest_profile(con, wf)["data"]


def test_extraction_is_grounded_in_the_cv(bridge):
    wf = new_career(bridge)
    out = ingest_cv(bridge, wf)
    d = profile_data(bridge, wf)
    skills = {s["name"] for s in d["skills"]}
    assert {"python", "fastapi", "postgresql", "docker", "git", "scikit-learn", "pandas", "react", "javascript", "linux"} <= skills
    assert not ({"java", "kubernetes", "rust", "tensorflow"} & skills)
    assert len(d["projects"]) == 2 and len(d["education"]) >= 1 and len(d["experience"]) >= 1
    assert d["candidates"]["graduation_year"] == [2027] and d["candidates"]["gpa"] == ["3.72"]
    assert all(s["source"].startswith("cv_good.md#L") for s in d["skills"])
    assert {"availability", "work_authorization", "student_status", "work_preference"} <= set(d["unknown"])
    assert out["version"] == 1 and out["contact_on_file"]["phone"] is True


def test_extracted_document_text_binds_to_original_evidence(bridge):
    wf = new_career(bridge)
    text = (FIX / "cv_good.md").read_text()
    ev = bridge.evidence.register(workflow_id=wf, claim="Extracted local CV", origin="local_file", requested="VERIFIED", source_ref=str(FIX / "cv_good.md"), content=text)
    out = act(bridge, wf, "profile.ingest", {"text": text, "evidence_id": ev["id"], "extractor": "markitdown"})
    assert out["evidence_id"] == ev["id"]
    with pytest.raises(ValidationFailed, match="exact text"):
        act(bridge, wf, "profile.ingest", {"text": text + "\nI know Rust", "evidence_id": ev["id"]})
    other = new_career(bridge)
    with pytest.raises(ValidationFailed, match="this workflow"):
        act(bridge, other, "profile.ingest", {"text": text, "evidence_id": ev["id"]})


def test_contact_only_cv_changes_create_a_new_profile_version(bridge, tmp_path):
    wf = new_career(bridge)
    first = ingest_cv(bridge, wf)
    path = tmp_path / "cv-changed.md"
    path.write_text((FIX / "cv_good.md").read_text().replace("rina.kartika@example.com", "new.contact@example.org"))
    out = act(bridge, wf, "profile.ingest", {"path": str(path)})
    assert out["version"] == first["version"] + 1
    assert profile_data(bridge, wf)["private"]["emails"] == ["new.contact@example.org"]


def test_contact_details_never_leak_into_outputs(bridge):
    wf = new_career(bridge)
    out = ingest_cv(bridge, wf)
    blob = str(out)
    assert "rina.kartika@example.com" not in blob and "812 3456" not in blob
    assert out["contact_on_file"]["email"] == ["r***@example.com"]


def test_reingest_same_cv_is_unchanged_and_new_content_versions(bridge, tmp_path):
    wf = new_career(bridge)
    ingest_cv(bridge, wf)
    again = ingest_cv(bridge, wf)
    assert again["unchanged"] is True and again["version"] == 1
    edited = tmp_path / "cv2.md"
    edited.write_text((FIX / "cv_good.md").read_text() + "\n- Built a Kubernetes lab cluster with Docker.\n")
    out = act(bridge, wf, "profile.ingest", {"path": str(edited)})
    assert out["unchanged"] is False and out["version"] == 2
    with bridge.store.read() as con:
        rows = entities.listing(con, wf, "profile")
    assert {r["dedupe_key"]: r["status"] for r in rows} == {"v1": "SUPERSEDED", "v2": "CURRENT"}


def test_confirm_adds_facts_with_evidence_and_carries_across_versions(bridge, tmp_path):
    wf = new_career(bridge)
    ingest_cv(bridge, wf)
    out = confirm_all(bridge, wf)
    assert out["version"] == 2 and "availability" in out["confirmed"]
    d = profile_data(bridge, wf)
    assert d["confirmed"]["student_status"]["value"] == "enrolled"
    ev = bridge.evidence.get(d["confirmed"]["student_status"]["evidence_id"])
    assert ev["origin"] == "user_statement" and ev["verification"] == "VERIFIED" and ev["excerpt"]
    edited = tmp_path / "cv3.md"
    edited.write_text((FIX / "cv_good.md").read_text() + "\n- Built a CLI tool in Python.\n")
    act(bridge, wf, "profile.ingest", {"path": str(edited)})
    assert "student_status" in profile_data(bridge, wf)["confirmed"]


def test_conflicts_are_surfaced_and_resolved_only_by_user(bridge):
    wf = new_career(bridge)
    out = ingest_cv(bridge, wf, "cv_conflict.md")
    fields = {c["field"]: c["values"] for c in out["conflicts"]}
    assert fields["graduation_year"] == [2026, 2027] and fields["gpa"] == ["3.40", "3.55"]
    res = act(bridge, wf, "profile.confirm", {"facts": {"graduation_year": 2027}, "quote": "I graduate in 2027"})
    assert {c["field"] for c in res["conflicts"]} == {"gpa"}


def test_unsafe_or_unsupported_inputs_rejected(bridge, tmp_path):
    wf = new_career(bridge)
    with pytest.raises(PolicyDenied):
        act(bridge, wf, "profile.ingest", {"path": "/etc/passwd"})
    with pytest.raises(PolicyDenied):
        act(bridge, wf, "profile.ingest", {"path": str(__import__("pathlib").Path.home() / ".ssh" / "id_rsa")})
    pdf = tmp_path / "cv.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    with pytest.raises(ValidationFailed):
        act(bridge, wf, "profile.ingest", {"path": str(pdf)})
    with pytest.raises(ValidationFailed):
        act(bridge, wf, "profile.ingest", {"text": "too short"})
    with pytest.raises(ValidationFailed):
        act(bridge, wf, "profile.ingest", {"text": "x" * 100, "path": str(FIX / "cv_good.md")})
    ingest_cv(bridge, wf)
    for bad in ({"citizenship": "X"}, {"gpa": 9.9}, {"student_status": "wizard"}, {"graduation_year": "soon"}):
        with pytest.raises(ValidationFailed):
            act(bridge, wf, "profile.confirm", {"facts": bad, "quote": "because I said so"})


def test_no_profile_means_actions_that_need_one_fail_loudly(bridge):
    from xnbridge.errors import NotFound

    wf = new_career(bridge)
    with pytest.raises(NotFound):
        act(bridge, wf, "match.run", {})
