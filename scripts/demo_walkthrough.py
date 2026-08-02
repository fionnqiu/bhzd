"""AC14 比赛演示主线彩排（PRD-05 §9 推荐演示主线逐步验收）。

主线：学生打开系统 → 点击"语音标注入门"预设 → 切换到"智能客服场景" →
Agent 生成学习计划 → RAG 召回客服语音标注规范 → 图谱显示相关能力路径 →
生成学习任务卡 → 学生完成练习并上传 TextGrid 结果 → 系统诊断错误 →
展示引用依据、薄弱能力和补强路径 → 保存诊断摘要并更新掌握度。

用法：python scripts/demo_walkthrough.py（独立临时库 + demo 种子，离线可跑）
"""

from __future__ import annotations

from base64 import b64encode
from collections.abc import Iterator
from contextlib import contextmanager
import os
import secrets
import sys
import tempfile
import time
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "server"))

from fastapi.testclient import TestClient  # noqa: E402

from bhzd_py.app import create_app  # noqa: E402
from bhzd_py.config import reset_config_cache  # noqa: E402
from bhzd_py.seed.loader import run_seed  # noqa: E402

steps: list[tuple[str, bool, str]] = []


@contextmanager
def isolated_runtime() -> Iterator[None]:
    """Run the demo in disposable storage and restore any caller environment afterwards."""
    env_names = ("BHZD_DATABASE_PATH", "BHZD_UPLOAD_DIR")
    original_environment = {name: os.environ.get(name) for name in env_names}
    with tempfile.TemporaryDirectory(prefix="bhzd-demo-") as temporary_root:
        root = Path(temporary_root)
        # The rehearsal must not seed, upload to, or otherwise alter the persistent var/ tree.
        os.environ["BHZD_DATABASE_PATH"] = str(root / "demo.sqlite")
        os.environ["BHZD_UPLOAD_DIR"] = str(root / "uploads")
        reset_config_cache()
        try:
            yield
        finally:
            # Resetting the cache after restoration prevents stale paths in embedding callers.
            for name, value in original_environment.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
            reset_config_cache()


def step(name: str, ok: bool, note: str = "") -> None:
    steps.append((name, ok, note))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {note}")


def _password_envelope(client: TestClient, password: str) -> dict[str, str]:
    """Mirror the browser password contract instead of sending a plaintext demo password."""
    key_response = client.get("/api/auth/password-key")
    assert key_response.status_code == 200
    key = key_response.json()
    public_key = serialization.load_pem_public_key(key["publicKeyPem"].encode("ascii"))
    aes_key = secrets.token_bytes(32)
    iv = secrets.token_bytes(12)
    ciphertext = AESGCM(aes_key).encrypt(iv, password.encode("utf-8"), None)
    encrypted_key = public_key.encrypt(
        aes_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return {
        "keyId": key["keyId"],
        "encryptedKey": b64encode(encrypted_key).decode("ascii"),
        "iv": b64encode(iv).decode("ascii"),
        "ciphertext": b64encode(ciphertext).decode("ascii"),
    }


def _run_demo() -> int:
    print("== 演示环境准备（demo 种子）==")
    run_seed(demo=True)
    c = TestClient(create_app())

    print("== PRD-05 §9 演示主线 ==")
    # 1. 学生打开系统并登录
    r = c.post(
        "/api/auth/login",
        json={"email": "student@demo.bhzd", "passwordEnvelope": _password_envelope(c, "Demo1234!")},
    )
    csrf = c.get("/api/auth/session").json()["csrf_token"]
    H = {"x-csrf-token": csrf}
    step("1 学生登录进入系统", r.status_code == 200)

    # 2. 点击"语音标注入门"预设学习
    presets = c.get("/api/presets").json()["items"]
    audio_preset = next((p for p in presets if p["data_type"] == "audio"), None)
    step("2 预设学习含语音标注入口", audio_preset is not None, audio_preset["title"] if audio_preset else "")

    # 3. 切换到智能客服场景（演示主线：携带场景发起目标）
    scenario = "SCN-CUSTOMER-SERVICE-001"

    # 4. Agent 生成学习计划
    r = c.post("/api/runs", json={"input": "我想学客服语音情感标注", "scenario_id": scenario, "data_type": "audio"}, headers=H)
    run_id = r.json()["run_id"]
    deadline = time.time() + 30
    d = {}
    while time.time() < deadline:
        d = c.get(f"/api/runs/{run_id}").json()
        if d["run"]["status"] in ("waiting_confirmation", "completed", "failed"):
            break
        time.sleep(0.3)
    plan = d.get("plan") or {}
    step("4 Agent 生成学习计划", bool(plan.get("steps")), f"steps={len(plan.get('steps') or [])}")

    # 5. RAG 召回客服语音标注规范
    r = c.post("/api/rag/query", json={"question": "客服语音情感标注有哪些标签？副语言事件怎么标？", "scenario_id": scenario, "data_type": "audio"}, headers=H)
    j = r.json()
    hit = any("客服" in ct["title"] for ct in j.get("citations", []))
    step("5 RAG 召回客服语音标注规范（带引用）", not j.get("refused") and hit, f"citations={[ct['title'] for ct in j.get('citations', [])][:3]}")

    # 6. 图谱显示相关能力路径
    caps = [n for n in c.get("/api/graph/overview").json()["nodes"] if n["id"].startswith("CAP-AUD")]
    r = c.get(f"/api/graph/pre-path?target_id={caps[0]['id']}")
    seq = r.json().get("path") or r.json().get("nodes") or []
    step("6 图谱相关能力路径（PRE）", r.status_code == 200 and len(seq) >= 1, f"target={caps[0]['id']} len={len(seq)}")

    # 7. 生成学习任务卡（确认门 → 确认创建）
    confs = d.get("confirmations") or []
    task_id = None
    if confs:
        rc = c.post(f"/api/confirmations/{confs[0]['id']}/confirm", headers=H)
        if rc.status_code == 200:
            tasks = c.get("/api/tasks").json().get("items", [])
            task_id = tasks[0]["id"] if tasks else None
    step("7 学习任务卡确认创建", task_id is not None, f"action={confs[0]['action_type'] if confs else None}")

    # 8. 学生上传 TextGrid 标注结果（含错误：情感标签非法 + 边界重叠）
    tg = '''File type = "ooTextFile"
Object class = "TextGrid"

xmin = 0
xmax = 5
tiers? <exists>
size = 1
item []:
    item [1]:
        class = "IntervalTier"
        name = "emotion"
        xmin = 0
        xmax = 5
        intervals: size = 2
        intervals [1]:
            xmin = 0
            xmax = 2.5
            text = "happy"
        intervals [2]:
            xmin = 2.0
            xmax = 5
            text = "非常开心"
'''
    r = c.post("/api/diagnostics", files={"file": ("demo.TextGrid", tg.encode(), "text/plain")}, data={"data_type": "audio", "scenario_id": scenario}, headers=H)
    rep = r.json()
    step("8 上传 TextGrid 并诊断出错误", r.status_code == 200 and len(rep.get("errors", [])) >= 1, f"errors={len(rep.get('errors', []))}")

    # 9. 展示引用依据 / 薄弱能力 / 补强路径
    has_cite_or_rule = all(e.get("rule") for e in rep.get("errors", []))
    plan9 = rep.get("plan") or {}
    step("9 报告含规则依据+薄弱能力+补强路径", bool(has_cite_or_rule and rep.get("weak_cap_ids") and plan9.get("pre_path") is not None), f"weak={rep.get('weak_cap_ids')}")

    # 10. 保存诊断摘要并更新掌握度
    r = c.post("/api/diagnostics/save-summary", json={"diagnostic_token": rep.get("diagnostic_token")}, headers=H)
    applied = r.json().get("mastery_applied", [])
    mastery = c.get("/api/profile/mastery").json()
    rows = mastery.get("items", mastery if isinstance(mastery, list) else [])
    step("10 保存摘要并更新掌握度", r.status_code == 200 and len(applied) >= 1 and len(rows) >= 1, f"applied={len(applied)} mastery_rows={len(rows)}")

    failed = [s for s in steps if not s[1]]
    print(f"\n== AC14 演示主线：{len(steps) - len(failed)}/{len(steps)} 步通过 ==")
    return 1 if failed else 0


def main() -> int:
    """Run the accepted demo route with isolated state and ephemeral storage."""
    steps.clear()
    with isolated_runtime():
        return _run_demo()


if __name__ == "__main__":
    raise SystemExit(main())
