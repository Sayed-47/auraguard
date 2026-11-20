"""Docs-module tests. Run: python -m unittest discover -s server -p 'test_*.py' -v"""

from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest

from app import Settings, create_app

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class DocsTestCase(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.config_path = Path(self.tempdir.name) / "docs-config.json"
        settings = Settings(database=":memory:", docs_config=self.config_path)
        self.client = TestClient(create_app(settings))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.token = json.loads(self.config_path.read_text(encoding="utf-8"))["admin_token"]

    def admin(self, method: str, path: str, token: str | None = None, **kwargs):
        headers = kwargs.pop("headers", {})
        headers["X-Admin-Token"] = self.token if token is None else token
        return getattr(self.client, method)(path, headers=headers, **kwargs)

    def set_visibility(self, **fields):
        response = self.admin("put", "/api/docs/admin", json=fields)
        self.assertEqual(response.status_code, 200, response.text)
        return response


class VisibilityTests(DocsTestCase):
    def test_public_page_is_on_by_default(self):
        self.assertEqual(self.client.get("/docs").status_code, 200)
        payload = self.client.get("/api/docs").json()
        for key in ("pitch", "team", "visibility", "live"):
            self.assertIn(key, payload)

    def test_disabled_page_returns_404_everywhere_public(self):
        self.set_visibility(enabled=False)
        for path in ("/docs", "/api/docs", "/api/docs/live", "/api/docs/team-image/tm-x"):
            self.assertEqual(self.client.get(path).status_code, 404, path)

    def test_future_window_keeps_page_closed(self):
        self.set_visibility(enabled=True, visible_from=iso(datetime.now(timezone.utc) + timedelta(hours=1)))
        self.assertEqual(self.client.get("/docs").status_code, 404)

    def test_covering_window_opens_page(self):
        now = datetime.now(timezone.utc)
        self.set_visibility(enabled=True, visible_from=iso(now - timedelta(hours=1)), visible_until=iso(now + timedelta(hours=1)))
        self.assertEqual(self.client.get("/docs").status_code, 200)

    def test_past_window_closes_page(self):
        self.set_visibility(enabled=True, visible_until=iso(datetime.now(timezone.utc) - timedelta(hours=1)))
        self.assertEqual(self.client.get("/api/docs").status_code, 404)

    def test_invalid_schedule_is_rejected(self):
        response = self.admin("put", "/api/docs/admin", json={"visible_from": "not-a-date"})
        self.assertEqual(response.status_code, 422)

    def test_admin_page_stays_reachable_when_public_page_is_off(self):
        self.set_visibility(enabled=False)
        self.assertEqual(self.client.get("/docs/admin").status_code, 200)


class AdminAuthTests(DocsTestCase):
    def test_admin_endpoints_require_the_token(self):
        for path in ("/api/docs/admin",):
            self.assertEqual(self.client.get(path).status_code, 403)
        self.assertEqual(self.admin("get", "/api/docs/admin", token="wrong").status_code, 403)
        self.assertEqual(self.admin("get", "/api/docs/admin").status_code, 200)

    def test_token_is_not_exposed_in_public_payload(self):
        payload = self.client.get("/api/docs").text
        self.assertNotIn(self.token, payload)

    def test_env_token_overrides_the_file_token(self):
        import os
        os.environ["AURAGUARD_DOCS_TOKEN"] = "env-token-for-test"
        self.addCleanup(os.environ.pop, "AURAGUARD_DOCS_TOKEN")
        self.assertEqual(self.admin("get", "/api/docs/admin", token="env-token-for-test").status_code, 200)
        self.assertEqual(self.admin("get", "/api/docs/admin", token=self.token).status_code, 403)


class PitchTests(DocsTestCase):
    def test_pitch_edit_reflects_immediately_on_public_payload(self):
        response = self.admin("put", "/api/docs/admin", json={
            "pitch": {"tagline": "Edited tagline for the judges.", "features": ["first", "second"]},
        })
        self.assertEqual(response.status_code, 200, response.text)
        payload = self.client.get("/api/docs").json()
        self.assertEqual(payload["pitch"]["tagline"], "Edited tagline for the judges.")
        self.assertEqual(payload["pitch"]["features"], ["first", "second"])
        # Untouched fields keep their defaults.
        self.assertTrue(payload["pitch"]["problem"])

    def test_pitch_config_survives_a_config_reload(self):
        self.admin("put", "/api/docs/admin", json={"pitch": {"product_name": "AuraGuard X"}})
        from docs_module import DocsConfigStore
        reloaded = DocsConfigStore(self.config_path)
        self.assertEqual(reloaded.config["pitch"]["product_name"], "AuraGuard X")

    def test_bad_urls_are_rejected(self):
        response = self.admin("put", "/api/docs/admin", json={"pitch": {"repo_url": "javascript:alert(1)"}})
        self.assertEqual(response.status_code, 422)


class TeamTests(DocsTestCase):
    def add_member(self, name="Afnan Rahman", role="Hardware lead", email="afnan@example.com"):
        response = self.admin("post", "/api/docs/admin/team", json={"name": name, "role": role, "email": email})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["member"]

    def test_team_crud_reflects_on_public_payload(self):
        member = self.add_member()
        team = self.client.get("/api/docs").json()["team"]
        self.assertEqual([m["name"] for m in team], ["Afnan Rahman"])
        self.assertEqual(team[0]["role"], "Hardware lead")
        self.assertEqual(team[0]["email"], "afnan@example.com")
        self.assertIsNone(team[0]["image_url"])

        response = self.admin("put", f"/api/docs/admin/team/{member['id']}", json={"name": "Afnan R.", "role": "Firmware", "email": ""})
        self.assertEqual(response.status_code, 200)
        team = self.client.get("/api/docs").json()["team"]
        self.assertEqual(team[0]["name"], "Afnan R.")

        response = self.admin("delete", f"/api/docs/admin/team/{member['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/docs").json()["team"], [])

    def test_blank_name_is_rejected(self):
        response = self.admin("post", "/api/docs/admin/team", json={"name": "   ", "role": "", "email": ""})
        self.assertEqual(response.status_code, 422)

    @unittest.skipUnless(HAS_PIL, "Pillow is required for image resizing")
    def test_uploaded_image_is_center_cropped_and_resized(self):
        member = self.add_member()
        source = Image.new("RGB", (400, 200), (120, 30, 40))
        buffer = BytesIO()
        source.save(buffer, format="PNG")
        buffer.seek(0)
        response = self.client.post(
            f"/api/docs/admin/team/{member['id']}/image",
            files={"image": ("photo.png", buffer, "image/png")},
            headers={"X-Admin-Token": self.token},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["size"], 256)

        served = self.client.get(f"/api/docs/team-image/{member['id']}")
        self.assertEqual(served.status_code, 200)
        resized = Image.open(BytesIO(served.content))
        self.assertEqual(resized.size, (256, 256))
        self.assertEqual(resized.format, "PNG")

        member_public = self.client.get("/api/docs").json()["team"][0]
        self.assertIn(f"/api/docs/team-image/{member['id']}?v=1", member_public["image_url"])

    @unittest.skipUnless(HAS_PIL, "Pillow is required for image resizing")
    def test_non_image_upload_is_rejected(self):
        member = self.add_member()
        response = self.client.post(
            f"/api/docs/admin/team/{member['id']}/image",
            files={"image": ("notes.txt", BytesIO(b"definitely not an image"), "text/plain")},
            headers={"X-Admin-Token": self.token},
        )
        self.assertEqual(response.status_code, 415)


class LiveDataTests(DocsTestCase):
    def test_live_payload_is_assembled_from_the_running_server(self):
        payload = self.client.get("/api/docs/live").json()
        self.assertEqual(payload["protocol"], "uno-room-v1")
        self.assertIn(payload["connection"]["status"], {"waiting", "connected", "stale", "offline"})
        self.assertIn("event_counts_by_type", payload)
        self.assertIn("diagnostics", payload)
        paths = {row["path"] for row in payload["api_routes"]}
        self.assertIn("/api/status", paths)
        self.assertIn("/api/docs", paths)  # the module lists itself
        self.assertTrue(payload["tech_stack"])

    def test_ai_model_cards_come_from_shipped_weight_files(self):
        payload = self.client.get("/api/docs/live").json()
        models = {model["id"]: model for model in payload["ai_models"]}
        self.assertIn("cry", models)
        self.assertIn("motion", models)
        self.assertEqual(models["cry"]["n_classes"], 2)
        self.assertEqual(models["motion"]["n_classes"], 3)
        self.assertTrue(models["cry"]["feature_names"])

    def test_docs_library_lists_real_files(self):
        payload = self.client.get("/api/docs/live").json()
        paths = {row["path"] for row in payload["docs_library"]}
        self.assertIn("docs/AI.md", paths)
        self.assertIn("docs/PROTOCOL.md", paths)


if __name__ == "__main__":
    unittest.main()
