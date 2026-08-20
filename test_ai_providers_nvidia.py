"""NVIDIA built-in + admin-added custom OpenAI-compatible providers."""
import os
import sys

sys.path.insert(0, "/home/claude/tprm")
os.environ["BRO_TRUST_HEADER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402
from app.bro_app import create_app  # noqa: E402
from app.agents import llm_config as L  # noqa: E402

H = {"x-user": "admin"}
DB = "sqlite:////tmp/nvp.db"


def _c():
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY", "MANUS_API_KEY",
              "NVIDIA_API_KEY", "BRO_LLM_PROVIDER", "BRO_SECRET_KEY"):
        os.environ.pop(k, None)
    for pid in list(L._CUSTOM_IDS):
        L.unregister_provider(pid)
        os.environ.pop(f"CUSTOM_{pid.upper()}_API_KEY", None)
    if os.path.exists("/tmp/nvp.db"):
        os.remove("/tmp/nvp.db")
    return TestClient(create_app(DB))


def test_nvidia_is_builtin():
    _c()
    assert "nvidia" in L.all_provider_ids()
    assert L._OAI_COMPAT_BASE["nvidia"][1].startswith("https://integrate.api.nvidia.com")
    assert L._DEFAULT_MODEL["nvidia"]


def test_nvidia_key_select_resolve():
    c = _c()
    c.post("/api/v1/ai/keys", headers=H, json={"nvidia": "nvapi-test-123"})
    assert os.environ.get("NVIDIA_API_KEY") == "nvapi-test-123"
    r = c.post("/api/v1/ai/provider", headers=H, json={"provider": "nvidia"})
    assert r.status_code == 200 and r.json()["provider"] == "nvidia"
    assert L.configured_provider() == "nvidia"
    st = c.get("/api/v1/ai/status", headers=H).json()
    assert st["nvidia_key_present"] is True
    assert any(p["id"] == "nvidia" and p["active"] for p in st["providers"])


def test_custom_provider_roundtrip():
    c = _c()
    r = c.post("/api/v1/ai/custom-provider", headers=H,
               json={"label": "Together AI", "base_url": "https://api.together.xyz/v1",
                     "model": "meta-llama/Llama-3-70b", "api_key": "tk-1"})
    assert r.status_code == 200
    st = r.json()
    pid = next(p["id"] for p in st["providers"] if p.get("custom"))
    assert pid == "together_ai"
    r2 = c.post("/api/v1/ai/provider", headers=H, json={"provider": pid})
    assert r2.status_code == 200 and L.configured_provider() == pid
    c.post(f"/api/v1/ai/custom-provider/{pid}/delete", headers=H)
    assert pid not in L.all_provider_ids()


def test_custom_provider_collision_rejected():
    c = _c()
    r = c.post("/api/v1/ai/custom-provider", headers=H,
               json={"label": "claude", "base_url": "https://x/v1", "model": "m"})
    assert r.status_code == 400


if __name__ == "__main__":
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:
            print(f"FAIL {fn.__name__}: {e}")
