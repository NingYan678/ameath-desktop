import json
from datetime import UTC, datetime, timedelta

from digital_pet.app_update import AppUpdateService
from digital_pet.memory_cue import CompanionCue, MemoryCueController
from digital_pet.pet_state import PetStateEngine, PetStateStore
from digital_pet.preferences import DesktopPreferences


def test_pet_state_daily_click_cap_and_hidden_relationship_stage(tmp_path):
    engine = PetStateEngine(PetStateStore(tmp_path), DesktopPreferences())
    for _ in range(8):
        engine.record_interaction()
    assert engine.state.familiarity == 5
    assert engine.relationship_stage() == "初识"


def test_memory_cue_requires_consent_and_persists_only_hash(tmp_path):
    preferences = DesktopPreferences(memory_cues_enabled=True, memory_consent_version=1)
    controller = MemoryCueController(tmp_path, preferences)

    class Client:
        def request_companion_cue(self, request_id, categories):
            self.request_id = request_id
            return True

    client = Client()
    request_id = controller.request(client)
    assert request_id == client.request_id
    expires = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    cue = controller.accept({"request_id": request_id, "text": "你最近对纸飞机很有兴趣。", "category": "interest", "expires_at": expires})
    assert isinstance(cue, CompanionCue)
    payload = json.loads((tmp_path / "companion_cue_state.json").read_text(encoding="utf-8"))
    assert "text" not in payload
    assert len(payload["cue_hash"]) == 64


def test_app_update_accepts_only_stable_official_assets(tmp_path):
    service = AppUpdateService(tmp_path, current_version="1.0.1")
    now = datetime.now(UTC)
    payload = {
        "tag_name": "v1.1.0",
        "draft": False,
        "prerelease": False,
        "html_url": "https://github.com/NingYan678/ameath-desktop/releases/tag/v1.1.0",
        "assets": [
            {"name": "Ameath-1.1.0-offline-setup.exe", "browser_download_url": "https://github.com/NingYan678/ameath-desktop/releases/download/v1.1.0/Ameath-1.1.0-offline-setup.exe"},
            {"name": "Ameath-1.1.0-offline-setup.exe.sha256", "browser_download_url": "https://github.com/NingYan678/ameath-desktop/releases/download/v1.1.0/Ameath-1.1.0-offline-setup.exe.sha256"},
        ],
    }
    info = service._parse_release(payload, now)
    assert info.update_available
    assert info.target_version == "1.1.0"


def test_app_update_rejects_prerelease(tmp_path):
    service = AppUpdateService(tmp_path, current_version="1.0.1")
    info = service._parse_release({"tag_name": "v1.2.0-rc.1", "prerelease": True}, datetime.now(UTC))
    assert not info.update_available
