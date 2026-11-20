import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "career_trigger_hook.py"

spec = importlib.util.spec_from_file_location("career_trigger_hook", SCRIPT)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


def run(stdin):
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT)],
        input=stdin, capture_output=True, text=True, check=False,
    )


@pytest.mark.parametrize("prompt", [
    "cari PKL di Surabaya",
    "bantu aku magang semester depan",
    "Apakah aku harus melamar ke Pelindo sebelum 22 Nov?",
    "kirim email lamaran ke 100 perusahaan",
    "scrape lowongan dari Jobstreet dan Glints",
    "ada loker entry-level untuk fresh graduate?",
    "MagangHub automation check",
    "I want an internship at a logistics company",
    "help me with a job application and CV matching",
    "should I apply for the position before Friday",
    "find the careers page of this company",
])
def test_career_requests_match(prompt):
    assert hook.matches(prompt)


@pytest.mark.parametrize("prompt", [
    "fix the cron job that runs nightly",
    "the background job queue is stuck",
    "refactor the internal tool module",
    "write a unit test for the parser",
    "deploy the dashboard to staging",
    "",
])
def test_unrelated_requests_do_not_match(prompt):
    assert not hook.matches(prompt)


def test_platform_name_is_matched_even_when_the_word_has_another_meaning():
    assert hook.matches("explain how glints of light render in this shader")


@pytest.mark.parametrize("value", [None, 5, ["pkl"], {"prompt": "pkl"}])
def test_non_string_input_never_matches(value):
    assert not hook.matches(value)


def test_match_emits_additional_context_json():
    result = run(json.dumps({"prompt": "cari PKL di Surabaya"}))
    assert result.returncode == 0
    body = json.loads(result.stdout)
    output = body["hookSpecificOutput"]
    assert output["hookEventName"] == "UserPromptSubmit"
    assert "XN-Bridge" in output["additionalContext"]
    assert "AGENTS.md" in output["additionalContext"]


def test_no_match_prints_nothing():
    result = run(json.dumps({"prompt": "write a unit test"}))
    assert result.returncode == 0
    assert result.stdout == ""


@pytest.mark.parametrize("stdin", ["", "not json", "[1, 2]", "null", json.dumps({"other": "pkl"})])
def test_bad_or_missing_prompt_is_silent_success(stdin):
    result = run(stdin)
    assert result.returncode == 0
    assert result.stdout == ""


def test_scan_is_bounded():
    late = "x" * (hook.MAX_SCAN + 10) + " pkl"
    assert not hook.matches(late)


@pytest.mark.parametrize("prompt", [
    "posting ke linkedin dan threads: rilis fitur baru",
    "balas komentar terbaru di instagram",
    "lihat analytics tiktok minggu ini",
    "hubungkan akun reddit saya",
])
def test_social_requests_get_the_social_reminder(prompt):
    assert hook.social_matches(prompt) and not hook.matches(prompt)
    out = run(json.dumps({"prompt": prompt})).stdout
    assert "social trigger" in json.loads(out)["hookSpecificOutput"]["additionalContext"]


@pytest.mark.parametrize("prompt", ["cari lowongan magang di linkedin", "apply for the internship posted on linkedin"])
def test_career_wins_over_social(prompt):
    assert hook.matches(prompt) and not hook.social_matches(prompt)
    assert "career trigger" in json.loads(run(json.dumps({"prompt": prompt})).stdout)["hookSpecificOutput"]["additionalContext"]


def test_platform_without_action_is_silent():
    assert not hook.social_matches("apa itu threads dalam python")
