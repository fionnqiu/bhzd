"""端到端集成冒烟：以 PRD-00 §8 验收标准（AC1-AC12 + AC13）为主线的全链路验证。

用法：python scripts/integration_smoke.py
说明：使用独立临时数据库 + run_seed(demo=True)，不触碰 var/ 真实数据；
全程离线（本地哈希嵌入 + 模板合成）。学生/教师/管理员各用独立 TestClient
（独立 cookie jar——同一 jar 后登录的角色会顶掉前一个角色的会话 cookie，
导致 CSRF 校验失败，这是脚本用法问题而非产品缺陷）。
任何一步失败以 FAIL 打印并继续，最后以退出码 0/1 汇总。
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

results: list[tuple[str, bool, str]] = []
DEMO_PASSWORD = "Demo1234!"


@contextmanager
def isolated_runtime() -> Iterator[None]:
    """Keep smoke data and configuration changes out of the developer runtime."""
    env_names = (
        "BHZD_DATABASE_PATH",
        "BHZD_UPLOAD_DIR",
        "BHZD_MAIL_OUTBOX_PATH",
        "BHZD_SMTP_HOST",
        "NODE_ENV",
    )
    original_environment = {name: os.environ.get(name) for name in env_names}
    with tempfile.TemporaryDirectory(prefix="bhzd-smoke-") as temporary_root:
        root = Path(temporary_root)
        # A disposable database prevents the acceptance flow from changing var/ data or uploads.
        os.environ["BHZD_DATABASE_PATH"] = str(root / "smoke.sqlite")
        os.environ["BHZD_UPLOAD_DIR"] = str(root / "uploads")
        # Authentication fixtures need a local verification token.  Force the no-SMTP
        # development path and keep its outbox in the disposable directory; production
        # deliberately never returns this token, so this is not a production substitute.
        os.environ["BHZD_MAIL_OUTBOX_PATH"] = str(root / "mail_outbox.log")
        os.environ["BHZD_SMTP_HOST"] = ""
        os.environ["NODE_ENV"] = "development"
        reset_config_cache()
        try:
            yield
        finally:
            # A caller can safely run this script in-process more than once after the check ends.
            for name, value in original_environment.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
            reset_config_cache()


def check(ac: str, ok: bool, note: str = "") -> None:
    results.append((ac, ok, note))
    print(f"  [{'PASS' if ok else 'FAIL'}] {ac}  {note}")


def _password_envelope(client: TestClient, password: str) -> dict[str, str]:
    """Build the production browser envelope so smoke tests cannot bypass password encryption."""
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


def login(c: TestClient, email: str, password: str = DEMO_PASSWORD) -> dict:
    r = c.post(
        "/api/auth/login",
        json={"email": email, "passwordEnvelope": _password_envelope(c, password)},
    )
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text}"
    csrf = c.get("/api/auth/session").json()["csrf_token"]  # 末次轮换后的令牌
    return {"x-csrf-token": csrf}


def register_active_student(c: TestClient) -> tuple[str, dict]:
    """Create a genuinely new student for flows the seeded demo student cannot prove.

    The demo student is intentionally already onboarded, enrolled, and diagnostic-share
    enabled so the product walkthrough starts at the cockpit.  P0 regression checks for
    first-use onboarding and the default-deny diagnostics policy must instead exercise a
    new account through the real password-envelope and immediate activation contract.
    """
    # Use a syntactically routable domain because EmailStr deliberately rejects
    # reserved test TLDs before the local no-SMTP delivery branch can run.
    email = f"smoke-student-{secrets.token_hex(6)}@example.com"
    registered = c.post(
        "/api/auth/register",
        json={
            "email": email,
            "name": "冒烟新生",
            "passwordEnvelope": _password_envelope(c, DEMO_PASSWORD),
        },
    )
    assert registered.status_code == 201, f"register fixture: {registered.status_code}"
    assert registered.json()["user"]["email_verified"] is True
    return email, login(c, email)


def wait_run(c: TestClient, run_id: str, statuses: tuple[str, ...], timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    d: dict = {}
    while time.time() < deadline:
        d = c.get(f"/api/runs/{run_id}").json()
        if d["run"]["status"] in statuses:
            return d
        time.sleep(0.3)
    return d


def _run_smoke() -> int:
    print("== 种子加载（demo）==")
    summary = run_seed(demo=True)
    # Seed can generate a one-time administrator password; acceptance output must never reveal it.
    safe_summary = {
        key: value
        for key, value in summary.items()
        if key != "generated_admin_password" and not isinstance(value, (list, dict))
    }
    print("  seed summary:", safe_summary)
    app = create_app()
    # 角色和新生 fixture 各自使用独立 cookie jar，避免后登录覆盖会话。
    cs, ct, ca, cf = TestClient(app), TestClient(app), TestClient(app), TestClient(app)
    fresh_student_email, hf = register_active_student(cf)

    print("== 学生端链路 ==")
    hs = login(cs, "student@demo.bhzd")

    # AC1 目标输入 → 计划
    r = cs.post("/api/runs", json={"input": "我想学车载唤醒词标注"}, headers=hs)
    run_id = r.json()["run_id"]
    d = wait_run(cs, run_id, ("completed", "failed", "waiting_confirmation"))
    # 注意：/events SSE 在 waiting_confirmation 下不会关闭（设计如此，供前端持续接收
    # 确认后续事件），TestClient 读全量 body 会挂起——计划断言用 run 详情的 plan 字段，
    # 事件流只在 run 终态后读取。
    plan = d.get("plan") or {}
    steps = plan.get("steps") if isinstance(plan, dict) else None
    check("AC1 目标输入生成计划", bool(steps) and d["run"]["status"] in ("waiting_confirmation", "completed"), f"status={d['run']['status']} steps={len(steps or [])}")

    # AC11 确认门（创建任务须确认）
    confs = d.get("confirmations") or []
    check("AC11 写操作出现确认门", len(confs) > 0, f"action={confs[0]['action_type'] if confs else None}")
    if confs:
        rc = cs.post(f"/api/confirmations/{confs[0]['id']}/confirm", headers=hs)
        d = wait_run(cs, run_id, ("completed", "failed"))
        check("AC11 确认后写操作生效", rc.status_code == 200 and d["run"]["status"] == "completed", f"confirm={rc.status_code} final={d['run']['status']}")

    tasks = cs.get("/api/tasks").json().get("items", [])
    check("AC1/AC8 任务卡写入任务列表", len(tasks) > 0, tasks[0]["title"] if tasks else "无任务")

    # run 已到终态，此时读 SSE 事件流会正常关闭：校验 PRD-05 §5 关键事件序列
    ev = cs.get(f"/api/runs/{run_id}/events?after_seq=0").text
    ev_types = [l[7:] for l in ev.splitlines() if l.startswith("event: ")]
    need = {"run.started", "plan.updated", "confirmation.required", "run.completed"}
    check("AC11 事件流完整（§5）", need <= set(ev_types), f"{ev_types}")

    # AC2 预设学习创建任务
    presets = cs.get("/api/presets").json()["items"]
    r = cs.post(f"/api/presets/{presets[0]['id']}/start", headers=hs)
    j = r.json()
    ok = r.status_code in (200, 201) and j.get("confirmation")
    note = f"start={r.status_code}"
    if ok:
        rc = cs.post(f"/api/confirmations/{j['confirmation']['id']}/confirm", headers=hs)
        ok = rc.status_code == 200
        note += f" confirm={rc.status_code} {rc.text[:80]}"
    else:
        note += f" body={r.text[:120]}"
    check("AC2 预设入口确认创建任务", bool(ok), f"{presets[0]['title']} | {note}")

    # AC7 PRE 路径
    caps = [n for n in cs.get("/api/graph/overview").json()["nodes"] if n["id"].startswith("CAP")]
    r = cs.get(f"/api/graph/pre-path?target_id={caps[0]['id']}")
    path = r.json()
    seq = path.get("path") or path.get("nodes") or []
    check("AC7 PRE 补强路径生成", r.status_code == 200 and len(seq) >= 1, f"len={len(seq)}")

    # AC9 诊断（TextGrid 含重叠错误）
    tg = '''File type = "ooTextFile"
Object class = "TextGrid"

xmin = 0
xmax = 4
tiers? <exists>
size = 1
item []:
    item [1]:
        class = "IntervalTier"
        name = "emotion"
        xmin = 0
        xmax = 4
        intervals: size = 2
        intervals [1]:
            xmin = 0
            xmax = 2
            text = "happy"
        intervals [2]:
            xmin = 1
            xmax = 3
            text = "angry"
'''
    r = cs.post("/api/diagnostics", files={"file": ("sample.TextGrid", tg.encode(), "text/plain")}, data={"data_type": "audio", "scenario_id": "SCN-CUSTOMER-SERVICE-001"}, headers=hs)
    rep = r.json()
    check("AC9 诊断报告生成", r.status_code == 200 and len(rep.get("errors", [])) > 0 and rep.get("plan"), f"errors={len(rep.get('errors', []))} weak={rep.get('weak_cap_ids')}")
    token = rep.get("diagnostic_token")

    # AC10 掌握度更新（保存诊断摘要）
    r = cs.post("/api/diagnostics/save-summary", json={"diagnostic_token": token}, headers=hs)
    check("AC10 保存摘要更新掌握度", r.status_code == 200 and r.json().get("mastery_applied"), f"applied={len(r.json().get('mastery_applied', []))}")

    # AC9 补强计划含 PRE/资源
    check("AC9 补强计划完整", bool(rep["plan"].get("pre_path") is not None and rep["plan"].get("resources") is not None), "")

    print("== 教师端链路 ==")
    ht = login(ct, "teacher@demo.bhzd")
    dash = ct.get("/api/teacher/dashboard", headers=ht).json()
    check("教师工作台（薄弱 Top5/班级概览）", "weak_caps_top5" in dash or "classes" in dash, list(dash.keys())[:6])

    classes = ct.get("/api/teacher/classes", headers=ht).json().get("items", [])
    check("教师班级列表", len(classes) > 0, classes[0]["name"] if classes else "")
    class_id = classes[0]["id"] if classes else None
    invite_code = classes[0].get("invite_code") if classes else None
    joined = (
        cf.post("/api/student/join-class", json={"invite_code": invite_code}, headers=hf)
        if invite_code
        else None
    )
    check(
        "新学生验证后加入演示班级",
        joined is not None and joined.status_code in (200, 201),
        fresh_student_email,
    )

    # AC8 企业任务 → 学习任务卡 → 发布
    graph_nodes = ct.get("/api/graph/nodes?q=标注", headers=ht).json()
    cap_id = (graph_nodes.get("items") or graph_nodes.get("nodes") or [{}])[0]["id"]
    body = {
        "title": "客服语音情感标注实训（企业任务转化）",
        "goal": "完成 20 条客服语音情感标注并通过质检",
        "data_type": "audio", "scenario_id": "SCN-CUSTOMER-SERVICE-001",
        "cap_ids": [cap_id],
        "steps": [{"title": "学习规范", "description": "阅读客服语音标注规范"}, {"title": "完成标注", "description": "完成 20 条样本"}],
        "resources": [{"type": "document", "title": "智能客服语音标注规范 v2.3", "ref_id": "demo"}],
        "counts_toward_mastery": True,
    }
    r = ct.post("/api/teacher/tasks", json=body, headers=ht)
    tid = r.json().get("id") or r.json().get("task", {}).get("id")
    r = ct.post(f"/api/teacher/tasks/{tid}/publish", json={"class_id": class_id, "counts_toward_mastery": True}, headers=ht)
    pub = r.json()
    published_n = pub.get("published") or pub.get("published_count") or 0
    check("AC8 企业任务转学习任务卡并发布", r.status_code in (200, 201) and published_n >= 1, f"status={r.status_code} {pub}")
    stu_tasks = cs.get("/api/tasks?source=teacher").json().get("items", [])
    check("AC8 学生任务列表可见教师任务", len(stu_tasks) > 0, stu_tasks[0]["title"] if stu_tasks else "")

    print("== RAG 治理链路（AC3/4/5/6）==")
    md = "# 图像框选标注补充规范 v1.0\n\n## 框选边界\n所有目标框必须贴合目标外接矩形，误差不超过 2 像素。\n\n## 类别使用\n仅允许使用任务书发布的类别表。\n"
    data = {"title": "图像框选标注补充规范", "source_type": "standard", "source_name": "标航教研组", "version": "v1.0", "license_status": "authorized", "visibility": "student", "data_types": "image", "scenario_ids": ""}
    r = ct.post("/api/rag/documents", files={"file": ("box.md", md.encode(), "text/markdown")}, data=data, headers=ht)
    doc_id = r.json().get("document", {}).get("id") or r.json().get("id")
    check("AC3 资料上传并进入处理队列", r.status_code in (200, 201, 202) and doc_id, f"status={r.status_code}")

    q = {"question": "目标框边界误差允许多少？"}
    r0 = cs.post("/api/rag/query", json=q, headers=hs)
    j0 = r0.json()
    check("AC4 未审核资料不进学生召回", r0.status_code == 200 and (j0.get("refused") is True or all("框选" not in ct_["title"] for ct_ in j0.get("citations", []))), f"status={r0.status_code} refused={j0.get('refused')}")

    r = ct.post(f"/api/rag/documents/{doc_id}/submit-review", headers=ht)
    note = f"submit={r.status_code}"
    r = ct.post(f"/api/rag/documents/{doc_id}/publish", json={"scope": "student"}, headers=ht)
    note += f" publish={r.status_code}"
    check("AC3 发布成功", r.status_code == 200, note)
    r1 = cs.post("/api/rag/query", json=q, headers=hs).json()
    hit = any("框选" in ct_["title"] for ct_ in r1.get("citations", []))
    check("AC5 发布后命中且带引用", not r1.get("refused") and hit, f"citations={[ct_['title'] for ct_ in r1.get('citations', [])]}")
    r2 = cs.post("/api/rag/query", json={"question": "曲率引擎如何充电？"}, headers=hs).json()
    check("AC6 无可靠资料时拒答", r2.get("refused") is True, f"refused={r2.get('refused')} | {(r2.get('answer') or '')[:40]}")

    print("== 安全（AC12/AC13）==")
    ha = login(ca, "admin@demo.bhzd")
    r = ca.post("/api/admin/providers", json={"name": "测试供应商", "protocol": "chat_completions", "base_url": "https://api.example.com", "model": "m1", "api_key": "sk-secret-123456", "role": "none"}, headers=ha)
    dumped = ca.get("/api/admin/providers", headers=ha).text
    check("AC12 API Key 不回显", r.status_code in (200, 201) and "sk-secret-123456" not in dumped, f"create={r.status_code}")
    r = ca.post("/api/admin/providers", json={"name": "恶意识别", "protocol": "chat_completions", "base_url": "http://169.254.169.254/latest", "model": "m1", "api_key": "x"}, headers=ha)
    check("AC12 base_url 安全校验（NF9）", r.status_code in (400, 422), f"{r.status_code}")
    uploads_root = Path(os.environ["BHZD_UPLOAD_DIR"])
    tg_files = list(uploads_root.rglob("*.TextGrid")) if uploads_root.exists() else []
    check("AC12 诊断原文件不持久化（NF3）", len(tg_files) == 0, f"uploads 中 TextGrid={len(tg_files)}")

    r = ca.get("/api/admin/audit-logs", headers=ha)
    any_publish = "publish" in r.text or "发布" in r.text
    check("AC13 发布动作写审计日志", r.status_code == 200 and any_publish, "")

    print("== 新特性链路（增强包）==")
    # 入学测评闭环（v3.0 §11.1）
    r = cf.get("/api/onboarding/assessment")
    assess = r.json()
    check("入学测评题目下发（不含答案）", r.status_code == 200 and assess.get("status") == "not_started" and len(assess.get("questions", [])) == 8 and all("answer_index" not in q for q in assess["questions"]), f"status={assess.get('status')}")
    answers = {q["id"]: 0 for q in assess["questions"]}
    r = cf.post("/api/onboarding/assessment", json={"answers": answers, "goal": "考证", "major": "人工智能技术应用"}, headers=hf)
    j = r.json()
    check("入学测评提交→初始掌握度", r.status_code == 200 and j.get("mastery_applied") is not None and j.get("status") == "completed", f"score={j.get('score')} applied={len(j.get('mastery_applied', []))}")
    r = cf.get("/api/profile/mastery/trend?days=30")
    check("掌握度趋势序列", r.status_code == 200 and len(r.json().get("items", [])) >= 1, "")

    # 收藏资料
    r = cf.post("/api/profile/favorites", json={"item_type": "citation", "item_id": "demo-doc-1", "title": "车载唤醒词标注指南", "meta": {"version": "v1.4"}}, headers=hf)
    ok = r.status_code in (200, 201)
    r = cf.get("/api/profile/favorites")
    favs = r.json().get("items", [])
    check("收藏新增与列表", ok and len(favs) >= 1, f"n={len(favs)}")
    if favs:
        r = cf.request("DELETE", f"/api/profile/favorites/{favs[0]['id']}", headers=hf)
        check("收藏删除", r.status_code in (200, 204), f"{r.status_code}")

    # 站内通知（教师发布 → 学生未读 → 已读）
    r = cf.get("/api/notifications/unread-count")
    n0 = r.json().get("count", r.json().get("unread", 0))
    task_payload = {  # 全新任务体（不可复用变量名 body——上面测评段已占用）
        "title": "通知链路验证任务",
        "goal": "验证通知触达",
        "data_type": "audio", "scenario_id": "SCN-CUSTOMER-SERVICE-001",
        "cap_ids": [cap_id],
        "steps": [{"title": "完成练习", "description": "按规范完成"}],
        "resources": [{"type": "document", "title": "智能客服语音标注规范 v2.3", "ref_id": "demo"}],
    }
    r = ct.post("/api/teacher/tasks", json=task_payload, headers=ht)
    create_status, create_body = r.status_code, r.text[:100]
    tid2 = r.json().get("id") or r.json().get("task", {}).get("id")
    rp = ct.post(f"/api/teacher/tasks/{tid2}/publish", json={"class_id": class_id}, headers=ht)
    r = cf.get("/api/notifications?limit=5")
    notifs = r.json().get("items", [])
    has_pub = any(n.get("type") == "task_published" for n in notifs)
    r2 = cf.get("/api/notifications/unread-count")
    n1 = r2.json().get("count", r2.json().get("unread", 0))
    check("发布任务触发学生通知", has_pub and n1 > n0, f"create={create_status}:{create_body} publish={rp.status_code} unread {n0}→{n1}")
    if notifs:
        cf.post(f"/api/notifications/{notifs[0]['id']}/read", headers=hf)
        r3 = cf.get("/api/notifications/unread-count")
        check("通知标记已读", r3.json().get("count", r3.json().get("unread", 0)) <= n1, "")

    # 任务批量归档
    two = [cf.post("/api/tasks", json={"title": f"批量验证{i}", "cap_ids": [cap_id]}, headers=hf).json() for i in range(2)]
    ids = [t.get("id") or t.get("task", {}).get("id") for t in two]
    r = cf.post("/api/tasks/batch", json={"ids": ids, "action": "archive"}, headers=hf)
    res = r.json().get("results", [])
    check("任务批量归档", r.status_code == 200 and all(x.get("ok") for x in res) and len(res) == 2, f"{res}")

    # 教师 AI 任务卡生成（离线模板）
    r = ct.post("/api/teacher/tasks/generate", json={"description": "车载语音助手唤醒词检测标注实训：完成正负例判定与边界标注"}, headers=ht)
    draft = r.json()
    check("教师 AI 任务卡生成", r.status_code == 200 and draft.get("cap_ids") and draft.get("steps") and draft.get("citations") is not None, f"caps={len(draft.get('cap_ids', []))} citations={len(draft.get('citations', []))}")

    # 诊断授权链路：学生开启 → 教师可见；关闭 → 403
    fresh_diagnostic = cf.post("/api/diagnostics", files={"file": ("s2.TextGrid", tg.encode(), "text/plain")}, data={"data_type": "audio"}, headers=hf)
    diagnostic_token = fresh_diagnostic.json().get("diagnostic_token")
    saved_diagnostic = cf.post("/api/diagnostics/save-summary", json={"diagnostic_token": diagnostic_token}, headers=hf)
    stu_id = cf.get("/api/auth/session").json()["user"]["id"]
    r = ct.get(f"/api/teacher/classes/{class_id}/students/{stu_id}/diagnostics", headers=ht)
    denied = r.status_code == 403
    cf.patch("/api/profile", json={"share_diagnostics": True}, headers=hf)
    r = ct.get(f"/api/teacher/classes/{class_id}/students/{stu_id}/diagnostics", headers=ht)
    granted = r.status_code == 200 and len(r.json().get("items", [])) >= 1
    check("诊断授权后教师可见（默认拒绝）", fresh_diagnostic.status_code == 200 and saved_diagnostic.status_code == 200 and denied and granted, f"saved={saved_diagnostic.status_code} denied={denied} granted={granted}")

    # 召回记录（学生问答已触发）
    docs = ct.get("/api/rag/documents?limit=1", headers=ht).json().get("items", [])
    if docs:
        r = ct.get(f"/api/rag/documents/{docs[0]['id']}/recall-records", headers=ht)
        check("资料召回记录", r.status_code == 200 and r.json().get("total", 0) >= 0, f"total={r.json().get('total')}")

    # 资料批量操作（送审→发布链路已完成一单，此处批量重新索引）
    r = ct.post("/api/rag/documents/batch", json={"ids": [doc_id], "action": "reindex"}, headers=ht)
    res = r.json().get("results", [])
    check("资料批量重新索引", r.status_code == 200 and res and res[0].get("ok"), f"{res}")

    # CSV 解析（P1 格式）
    csv_content = "名称,阈值\n日合格率,96%\n抽检比例,10%\n"
    data_csv = {"title": "质检指标表", "source_type": "standard", "source_name": "标航教研组", "version": "v1.0", "license_status": "internal", "visibility": "teacher", "data_types": "text"}
    r = ct.post("/api/rag/documents", files={"file": ("qa.csv", csv_content.encode("utf-8-sig"), "text/csv")}, data=data_csv, headers=ht)
    check("CSV 资料解析入库", r.status_code in (200, 201, 202), f"status={r.status_code}")

    # 评测历史列表
    r = ct.get("/api/rag/eval-runs", headers=ht)
    check("评测历史列表端点", r.status_code == 200 and "items" in r.json(), "")

    # 系统告警评估
    r = ca.get("/api/admin/alerts", headers=ha)
    j = r.json()
    check("系统告警评估端点", r.status_code == 200 and "alerts" in j and "evaluated_at" in j, f"alerts={len(j.get('alerts', []))}")

    failed = [x for x in results if not x[1]]
    print(f"\n== 汇总：{len(results) - len(failed)}/{len(results)} 通过 ==")
    return 1 if failed else 0


def main() -> int:
    """Run the full smoke flow with fresh process-local state and storage."""
    results.clear()
    with isolated_runtime():
        return _run_smoke()


if __name__ == "__main__":
    raise SystemExit(main())
