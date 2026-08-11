"""Build the approved Batch 05 original-teaching-material package.

The generator uses public reference portals as topic anchors but writes
original learning guides.  Existing files must match byte-for-byte, so reruns
never overwrite a revised artifact accidentally.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "docs" / "ragData"
MATERIALS = ROOT / "materials"
SOURCES = ROOT / "sources"
LENSES = "概念辨析|目标拆解|流程设计|检查清单|常见误区|案例推演|质量度量|风险控制|协作分工|复盘改进".split("|")
CATEGORIES = {
    "std": ("standard", "SRC-AUTO-STD-2026", "https://openstd.samr.gov.cn/", "术语一致性|范围边界|角色职责|数据分级|数据最小化|访问控制|身份鉴别|日志留存|变更管理|漏洞响应|风险评估|业务连续性|备份恢复|接口安全|配置基线|供应链安全|加密使用|密钥生命周期|安全测试|事件分级|隐私告知|数据保留|审计证据|合规映射|版本替代"),
    "tbk": ("textbook", "SRC-AUTO-TBK-2026", "https://ocw.mit.edu/", "监督学习|无监督学习|概率建模|线性代数基础|优化方法|特征工程|模型评估|交叉验证|过拟合控制|神经网络|卷积网络|序列模型|注意力机制|检索系统|知识图谱|强化学习|因果推断|时间序列|异常检测|聚类分析|数据标注|自然语言处理|计算机视觉|语音处理|提示工程"),
    "com": ("competition", "SRC-AUTO-COM-2026", "https://www.moe.gov.cn/", "赛题解读|需求拆分|数据合规|方案选型|实验设计|基线构建|指标选择|误差分析|消融实验|复现管理|团队分工|进度规划|答辩表达|技术写作|可视化呈现|代码规范|提交检查|资源预算|风险登记|创新点提炼|用户调研|原型验证|评审反馈|成果归档|赛后复盘"),
    "ent": ("enterprise", "SRC-AUTO-ENT-2026", "https://www.cncf.io/", "需求澄清|服务边界|接口契约|数据治理|特征平台|模型部署|灰度发布|可观测性|容量规划|成本治理|故障演练|事件响应|质量保障|安全评审|权限设计|检索增强|向量索引|模型评测|提示版本|人工复核|反馈闭环|知识维护|供应商管理|项目交接|持续改进"),
}


def write_once(path: Path, text: str) -> None:
    """Prevent a later generation run from replacing a deliberately revised file."""
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise RuntimeError(f"artifact differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def ledger(source_type: str, source_id: str, url: str) -> str:
    """Record the project-owner approval separately from the public topic portal."""
    return f"""---
source_id: {source_id}
title: BHZD 批次 05 原创 {source_type} 教学资料集
issued_by: BHZD 项目组
category: {source_type}
version: 2026-08
status: approved
url: {url}
---

# 来源台账：BHZD 批次 05 原创 {source_type} 教学资料集

| 字段 | 值 |
| --- | --- |
| **来源编码** | `{source_id}` |
| **来源名称** | BHZD 批次 05 原创 {source_type} 教学资料集 |
| **发布方** | BHZD 项目组 |
| **来源类型** | {source_type} |
| **版本** | 2026-08 |
| **授权状态** | approved |
| **授权依据** | 项目负责人于 2026-08-09 确认：本批原创教学资料可用于 BHZD 教学并允许发布到学生端；公开参考入口：{url}。 |
| **有效期起** | 2026-08-09 |
| **有效期止** | 长期 |
| **使用范围** | teacher / student |
| **风险说明** | 仅生成原创教学解释，不复制第三方全文；公开信息变化时需制作修订版本。 |
| **责任人** | admin |
"""


def material(mid: str, title: str, source_type: str, source_id: str, url: str, ordinal: int) -> str:
    """Create a long enough structured guide for parse/chunk/index verification."""
    topic, lens = title.split("：", 1)
    return f"""---
id: {mid}
title: {title}
version: v1.0
source: {source_id}
source_type: {source_type}
license_status: authorized
data_types: text
visibility: student
status: draft
created: 2026-08-09
---

# {title}

> 本文是 BHZD 项目组生成的原创教学资料（批次 05 第 {ordinal} 份）。它以公开资料主题为事实线索，提供“{topic}”的学习与实践说明，不复制第三方网页、标准或教材全文。公开参考入口：<{url}>。

## 学习目标

学习者应能说明“{topic}”解决的问题、适用边界和可验证证据，并在面对不完整信息时把未知项标为待确认。学习结论必须保留版本、角色和场景条件，不能把经验性判断写成没有依据的通用规则。

## 核心框架

从“{lens}”视角，将“{topic}”拆为目标、输入、过程、产出和约束。目标定义希望降低的不确定性；输入必须能回溯来源；过程要明确执行顺序和责任人；产出应可检查；约束覆盖时效、隐私、安全、成本和场景差异。任何一项缺失时，都应补充资料或退回设计。

对于初学者，应先确认何时适用、何时不适用，再整理术语、条件和例外，最后形成可复用检查表。这个顺序避免只记住名词却无法判断具体任务是否应该采用该方法。

## 操作步骤

1. 用一句话写下任务目标及其与“{topic}”的关系。
2. 列出至少三项可观察输入，并把无法验证的前提单独记录。
3. 为输入选择处理动作，说明责任人、完成时点和应保留的证据。
4. 用小样本或模拟案例检查输出，记录偏差、例外和修订理由。
5. 复盘预期与实际差异，把未解决问题转成下一轮核验或实验任务。

## 常见误区与质量检查

不要把“{topic}”当作固定答案，忽略版本、角色和场景。检查时确认术语是否一致、输入是否有来源、过程是否可重复、结论是否保留条件，并确保不写入个人信息、凭据、客户数据或未经授权的原文。任一项失败时，资料必须修订而不是继续发布。

## 练习

- 为一个相关任务写出目标、输入和可复核产出。
- 设计一个反例，说明什么条件下不应直接使用当前方法。
- 说明复盘结论如何改变下一次的资料选择、实验设计或协作分工。

## 资料元数据

| 字段 | 值 |
| --- | --- |
| 资料编号 | {mid} |
| 来源台账 | {source_id} |
| 可见范围 | student |
| 验收负责人 | admin |
"""


def main() -> None:
    """Generate 25 topics x 10 lenses in each of four source categories."""
    manifest = []
    for prefix, (source_type, source_id, url, topic_text) in CATEGORIES.items():
        write_once(SOURCES / f"{source_id}__batch05.md", ledger(source_type, source_id, url))
        for topic_index, topic in enumerate(topic_text.split("|")):
            for lens_index, lens in enumerate(LENSES):
                number = 51 + topic_index * len(LENSES) + lens_index
                mid = f"MAT-{prefix.upper()}-{number:03d}"
                title = f"{topic}：{lens}教学指南"
                digest = hashlib.sha256(title.encode("utf-8")).hexdigest()[:10]
                filename = f"mat_{prefix}_{number:03d}_batch05_{digest}.md"
                write_once(MATERIALS / filename, material(mid, title, source_type, source_id, url, number))
                manifest.append({"id": mid, "title": title, "file": filename, "source_id": source_id, "source_type": source_type})
    if len(manifest) != 1000 or len({item['id'] for item in manifest}) != 1000:
        raise RuntimeError("Batch 05 must contain exactly 1,000 unique documents")
    # The manifest is the deterministic handoff between generation and governed import.
    write_once(ROOT / "_process" / "batch05_manifest.json", json.dumps({"batch": "05", "materials": manifest}, ensure_ascii=False, indent=2) + "\n")
    print(f"generated {len(manifest)} materials")


if __name__ == "__main__":
    main()
