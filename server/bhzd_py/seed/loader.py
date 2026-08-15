"""种子数据加载器：`python -m bhzd_py.seed.loader [--demo]`（蓝图 §13）。

幂等策略（为什么不用"先清空再插入"）：所有种子行的 id 用
`uuid5(NAMESPACE_URL, "bhzd:seed:<业务键>")` 从业务键确定性派生，重跑时按
id/唯一键（email、source_code、invite_code）先查后插，已存在即跳过——
既满足 §4 的 hex id 约定，又保证重复执行零副作用，演示环境可随时重跑。

`--demo` 的文档入库走"最小内联管线"：rag/ 完整管线（parsers/chunker/
pipeline）在 Wave2 才落地，这里按相同表结构直接写入 published 态文档 +
切片 + 嵌入 + 审核记录，保证演示与离线评测先行可用；Wave2 管线落地后
两条路径写入的表结构一致，无需迁移。
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import secrets
import sqlite3
import sys
import uuid
from pathlib import Path

from ..config import AppConfig, get_config
from ..db import apply_migrations, connect, utc_now_iso
from ..rag.local_embed import EMBEDDING_MODEL, embed_text
from ..security import hash_password
from .presets import get_presets

logger = logging.getLogger(__name__)

DEMO_PASSWORD = "Demo1234!"
DEFAULT_SCHOOL_NAME = "标航职业学院"
DEMO_CLASS_NAME = "数据标注2301班"
DEMO_CLASS_INVITE_CODE = "BHZD-DATA-2301"

_DEMO_DOCS_DIR = Path(__file__).resolve().parent / "demo_docs"

# 每篇演示文档的入库元数据（键为 demo_docs 下的文件名）
# 能力节点均取自真实图谱节点，保证图谱联动演示不出现悬空引用
_DEMO_DOC_META: dict[str, dict] = {
    "智能客服语音标注规范-v2.3.md": {
        "source_type": "enterprise",
        "data_types": ["audio"],
        "cap_ids": [
            "CAP-AUD-EMOTION-PARALING-001",
            "CAP-AUD-TRANSCRIBE-PUNCT-001",
            "CAP-AUD-SPEAKER-001",
        ],
        "publisher": "标航智导合作企业语音数据组",
    },
    "车载唤醒词标注指南-v1.4.md": {
        "source_type": "enterprise",
        "data_types": ["audio"],
        "cap_ids": ["CAP-AUD-WAKE-COMMAND-001", "CAP-AUD-NOISE-OVERLAP-001"],
        "publisher": "标航智导合作企业车载语音项目组",
    },
    "NER实体标注规范-v3.0.md": {
        "source_type": "standard",
        "data_types": ["text"],
        "cap_ids": ["CAP-TXT-ENTITY-BOUNDARY-001", "CAP-TXT-ENTITY-TYPE-001"],
        "publisher": "标航职业学院数据标注教研室",
    },
    "1+X数据标注职业技能考试说明-v2026.md": {
        "source_type": "standard",
        "data_types": ["text", "image", "audio"],
        "cap_ids": ["CAP-CORE-LABEL-SCHEMA-001", "CAP-CORE-EXPORT-QA-001"],
        "publisher": "1+X 数据标注职业技能等级证书考核办公室",
    },
}

# 每篇文档 5 条骨架评测用例（问题/参考答案），共 20 条
_EVAL_CASES: dict[str, list[tuple[str, str]]] = {
    "智能客服语音标注规范-v2.3.md": [
        ("客服通话里客户语速加快、音调升高并叹气，应标什么情感标签？", "应标 anxious（焦虑），判定以语音表现为准而非文字内容。"),
        ("客服语音标注中听不清的片段怎么处理？", "用 [UNK] 标记，禁止臆测补全。"),
        ("副语言事件包括哪些？", "笑声、叹气、咳嗽和超过 2 秒的长时间沉默。"),
        ("单个语音切分段的时长要求是什么？", "不小于 200 毫秒、不超过 30 秒。"),
        ("客服语音一级质检通过率低于多少会整批退回？", "低于 95% 整批退回。"),
    ],
    "车载唤醒词标注指南-v1.4.md": [
        ("唤醒词边界误差要求控制在多少以内？", "±50 毫秒以内。"),
        ("车载唤醒词负例分哪三类？", "near_miss（近音词）、partial（只说出部分唤醒词）、noise_trigger（环境音中的同音片段）。"),
        ("为什么负例样本不能删除？", "负例是抑制误唤醒的关键训练信号，占比应保持 30% 以上。"),
        ("唤醒词与他人说话声完全重叠时怎么办？", "标记 overlap=true 并提交复核，不强行切分。"),
        ("批次抽检中边界误差超差样本占比多少会整批返工？", "超过 5% 时整批返工。"),
    ],
    "NER实体标注规范-v3.0.md": [
        ("BIO 标注中实体首字和非实体字分别标什么？", "实体首字标 B-类型，非实体字标 O，实体后续字标 I-类型。"),
        ("NER 标注允许嵌套实体吗？冲突时怎么处理？", "不允许嵌套；长短候选冲突时取最长完整实体。"),
        ("“苹果”在 NER 中如何判定是否标为 PRODUCT？", "按上下文判定：指手机品牌时标 PRODUCT，指水果时为普通名词标 O。"),
        ("NER 交付验收的实体级 F1 要求是多少？", "精确率与召回率均不得低于 0.92。"),
        ("双人标注不一致率超过多少需要第三人仲裁？", "超过 8% 时启动第三人仲裁。"),
    ],
    "1+X数据标注职业技能考试说明-v2026.md": [
        ("1+X 数据标注中级考试的总时长和合格线是多少？", "总时长 150 分钟，总分 100 分，70 分合格。"),
        ("实操图像标注题的 IOU 合格线是多少？", "IOU ≥ 0.85 得分（v2026 由 0.80 提升至 0.85）。"),
        ("实操部分包含哪三个标注任务？", "文本分类、图像矩形框标注、语音片段切分与转写。"),
        ("标注错误分哪几个等级？", "一级致命、二级严重、三级轻微。"),
        ("考试中出现一级错误会怎样？", "该任务直接判零分。"),
    ],
}


def _seed_id(key: str) -> str:
    """由业务键派生确定性 hex id：幂等的基石（见模块 docstring）。"""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"bhzd:seed:{key}").hex


def _insert_user(
    conn: sqlite3.Connection,
    *,
    email: str,
    name: str,
    role: str,
    password_hash: str,
    school_id: str | None,
) -> tuple[str, bool]:
    """按邮箱先查后插用户与口令，返回 (user_id, 是否新建)。"""
    existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        return existing["id"], False
    now = utc_now_iso()
    user_id = _seed_id(f"user:{email}")
    conn.execute(
        "INSERT INTO users (id, email, name, role, status, school_id, email_verified_at, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?)",
        (user_id, email, name, role, school_id, now, now, now),
    )
    conn.execute(
        "INSERT INTO user_credentials (user_id, password_hash, algo, updated_at) VALUES (?, ?, 'argon2id', ?)",
        (user_id, password_hash, now),
    )
    return user_id, True


def _validate_presets(config: AppConfig) -> list[str]:
    """校验预设引用的图谱节点/教学单元是否存在，返回告警列表（只告警不阻断）。"""
    warnings: list[str] = []
    data_dir = Path(config.resolved_data_dir)
    graph_path = data_dir / "graph" / "annotation-capability-graph.json"
    units_path = data_dir / "curriculum" / "teaching-units.json"
    node_ids: set[str] = set()
    unit_ids: set[str] = set()
    try:
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        node_ids = {node["id"] for node in graph.get("nodes", [])}
    except Exception as exc:  # 图谱缺失时降级为只告警：seed 不应被内容数据卡死
        warnings.append(f"能力图谱加载失败，跳过 cap_ids 校验：{exc}")
    try:
        units = json.loads(units_path.read_text(encoding="utf-8"))
        unit_ids = {unit["id"] for unit in units.get("units", [])}
    except Exception as exc:
        warnings.append(f"教学单元加载失败，跳过 unit_ids 校验：{exc}")
    for preset in get_presets():
        for cap_id in preset["cap_ids"]:
            if node_ids and cap_id not in node_ids:
                warnings.append(f"预设 {preset['id']} 引用了不存在的能力节点 {cap_id}")
        for unit_id in preset["unit_ids"]:
            if unit_ids and unit_id not in unit_ids:
                warnings.append(f"预设 {preset['id']} 引用了不存在的教学单元 {unit_id}")
    return warnings


def _split_markdown_chunks(text: str, target_chars: int = 400) -> list[tuple[str, str | None]]:
    """按标题边界把 markdown 切成约 target_chars 的块，返回 (内容, 所属标题) 列表。

    先按 `#`/`##` 标题切段，再贪心合并相邻小段、拆分超长段（按段落空行），
    保证切片不横跨主题——检索时标题继承是召回质量的关键（蓝图 rag_settings
    title_inherit 默认开启的原因）。
    """
    sections: list[tuple[str | None, list[str]]] = []
    current_title: str | None = None
    current_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("#"):
            if current_lines:
                sections.append((current_title, current_lines))
            current_title = line.lstrip("#").strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_lines:
        sections.append((current_title, current_lines))

    chunks: list[tuple[str, str | None]] = []
    buffer = ""
    buffer_title: str | None = None
    for title, lines in sections:
        body = "\n".join(lines).strip()
        if not body:
            continue
        # 单段超过目标长度：按段落（空行）再拆，避免超大块稀释向量主题
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
        for para in paragraphs:
            candidate = f"{buffer}\n\n{para}".strip() if buffer else para
            if buffer and len(candidate) > target_chars:
                chunks.append((buffer, buffer_title))
                buffer, buffer_title = para, title
            else:
                buffer, buffer_title = candidate, buffer_title or title
    if buffer:
        chunks.append((buffer, buffer_title))
    return chunks


def _ingest_demo_document(
    conn: sqlite3.Connection,
    *,
    path: Path,
    meta: dict,
    created_by: str,
) -> tuple[str, int, bool]:
    """把一篇演示文档内联走完整管线至 published，返回 (doc_id, 切片数, 是否新建)。"""
    title = re.sub(r"-v[\d.]+\.md$", "", path.name)
    version_match = re.search(r"-(v[\d.]+)\.md$", path.name)
    version = version_match.group(1) if version_match else "v1.0"
    doc_id = _seed_id(f"doc:{path.name}")
    existing = conn.execute("SELECT id FROM rag_documents WHERE id = ?", (doc_id,)).fetchone()
    if existing:
        chunk_count = conn.execute(
            "SELECT COUNT(*) AS n FROM rag_chunks WHERE document_id = ?", (doc_id,)
        ).fetchone()["n"]
        return doc_id, chunk_count, False

    now = utc_now_iso()
    text = path.read_text(encoding="utf-8")
    ledger_id = _seed_id(f"ledger:{path.name}")
    conn.execute(
        "INSERT INTO source_ledgers (id, source_code, name, publisher, source_type, version,"
        " authorization_status, valid_from, valid_to, related_document_ids_json,"
        " review_status, notes, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, 'approved', '2026-01-01', '2027-12-31', ?, 'published', ?, ?, ?)",
        (
            ledger_id,
            f"LEDGER-{doc_id[:8].upper()}",
            title,
            meta["publisher"],
            meta["source_type"],
            version,
            json.dumps([doc_id], ensure_ascii=False),
            "演示模式内置规范文档，已获授权",
            now,
            now,
        ),
    )
    conn.execute(
        "INSERT INTO rag_documents (id, title, file_type, source_type, source_name, source_url,"
        " source_ledger_id, version, license_status, data_types_json,"
        " cap_ids_json, visibility, status, storage_path, file_hash, process_version,"
        " created_by, created_at, updated_at, published_at)"
        " VALUES (?, ?, 'md', ?, ?, NULL, ?, ?, 'authorized', ?, ?, 'student', 'published',"
        " NULL, NULL, 1, ?, ?, ?, ?)",
        (
            doc_id,
            title,
            meta["source_type"],
            meta["publisher"],
            ledger_id,
            version,
            json.dumps(meta["data_types"], ensure_ascii=False),
            json.dumps(meta["cap_ids"], ensure_ascii=False),
            created_by,
            now,
            now,
            now,
        ),
    )
    chunks = _split_markdown_chunks(text)
    for index, (content, section_title) in enumerate(chunks):
        conn.execute(
            "INSERT INTO rag_chunks (id, document_id, chunk_index, content, summary,"
            " keywords_json, section_title, token_count, embedding, embedding_model,"
            " metadata_json, status, process_version)"
            " VALUES (?, ?, ?, ?, NULL, '[]', ?, ?, ?, ?, '{}', 'active', 1)",
            (
                _seed_id(f"chunk:{path.name}:{index}"),
                doc_id,
                index,
                content,
                section_title,
                len(content),
                embed_text(content),
                EMBEDDING_MODEL,
            ),
        )
    # 审核闭环：approve + publish 两条记录，演示"已审核已发布"的完整链路
    for action in ("approve", "publish"):
        conn.execute(
            "INSERT INTO review_records (id, target_type, target_id, reviewer_id, action, comment, created_at)"
            " VALUES (?, 'rag_document', ?, ?, ?, ?, ?)",
            (_seed_id(f"review:{path.name}:{action}"), doc_id, created_by, action, "演示模式自动审核", now),
        )
    return doc_id, len(chunks), True


def run_seed(demo: bool = False, config: AppConfig | None = None) -> dict:
    """执行种子加载，返回汇总字典（测试与 CLI 共用此入口）。"""
    config = config or get_config()
    conn = connect(config.resolved_database_path)
    summary: dict = {
        "database": config.resolved_database_path,
        "migrations_applied": [],
        "warnings": [],
        "admin_email": config.admin_email,
        "generated_admin_password": None,  # 仅首次创建且未配置密码时回填
        "demo": None,
    }
    try:
        summary["migrations_applied"] = apply_migrations(conn)
        now = utc_now_iso()

        # 1) rag_settings 单行默认值（列默认值由 schema 提供，只写 id 与时间戳）
        conn.execute(
            "INSERT OR IGNORE INTO rag_settings (id, updated_at) VALUES (1, ?)", (now,)
        )

        # 2) 默认学校
        school_id = _seed_id("school:default")
        conn.execute(
            "INSERT OR IGNORE INTO schools (id, name, created_at) VALUES (?, ?, ?)",
            (school_id, DEFAULT_SCHOOL_NAME, now),
        )

        # 3) 初始系统管理员：旧变量 BHZD_ADMIN_PASSWORD_HASH 优先（兼容），
        #    其次 BHZD_ADMIN_PASSWORD，都未配置则生成随机密码并打印一次
        password_hash = config.admin_password_hash
        generated_password: str | None = None
        if not password_hash:
            if config.admin_password:
                password_hash = hash_password(config.admin_password)
            else:
                generated_password = secrets.token_urlsafe(12)
                password_hash = hash_password(generated_password)
        admin_id, admin_created = _insert_user(
            conn,
            email=config.admin_email,
            name="系统管理员",
            role="system_admin",
            password_hash=password_hash,
            school_id=school_id,
        )
        # 管理员已存在时不消耗随机密码，也不打印（"只打印一次"）
        if not admin_created:
            generated_password = None
        summary["generated_admin_password"] = generated_password

        # 4) 预设引用校验（图谱/单元运行时从 data/ 加载，不入库）
        summary["warnings"] = _validate_presets(config)

        if demo:
            summary["demo"] = _seed_demo(conn, school_id=school_id, admin_id=admin_id)

        conn.commit()
    finally:
        conn.close()
    return summary


def _seed_demo(conn: sqlite3.Connection, *, school_id: str, admin_id: str) -> dict:
    """`--demo` 演示数据：账号、班级、台账、评测用例与 4 篇已发布文档。"""
    demo_summary: dict = {"users_created": 0, "documents": [], "eval_cases": 0}

    demo_users = [
        ("student@demo.bhzd", "演示学生", "student"),
        ("teacher@demo.bhzd", "演示教师", "teacher"),
        ("admin@demo.bhzd", "演示管理员", "system_admin"),
    ]
    user_ids: dict[str, str] = {}
    for email, name, role in demo_users:
        user_id, created = _insert_user(
            conn,
            email=email,
            name=name,
            role=role,
            password_hash=hash_password(DEMO_PASSWORD),
            school_id=school_id,
        )
        user_ids[email] = user_id
        demo_summary["users_created"] += 1 if created else 0
    teacher_id = user_ids["teacher@demo.bhzd"]
    student_id = user_ids["student@demo.bhzd"]
    demo_admin_id = user_ids["admin@demo.bhzd"]

    # 演示学生直接置为"已完成入学测评"：演示账号从指挥舱开始演示主线，
    # 不应被首次使用引导（onboarding gate）拦截；share_diagnostics 默认授权，
    # 便于演示"教师查看诊断详情"链路（真实学生默认关闭，此处仅演示库）
    now = utc_now_iso()
    onboarding_done = json.dumps(
        {"completed_at": now, "note": "演示账号免测评"}, ensure_ascii=False
    )
    conn.execute(
        "INSERT INTO learning_profiles (user_id, onboarding_json, share_diagnostics, created_at, updated_at)"
        " VALUES (?, ?, 1, ?, ?)"
        " ON CONFLICT(user_id) DO UPDATE SET onboarding_json = excluded.onboarding_json",
        (student_id, onboarding_done, now, now),
    )

    # 班级 + 教师归属 + 学生入班（复合主键，重跑天然幂等）
    now = utc_now_iso()
    class_id = _seed_id(f"class:{DEMO_CLASS_NAME}")
    conn.execute(
        "INSERT OR IGNORE INTO classes (id, name, school_id, invite_code, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (class_id, DEMO_CLASS_NAME, school_id, DEMO_CLASS_INVITE_CODE, now),
    )
    conn.execute(
        "INSERT OR IGNORE INTO class_teachers (class_id, teacher_id) VALUES (?, ?)",
        (class_id, teacher_id),
    )
    conn.execute(
        "INSERT OR IGNORE INTO class_enrollments (class_id, student_id, joined_at)"
        " VALUES (?, ?, ?)",
        (class_id, student_id, now),
    )

    # 4 篇演示文档走内联完整管线至 published
    doc_ids: dict[str, str] = {}
    for filename, meta in _DEMO_DOC_META.items():
        doc_id, chunk_count, created = _ingest_demo_document(
            conn, path=_DEMO_DOCS_DIR / filename, meta=meta, created_by=demo_admin_id
        )
        doc_ids[filename] = doc_id
        demo_summary["documents"].append(
            {"title": filename, "id": doc_id, "chunks": chunk_count, "created": created}
        )

    # 20 条骨架评测用例：按 id 先查后插，重跑不重复
    for filename, cases in _EVAL_CASES.items():
        for question, expected in cases:
            case_id = _seed_id(f"eval:{question}")
            exists = conn.execute(
                "SELECT id FROM eval_cases WHERE id = ?", (case_id,)
            ).fetchone()
            if exists:
                continue
            conn.execute(
                "INSERT INTO eval_cases (id, question, expected_answer,"
                " must_hit_document_ids_json, must_hit_chunk_ids_json, filters_json,"
                " created_by, created_at)"
                " VALUES (?, ?, ?, ?, '[]', '{}', ?, ?)",
                (
                    case_id,
                    question,
                    expected,
                    json.dumps([doc_ids[filename]], ensure_ascii=False),
                    demo_admin_id,
                    now,
                ),
            )
            demo_summary["eval_cases"] += 1

    # 示例学习任务（agent 来源，NER 入门）与一条诊断摘要：演示"任务+诊断"数据形态
    task_id = _seed_id("task:demo-ner-intro")
    conn.execute(
        "INSERT OR IGNORE INTO learning_tasks (id, user_id, title, goal, data_type,"
        " cap_ids_json, source, status, steps_json, resources_json,"
        " counts_toward_mastery, created_by, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, 'text', ?, 'agent', 'not_started', ?, '[]', 1, ?, ?, ?)",
        (
            task_id,
            student_id,
            "NER 实体标注入门练习",
            "按 BIO 规范完成一段客服对话的实体标注",
            json.dumps(["CAP-TXT-ENTITY-BOUNDARY-001"], ensure_ascii=False),
            json.dumps(
                [{"title": "通读 NER 规范", "description": "重点掌握 BIO 边界与最长实体优先规则"}],
                ensure_ascii=False,
            ),
            demo_admin_id,
            now,
            now,
        ),
    )
    conn.execute(
        "INSERT OR IGNORE INTO diagnostic_summaries (id, user_id, file_format, data_type,"
        " error_count, severity_counts_json, report_json, weak_cap_ids_json,"
        " plan_json, created_at)"
        " VALUES (?, ?, 'json', 'text', 2, ?, ?, ?, NULL, ?)",
        (
            _seed_id("diag:demo-summary"),
            student_id,
            json.dumps({"minor": 1, "major": 1}, ensure_ascii=False),
            json.dumps(
                {"notice": "演示诊断摘要：实体边界偏移 1 处、标签体系误用 1 处"},
                ensure_ascii=False,
            ),
            json.dumps(["CAP-TXT-ENTITY-BOUNDARY-001"], ensure_ascii=False),
            now,
        ),
    )

    return demo_summary


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：打印人类可读的中文汇总。"""
    parser = argparse.ArgumentParser(description="标航智导数据库种子加载器")
    parser.add_argument("--demo", action="store_true", help="追加演示数据（账号/班级/文档/评测用例）")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    summary = run_seed(demo=args.demo)

    print("== 标航智导种子加载完成 ==")
    print(f"数据库：{summary['database']}")
    applied = summary["migrations_applied"]
    print(f"本次应用迁移：{', '.join(applied) if applied else '无（已是最新）'}")
    print(f"系统管理员：{summary['admin_email']}")
    if summary["generated_admin_password"]:
        # 只在此刻打印一次；不落日志文件，避免明文密码扩散
        print(f"初始管理员随机密码（仅显示一次，请立即保存）：{summary['generated_admin_password']}")
    for warning in summary["warnings"]:
        print(f"告警：{warning}")
    if summary["demo"] is not None:
        demo = summary["demo"]
        print(f"演示账号：student@demo.bhzd / teacher@demo.bhzd / admin@demo.bhzd（密码 {DEMO_PASSWORD}）")
        print(f"演示班级：{DEMO_CLASS_NAME}（邀请码 {DEMO_CLASS_INVITE_CODE}）")
        print(f"本次新建演示用户：{demo['users_created']} 个")
        for doc in demo["documents"]:
            state = "新建" if doc["created"] else "已存在（跳过）"
            print(f"  文档 {doc['title']}：{doc['chunks']} 个切片，{state}")
        print(f"本次新建评测用例：{demo['eval_cases']} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
