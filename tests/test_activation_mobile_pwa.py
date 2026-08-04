from fastapi.testclient import TestClient

import main
from curricula import DEFAULT_CURRICULUM_ID, curriculum_options, verified_curriculum
from main import app


client = TestClient(app)


def login_student():
    client.cookies.clear()
    response = client.post(
        "/login",
        data={"identifier": "student", "password": "student123"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_public_sample_and_real_trial_are_available_before_signup(monkeypatch):
    client.cookies.clear()
    sample = client.get("/sample")
    assert sample.status_code == 200
    assert "See what Sumkora returns" in sample.text
    assert "3 / 3" in sample.text

    monkeypatch.setattr(
        main,
        "solve_question_image",
        lambda _path: {
            "final_answer": "x = 2",
            "final_answer_zh": "x = 2",
            "solution_en": "Subtract 3, then divide by 2. Therefore x = 2.",
            "solution_zh": "先减 3，再除以 2。因此 x = 2。",
        },
    )
    trial = client.post(
        "/trial",
        files={"image": ("question.jpg", b"synthetic-image", "image/jpeg")},
    )
    assert trial.status_code == 200
    assert "x = 2" in trial.text
    assert "deleted after processing" in trial.text


def test_upload_is_phone_ready_and_only_verified_curriculum_is_selectable():
    login_student()
    page = client.get("/student/analyse")
    assert page.status_code == 200
    assert 'capture="environment"' in page.text
    assert "Take a page photo" in page.text
    assert "Retry upload" in page.text
    assert 'name="curriculum"' in page.text
    assert DEFAULT_CURRICULUM_ID in page.text
    assert "General Mathematics" in page.text
    assert "coming later" in page.text

    options = curriculum_options()
    assert sum(item["status"] == "verified" for item in options) == 1
    assert verified_curriculum(DEFAULT_CURRICULUM_ID)["code"] == "0606"

    rejected = client.post(
        "/student/analyse",
        data={"curriculum": "general-mathematics"},
        files={"answer_script": ("work.pdf", b"%PDF-invalid", "application/pdf")},
    )
    assert rejected.status_code == 400
    assert "not yet available" in rejected.text


def test_pwa_assets_have_root_scope_and_private_pages_are_not_precached():
    manifest = client.get("/static/site.webmanifest").json()
    assert manifest["id"] == "/"
    assert manifest["display"] == "standalone"
    assert "maskable" in manifest["icons"][0]["purpose"]

    worker = client.get("/service-worker.js")
    assert worker.status_code == 200
    assert worker.headers["service-worker-allowed"] == "/"
    assert "/static/offline.html" in worker.text
    assert "/student/" not in worker.text

    login = client.get("/login")
    assert "/static/pwa.js" in login.text
    assert "Install Sumkora" in login.text


def test_security_policy_allows_same_origin_camera_only():
    response = client.get("/login")
    assert "camera=(self)" in response.headers["permissions-policy"]
    assert "microphone=()" in response.headers["permissions-policy"]
