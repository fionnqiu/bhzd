"""诊断域测试：引擎四格式 + 边界（PRD-06 §9/§14.3）+ 诊断 API（上传/确认/隔离/限制）。"""

from __future__ import annotations

import io
import json

import pytest

from bhzd_py.diagnosis import engine
from bhzd_py.diagnosis.engine import DiagnosticError

from _learning_fixtures import api  # noqa: F401  # pytest 夹具复用

# ---------------------------------------------------------------- 样本文件

TEXTGRID_OVERLAP = '''File type = "ooTextFile"
Object class = "TextGrid"

xmin = 0
xmax = 4.0
tiers? <exists>
size = 1
item []:
    item [1]:
        class = "IntervalTier"
        name = "emotion"
        xmin = 0
        xmax = 4.0
        intervals: size = 3
        intervals [1]:
            xmin = 0
            xmax = 1.5
            text = "happy"
        intervals [2]:
            xmin = 1.2
            xmax = 2.5
            text = "sad"
        intervals [3]:
            xmin = 2.5
            xmax = 4.0
            text = "happy"
'''

COCO_BAD = json.dumps(
    {
        "images": [{"id": 1, "file_name": "a.jpg", "width": 100, "height": 80}],
        "annotations": [
            {"id": 1, "image_id": 1, "category_id": 1, "bbox": [90, 70, 20, 20]},  # 越界
            {"id": 2, "image_id": 1, "category_id": 99, "bbox": [0, 0, 10, 10]},  # 未声明类别
            {"id": 3, "image_id": 1, "category_id": 1, "bbox": [5, 5, 10, 10]},
        ],
        "categories": [{"id": 1, "name": "car"}],
    },
    ensure_ascii=False,
)

VOC_ZERO_AREA = """<?xml version="1.0" encoding="UTF-8"?>
<annotation>
  <filename>b.jpg</filename>
  <size><width>640</width><height>480</height><depth>3</depth></size>
  <object><name>car</name><bndbox><xmin>10</xmin><ymin>10</ymin><xmax>10</xmax><ymax>30</ymax></bndbox></object>
</annotation>
"""

GENERIC_MISSING_END = json.dumps({"annotations": [{"start": 0.0, "label": "happy"}]})


# ---------------------------------------------------------------- 引擎单测


def test_textgrid_valid_with_one_overlap():
    report = engine.diagnose(
        TEXTGRID_OVERLAP.encode("utf-8"), "sample.TextGrid", data_type="audio"
    )
    assert report["file_format"] == "textgrid"
    assert report["sample_count"] == 3
    overlaps = [e for e in report["errors"] if e["error_type"] == "overlap"]
    assert len(overlaps) == 1 and overlaps[0]["severity"] == "minor"
    # 其他合法区间不应误报；相邻共享端点不算重叠
    assert {e["error_type"] for e in report["errors"]} == {"overlap"}


def test_textgrid_empty_label_minor_and_media_duration():
    text = TEXTGRID_OVERLAP.replace('text = "sad"', 'text = ""')
    report = engine.diagnose(text.encode("utf-8"), "t.TextGrid")
    empty = [e for e in report["errors"] if e["error_type"] == "empty_label"]
    assert len(empty) == 1 and empty[0]["severity"] == "minor"  # TextGrid 空白段按惯例记 minor


def test_coco_out_of_bounds_and_bad_category():
    report = engine.diagnose(COCO_BAD.encode("utf-8"), "det.json", data_type="image")
    types = {e["error_type"] for e in report["errors"]}
    assert "bbox_out_of_bounds" in types
    assert "unknown_category" in types
    assert report["file_format"] == "coco_json"
    assert report["sample_count"] == 3
    # 类别 99 未声明 → user_value 是原始 id 字符串；major 级别
    bad_cat = next(e for e in report["errors"] if e["error_type"] == "unknown_category")
    assert bad_cat["severity"] == "major" and bad_cat["user_value"] == "99"


def test_voc_zero_area():
    report = engine.diagnose(VOC_ZERO_AREA.encode("utf-8"), "ann.xml")
    assert report["file_format"] == "voc_xml"
    zero = [e for e in report["errors"] if e["error_type"] == "zero_area_box"]
    assert len(zero) == 1 and zero[0]["severity"] == "major"


def test_generic_json_missing_field_not_scored():
    """缺字段 → FIELDS_MISSING 且消息点名缺哪个字段，不进入评分（PRD-06 §9.2）。"""
    with pytest.raises(DiagnosticError) as excinfo:
        engine.diagnose(GENERIC_MISSING_END.encode("utf-8"), "a.json")
    assert excinfo.value.code == "FIELDS_MISSING"
    assert "start/end" in excinfo.value.message


def test_garbage_parse_failed_with_template_hint():
    with pytest.raises(DiagnosticError) as excinfo:
        engine.diagnose(b"\x89PNG binary garbage", "x.bin")
    assert excinfo.value.code == "PARSE_FAILED"
    assert "TextGrid" in excinfo.value.message  # 提示里带示例模板说明


def test_uncovered_task_type_notice_no_deduction():
    """规则库未覆盖的任务类型：不扣分 + notice（PRD-06 §9.2）。"""
    report = engine.diagnose(
        TEXTGRID_OVERLAP.encode("utf-8"), "t.TextGrid", data_type="hologram"
    )
    assert report["errors"] == []
    assert report["severity_counts"] == {"major": 0, "minor": 0}
    assert "暂未覆盖" in report["notice"]
    assert report["mastery_preview"] == []


def test_report_dto_keys_complete():
    """蓝图 §6.3 DiagnosticReportDTO 最低结构（PRD-06 §9.3）。"""
    report = engine.diagnose(COCO_BAD.encode("utf-8"), "det.json", data_type="image")
    for key in (
        "file_format",
        "sample_count",
        "precheck",
        "errors",
        "severity_counts",
        "weak_cap_ids",
        "mastery_preview",
        "plan",
        "notice",
    ):
        assert key in report, f"报告缺字段 {key}"
    assert set(report["precheck"]) == {"fields", "warnings"}
    for key in ("weak_caps", "pre_path", "resources", "tasks"):
        assert key in report["plan"], f"plan 缺字段 {key}"
    for err in report["errors"]:
        for key in (
            "error_type",
            "severity",
            "user_value",
            "expected",
            "rule",
            "cap_id",
            "cap_name",
            "suggestion",
        ):
            assert key in err, f"错误项缺字段 {key}"


def test_weak_caps_and_plan_present_for_major_errors():
    report = engine.diagnose(COCO_BAD.encode("utf-8"), "det.json", data_type="image")
    # major 错误的 cap 进入 weak_cap_ids（bbox 越界→RECT-VALIDATE，类别→OBJECT-CLASS）
    assert "CAP-IMG-RECT-VALIDATE-001" in report["weak_cap_ids"]
    assert "CAP-IMG-OBJECT-CLASS-001" in report["weak_cap_ids"]
    plan = report["plan"]
    assert [c["cap_id"] for c in plan["weak_caps"]] == report["weak_cap_ids"]
    assert all(c["cap_name"] for c in plan["weak_caps"])  # 中文名已从图谱拼上
    assert plan["pre_path"]  # 图谱在线时有 PRE 路径
    assert plan["resources"] and len(plan["resources"]) <= 5
    assert plan["tasks"]  # 有建议练习标题


def test_mastery_preview_math_two_majors_same_cap():
    """同 cap 两个 major → delta = −0.4（聚合）；engine 无 db，old/new 为 None。"""
    report = engine.diagnose(COCO_BAD.encode("utf-8"), "det.json", data_type="image")
    by_cap = {p["cap_id"]: p for p in report["mastery_preview"]}
    # bbox_out_of_bounds 与 unknown_category 是不同 cap；各自 −0.2
    assert by_cap["CAP-IMG-RECT-VALIDATE-001"]["delta"] == pytest.approx(-0.2)
    assert by_cap["CAP-IMG-OBJECT-CLASS-001"]["delta"] == pytest.approx(-0.2)
    assert by_cap["CAP-IMG-RECT-VALIDATE-001"]["old_score"] is None
    # 无场景时 scenario_id 为 ''（通用掌握度）
    assert by_cap["CAP-IMG-RECT-VALIDATE-001"]["scenario_id"] == ""


def test_cite_fn_attaches_citations():
    """router 注入的 cite_fn 按规则名召回引用；无召回不给 citation（PRD-06 §9.2）。"""
    calls: list[list[str]] = []

    def fake_cite(rule_texts):
        calls.append(rule_texts)
        return [{"rule": rule_texts[0], "citations": [{"title": "规范", "score": 0.9}]}]

    report = engine.diagnose(
        COCO_BAD.encode("utf-8"), "det.json", data_type="image", cite_fn=fake_cite
    )
    assert calls and set(calls[0]) == {e["rule"] for e in report["errors"]}
    cited = [e for e in report["errors"] if "citation" in e]
    assert cited and cited[0]["citation"][0]["title"] == "规范"
    # cite_fn 缺席时不附引用
    plain = engine.diagnose(COCO_BAD.encode("utf-8"), "det.json", data_type="image")
    assert all("citation" not in e for e in plain["errors"])


def test_scenario_label_set_rule():
    """场景规则包有标签集时启用标签合法性校验（医疗场景 configured_labels）。"""
    generic = json.dumps(
        {
            "media_duration": 10.0,
            "annotations": [
                {"start": 0.0, "end": 1.0, "label": "SYMPTOM"},
                {"start": 1.0, "end": 2.0, "label": "NOT_A_LABEL"},
            ],
        }
    )
    report = engine.diagnose(
        generic.encode("utf-8"),
        "a.json",
        data_type="text",
        scenario_id="SCN-MEDICAL-001",
    )
    unknown = [e for e in report["errors"] if e["error_type"] == "unknown_label"]
    assert len(unknown) == 1 and unknown[0]["user_value"] == "NOT_A_LABEL"


# ---------------------------------------------------------------- API 测试


def _upload(client, headers, content: bytes, filename: str, **form):
    files = {"file": (filename, io.BytesIO(content), "application/octet-stream")}
    data = {k: v for k, v in form.items() if v is not None}
    return client.post("/api/diagnostics", files=files, data=data, headers=headers)


def test_upload_save_summary_flow(api):
    """上传 TextGrid → token → save-summary → mastery 行更新 + 摘要行落库。"""
    user = api.login_as("stu@test.local")
    # 先垫一条 0.5 的掌握度，让 −0.05 的诊断扣分有可视空间（否则从 0 扣到 0 看不出变化）
    api.conn.execute(
        "INSERT INTO mastery (user_id, cap_id, scenario_id, score, source, updated_at) "
        "VALUES (?, 'CAP-AUD-NOISE-OVERLAP-001', '', 0.5, 'exercise', '2026-07-01')",
        (user["user_id"],),
    )
    api.conn.commit()
    resp = _upload(
        api.client, user["headers"], TEXTGRID_OVERLAP.encode("utf-8"), "a.TextGrid",
        data_type="audio",
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["file_format"] == "textgrid"
    token = body["diagnostic_token"]
    # 上传时的 mastery_preview 已带真实 old/new（0.5 → 0.45）
    preview = {p["cap_id"]: p for p in body["mastery_preview"]}
    assert preview["CAP-AUD-NOISE-OVERLAP-001"]["old_score"] == pytest.approx(0.5)
    assert preview["CAP-AUD-NOISE-OVERLAP-001"]["new_score"] == pytest.approx(0.45)

    save = api.client.post(
        "/api/diagnostics/save-summary", json={"diagnostic_token": token}, headers=user["headers"]
    )
    assert save.status_code == 200, save.text
    saved = save.json()
    assert saved["summary_id"]
    applied = {a["cap_id"]: a for a in saved["mastery_applied"]}
    assert applied["CAP-AUD-NOISE-OVERLAP-001"]["new_score"] == pytest.approx(0.45)
    row = api.conn.execute(
        "SELECT score FROM mastery WHERE user_id = ? AND cap_id = 'CAP-AUD-NOISE-OVERLAP-001'",
        (user["user_id"],),
    ).fetchone()
    assert row["score"] == pytest.approx(0.45)
    summary = api.conn.execute(
        "SELECT * FROM diagnostic_summaries WHERE id = ?", (saved["summary_id"],)
    ).fetchone()
    assert summary is not None and summary["user_id"] == user["user_id"]
    # token 一次性：确认后失效
    again = api.client.post(
        "/api/diagnostics/save-summary", json={"diagnostic_token": token}, headers=user["headers"]
    )
    assert again.status_code == 410

    listing = api.client.get("/api/diagnostics/summaries")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["id"] == saved["summary_id"]


def test_token_isolated_between_users(api):
    """第二个用户不能拿别人的 diagnostic_token 保存摘要。"""
    owner = api.login_as("owner@test.local")
    resp = _upload(api.client, owner["headers"], TEXTGRID_OVERLAP.encode("utf-8"), "a.TextGrid")
    token = resp.json()["diagnostic_token"]
    other = api.login_as("other@test.local", name="另一个")
    save = api.client.post(
        "/api/diagnostics/save-summary", json={"diagnostic_token": token}, headers=other["headers"]
    )
    assert save.status_code == 403
    # 他人 token 不可见后，原主仍可正常确认（切回原主身份：cookie 是单槽位）
    api.act_as(owner)
    ok = api.client.post(
        "/api/diagnostics/save-summary", json={"diagnostic_token": token}, headers=owner["headers"]
    )
    assert ok.status_code == 200


def test_oversize_upload_rejected(api):
    """PRD-06 §9.1：>20MB 直接 413。"""
    user = api.login_as("big@test.local")
    big = b"x" * (20 * 1024 * 1024 + 1)
    resp = _upload(api.client, user["headers"], big, "big.TextGrid")
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_unverified_user_blocked(api):
    """未验证邮箱：403 EMAIL_NOT_VERIFIED（PRD-06 §3.2）。"""
    user = api.login_as("unverified@test.local", verified=False)
    resp = _upload(api.client, user["headers"], TEXTGRID_OVERLAP.encode("utf-8"), "a.TextGrid")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "EMAIL_NOT_VERIFIED"


def test_upload_garbage_returns_chinese_error(api):
    user = api.login_as("garbage@test.local")
    resp = _upload(api.client, user["headers"], b"\x89PNG....", "x.bin")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "PARSE_FAILED"
    assert "TextGrid" in resp.json()["error"]["message"]
