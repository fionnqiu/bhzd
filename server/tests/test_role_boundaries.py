"""Regression coverage for the teacher, learner, and RAG role boundaries."""

from __future__ import annotations

import pytest

from _learning_fixtures import api as shared_api  # noqa: F401  # Shared isolated API fixture.


@pytest.fixture(name="api")
def api_for_role_boundary_tests(request):
    """Expose the shared fixture under a local name without an import-name clash."""
    return request.getfixturevalue("shared_api")


@pytest.mark.parametrize(
    "path",
    (
        "/api/tasks",
        "/api/profile",
        "/api/presets",
        "/api/diagnostics/summaries",
        "/api/conversations",
        "/api/runs/not-a-real-run",
    ),
)
def test_teacher_cannot_read_student_portal_apis(api, path):
    """A direct request cannot bypass the frontend's teacher route guard."""
    teacher = api.login_as("teacher-student-read@test.local", role="teacher")

    response = api.client.get(path, headers=teacher["headers"])

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.parametrize(
    ("path", "body"),
    (
        ("/api/tasks", {"title": "not permitted"}),
        ("/api/student/join-class", {"invite_code": "missing"}),
        ("/api/rag/query", {"question": "What is a label?"}),
        ("/api/conversations", {"title": "not permitted"}),
        ("/api/runs", {"input": "not permitted"}),
        ("/api/confirmations/not-a-real-confirmation/cancel", {}),
    ),
)
def test_teacher_cannot_mutate_student_portal_apis(api, path, body):
    """Role denial happens before CSRF or endpoint-specific business logic."""
    teacher = api.login_as("teacher-student-write@test.local", role="teacher")

    response = api.client.post(path, json=body, headers=teacher["headers"])

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.parametrize("role", ("system_admin",))
def test_administrative_roles_keep_student_portal_access(api, role):
    """The learner boundary excludes teachers without removing administrator access."""
    user = api.login_as(f"{role}-student-portal@test.local", role=role)

    for path in (
        "/api/tasks",
        "/api/profile",
        "/api/presets",
        "/api/diagnostics/summaries",
        "/api/conversations",
    ):
        response = api.client.get(path, headers=user["headers"])
        assert response.status_code == 200, response.text

    # A nonexistent invite reaches the business layer for allowed roles. This
    # proves the route is reachable while avoiding an enrollment side effect.
    join_response = api.client.post(
        "/api/student/join-class",
        json={"invite_code": "missing"},
        headers=user["headers"],
    )
    assert join_response.status_code == 404

    query_response = api.client.post(
        "/api/rag/query",
        json={"question": "What is a label?", "published_only": False},
        headers=user["headers"],
    )
    assert query_response.status_code == 200, query_response.text
