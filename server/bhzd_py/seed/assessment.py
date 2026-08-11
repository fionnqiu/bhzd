"""入学测评题库（v3.0 §11.1 首次使用流程：注册→选方向目标→入学测评→初始能力地图）。

设计决策（为什么）：
- 题库是**内容数据**而非用户数据，按图谱/教学单元的先例放代码里做常量
  （graphx/seed 同口径：内容运行时加载，不入库），改题走代码评审即可追溯。
- 每题绑定真实 cap_id（data/graph/annotation-capability-graph.json 中存在的
  CAP 节点）：测评结果直接写成这些能力的初始掌握度，前端能力地图无需再做
  一层"题目→能力"的映射。validate_question_caps() 在加载时校验悬空引用。
- 8 题覆盖文本/图像/语音/视频四类标注基础（BIO 边界、IOU 含义、TextGrid 层、
  质检指标、框选规范、唤醒词正负例、情感标签、格式识别），全部为中文单选四选一。
- 答案只经服务端评分接口使用；下发题目的接口必须剥掉 answer_index（防作弊）。
"""

from __future__ import annotations

# 评分规则（任务契约）：答对 +0.4、答错 +0.1 基线分，经 mastery.service 落库 clamp[0,1]
ASSESSMENT_CORRECT_DELTA = 0.4
ASSESSMENT_WRONG_DELTA = 0.1
ASSESSMENT_SOURCE = "assessment"  # mastery_events.source 白名单值之一（蓝图 §5 schema 注释）

QUESTIONS: list[dict] = [
    {
        "id": "q-bio-boundary",
        "question": "在 BIO 序列标注中，一个实体片段的第一个字（词）应该标注为？",
        "options": [
            "I-类型（实体内部）",
            "B-类型（实体起始）",
            "O（非实体）",
            "E-类型（实体结束）",
        ],
        "answer_index": 1,
        "cap_id": "CAP-TXT-ENTITY-BOUNDARY-001",  # 确定实体边界
        "data_type": "text",
    },
    {
        "id": "q-iou-meaning",
        "question": "图像矩形框质检中，IOU（交并比）指的是什么？",
        "options": [
            "预测框与真值框的交集面积除以并集面积",
            "标注框面积占整张图片的比例",
            "两个标注框中心点之间的像素距离",
            "标注框长边与短边的比值",
        ],
        "answer_index": 0,
        "cap_id": "CAP-IMG-RECT-VALIDATE-001",  # 校验矩形框坐标
        "data_type": "image",
    },
    {
        "id": "q-textgrid-tier",
        "question": "Praat TextGrid 文件中的“层（tier）”是用来做什么的？",
        "options": [
            "存储音频的波形数据",
            "在时间轴上分层存放不同维度的标注（如转写、说话人、情感各占一层）",
            "记录音频的采样率与位深",
            "保存标注员的账号信息",
        ],
        "answer_index": 1,
        "cap_id": "CAP-AUD-SEGMENT-ALIGN-001",  # 切割音频并对齐
        "data_type": "audio",
    },
    {
        "id": "q-qa-metrics",
        "question": "标注交付前的质检中，“漏标率”指的是什么？",
        "options": [
            "被标错类别的目标占全部目标的比例",
            "应标而未标的目标占全部应标目标的比例",
            "标注框超出素材边界的样本占比",
            "同一目标被重复标注的样本占比",
        ],
        "answer_index": 1,
        "cap_id": "CAP-CORE-EXPORT-QA-001",  # 执行导出前质量检查
        "data_type": "image",
    },
    {
        "id": "q-box-rule",
        "question": "按照矩形框标注规范，正确的框选方式是？",
        "options": [
            "框尽量画大，把目标周围的背景也包进去，防止漏掉",
            "框边缘贴合目标最外缘像素，紧致且完整包含目标",
            "只框住目标的主体部分，边缘可以截掉一些",
            "相邻的多个同类目标可以共用一个框",
        ],
        "answer_index": 1,
        "cap_id": "CAP-IMG-BOX-ANNOTATE-001",  # 绘制紧致目标框
        "data_type": "image",
    },
    {
        "id": "q-wake-negative",
        "question": "车载唤醒词标注中，下列哪项属于应保留并标注的“负例”样本？",
        "options": [
            "与唤醒词发音相近的近音词（near-miss）",
            "发音完整清晰的唤醒词",
            "完全静音的空白片段",
            "标注员自己朗读的测试音",
        ],
        "answer_index": 0,
        "cap_id": "CAP-AUD-WAKE-COMMAND-001",  # 标注唤醒词与命令词
        "data_type": "audio",
    },
    {
        "id": "q-sentiment-label",
        "question": "客服对话文本“你们这个故障都拖了三天了还没人处理！”的情感极性应标为？",
        "options": ["正面", "中性", "负面", "无法判断"],
        "answer_index": 2,
        "cap_id": "CAP-TXT-SENTIMENT-001",  # 标注情感极性
        "data_type": "text",
    },
    {
        "id": "q-format-detect",
        "question": "下列哪种文件最可能是视频标注的结构化导出结果？",
        "options": [
            "含时间戳与轨迹 ID 的 JSON 文件",
            "MP3 音频文件",
            "纯文本小说 TXT 文件",
            "Word 排版文档 DOCX 文件",
        ],
        "answer_index": 0,
        "cap_id": "CAP-VID-EXPORT-QA-001",  # 检查视频标注导出
        "data_type": "video",
    },
]


def get_questions() -> list[dict]:
    """完整题库（含答案，仅服务端评分使用）。"""
    return QUESTIONS


def public_questions() -> list[dict]:
    """下发给前端的题目视图：剥离 answer_index，防止答案随响应泄露。"""
    return [
        {
            "id": q["id"],
            "question": q["question"],
            "options": list(q["options"]),
            "cap_id": q["cap_id"],
            "data_type": q["data_type"],
        }
        for q in QUESTIONS
    ]


def score_answers(answers: dict[str, int]) -> tuple[list[dict], int]:
    """确定性评分：返回 (逐题结果, 答对题数)。

    逐题结果含 cap_id/correct/delta，供 mastery.service.apply_updates 直接消费；
    未知题目 id 直接忽略（前端串改不加分），未作答的题按答错给基线分。
    """
    results: list[dict] = []
    correct = 0
    for q in QUESTIONS:
        given = answers.get(q["id"])
        ok = given == q["answer_index"]
        if ok:
            correct += 1
        results.append(
            {
                "question_id": q["id"],
                "cap_id": q["cap_id"],
                "correct": ok,
                "delta": ASSESSMENT_CORRECT_DELTA if ok else ASSESSMENT_WRONG_DELTA,
            }
        )
    return results, correct


def validate_question_caps() -> list[str]:
    """校验每题 cap_id 都存在于图谱；返回缺失的 cap_id 列表（空 = 全部有效）。

    为什么容忍图谱缺席：题库校验是启动/测试期的自检，图谱文件不可用时
    返回空列表（不阻断），与 graphx 相关路由的降级口径一致。
    """
    try:
        from ..graphx import reason

        cap_ids = {
            n["id"] for n in reason.get_graph()["nodes"] if n.get("type") == "CAP"
        }
    except Exception:
        return []
    return [q["cap_id"] for q in QUESTIONS if q["cap_id"] not in cap_ids]
