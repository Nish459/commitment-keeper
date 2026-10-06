from pathlib import Path

import pytest

from kept.cli import exit_code, format_result, main
from kept.domain.models import Draft
from kept.services.sweep import SweepFailure, SweepResult


def _draft(draft_id: int, commitment_id: int) -> Draft:
    return Draft(id=draft_id, commitment_id=commitment_id, subject=f"Subject {draft_id}", body="b")


def test_summary_lists_drafts_failures_deferred_work_and_early_stops() -> None:
    result = SweepResult(
        prepared=[_draft(1, 10), _draft(2, 11)],
        failed=[SweepFailure(commitment_id=12, description="Book venue", reason="search is down")],
        skipped=3,
        stopped="allowance used",
    )
    text = format_result(result)
    assert "Prepared 2 draft(s)" in text
    assert "draft 1 for promise 10: Subject 1" in text
    assert "promise 12 (Book venue): search is down" in text
    assert "3 more are due soon" in text
    assert "Stopped early: allowance used" in text


def test_nothing_to_do_is_a_calm_success() -> None:
    assert format_result(SweepResult()) == "Prepared 0 draft(s) for review."
    assert exit_code(SweepResult()) == 0


def test_a_run_fails_only_when_everything_it_tried_failed() -> None:
    failure = SweepFailure(commitment_id=1, description="d", reason="r")
    assert exit_code(SweepResult(failed=[failure])) == 1
    assert exit_code(SweepResult(prepared=[_draft(1, 1)], failed=[failure])) == 0


def test_the_command_runs_end_to_end_against_an_empty_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("KEPT_DB_PATH", str(tmp_path / "cli.db"))
    monkeypatch.chdir(tmp_path)
    assert main(["sweep", "--horizon", "7", "--max", "2", "--json"]) == 0
    assert '"prepared": []' in capsys.readouterr().out


def test_a_subcommand_is_required() -> None:
    with pytest.raises(SystemExit):
        main([])
