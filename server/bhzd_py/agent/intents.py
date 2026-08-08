"""规则式意图 / 数据类型 / 场景识别（蓝图 §10.1，PRD-06 §6.2）。

设计取向（为什么是纯规则、不依赖 LLM）：
- 离线优先：未配置任何 provider 时指挥舱仍须可用（PRD-06 §11 降级），
  意图识别是编排的第一步，不能成为单点。
- 中文关键词打分即可覆盖 PRD 语料（数据类型四枚举、场景五枚举、目标六类），
  确定性行为也让追问规则"每轮只问一个"可测试、可验收。

场景 id 映射：data/graph/annotation-capability-graph.json 中真实的 SCN 节点
id 硬编码于 `SCENARIO_ID_MAP`（已核对数据文件）；若图谱结构后续变化，
graphx 就绪时可在 `_resolve_scenario_id` 处做存在性校验，加载失败也不
回退到臆造的 slug id——硬编码值本身就是真实 id。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---- 数据类型关键词（蓝图枚举 text/image/audio/video）----
# 覆盖 PRD 语料：NER/COCO/VOC/TextGrid/框选/转写/唤醒词等（任务书要求）
DATA_TYPE_KEYWORDS: dict[str, list[str]] = {
    "audio": [
        "语音", "音频", "转写", "唤醒词", "唤醒", "声纹", "说话人",
        "textgrid", "praat", "切片", "副语言",
    ],
    "image": [
        "图像", "图片", "影像", "框选", "拉框", "目标检测", "分割",
        "关键点", "边界框", "bbox", "coco", "voc", "yolo",
    ],
    "video": [
        "视频", "抽帧", "目标跟踪", "轨迹", "reid", "re-id", "动作识别",
    ],
    "text": [
        "文本", "文字", "ner", "命名实体", "实体识别", "分词", "词性",
        "文本分类", "意图识别", "关键词抽取",
    ],
}

# ---- 场景名 → 真实 SCN id（源自 data/graph/annotation-capability-graph.json）----
SCENARIO_ID_MAP: dict[str, str] = {
    "customer_service": "SCN-CUSTOMER-SERVICE-001",
    "in_vehicle": "SCN-IN-VEHICLE-001",
    "medical": "SCN-MEDICAL-001",
    "content_safety": "SCN-CONTENT-SAFETY-001",
}

SCENARIO_KEYWORDS: dict[str, list[str]] = {
    "customer_service": ["客服", "智能客服", "客服语音", "呼叫中心", "话务"],
    "in_vehicle": ["车载", "车载语音", "座舱", "车内", "车机", "行车"],
    "medical": ["医疗", "医学", "病历", "临床", "医工"],
    "content_safety": ["内容安全", "内容审核", "安全审核", "审核"],
}
# "通用"是显式选择而非缺失：图谱中没有通用 SCN 节点（掌握度约定 scenario_id=''
# 表示通用），因此识别到通用时 scenario_id 记 None 且不计入 missing。
GENERIC_SCENARIO_KEYWORDS = ["通用"]

# ---- 目标类意图关键词（蓝图 §10.1 六类 + unknown）----
KIND_LEARN_GOAL = "learn_goal"
KIND_PRESET_START = "preset_start"
KIND_DIAGNOSE_UPLOAD = "diagnose_upload"
KIND_RAG_QUESTION = "rag_question"
KIND_TASK_CONVERT = "task_convert"
KIND_TEACHER_TASK = "teacher_task"
KIND_AGENT_IDENTITY = "agent_identity"
KIND_CONVERSATION_RECALL = "conversation_recall"
KIND_UNKNOWN = "unknown"

# A persisted clarification is input to a later request, so accept only the
# finite set of slots that the server can safely resume.
_CLARIFICATION_SLOTS = frozenset({"data_type", "scenario", "goal", "file"})

_DIAGNOSE_RE = re.compile(r"诊断|检查.{0,6}标注|帮我看看|看看.{0,4}(错|问题)|上传")
_TEACHER_RE = re.compile(r"发布.{0,6}任务|布置|班级任务|给.{0,4}班")
_TASK_CONVERT_RE = re.compile(r"转成任务|转化为任务|任务卡|企业任务|岗位任务")
# Creation requests often insert a domain modifier between the verb and
# ``任务`` (for example, "帮我生成学习任务").  Require either an imperative
# at the beginning or an explicit request cue so explanatory questions such as
# "如何生成学习任务？" keep their normal RAG route instead of opening a task flow.
_TASK_CREATE_REQUEST_RE = re.compile(
    r"(?:^\s*(?:请(?:帮我)?|帮我|给我|为我|替我|我要|我想|麻烦|直接)?\s*"
    r"|(?:请|帮我|给我|为我|替我|我要|我想|麻烦|能否|能|可以|可否|直接)\s*)"
    r"(?:生成|创建|制定|安排)\s*(?:一(?:个|份))?\s*(?:学习|练习|标注)?\s*任务(?!的)"
)
_PRESET_RE = re.compile(r"预设|入门路径|学习路径|考证路径")
_QUESTION_RE = re.compile(r"(什么是|怎么|如何|为什么|请问|吗[？?]?$|[？?]$)")
_LEARN_RE = re.compile(r"我想学|想学|学习|入门|掌握|提升|学一下|补强")
_CONVERSATION_RECALL_RE = re.compile(
    r"(?:你还记得|还记得.{0,20}(?:之前|前面)|"
    r"(?:我们|咱们).{0,20}(?:之前|前面).{0,20}(?:聊过|聊了|说过|问过)|"
    r"(?:之前|前面).{0,20}(?:聊过|说过|问过)|"
    r"(?:回顾|总结).{0,12}(?:对话|会话|聊天))"
)

# Keep this anchored and address-oriented: a course question such as
# "什么是模型" still belongs to RAG, while questions about this Agent
# must not spend a retrieval turn before the model can answer directly.
_AGENT_IDENTITY_RE = re.compile(
    r"^\s*(?:请问|想问一下|麻烦问下)?\s*(?:"
    r"(?:(?:你|您|这个(?:智能体|助手|系统)|本(?:智能体|助手|系统)|标航智导)\s*)"
    r"(?:"
    r"(?:是|用(?:的)?(?:是)?|使用(?:的)?(?:是)?|属于)(?:什么|哪个|哪种)(?:大)?模型"
    r"|(?:是|叫)谁"
    r"|(?:是|做)什么的"
    r"|(?:能|可以|会)(?:做|帮(?:我)?做|提供)(?:什么|哪些)(?:事|事情|功能|能力)?"
    r"|(?:有什么|有哪些|具备什么)(?:功能|能力)"
    r"|(?:功能|能力)(?:是|有)(?:什么|哪些)"
    r"|介绍(?:一下)?(?:你|自己)"
    r")"
    r"|(?:能|可以|会)(?:做|帮(?:我)?做|提供)(?:什么|哪些)(?:事|事情|功能|能力)?"
    r"|(?:有什么|有哪些|具备什么)(?:功能|能力)"
    r")\s*(?:吗)?\s*[？?!！。.]?\s*$",
    re.IGNORECASE,
)

# PRD-06 §6.2 话术表（逐字，前端/测试均按原文断言，不得改写）
QUESTION_DATA_TYPE = "你要学习的是文本、图像、语音还是视频标注？"
QUESTION_SCENARIO = "这次任务更接近通用、客服、车载、医疗还是内容安全场景？"
QUESTION_GOAL = "你是想学习规范、完成任务，还是诊断已有标注结果？"
QUESTION_FILE_SOURCE = "这个文件是从哪个标注工具导出的？"


@dataclass
class Intent:
    """一次用户输入的识别结果。

    missing 取值："data_type" / "scenario" / "goal" / "file"，
    编排层据此决定是否需要追问（每轮只问一个，见 next_question）。
    """

    kind: str
    data_type: str | None = None
    scenario_id: str | None = None
    # ``None`` can mean either an unknown scenario or the user's explicit
    # “通用” answer.  Preserve that distinction for durable follow-up state.
    generic_scenario: bool = False
    confidence: float = 0.5
    missing: list[str] = field(default_factory=list)


@dataclass
class ClarificationState:
    """The small, durable context required to continue one clarification flow."""

    kind: str
    data_type: str | None
    scenario_id: str | None
    generic_scenario: bool
    goal_text: str
    missing: list[str]
    awaiting_slot: str | None

    def to_payload(self) -> dict[str, Any]:
        """Keep the JSON contract explicit because it is stored in plan_json."""

        return {
            "kind": self.kind,
            "data_type": self.data_type,
            "scenario_id": self.scenario_id,
            "generic_scenario": self.generic_scenario,
            "goal_text": self.goal_text,
            "missing": self.missing,
            "awaiting_slot": self.awaiting_slot,
        }

    @classmethod
    def from_payload(cls, value: object) -> "ClarificationState | None":
        """Load a self-consistent durable clarification without rebuilding its slots.

        ``missing`` and ``awaiting_slot`` describe the question that was actually
        shown to the user.  Recomputing them here would hide corrupt or stale
        JSON and can make a short reply resume against the wrong question.
        """

        if not isinstance(value, dict):
            return None
        kind = value.get("kind")
        goal_text = value.get("goal_text")
        data_type = value.get("data_type")
        scenario_id = value.get("scenario_id")
        generic_scenario = value.get("generic_scenario")
        missing = value.get("missing")
        awaiting_slot = value.get("awaiting_slot")
        if (
            kind not in {
                KIND_LEARN_GOAL,
                KIND_PRESET_START,
                KIND_TASK_CONVERT,
                KIND_TEACHER_TASK,
                KIND_UNKNOWN,
            }
            or not isinstance(goal_text, str)
            or not goal_text.strip()
            or data_type is not None and not isinstance(data_type, str)
            or scenario_id is not None and not isinstance(scenario_id, str)
            or not isinstance(generic_scenario, bool)
            or not isinstance(missing, list)
            or not missing
            or any(
                not isinstance(slot, str) or slot not in _CLARIFICATION_SLOTS
                for slot in missing
            )
            or len(set(missing)) != len(missing)
            or awaiting_slot is not None
            and (
                not isinstance(awaiting_slot, str)
                or awaiting_slot not in _CLARIFICATION_SLOTS
            )
        ):
            return None
        expected_missing = _missing_for(
            kind, data_type, scenario_id, generic_scenario
        )
        # Persisted state is canonical at question time.  Validate its shape
        # before retaining it verbatim, rather than silently replacing it with
        # a newly computed value after an implementation or data-version drift.
        if (
            missing != expected_missing
            or awaiting_slot != next(iter(missing), None)
        ):
            return None
        return cls(
            kind=kind,
            data_type=data_type,
            scenario_id=scenario_id,
            generic_scenario=generic_scenario,
            goal_text=goal_text,
            missing=list(missing),
            awaiting_slot=awaiting_slot,
        )


def _missing_for(
    kind: str,
    data_type: str | None,
    scenario_id: str | None,
    generic_scenario: bool,
) -> list[str]:
    """Compute follow-up slots in one place for detection and resumed turns."""

    missing: list[str] = []
    if kind in (KIND_LEARN_GOAL, KIND_PRESET_START, KIND_TASK_CONVERT, KIND_TEACHER_TASK):
        if data_type is None:
            missing.append("data_type")
        if scenario_id is None and not generic_scenario:
            missing.append("scenario")
    if kind == KIND_UNKNOWN:
        if data_type is None:
            missing.append("data_type")
        if scenario_id is None and not generic_scenario:
            missing.append("scenario")
        missing.append("goal")
    return missing


def _make_intent(
    *,
    kind: str,
    data_type: str | None,
    scenario_id: str | None,
    generic_scenario: bool,
    confidence: float = 0.5,
) -> Intent:
    """Construct an Intent while retaining whether a null scenario is intentional."""

    return Intent(
        kind=kind,
        data_type=data_type,
        scenario_id=scenario_id,
        generic_scenario=generic_scenario,
        confidence=confidence,
        missing=_missing_for(kind, data_type, scenario_id, generic_scenario),
    )


def apply_context(
    intent: Intent,
    *,
    data_type: str | None = None,
    scenario_id: str | None = None,
    prefer_context: bool = True,
) -> Intent:
    """Fill omissions from the run/conversation context before asking again.

    The caller supplies only explicit non-empty context.  By default it is
    authoritative (the usual run > conversation > current-input precedence).
    A resumed clarification can instead retain its already captured slots and
    use conversation context only as a fallback.  A generic answer remains
    distinguishable from an absent scenario in both modes.
    """

    resolved_data_type = (
        data_type or intent.data_type
        if prefer_context
        else intent.data_type or data_type
    )
    if prefer_context and scenario_id:
        resolved_scenario_id = scenario_id
        resolved_generic = False
    elif intent.scenario_id is not None or intent.generic_scenario:
        resolved_scenario_id = intent.scenario_id
        resolved_generic = intent.generic_scenario
    elif scenario_id:
        resolved_scenario_id = scenario_id
        resolved_generic = False
    else:
        resolved_scenario_id = None
        resolved_generic = False
    return _make_intent(
        kind=intent.kind,
        data_type=resolved_data_type,
        scenario_id=resolved_scenario_id,
        generic_scenario=resolved_generic,
        confidence=intent.confidence,
    )


def make_clarification(intent: Intent, goal_text: str) -> ClarificationState:
    """Capture the original goal so short answers cannot replace it as task text."""

    return ClarificationState(
        kind=intent.kind,
        data_type=intent.data_type,
        scenario_id=intent.scenario_id,
        generic_scenario=intent.generic_scenario,
        goal_text=goal_text,
        missing=list(intent.missing),
        awaiting_slot=next(iter(intent.missing), None),
    )


def resume_clarification(
    state: ClarificationState, answer: Intent, answer_text: str
) -> tuple[Intent, str] | None:
    """Merge a short answer into only the immediately previous clarification.

    A newly recognized intent deliberately returns ``None``: that input starts a
    new request rather than accidentally inheriting a prior user's incomplete
    task.  The exception is a bare learn-goal reply while the prior question
    explicitly awaits ``goal``.  It supplies the missing goal, rather than a
    new scope, so it may safely reuse the preceding data type and scenario.
    """

    normalized_answer = answer_text.strip()
    if not normalized_answer:
        return None
    if (
        state.kind == KIND_UNKNOWN
        and state.awaiting_slot == "goal"
        and answer.kind == KIND_LEARN_GOAL
        and answer.data_type is None
        and answer.scenario_id is None
        and not answer.generic_scenario
    ):
        # A complete new request identifies its own type or scenario.  Keep
        # those requests independent; only the otherwise ambiguous short
        # phrase (for example “学习规范”) answers the displayed goal prompt.
        intent = _make_intent(
            kind=KIND_LEARN_GOAL,
            data_type=state.data_type,
            scenario_id=state.scenario_id,
            generic_scenario=state.generic_scenario,
            confidence=max(0.5, answer.confidence),
        )
        return intent, normalized_answer
    if answer.kind != KIND_UNKNOWN:
        return None
    data_type = answer.data_type or state.data_type
    if answer.scenario_id is not None or answer.generic_scenario:
        scenario_id = answer.scenario_id
        generic_scenario = answer.generic_scenario
    else:
        scenario_id = state.scenario_id
        generic_scenario = state.generic_scenario
    intent = _make_intent(
        kind=state.kind,
        data_type=data_type,
        scenario_id=scenario_id,
        generic_scenario=generic_scenario,
        confidence=max(0.5, answer.confidence),
    )
    return intent, state.goal_text


def _detect_data_type(text: str) -> str | None:
    """按关键词命中数打分取最高；平分时不猜（返回 None 走追问）。"""
    lowered = text.lower()
    scores: dict[str, int] = {}
    for data_type, keywords in DATA_TYPE_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in lowered or kw in text)
        if hits:
            scores[data_type] = hits
    if not scores:
        return None
    best = max(scores.values())
    winners = [dt for dt, s in scores.items() if s == best]
    return winners[0] if len(winners) == 1 else None


def _resolve_scenario_id(scenario_id: str) -> str:
    """校验场景 id 在图谱中存在（graphx 就绪时）；失败时保留硬编码真实 id。

    为什么不做 slug 回退：硬编码表已核对真实数据文件，校验失败只说明
    graphx 未就绪或图谱暂不可读，此时真实 id 仍是最佳答案。
    """
    try:
        from ..graphx import reason as gx_reason  # B4，惰性导入
    except ImportError:
        return scenario_id
    try:
        detail = gx_reason.node_detail(scenario_id)
        if detail:
            return scenario_id
    except Exception:  # 图谱文件不可读等，不阻断意图识别
        logger.warning("场景 id %s 图谱校验失败，沿用硬编码映射", scenario_id)
    return scenario_id


def _detect_scenario(text: str) -> tuple[str | None, bool]:
    """返回 (scenario_id, 是否显式提到通用)；未提及任一场景时二者皆为假值。"""
    for key, keywords in SCENARIO_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return _resolve_scenario_id(SCENARIO_ID_MAP[key]), False
    if any(kw in text for kw in GENERIC_SCENARIO_KEYWORDS):
        return None, True
    return None, False


def detect(text: str, *, has_attachment: bool = False) -> Intent:
    """识别意图。规则按"更具体者优先"排序：诊断 > 教师任务 > 任务转化 >
    预设 > 智能体身份/会话回顾 > 知识问答 > 学习目标 > unknown。"""
    text = (text or "").strip()
    data_type = _detect_data_type(text)
    scenario_id, generic = _detect_scenario(text)

    if has_attachment or _DIAGNOSE_RE.search(text):
        kind = KIND_DIAGNOSE_UPLOAD
    elif _TEACHER_RE.search(text):
        kind = KIND_TEACHER_TASK
    elif _TASK_CONVERT_RE.search(text) or _TASK_CREATE_REQUEST_RE.search(text):
        kind = KIND_TASK_CONVERT
    elif _PRESET_RE.search(text):
        kind = KIND_PRESET_START
    elif _AGENT_IDENTITY_RE.match(text):
        kind = KIND_AGENT_IDENTITY
    elif _CONVERSATION_RECALL_RE.search(text):
        # A recall question must reach private chat memory before generic RAG.
        kind = KIND_CONVERSATION_RECALL
    elif _QUESTION_RE.search(text):
        kind = KIND_RAG_QUESTION
    elif _LEARN_RE.search(text):
        kind = KIND_LEARN_GOAL
    else:
        kind = KIND_UNKNOWN

    matched_signals = int(data_type is not None) + int(
        scenario_id is not None or generic
    ) + int(kind != KIND_UNKNOWN)
    confidence = min(0.5 + 0.15 * matched_signals, 0.95)

    missing: list[str] = []
    # 任务化意图必须有数据类型与场景才能生成可靠任务卡（PRD-06 §6.3）；
    # 纯知识问答/诊断不强制（召回与诊断可按全量过滤进行）。
    if kind in (KIND_LEARN_GOAL, KIND_PRESET_START, KIND_TASK_CONVERT, KIND_TEACHER_TASK):
        if data_type is None:
            missing.append("data_type")
        if scenario_id is None and not generic:
            missing.append("scenario")
    if kind == KIND_UNKNOWN:
        # 目标本身不明时把 goal 放到最后追问（数据类型→场景→目标顺序）
        if data_type is None:
            missing.append("data_type")
        if scenario_id is None and not generic:
            missing.append("scenario")
        missing.append("goal")

    return _make_intent(
        kind=kind,
        data_type=data_type,
        scenario_id=scenario_id,
        generic_scenario=generic,
        confidence=confidence,
    )


def next_question(intent: Intent) -> str | None:
    """返回当前最关键的**一个**追问（PRD-06 §6.2：每轮只问一个）。

    优先级与蓝图 §10.2 一致：数据类型 → 场景 → 目标 → 文件来源工具。
    话术逐字取自 PRD-06 §6.2 话术表。
    """
    if "data_type" in intent.missing:
        return QUESTION_DATA_TYPE
    if "scenario" in intent.missing:
        return QUESTION_SCENARIO
    if "goal" in intent.missing:
        return QUESTION_GOAL
    if "file" in intent.missing:
        return QUESTION_FILE_SOURCE
    return None
