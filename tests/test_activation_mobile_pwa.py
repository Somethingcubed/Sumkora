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
            "final_answer": r"\(x = \frac{1}{2}\)",
            "final_answer_zh": r"\(x = \frac{1}{2}\)",
            "solution_en": r"Divide both sides by 2. Therefore \(x = \frac{1}{2}\).",
            "solution_zh": r"两边同时除以 2。因此 \(x = \frac{1}{2}\)。",
        },
    )
    trial = client.post(
        "/trial",
        files={"image": ("question.jpg", b"synthetic-image", "image/jpeg")},
    )
    assert trial.status_code == 200
    assert r"\(x = \frac{1}{2}\)" in trial.text
    assert "/static/vendor/mathjax/tex-chtml.js" in trial.text
    assert "you do not need to solve it" in trial.text
    assert "no completed work or answer needed" in trial.text
    assert "deleted after processing" in trial.text

    picker = client.get("/trial")
    assert "No question selected yet." in picker.text
    assert "Choose a question first" in picker.text
    assert "Question selected. You can now ask Sumkora to solve it." in picker.text
    assert "data-trial-preview" in picker.text
    assert "data-trial-filename" in picker.text
    assert 'data-trial-submit disabled' in picker.text


def test_upload_is_phone_ready_and_available_curricula_are_selectable():
    login_student()
    page = client.get("/student/analyse")
    assert page.status_code == 200
    assert 'capture="environment"' in page.text
    assert "Take a page photo" in page.text
    assert "Retry upload" in page.text
    assert 'name="curriculum"' in page.text
    assert DEFAULT_CURRICULUM_ID in page.text
    assert "General Mathematics" in page.text
    assert "Cambridge IGCSE Physics" in page.text
    assert 'name="curriculum_level"' in page.text
    assert 'name="study_language"' in page.text

    options = curriculum_options()
    assert sum(item["status"] == "verified" for item in options) == 1
    assert verified_curriculum(DEFAULT_CURRICULUM_ID)["code"] == "0606"
    assert verified_curriculum("general-mathematics")["status"] == "beta"

    rejected = client.post(
        "/student/analyse",
        data={"curriculum": "general-mathematics"},
        files={"answer_script": ("work.pdf", b"%PDF-invalid", "application/pdf")},
    )
    assert rejected.status_code == 400
    assert "not yet available" not in rejected.text


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
    assert 'class="auth-preview-grid"' in login.text
    assert 'href="/sample"' in login.text
    assert 'href="/trial"' in login.text

    login_student()
    dashboard = client.get("/student")
    assert 'class="nav-install"' in dashboard.text
    assert "Install app" in dashboard.text
    assert "data-install-always" in dashboard.text
    assert "Add to Home Screen" in dashboard.text
    assert "Add Sumkora to your Home Screen" in dashboard.text
    assert "It takes about 10 seconds" in dashboard.text
    assert "data-install-nudge" in dashboard.text

    settings = client.get("/student/settings")
    assert "Install or view instructions" in settings.text
    assert "Safari instructions are included" in settings.text
    assert "data-install-help" in settings.text


def test_account_created_page_offers_four_clear_next_steps():
    client.cookies.clear()
    response = client.post(
        "/signup",
        data={
            "username": "ActivationOptions",
            "password": "activation-password",
            "password_confirmation": "activation-password",
            "display_name": "",
        },
    )
    assert response.status_code == 200
    assert 'class="signup-next-actions"' in response.text
    assert 'href="/student/analyse"' in response.text
    assert 'href="/student"' in response.text
    assert 'href="/sample"' in response.text
    assert 'href="/student/solve"' in response.text


def test_security_policy_allows_same_origin_camera_only():
    response = client.get("/login")
    assert "camera=(self)" in response.headers["permissions-policy"]
    assert "microphone=()" in response.headers["permissions-policy"]
