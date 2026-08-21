"""Rule-based intent and data-type recognition used by the agent planner.

The detector remains provider-independent so task routing still works offline;
the contract only recognizes data type and goal information.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

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
# Persisted clarification payloads are limited to business-neutral slots.
_CLARIFICATION_SLOTS = frozenset({"data_type", "goal", "file"})

_DIAGNOSE_RE = re.compile(r"诊断|检查.{0,6}标注|帮我看看|看看.{0,4}(错|问题)|上传")
_TEACHER_RE = re.compile(r"发布.{0,6}任务|布置|班级任务|给.{0,4}班")
_TASK_CONVERT_RE = re.compile(r"转成任务|转化为任务|任务卡|企业任务|岗位任务")
# Creation requests often insert a domain modifier between the verb and
# ``任务`` (for example, "帮我生成学习任务").  Require either an imperative
# at the beginning or an explicit request cue so explanatory questions such as
# "如何生成学习任务？" keep their normal RAG route instead of opening a task flow.
# 修改/调整/更新 同属任务动词：卡片「继续修改」预填的修订请求据此复用任务链路。
_TASK_CREATE_REQUEST_RE = re.compile(
    r"(?:^\s*(?:请(?:帮我)?|帮我|给我|为我|替我|我要|我想|麻烦|直接)?\s*"
    r"|(?:请|帮我|给我|为我|替我|我要|我想|麻烦|能否|能|可以|可否|直接)\s*)"
    r"(?:生成|创建|制定|安排|修改|调整|更新)\s*(?:一(?:个|份))?\s*"
    r"(?:\S{0,6}的|一下)?\s*(?:学习|练习|标注)?\s*任务(?!的)"
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
QUESTION_GOAL = "你是想学习规范、完成任务，还是诊断已有标注结果？"
QUESTION_FILE_SOURCE = "这个文件是从哪个标注工具导出的？"

@dataclass
class Intent:
    """一次用户输入的识别结果。

    missing 取值："data_type" / "goal" / "file"，
    编排层据此决定是否需要追问（每轮只问一个，见 next_question）。
    """

    kind: str
    data_type: str | None = None
    confidence: float = 0.5
    missing: list[str] = field(default_factory=list)


@dataclass
class ClarificationState:
    """The small, durable context required to continue one clarification flow."""

    kind: str
    data_type: str | None
    goal_text: str
    missing: list[str]
    awaiting_slot: str | None

    def to_payload(self) -> dict[str, Any]:
        """Keep the JSON contract explicit because it is stored in plan_json."""

        return {
            "kind": self.kind,
            "data_type": self.data_type,
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
        expected_missing = _missing_for(kind, data_type)
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
            goal_text=goal_text,
            missing=list(missing),
            awaiting_slot=awaiting_slot,
        )


def _missing_for(
    kind: str,
    data_type: str | None,
) -> list[str]:
    """Compute follow-up slots in one place for detection and resumed turns."""

    missing: list[str] = []
    if kind in (KIND_LEARN_GOAL, KIND_PRESET_START, KIND_TASK_CONVERT, KIND_TEACHER_TASK):
        if data_type is None:
            missing.append("data_type")
    if kind == KIND_UNKNOWN:
        if data_type is None:
            missing.append("data_type")
        missing.append("goal")
    return missing


def _make_intent(
    *,
    kind: str,
    data_type: str | None,
    confidence: float = 0.5,
) -> Intent:
    """Construct an Intent and derive its neutral clarification slots."""

    return Intent(
        kind=kind,
        data_type=data_type,
        confidence=confidence,
        missing=_missing_for(kind, data_type),
    )


def apply_context(
    intent: Intent,
    *,
    data_type: str | None = None,
    prefer_context: bool = True,
) -> Intent:
    """Fill omissions from the run/conversation context before asking again.

    The caller supplies only explicit non-empty context.  By default it is
    authoritative (the usual run > conversation > current-input precedence).
    A resumed clarification can instead retain its already captured slots and
    use conversation context only as a fallback.
    """

    resolved_data_type = (
        data_type or intent.data_type
        if prefer_context
        else intent.data_type or data_type
    )
    return _make_intent(
        kind=intent.kind,
        data_type=resolved_data_type,
        confidence=intent.confidence,
    )


def make_clarification(intent: Intent, goal_text: str) -> ClarificationState:
    """Capture the original goal so short answers cannot replace it as task text."""

    return ClarificationState(
        kind=intent.kind,
        data_type=intent.data_type,
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
    new scope, so it may safely reuse the preceding data type.
    """

    normalized_answer = answer_text.strip()
    if not normalized_answer:
        return None
    if (
        state.kind == KIND_UNKNOWN
        and state.awaiting_slot == "goal"
        and answer.kind == KIND_LEARN_GOAL
        and answer.data_type is None
    ):
        # A complete new request identifies its own data type. Keep those
        # requests independent; only an otherwise ambiguous short learning
        # phrase answers the displayed goal prompt.
        intent = _make_intent(
            kind=KIND_LEARN_GOAL,
            data_type=state.data_type,
            confidence=max(0.5, answer.confidence),
        )
        return intent, normalized_answer
    if answer.kind != KIND_UNKNOWN:
        return None
    data_type = answer.data_type or state.data_type
    intent = _make_intent(
        kind=state.kind,
        data_type=data_type,
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


def detect(text: str, *, has_attachment: bool = False) -> Intent:
    """识别意图。规则按"更具体者优先"排序：诊断 > 教师任务 > 任务转化 >
    预设 > 智能体身份/会话回顾 > 知识问答 > 学习目标 > unknown。"""
    text = (text or "").strip()
    data_type = _detect_data_type(text)

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

    matched_signals = int(data_type is not None) + int(kind != KIND_UNKNOWN)
    confidence = min(0.5 + 0.15 * matched_signals, 0.95)

    missing: list[str] = []
    # Task generation requires a recognized data type before composing a task card.
    # 纯知识问答/诊断不强制（召回与诊断可按全量过滤进行）。
    if kind in (KIND_LEARN_GOAL, KIND_PRESET_START, KIND_TASK_CONVERT, KIND_TEACHER_TASK):
        if data_type is None:
            missing.append("data_type")
    if kind == KIND_UNKNOWN:
        # Ask for the goal last when the requested task itself is still unclear.
        if data_type is None:
            missing.append("data_type")
        missing.append("goal")

    return _make_intent(
        kind=kind,
        data_type=data_type,
        confidence=confidence,
    )


def next_question(intent: Intent) -> str | None:
    """返回当前最关键的**一个**追问（PRD-06 §6.2：每轮只问一个）。

    优先级与蓝图 §10.2 一致：数据类型 → 目标 → 文件来源工具。
    话术逐字取自 PRD-06 §6.2 话术表。
    """
    if "data_type" in intent.missing:
        return QUESTION_DATA_TYPE
    if "goal" in intent.missing:
        return QUESTION_GOAL
    if "file" in intent.missing:
        return QUESTION_FILE_SOURCE
    return None
