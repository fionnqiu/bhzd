"""种子加载器测试：幂等性、演示数据完整性、预设引用无悬空。"""

from __future__ import annotations

import json

from bhzd_py.config import REPO_ROOT
from bhzd_py.db import connect
from bhzd_py.seed.demo_learning_content import get_demo_learning_content
from bhzd_py.seed.loader import run_seed
from bhzd_py.seed.presets import get_presets


def test_seed_is_idempotent(tmp_db_path, clean_admin_env):
    first = run_seed(demo=True)
    # 首次创建管理员且未配置密码 → 生成随机密码（只此一次）
    assert first["generated_admin_password"]
    assert first["warnings"] == []
    assert first["demo"]["tasks_created"] == 8
    assert first["demo"]["knowledge_points_created"] == 16
    assert first["demo"]["exercises_created"] == 24

    second = run_seed(demo=True)
    assert second["generated_admin_password"] is None  # 不再重复打印密码
    assert second["migrations_applied"] == []
    assert second["demo"]["users_created"] == 0
    assert second["demo"]["eval_cases"] == 0
    assert second["demo"]["tasks_created"] == 0
    assert second["demo"]["knowledge_points_created"] == 0
    assert second["demo"]["exercises_created"] == 0
    assert all(not doc["created"] for doc in second["demo"]["documents"])

    # 两次运行后行数不变，证明幂等而非"插入失败被吞掉"
    conn = connect(tmp_db_path)
    try:
        counts = {
            table: conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            for table in (
                "users",
                "rag_documents",
                "rag_chunks",
                "eval_cases",
                "source_ledgers",
                "learning_tasks",
                "task_knowledge_points",
                "task_exercises",
            )
        }
    finally:
        conn.close()
    third = run_seed(demo=True)
    assert third["demo"]["users_created"] == 0
    conn = connect(tmp_db_path)
    try:
        for table, n in counts.items():
            assert conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"] == n
    finally:
        conn.close()


def test_demo_seed_contents(tmp_db_path, clean_admin_env):
    run_seed(demo=True)
    conn = connect(tmp_db_path)
    try:
        # rag_settings 单行
        assert conn.execute("SELECT COUNT(*) AS n FROM rag_settings WHERE id = 1").fetchone()["n"] == 1
        # 演示账号齐、角色对、邮箱已验证
        rows = {
            row["email"]: row
            for row in conn.execute("SELECT email, role, email_verified_at FROM users")
        }
        assert rows["admin@bhzd.local"]["role"] == "system_admin"
        assert rows["student@demo.bhzd"]["role"] == "student"
        assert rows["teacher@demo.bhzd"]["role"] == "teacher"
        assert rows["student@demo.bhzd"]["email_verified_at"] is not None
        # 班级、邀请码、教师归属、学生入班
        clazz = conn.execute("SELECT * FROM classes WHERE name = '数据标注2301班'").fetchone()
        assert clazz is not None and clazz["invite_code"]
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM class_teachers WHERE class_id = ?", (clazz["id"],)
        ).fetchone()["n"] == 1
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM class_enrollments WHERE class_id = ?", (clazz["id"],)
        ).fetchone()["n"] == 1
        # 4 篇文档全部 published + authorized + student 可见，且有带嵌入的切片
        docs = conn.execute("SELECT * FROM rag_documents").fetchall()
        assert len(docs) == 4
        for doc in docs:
            assert doc["status"] == "published"
            assert doc["license_status"] == "authorized"
            assert doc["visibility"] == "student"
            assert doc["published_at"] is not None
            chunk = conn.execute(
                "SELECT embedding, embedding_model FROM rag_chunks WHERE document_id = ? LIMIT 1",
                (doc["id"],),
            ).fetchone()
            assert chunk is not None and len(chunk["embedding"]) == 512 * 4
            # 台账联动：related_document_ids_json 指回文档
            ledger = conn.execute(
                "SELECT related_document_ids_json FROM source_ledgers WHERE id = ?",
                (doc["source_ledger_id"],),
            ).fetchone()
            assert doc["id"] in json.loads(ledger["related_document_ids_json"])
        assert conn.execute("SELECT COUNT(*) AS n FROM source_ledgers").fetchone()["n"] == 4
        assert conn.execute("SELECT COUNT(*) AS n FROM eval_cases").fetchone()["n"] == 20
        # 每条预设都有一张项目相关任务卡、两个知识点和三道练习；
        # graph_task 资源让学生任务可以回溯到知识图谱的具体 TSK 节点。
        tasks = conn.execute(
            "SELECT id, source, content_status, resources_json FROM learning_tasks "
            "WHERE user_id = (SELECT id FROM users WHERE email = 'student@demo.bhzd') "
            "ORDER BY id"
        ).fetchall()
        assert len(tasks) == 8
        expected_graph_tasks = {
            lesson["graph_task_id"] for lesson in get_demo_learning_content()
        }
        graph_task_refs = set()
        for task in tasks:
            assert task["source"] == "preset"
            assert task["content_status"] == "done"
            resources = json.loads(task["resources_json"])
            graph_resources = [item for item in resources if item.get("type") == "graph_task"]
            assert len(graph_resources) == 1
            graph_task_refs.add(graph_resources[0]["ref_id"])
            assert conn.execute(
                "SELECT COUNT(*) AS n FROM task_knowledge_points WHERE task_id = ?", (task["id"],)
            ).fetchone()["n"] == 2
            assert conn.execute(
                "SELECT COUNT(*) AS n FROM task_exercises WHERE task_id = ?", (task["id"],)
            ).fetchone()["n"] == 3
        assert graph_task_refs == expected_graph_tasks
        assert conn.execute("SELECT COUNT(*) AS n FROM task_knowledge_points").fetchone()["n"] == 16
        assert conn.execute("SELECT COUNT(*) AS n FROM task_exercises").fetchone()["n"] == 24
        # 每篇文档 approve + publish 两条审核记录
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM review_records WHERE target_type = 'rag_document'"
        ).fetchone()["n"] == 8
    finally:
        conn.close()


def test_presets_have_no_dangling_references():
    """预设的 cap_ids/unit_ids 必须全部存在于真实图谱与单元库。"""
    graph_path = REPO_ROOT / "data" / "graph" / "annotation-capability-graph.json"
    units_path = REPO_ROOT / "data" / "curriculum" / "teaching-units.json"
    node_ids = {n["id"] for n in json.loads(graph_path.read_text(encoding="utf-8"))["nodes"]}
    unit_ids = {u["id"] for u in json.loads(units_path.read_text(encoding="utf-8"))["units"]}
    presets = get_presets()
    assert len(presets) == 8
    for preset in presets:
        for cap_id in preset["cap_ids"]:
            assert cap_id in node_ids, f"{preset['id']} 悬空能力 {cap_id}"
        for unit_id in preset["unit_ids"]:
            assert unit_id in unit_ids, f"{preset['id']} 悬空单元 {unit_id}"
    for lesson in get_demo_learning_content():
        assert lesson["graph_task_id"] in node_ids, (
            f"{lesson['preset_id']} 悬空图谱任务 {lesson['graph_task_id']}"
        )
