import argparse
import importlib.util
import sys
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).with_name("gh_pr_watch.py")
MODULE_SPEC = importlib.util.spec_from_file_location("gh_pr_watch", MODULE_PATH)
gh_pr_watch = importlib.util.module_from_spec(MODULE_SPEC)
assert MODULE_SPEC.loader is not None
MODULE_SPEC.loader.exec_module(gh_pr_watch)


def sample_pr():
    return {
        "number": 123,
        "url": "https://github.com/openai/codex/pull/123",
        "repo": "openai/codex",
        "head_sha": "abc123",
        "head_branch": "feature",
        "state": "OPEN",
        "merged": False,
        "closed": False,
        "mergeable": "MERGEABLE",
        "merge_state_status": "CLEAN",
        "review_decision": "",
    }


def sample_checks(**overrides):
    checks = {
        "pending_count": 0,
        "failed_count": 0,
        "passed_count": 12,
        "all_terminal": True,
    }
    checks.update(overrides)
    return checks


def sample_copilot_review(**overrides):
    review = {
        "requester": "@copilot",
        "requested_reviewer": "Copilot",
        "request_attempted": True,
        "request_succeeded": True,
        "request_unavailable": False,
        "request_retryable": False,
        "request_error": None,
        "requested_reviewers_confirmed": True,
        "pending": False,
        "requested_reviewer_logins": [],
    }
    review.update(overrides)
    return review


def test_parse_args_watch_defaults_to_quiet(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["gh_pr_watch.py", "--watch"])

    args = gh_pr_watch.parse_args()

    assert args.watch is True
    assert args.full_watch is False
    assert args.once is False
    assert args.poll_seconds == 60
    assert args.watch_heartbeat_seconds == 900
    assert args.heartbeat_format == "minimal"


def test_parse_args_quiet_watch_implies_watch(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["gh_pr_watch.py", "--quiet-watch"])

    args = gh_pr_watch.parse_args()

    assert args.watch is True
    assert args.quiet_watch is True
    assert args.full_watch is False
    assert args.once is False


def test_parse_args_rejects_quiet_and_full_watch(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["gh_pr_watch.py", "--quiet-watch", "--full-watch"])

    with pytest.raises(SystemExit):
        gh_pr_watch.parse_args()


def test_collect_snapshot_fetches_review_items_before_ci(monkeypatch, tmp_path):
    call_order = []
    pr = sample_pr()

    monkeypatch.setattr(gh_pr_watch, "resolve_pr", lambda *args, **kwargs: pr)
    monkeypatch.setattr(gh_pr_watch, "load_state", lambda path: ({}, True))
    monkeypatch.setattr(
        gh_pr_watch,
        "get_authenticated_login",
        lambda: call_order.append("auth") or "octocat",
    )
    monkeypatch.setattr(
        gh_pr_watch,
        "get_requested_reviewers_best_effort",
        lambda *args, **kwargs: call_order.append("requested_reviewers") or ({"users": [], "teams": []}, None),
    )
    monkeypatch.setattr(
        gh_pr_watch,
        "request_copilot_review_if_possible",
        lambda *args, **kwargs: call_order.append("copilot") or sample_copilot_review(),
    )
    monkeypatch.setattr(
        gh_pr_watch,
        "fetch_new_review_items",
        lambda *args, **kwargs: call_order.append("review") or [],
    )
    monkeypatch.setattr(
        gh_pr_watch,
        "get_pr_checks",
        lambda *args, **kwargs: call_order.append("checks") or [],
    )
    monkeypatch.setattr(
        gh_pr_watch,
        "summarize_checks",
        lambda checks: call_order.append("summarize") or sample_checks(),
    )
    monkeypatch.setattr(
        gh_pr_watch,
        "get_workflow_runs_for_sha",
        lambda *args, **kwargs: call_order.append("workflow") or [],
    )
    monkeypatch.setattr(
        gh_pr_watch,
        "failed_runs_from_workflow_runs",
        lambda *args, **kwargs: call_order.append("failed_runs") or [],
    )
    monkeypatch.setattr(
        gh_pr_watch,
        "failed_jobs_from_workflow_runs",
        lambda *args, **kwargs: call_order.append("failed_jobs") or [],
    )
    monkeypatch.setattr(
        gh_pr_watch,
        "recommend_actions",
        lambda *args, **kwargs: call_order.append("recommend") or ["idle"],
    )
    monkeypatch.setattr(gh_pr_watch, "save_state", lambda *args, **kwargs: None)

    args = argparse.Namespace(
        pr="123",
        repo=None,
        state_file=str(tmp_path / "watcher-state.json"),
        max_flaky_retries=3,
    )

    gh_pr_watch.collect_snapshot(args)

    assert call_order.index("copilot") < call_order.index("review")
    assert call_order.index("review") < call_order.index("checks")
    assert call_order.index("review") < call_order.index("workflow")


def test_recommend_actions_prioritizes_review_comments():
    actions = gh_pr_watch.recommend_actions(
        sample_pr(),
        sample_checks(failed_count=1),
        [{"run_id": 99}],
        [],
        [{"kind": "review_comment", "id": "1"}],
        0,
        3,
    )

    assert actions == [
        "process_review_comment",
        "diagnose_ci_failure",
        "retry_failed_checks",
    ]


def test_recommend_actions_stops_when_retry_budget_is_exhausted():
    actions = gh_pr_watch.recommend_actions(
        sample_pr(),
        sample_checks(failed_count=1),
        [{"run_id": 99}],
        [],
        [],
        3,
        3,
    )

    assert actions == ["stop_exhausted_retries"]


def test_recommend_actions_diagnoses_failed_job_before_workflow_terminal():
    actions = gh_pr_watch.recommend_actions(
        sample_pr(),
        sample_checks(failed_count=0, pending_count=1, all_terminal=False),
        [],
        [{"run_id": 99, "job_id": 555}],
        [],
        0,
        3,
    )

    assert actions == ["diagnose_ci_failure"]


def test_retry_failed_now_reruns_failed_runs_and_increments_retry_count(monkeypatch, tmp_path):
    state_path = tmp_path / "watcher-state.json"
    state = {"retries_by_sha": {"abc123": 1}}
    saves = []
    reruns = []
    snapshot = {
        "pr": sample_pr(),
        "checks": sample_checks(failed_count=1),
        "failed_runs": [{"run_id": 99}, {"run_id": 100}],
        "failed_jobs": [],
        "new_review_items": [],
        "actions": ["diagnose_ci_failure", "retry_failed_checks"],
        "retry_state": {
            "current_sha_retries_used": 1,
            "max_flaky_retries": 3,
        },
    }

    monkeypatch.setattr(gh_pr_watch, "collect_snapshot", lambda args: (snapshot, state_path))
    monkeypatch.setattr(gh_pr_watch, "load_state", lambda path: (state, False))
    monkeypatch.setattr(gh_pr_watch, "save_state", lambda path, next_state: saves.append(dict(next_state)))
    monkeypatch.setattr(gh_pr_watch, "gh_text", lambda args, repo=None: reruns.append((args, repo)) or "")

    result = gh_pr_watch.retry_failed_now(
        argparse.Namespace(max_flaky_retries=3)
    )

    assert result["reason"] == "rerun_triggered"
    assert result["rerun_run_ids"] == [99, 100]
    assert reruns == [
        (["run", "rerun", "99", "--failed"], "openai/codex"),
        (["run", "rerun", "100", "--failed"], "openai/codex"),
    ]
    assert saves[-1]["retries_by_sha"]["abc123"] == 2


def test_retry_failed_now_respects_retry_budget(monkeypatch, tmp_path):
    snapshot = {
        "pr": sample_pr(),
        "checks": sample_checks(failed_count=1),
        "failed_runs": [{"run_id": 99}],
        "failed_jobs": [],
        "new_review_items": [],
        "actions": ["stop_exhausted_retries"],
        "retry_state": {
            "current_sha_retries_used": 3,
            "max_flaky_retries": 3,
        },
    }
    reruns = []

    monkeypatch.setattr(
        gh_pr_watch,
        "collect_snapshot",
        lambda args: (snapshot, tmp_path / "watcher-state.json"),
    )
    monkeypatch.setattr(gh_pr_watch, "gh_text", lambda args, repo=None: reruns.append((args, repo)) or "")

    result = gh_pr_watch.retry_failed_now(
        argparse.Namespace(max_flaky_retries=3)
    )

    assert result["reason"] == "retry_budget_exhausted"
    assert reruns == []


def test_requested_reviewer_logins_extracts_users_only():
    requested_reviewers = {
        "users": [{"login": "Copilot"}, {"login": "octocat"}, {"name": "missing-login"}],
        "teams": [{"slug": "reviewers"}],
    }

    assert gh_pr_watch.requested_reviewer_logins(requested_reviewers) == [
        "Copilot",
        "octocat",
    ]


def test_has_pending_copilot_review_from_requested_reviewers():
    assert gh_pr_watch.has_pending_copilot_review({"users": [{"login": "Copilot"}]})
    assert gh_pr_watch.has_pending_copilot_review(
        {"users": [{"login": "copilot-pull-request-reviewer[bot]"}]}
    )
    assert not gh_pr_watch.has_pending_copilot_review({"users": [{"login": "octocat"}]})


def test_permanent_copilot_request_error_classification():
    assert gh_pr_watch.is_permanent_copilot_request_error("reviewer not found")
    assert gh_pr_watch.is_permanent_copilot_request_error("Could not resolve to a user")
    assert not gh_pr_watch.is_permanent_copilot_request_error("404 Not Found")
    assert not gh_pr_watch.is_permanent_copilot_request_error("network timeout")


def test_request_copilot_review_records_success_and_pending_reviewer(monkeypatch):
    calls = []
    pr = sample_pr()
    state = {}

    def fake_gh_text(args, repo=None):
        calls.append((args, repo))
        return ""

    monkeypatch.setattr(gh_pr_watch, "gh_text", fake_gh_text)
    monkeypatch.setattr(
        gh_pr_watch,
        "get_requested_reviewers",
        lambda repo, pr_number: {"users": [{"login": "Copilot"}], "teams": []},
    )

    status = gh_pr_watch.request_copilot_review_if_possible(
        pr,
        state,
        {"users": [], "teams": []},
    )

    assert calls == [
        (["pr", "edit", "123", "--add-reviewer", "@copilot"], "openai/codex")
    ]
    assert status["request_attempted"] is True
    assert status["request_succeeded"] is True
    assert status["request_unavailable"] is False
    assert status["pending"] is True
    assert status["requested_reviewers_confirmed"] is True
    assert state["copilot_review"]["head_sha"] == "abc123"


def test_request_copilot_review_allows_retry_after_transient_error(monkeypatch):
    pr = sample_pr()
    state = {}

    monkeypatch.setattr(gh_pr_watch.time, "time", lambda: 1000)

    def fake_gh_text(args, repo=None):
        raise gh_pr_watch.GhCommandError("network timeout")

    monkeypatch.setattr(gh_pr_watch, "gh_text", fake_gh_text)

    status = gh_pr_watch.request_copilot_review_if_possible(
        pr,
        state,
        {"users": [], "teams": []},
    )

    assert status["request_attempted"] is True
    assert status["request_succeeded"] is False
    assert status["request_unavailable"] is False
    assert status["request_retryable"] is True
    assert "network timeout" in status["request_error"]
    assert state["copilot_review"]["request_attempted"] is False
    assert state["copilot_review"]["request_retryable"] is True
    assert state["copilot_review"]["last_request_attempt_at"] == 1000
    assert state["copilot_review"]["request_retry_after"] == 1300


def test_request_copilot_review_treats_admin_rights_as_unavailable(monkeypatch):
    pr = sample_pr()
    state = {}

    monkeypatch.setattr(gh_pr_watch.time, "time", lambda: 1000)

    def fake_gh_text(args, repo=None):
        raise gh_pr_watch.GhCommandError("HTTP 403: Must have admin rights to Repository. " + ("x" * 2000))

    monkeypatch.setattr(gh_pr_watch, "gh_text", fake_gh_text)

    status = gh_pr_watch.request_copilot_review_if_possible(
        pr,
        state,
        {"users": [], "teams": []},
    )

    assert status["request_attempted"] is True
    assert status["request_succeeded"] is False
    assert status["request_unavailable"] is True
    assert status["request_retryable"] is False
    assert status["request_retry_after"] is None
    assert "Must have admin rights" in status["request_error"]
    assert len(status["request_error"]) <= gh_pr_watch.MAX_ERROR_CHARS
    assert state["copilot_review"]["request_attempted"] is True


def test_request_copilot_review_defers_retry_until_retry_after(monkeypatch):
    pr = sample_pr()
    state = {
        "copilot_review": {
            "head_sha": "abc123",
            "request_attempted": False,
            "request_succeeded": False,
            "request_unavailable": False,
            "request_retryable": True,
            "request_error": "network timeout",
            "last_request_attempt_at": 1000,
            "request_retry_after": 1300,
        }
    }

    def fake_gh_text(args, repo=None):
        raise AssertionError("should not retry before request_retry_after")

    monkeypatch.setattr(gh_pr_watch, "gh_text", fake_gh_text)
    monkeypatch.setattr(gh_pr_watch.time, "time", lambda: 1200)

    status = gh_pr_watch.request_copilot_review_if_possible(
        pr,
        state,
        {"users": [], "teams": []},
    )

    assert status["request_retryable"] is True
    assert status["pending_unknown"] is True


def test_request_copilot_review_retries_after_retry_after(monkeypatch):
    pr = sample_pr()
    state = {
        "copilot_review": {
            "head_sha": "abc123",
            "request_attempted": False,
            "request_succeeded": False,
            "request_unavailable": False,
            "request_retryable": True,
            "request_error": "network timeout",
            "last_request_attempt_at": 1000,
            "request_retry_after": 1300,
        }
    }
    calls = []

    def fake_gh_text(args, repo=None):
        calls.append((args, repo))
        return ""

    monkeypatch.setattr(gh_pr_watch, "gh_text", fake_gh_text)
    monkeypatch.setattr(gh_pr_watch.time, "time", lambda: 1400)
    monkeypatch.setattr(
        gh_pr_watch,
        "get_requested_reviewers",
        lambda repo, pr_number: {"users": [{"login": "Copilot"}], "teams": []},
    )

    status = gh_pr_watch.request_copilot_review_if_possible(
        pr,
        state,
        {"users": [], "teams": []},
    )

    assert calls == [
        (["pr", "edit", "123", "--add-reviewer", "@copilot"], "openai/codex")
    ]
    assert status["request_succeeded"] is True
    assert status["pending"] is True
    assert status["requested_reviewers_confirmed"] is True


def test_recommend_actions_waits_for_pending_copilot_review():
    actions = gh_pr_watch.recommend_actions(
        sample_pr(),
        sample_checks(),
        [],
        [],
        [],
        0,
        3,
        copilot_review=sample_copilot_review(pending=True),
    )

    assert actions == ["wait_for_copilot_review"]


def test_pending_copilot_review_blocks_ready_to_merge():
    assert not gh_pr_watch.is_pr_ready_to_merge(
        sample_pr(),
        sample_checks(),
        [],
        copilot_review=sample_copilot_review(pending=True),
    )


def test_pending_review_feedback_surfaces_only_after_publication(monkeypatch):
    state = {
        "seen_review_comment_ids": ["20"],
        "seen_review_ids": ["10"],
    }
    review = {
        "id": 10,
        "user": {"login": "octocat"},
        "author_association": "MEMBER",
        "state": "PENDING",
        "body": "Please rename this.",
        "created_at": "2026-06-08T10:00:00Z",
        "submitted_at": None,
        "html_url": "https://github.com/openai/codex/pull/123#pullrequestreview-10",
    }
    review_comment = {
        "id": 20,
        "pull_request_review_id": 10,
        "user": {"login": "octocat"},
        "author_association": "MEMBER",
        "body": "Please rename this.",
        "created_at": "2026-06-08T10:00:00Z",
        "path": "src/example.rs",
        "line": 7,
        "html_url": "https://github.com/openai/codex/pull/123#discussion_r20",
    }

    def fake_list(endpoint, **kwargs):
        if endpoint.endswith("/issues/123/comments"):
            return []
        if endpoint.endswith("/pulls/123/comments"):
            return [review_comment]
        if endpoint.endswith("/pulls/123/reviews"):
            return [review]
        raise AssertionError(f"unexpected endpoint: {endpoint}")

    monkeypatch.setattr(gh_pr_watch, "gh_api_list_paginated", fake_list)

    assert (
        gh_pr_watch.fetch_new_review_items(
            sample_pr(),
            state,
            fresh_state=True,
            authenticated_login="octocat",
        )
        == []
    )
    assert state["seen_review_comment_ids"] == []
    assert state["seen_review_ids"] == []

    review["state"] = "COMMENTED"
    review["submitted_at"] = "2026-06-08T10:05:00Z"

    published_items = gh_pr_watch.fetch_new_review_items(
        sample_pr(),
        state,
        fresh_state=False,
        authenticated_login="octocat",
    )

    assert {(item["kind"], item["id"]) for item in published_items} == {
        ("review", "10"),
        ("review_comment", "20"),
    }
    assert state["seen_review_comment_ids"] == ["20"]
    assert state["seen_review_ids"] == ["10"]


def test_actionable_review_bot_login_allows_common_review_automation_accounts():
    assert gh_pr_watch.is_actionable_review_bot_login("bugbot[bot]")
    assert gh_pr_watch.is_actionable_review_bot_login("claude[bot]")
    assert gh_pr_watch.is_actionable_review_bot_login("Copilot")
    assert gh_pr_watch.is_actionable_review_bot_login("copilot-pull-request-reviewer")
    assert gh_pr_watch.is_actionable_review_bot_login("coderabbitai")
    assert gh_pr_watch.is_actionable_review_bot_login("cursor[bot]")
    assert gh_pr_watch.is_actionable_review_bot_login("gemini-code-assist[bot]")
    assert gh_pr_watch.is_actionable_review_bot_login("sourcery-ai[bot]")


def test_fetch_new_review_items_ignores_untrusted_non_allowlisted_automation(monkeypatch):
    review_payload = [
        {
            "id": 789,
            "user": {"login": "random-reviewer-service"},
            "author_association": "NONE",
            "state": "COMMENTED",
            "submitted_at": "2026-04-23T14:00:00Z",
            "body": "Untrusted automation.",
            "html_url": "https://github.com/openai/codex/pull/123#pullrequestreview-789",
        }
    ]

    def fake_list(endpoint, **kwargs):
        if endpoint.endswith("/pulls/123/reviews"):
            return review_payload
        return []

    monkeypatch.setattr(gh_pr_watch, "gh_api_list_paginated", fake_list)

    state = {
        "seen_issue_comment_ids": [],
        "seen_review_comment_ids": [],
        "seen_review_ids": [],
    }
    new_items = gh_pr_watch.fetch_new_review_items(
        sample_pr(),
        state,
        fresh_state=True,
        authenticated_login="octocat",
    )

    assert new_items == []
    assert state["seen_review_ids"] == []


def test_fetch_new_review_items_bounds_long_review_payloads(monkeypatch):
    long_body = "please inspect this\n" + ("details " * 1000)
    issue_payload = [
        {
            "id": 456,
            "user": {"login": "octocat"},
            "author_association": "MEMBER",
            "created_at": "2026-04-23T14:00:00Z",
            "body": long_body,
            "html_url": "https://github.com/openai/codex/pull/123#issuecomment-456",
        }
    ]

    def fake_list(endpoint, **kwargs):
        if endpoint.endswith("/issues/123/comments"):
            return issue_payload
        return []

    monkeypatch.setattr(gh_pr_watch, "gh_api_list_paginated", fake_list)

    state = {
        "seen_issue_comment_ids": [],
        "seen_review_comment_ids": [],
        "seen_review_ids": [],
    }
    new_items = gh_pr_watch.fetch_new_review_items(
        sample_pr(),
        state,
        fresh_state=True,
        authenticated_login="octocat",
    )

    assert len(new_items) == 1
    assert new_items[0]["body_truncated"] is True
    assert len(new_items[0]["body"]) <= gh_pr_watch.MAX_REVIEW_BODY_CHARS
    assert new_items[0]["body"].endswith("[truncated]")
    assert state["seen_issue_comment_ids"] == ["456"]


def test_run_watch_keeps_polling_open_ready_to_merge_pr(monkeypatch):
    sleeps = []
    events = []
    snapshot = {
        "pr": sample_pr(),
        "checks": sample_checks(),
        "failed_runs": [],
        "failed_jobs": [],
        "new_review_items": [],
        "actions": ["ready_to_merge"],
        "retry_state": {
            "current_sha_retries_used": 0,
            "max_flaky_retries": 3,
        },
    }

    monkeypatch.setattr(
        gh_pr_watch,
        "collect_snapshot",
        lambda args: (snapshot, Path("/tmp/codex-babysit-pr-state.json")),
    )
    monkeypatch.setattr(
        gh_pr_watch,
        "print_event",
        lambda event, payload: events.append((event, payload)),
    )

    class StopWatch(Exception):
        pass

    def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= 2:
            raise StopWatch

    monkeypatch.setattr(gh_pr_watch.time, "sleep", fake_sleep)

    with pytest.raises(StopWatch):
        gh_pr_watch.run_watch(argparse.Namespace(poll_seconds=30, full_watch=True))

    assert sleeps == [30, 30]
    assert [event for event, _ in events] == ["snapshot", "snapshot"]


def test_run_watch_quiet_mode_suppresses_unchanged_snapshots(monkeypatch):
    sleeps = []
    events = []
    current_time = [1000]
    snapshot = {
        "pr": sample_pr(),
        "checks": sample_checks(pending_count=1, all_terminal=False),
        "failed_runs": [],
        "failed_jobs": [],
        "new_review_items": [],
        "actions": ["idle"],
        "retry_state": {
            "current_sha_retries_used": 0,
            "max_flaky_retries": 3,
        },
    }

    monkeypatch.setattr(
        gh_pr_watch,
        "collect_snapshot",
        lambda args: (snapshot, Path("/tmp/codex-babysit-pr-state.json")),
    )
    monkeypatch.setattr(
        gh_pr_watch,
        "print_event",
        lambda event, payload: events.append((event, payload)),
    )
    monkeypatch.setattr(gh_pr_watch.time, "time", lambda: current_time[0])

    class StopWatch(Exception):
        pass

    def fake_sleep(seconds):
        sleeps.append(seconds)
        current_time[0] += seconds
        if len(sleeps) >= 2:
            raise StopWatch

    monkeypatch.setattr(gh_pr_watch.time, "sleep", fake_sleep)

    with pytest.raises(StopWatch):
        gh_pr_watch.run_watch(
            argparse.Namespace(
                poll_seconds=30,
                watch_heartbeat_seconds=300,
            )
        )

    assert sleeps == [30, 30]
    assert [event for event, _ in events] == ["snapshot"]


def test_run_watch_quiet_mode_emits_compact_heartbeat(monkeypatch):
    sleeps = []
    events = []
    current_time = [1000]
    snapshot = {
        "pr": sample_pr(),
        "checks": sample_checks(pending_count=1, all_terminal=False),
        "failed_runs": [],
        "failed_jobs": [
            {
                "workflow_name": "CI",
                "job_name": "Build and Test",
                "status": "completed",
                "conclusion": "failure",
                "html_url": "https://github.com/openai/codex/actions/runs/99/job/555",
            }
        ],
        "new_review_items": [],
        "actions": ["diagnose_ci_failure"],
        "retry_state": {
            "current_sha_retries_used": 0,
            "max_flaky_retries": 3,
        },
    }

    monkeypatch.setattr(
        gh_pr_watch,
        "collect_snapshot",
        lambda args: (snapshot, Path("/tmp/codex-babysit-pr-state.json")),
    )
    monkeypatch.setattr(
        gh_pr_watch,
        "print_event",
        lambda event, payload: events.append((event, payload)),
    )
    monkeypatch.setattr(gh_pr_watch.time, "time", lambda: current_time[0])

    class StopWatch(Exception):
        pass

    def fake_sleep(seconds):
        sleeps.append(seconds)
        current_time[0] += seconds
        if len(sleeps) >= 2:
            raise StopWatch

    monkeypatch.setattr(gh_pr_watch.time, "sleep", fake_sleep)

    with pytest.raises(StopWatch):
        gh_pr_watch.run_watch(
            argparse.Namespace(
                poll_seconds=60,
                watch_heartbeat_seconds=60,
                heartbeat_format="summary",
            )
        )

    assert sleeps == [60, 60]
    assert [event for event, _ in events] == ["snapshot", "heartbeat"]
    assert events[1][1]["reason"] == "ci_failure"
    assert events[1][1]["requires_attention"] is True
    assert "snapshot" not in events[1][1]
    assert events[1][1]["summary"]["reason"] == "ci_failure"
    assert events[1][1]["summary"]["requires_attention"] is True
    assert events[1][1]["summary"]["pr"]["head_sha"] == "abc123"
    assert events[1][1]["summary"]["failed_jobs"] == [
        {
            "workflow_name": "CI",
            "job_name": "Build and Test",
            "status": "completed",
            "conclusion": "failure",
            "html_url": "https://github.com/openai/codex/actions/runs/99/job/555",
        }
    ]
    assert events[1][1]["unchanged_seconds"] == 60


def test_run_watch_minimal_heartbeat_format_omits_detail_lists(monkeypatch):
    sleeps = []
    events = []
    current_time = [1000]
    snapshot = {
        "pr": sample_pr(),
        "checks": sample_checks(pending_count=1, all_terminal=False),
        "failed_runs": [],
        "failed_jobs": [
            {
                "workflow_name": "CI",
                "job_name": "Build and Test",
                "status": "completed",
                "conclusion": "failure",
            }
        ],
        "new_review_items": [],
        "actions": ["diagnose_ci_failure"],
        "retry_state": {
            "current_sha_retries_used": 0,
            "max_flaky_retries": 3,
        },
    }

    monkeypatch.setattr(
        gh_pr_watch,
        "collect_snapshot",
        lambda args: (snapshot, Path("/tmp/codex-babysit-pr-state.json")),
    )
    monkeypatch.setattr(
        gh_pr_watch,
        "print_event",
        lambda event, payload: events.append((event, payload)),
    )
    monkeypatch.setattr(gh_pr_watch.time, "time", lambda: current_time[0])

    class StopWatch(Exception):
        pass

    def fake_sleep(seconds):
        sleeps.append(seconds)
        current_time[0] += seconds
        if len(sleeps) >= 2:
            raise StopWatch

    monkeypatch.setattr(gh_pr_watch.time, "sleep", fake_sleep)

    with pytest.raises(StopWatch):
        gh_pr_watch.run_watch(
            argparse.Namespace(
                poll_seconds=60,
                watch_heartbeat_seconds=60,
                heartbeat_format="minimal",
            )
        )

    assert [event for event, _ in events] == ["snapshot", "heartbeat"]
    assert events[1][1]["summary"]["reason"] == "ci_failure"
    assert events[1][1]["summary"]["requires_attention"] is True
    assert "failed_jobs" not in events[1][1]["summary"]


def test_snapshot_change_key_tracks_individual_check_swaps():
    base = {
        "pr": sample_pr(),
        "checks": sample_checks(passed_count=1, pending_count=1, all_terminal=False),
        "check_runs": [
            {"name": "Build", "workflow": "CI", "state": "COMPLETED", "bucket": "pass"},
            {"name": "Test", "workflow": "CI", "state": "IN_PROGRESS", "bucket": "pending"},
        ],
        "new_review_items": [],
        "failed_jobs": [],
        "actions": ["idle"],
    }
    swapped = {
        "pr": sample_pr(),
        "checks": sample_checks(passed_count=1, pending_count=1, all_terminal=False),
        "check_runs": [
            {"name": "Build", "workflow": "CI", "state": "IN_PROGRESS", "bucket": "pending"},
            {"name": "Test", "workflow": "CI", "state": "COMPLETED", "bucket": "pass"},
        ],
        "new_review_items": [],
        "failed_jobs": [],
        "actions": ["idle"],
    }

    assert gh_pr_watch.snapshot_change_key(base) != gh_pr_watch.snapshot_change_key(swapped)


def test_failed_jobs_include_direct_logs_endpoint(monkeypatch):
    jobs_by_run = {
        99: [
            {
                "id": 555,
                "name": "unit tests",
                "status": "completed",
                "conclusion": "failure",
                "html_url": "https://github.com/openai/codex/actions/runs/99/job/555",
            },
            {
                "id": 556,
                "name": "lint",
                "status": "completed",
                "conclusion": "success",
            },
        ]
    }

    monkeypatch.setattr(
        gh_pr_watch,
        "get_jobs_for_run",
        lambda repo, run_id: jobs_by_run[run_id],
    )

    failed_jobs = gh_pr_watch.failed_jobs_from_workflow_runs(
        "openai/codex",
        [
            {
                "id": 99,
                "name": "CI",
                "status": "in_progress",
                "conclusion": "",
                "head_sha": "abc123",
            }
        ],
        "abc123",
    )

    assert failed_jobs == [
        {
            "run_id": 99,
            "workflow_name": "CI",
            "run_status": "in_progress",
            "run_conclusion": "",
            "job_id": 555,
            "job_name": "unit tests",
            "status": "completed",
            "conclusion": "failure",
            "html_url": "https://github.com/openai/codex/actions/runs/99/job/555",
            "logs_endpoint": "repos/openai/codex/actions/jobs/555/logs",
        }
    ]
