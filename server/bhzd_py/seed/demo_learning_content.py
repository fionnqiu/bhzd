"""项目内置的演示学习内容。

这些内容刻意使用标航智导现有的预设、能力节点和教学单元，保证 demo seed
不依赖 Provider 也能展示一条可学习、可练习、可追溯的任务链路。
"""

from __future__ import annotations

from typing import Any


def _choice(question: str, options: list[str], answer: str) -> dict[str, Any]:
    """构造选择题，保持 seed 定义紧凑并统一选项字段。"""
    return {
        "question": question,
        "type": "multiple_choice",
        "options": options,
        "reference_answer": answer,
    }


def _true_false(question: str, answer: str) -> dict[str, Any]:
    """构造判断题；显式保存选项以便学生端稳定渲染。"""
    return {
        "question": question,
        "type": "true_false",
        "options": ["正确", "错误"],
        "reference_answer": answer,
    }


def _open(question: str, answer: str) -> dict[str, Any]:
    """构造开放题，参考答案只存服务端，学生投影不会返回。"""
    return {
        "question": question,
        "type": "open_ended",
        "options": [],
        "reference_answer": answer,
    }


# 每条预设一条确定性任务；task_key 保留 NER 旧业务键，其他键按预设稳定派生。
# 五条专项路径指向新增的图谱任务节点，方便学生从练习回溯到项目规则。
DEMO_LEARNING_CONTENT: list[dict[str, Any]] = [
    {
        "preset_id": "preset-intro-basics",
        "task_key": "task:demo-intro-basics",
        "graph_task_id": "TSK-TXT-LABEL-AUDIT-001",
        "knowledge_points": [
            {"title": "任务范围与交付物", "content": "先明确标注对象、标签动作、质量门槛和最终交付格式，再开始处理样本。"},
            {"title": "标签体系与导出检查", "content": "标签必须来自任务配置，提交前检查缺失、错标、版本和文件完整性。"},
        ],
        "exercises": [
            _choice("开始标注前最先确认哪一项？", ["任务对象和交付规则", "个人偏好颜色", "文件压缩软件", "浏览器主题"], "任务对象和交付规则"),
            _true_false("只要标签名称正确，就可以跳过导出前质量检查。", "错误"),
            _open("请说明一次基础标注任务的最小质量检查清单。", "应包括任务范围、标签合法性、样本完整性、格式版本和交付文件可追溯性。"),
        ],
    },
    {
        "preset_id": "preset-ner-intro",
        "task_key": "task:demo-ner-intro",
        "graph_task_id": "TSK-TXT-NER-ANNOTATE-001",
        "knowledge_points": [
            {"title": "BIO 边界与偏移", "content": "实体首字使用 B-类型，后续字使用 I-类型，非实体字使用 O；偏移采用零基、end-exclusive。"},
            {"title": "实体类型与歧义", "content": "实体类型依赖上下文，嵌套冲突按项目规范处理，不能把品牌、组织和普通名词混为一类。"},
        ],
        "exercises": [
            _choice("BIO 标注中实体的首个字符应使用哪种前缀？", ["B-类型", "I-类型", "O", "E-类型"], "B-类型"),
            _true_false("“苹果”在所有句子中都应标为 PRODUCT。", "错误"),
            _open("请用项目规则说明如何处理重叠或嵌套实体候选。", "项目练习不允许嵌套；冲突时选择最长的完整实体，并按上下文确定类型。"),
        ],
    },
    {
        "preset_id": "preset-cs-emotion",
        "task_key": "task:demo-cs-emotion",
        "graph_task_id": "TSK-AUD-CUSTOMER-EMOTION-QA-001",
        "knowledge_points": [
            {"title": "客服情感证据", "content": "情感标签要结合语速、音调、停顿等可听证据，不能只依据转写文本猜测。"},
            {"title": "副语言事件区间", "content": "笑声、叹气、咳嗽和长停顿应作为独立事件记录，并与情感标签保持时间对齐。"},
        ],
        "exercises": [
            _choice("客户语速加快、音调升高并叹气，更符合哪类情感？", ["焦虑", "平静", "喜悦", "无关"], "焦虑"),
            _true_false("副语言事件可以直接并入情感标签，不需要独立区间。", "错误"),
            _open("客服情感标注为什么需要区分情感状态和副语言事件？", "两者表达的观察维度不同，分开记录才能支持复核、统计和后续质检。"),
        ],
    },
    {
        "preset_id": "preset-wake-word",
        "task_key": "task:demo-wake-word",
        "graph_task_id": "TSK-AUD-WAKEWORD-ROBUSTNESS-001",
        "knowledge_points": [
            {"title": "唤醒词时间边界", "content": "唤醒词和命令词应按可听起止点切分，项目演示规范要求边界误差控制在 ±50 毫秒内。"},
            {"title": "负例与噪声重叠", "content": "近音词、部分唤醒词和噪声触发都是重要负例；完全重叠时标记 overlap 并提交复核。"},
        ],
        "exercises": [
            _choice("哪一类样本属于唤醒词负例？", ["near_miss 近音词", "已确认正唤醒", "空白文件名", "导出目录"], "near_miss 近音词"),
            _true_false("负例样本可以为了界面整洁而全部删除。", "错误"),
            _open("遇到唤醒词与他人说话完全重叠时，应如何处理？", "标记 overlap=true 并提交复核，不强行切出一个看似精确的边界。"),
        ],
    },
    {
        "preset_id": "preset-image-detection",
        "task_key": "task:demo-image-detection",
        "graph_task_id": "TSK-IMG-IOU-REVIEW-001",
        "knowledge_points": [
            {"title": "紧致矩形框", "content": "矩形框应覆盖可见目标并尽量减少背景，检查坐标顺序、边界越界和非零面积。"},
            {"title": "遮挡与截断", "content": "遮挡表示目标被其他物体挡住，截断表示目标超出画面边界，两者要按项目标签分别记录。"},
        ],
        "exercises": [
            _choice("一个有效矩形框至少应满足什么条件？", ["坐标顺序正确且面积大于零", "四个坐标全部为负", "只填写类别不填坐标", "框住整张画布"], "坐标顺序正确且面积大于零"),
            _true_false("被画面边缘切掉的目标属于遮挡而不是截断。", "错误"),
            _open("请描述一次图像目标框提交前的三项检查。", "检查类别、框的贴合度、坐标范围与顺序，并确认遮挡/截断属性填写正确。"),
        ],
    },
    {
        "preset_id": "preset-video-event",
        "task_key": "task:demo-video-event",
        "graph_task_id": "TSK-VID-EVENT-BOUNDARY-QA-001",
        "knowledge_points": [
            {"title": "行为事件边界", "content": "事件开始帧对应可观察动作出现，结束帧对应动作完成或退出，边界应能被复核。"},
            {"title": "跨帧轨迹一致性", "content": "同一目标在连续帧中保持稳定轨迹 ID，遮挡后重现时依据外观和运动连续性判断是否续接。"},
        ],
        "exercises": [
            _choice("视频事件的起止边界主要依据什么确定？", ["可观察动作的出现与完成", "视频文件大小", "播放器主题", "随机抽取帧"], "可观察动作的出现与完成"),
            _true_false("同一物理目标可以在每一帧随意更换轨迹 ID。", "错误"),
            _open("遮挡后目标重新出现时，如何决定是否沿用原轨迹？", "结合遮挡前后位置、外观和运动连续性判断；证据不足时保留复核而不是强行合并。"),
        ],
    },
    {
        "preset_id": "preset-cert-1x",
        "task_key": "task:demo-cert-1x",
        "graph_task_id": "TSK-TXT-DOCUMENT-CLASSIFY-001",
        "knowledge_points": [
            {"title": "1+X 综合考点", "content": "综合练习覆盖文本分类、图像矩形框和语音切分，必须同时遵守各数据类型的标签与质量规则。"},
            {"title": "考试质量门槛", "content": "演示考试总分 100 分、70 分合格；一级致命错误会使对应任务直接判零分。"},
        ],
        "exercises": [
            _choice("演示的 1+X 中级考试合格线是多少？", ["70 分", "50 分", "60 分", "90 分"], "70 分"),
            _true_false("实操图像框的 IOU 达到 0.85 才满足本演示规范。", "正确"),
            _open("为什么综合考证练习要同时检查文本、图像和语音三类交付物？", "因为证书路径考查跨模态任务执行能力，任一数据类型的规则或质量失控都会影响整体交付。"),
        ],
    },
    {
        "preset_id": "preset-content-safety-text",
        "task_key": "task:demo-content-safety-text",
        "graph_task_id": "TSK-TXT-CONTENT-SAFETY-REVIEW-001",
        "knowledge_points": [
            {"title": "内容安全类别判定", "content": "先识别文本是否命中风险类别，再依据互斥和优先级规则提交稳定标签。"},
            {"title": "上下文与边界案例", "content": "敏感词本身不等于违规结论，需结合说话对象、语境和允许答案集处理歧义并保留复核依据。"},
        ],
        "exercises": [
            _choice("发现敏感词后，下一步最重要的判断是什么？", ["结合上下文确认风险类别", "立即删除样本", "只看词频", "忽略句子其余内容"], "结合上下文确认风险类别"),
            _true_false("出现敏感词就一定可以不看上下文直接判违规。", "错误"),
            _open("内容安全文本审核如何降低边界案例的一致性偏差？", "使用封闭类别、互斥/优先级规则和允许答案集，并对无法确定的案例提交复核。"),
        ],
    },
]


def get_demo_learning_content() -> list[dict[str, Any]]:
    """返回浅拷贝，避免调用方修改模块级演示定义。"""
    return [
        {
            **lesson,
            "knowledge_points": [dict(point) for point in lesson["knowledge_points"]],
            "exercises": [
                {**exercise, "options": list(exercise.get("options", []))}
                for exercise in lesson["exercises"]
            ],
        }
        for lesson in DEMO_LEARNING_CONTENT
    ]
