# -*- coding: utf-8 -*-
"""从 candidates 批次 04 提取 (mat_id -> src_id) 映射并写入 inventory 批次 04 行"""
import os
import re
from collections import Counter

BASE = r"E:\AgentWorkspaces\bhzd\docs\ragData"
MAT_DIR = os.path.join(BASE, "materials")

TYPE_META = {
    "std": ("text / tabular", "时效"),
    "tbk": ("text / image / tabular", "时效"),
    "com": ("text / image / tabular", "时效"),
    "ent": ("text / image / tabular / multimodal", "时效"),
}

TITLE_MAP = {
    "STD-026": "信息系统安全保障评估框架", "STD-027": "信息安全漏洞管理规范",
    "STD-028": "信息安全漏洞命名规范", "STD-029": "信息安全风险管理实施指南",
    "STD-030": "信息安全风险评估方法", "STD-031": "信息安全测试评估过程",
    "STD-032": "信息安全技术 实体鉴别", "STD-033": "信息安全技术 数字签名",
    "STD-034": "信息安全技术 带附录的数字签名", "STD-035": "SM2 密码算法使用规范",
    "STD-036": "SM2 密码算法签名规范", "STD-037": "SM3 杂凑算法规范",
    "STD-038": "SM4 分组密码算法规范", "STD-039": "SM2 椭圆曲线公钥密码算法",
    "STD-040": "信息安全技术 密码应用标识规范", "STD-041": "信息安全技术 移动应用安全检测",
    "STD-042": "信息安全技术 门户网站安全技术要求", "STD-043": "信息安全技术 证书认证系统技术规范",
    "STD-044": "信息安全技术 云计算云文件服务安全", "STD-045": "信息安全技术 云计算 PaaS 服务安全",
    "STD-046": "信息安全技术 云计算 SaaS 服务安全", "STD-047": "信息安全技术 云计算应用程序接口安全",
    "STD-048": "信息安全技术 信息系统安全运维管理指南", "STD-049": "计算机信息系统安全保护等级划分准则（1999 旧版对照）",
    "STD-050": "信息安全技术 信息系统安全管理要求",
    "TBK-026": "Probabilistic Machine Learning 概率机器学习导论",
    "TBK-027": "The Elements of Statistical Learning 统计学习要素目录",
    "TBK-028": "Reinforcement Learning 强化学习（第二版）目录",
    "TBK-029": "Probabilistic Graphical Models 概率图模型目录",
    "TBK-030": "Convex Optimization 凸优化目录",
    "TBK-031": "Machine Learning Mitchell 机器学习目录",
    "TBK-032": "Understanding Machine Learning 理解机器学习目录",
    "TBK-033": "Probabilistic Machine Learning: Advanced Topics 概率机器学习进阶",
    "TBK-034": "Pattern Recognition Theodoridis 模式识别（第四版）目录",
    "TBK-035": "Machine Learning Marsland 机器学习算法导论目录",
    "TBK-036": "An Introduction to Machine Learning Kubat 机器学习导论目录",
    "TBK-037": "Neural Networks for Pattern Recognition Bishop 神经网络模式识别目录",
    "TBK-038": "Pattern Recognition and Neural Networks Ripley 模式识别与神经网络目录",
    "TBK-039": "An Introduction to Statistical Learning 统计学习导论目录",
    "TBK-040": "Pattern Classification Duda 模式分类目录",
    "TBK-041": "Pattern Recognition Theodoridis 模式识别目录",
    "TBK-042": "Data Mining Witten 数据挖掘实用机器学习工具目录",
    "TBK-043": "Data Mining Han 数据挖掘概念与技术目录",
    "TBK-044": "Data Mining Larose 数据挖掘方法与应用目录",
    "TBK-045": "Introduction to Data Mining Tan 数据挖掘导论目录",
    "TBK-046": "CMU 10-606 Mathematical Background for Machine Learning 课程索引",
    "TBK-047": "Speech and Language Processing 语音与语言处理概览",
    "TBK-048": "Computer Vision: Algorithms and Applications 计算机视觉综合",
    "TBK-049": "AI Agent Foundations 智能体基础概览",
    "TBK-050": "Prompt Engineering 提示工程概览",
    "COM-026": "SIGIR 信息检索顶会赛道总览",
    "COM-027": "KDD 数据挖掘顶会赛道总览",
    "COM-028": "CVPR 计算机视觉顶会挑战赛概览",
    "COM-029": "AAAI/IJCAI 人工智能顶会竞赛概览",
    "COM-030": "ICLR 深度学习顶会竞赛概览",
    "COM-031": "ICML 机器学习顶会竞赛概览",
    "COM-032": "The Web Conference (WWW) Web 顶会竞赛概览",
    "COM-033": "IoT 物联网应用创新大赛概览",
    "COM-034": "软件创新大赛概览",
    "COM-035": "统计建模大赛概览",
    "COM-036": "市场调查与分析大赛概览",
    "COM-037": "节能减排社会实践与科技竞赛概览",
    "COM-038": "蓝桥杯全国软件和信息技术专业人才大赛概览",
    "COM-039": "中国大学生程序设计竞赛 (CCPC) 概览",
    "COM-040": "RoboCom 机器人开发者大赛概览",
    "COM-041": "中国高校计算机大赛 - 挑战赛概览",
    "COM-042": "全国大学生电子商务三创赛概览",
    "COM-043": "中国机器人及人工智能大赛概览",
    "COM-044": "全国大学生集成电路创新创业大赛概览",
    "COM-045": "全国大学生软件创新大赛（睿抗）概览",
    "COM-046": "RoboMaster 机甲大师赛概览",
    "COM-047": "全国大学生数字媒体科技作品及创意竞赛概览",
    "COM-048": "全国大学生物联网设计竞赛概览",
    "COM-049": "中国高校智能机器人创意大赛概览",
    "COM-050": "全国大学生信息安全竞赛概览",
    "ENT-026": "NVIDIA NeMo 大模型训练与推理框架概览",
    "ENT-027": "Google Gemini 多模态大模型概览",
    "ENT-028": "Anthropic Claude 大语言模型概览",
    "ENT-029": "Mistral 开源大语言模型概览",
    "ENT-030": "Meta Llama 开源大语言模型概览",
    "ENT-031": "Cohere 企业级大语言模型概览",
    "ENT-032": "Together AI 开源模型推理云平台概览",
    "ENT-033": "Anyscale Ray 企业分布式计算平台概览",
    "ENT-034": "Databricks 数据智能平台概览",
    "ENT-035": "Snowflake 云数据仓库概览",
    "ENT-036": "Pinecone 托管向量数据库概览",
    "ENT-037": "Weaviate 开源向量数据库概览",
    "ENT-038": "Qdrant 开源向量搜索引擎概览",
    "ENT-039": "Milvus 开源向量数据库概览",
    "ENT-040": "Chroma 嵌入式向量数据库概览",
    "ENT-041": "LangSmith LLM 应用调试与监控平台概览",
    "ENT-042": "LlamaIndex LLM 数据框架概览",
    "ENT-043": "LlamaCloud LlamaIndex 托管服务概览",
    "ENT-044": "Ollama 本地大模型运行框架概览",
    "ENT-045": "LM Studio 本地大模型 GUI 概览",
    "ENT-046": "Stable Diffusion 文生图扩散模型概览",
    "ENT-047": "Midjourney 文生图订阅服务概览",
    "ENT-048": "ElevenLabs AI 语音合成平台概览",
    "ENT-049": "Suno AI 音乐生成服务概览",
    "ENT-050": "奇安信企业级网络安全与数据合规产品概览",
}


def load_src_map():
    """从 candidates 提取 (mat_id, src) 映射"""
    cand_path = os.path.join(BASE, "candidates", "_candidates.md")
    src_map = {}
    with open(cand_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("|"):
                continue
            parts = [p.strip() for p in line.split("|")[1:-1]]
            if len(parts) < 5:
                continue
            # parts: [CAND-ID, 标题, 类型, 来源台账, 资料 ID, ...]
            mat_id = parts[4]
            src = parts[3]
            if mat_id.startswith("MAT-"):
                src_map[mat_id] = src
    return src_map


def collect_files():
    items = []
    for fname in sorted(os.listdir(MAT_DIR)):
        m = re.match(r"^mat_(std|tbk|com|ent)_(\d{3})_.*\.md$", fname)
        if not m:
            continue
        prefix = m.group(1)
        num = int(m.group(2))
        if num < 26 or num > 50:
            continue
        mat_id = f"MAT-{prefix.upper()}-{num:03d}"
        items.append((mat_id, prefix, fname))
    return items


def main():
    src_map = load_src_map()
    print(f"src_map entries: {len(src_map)}")
    items = collect_files()
    print(f"items: {len(items)}")
    # 排序
    order = {"std": 0, "tbk": 1, "com": 2, "ent": 3}
    items_sorted = sorted(items, key=lambda x: (order[x[1]], int(x[0].split("-")[2])))

    main_lines = []
    extra_lines = []
    for mat_id, prefix, fname in items_sorted:
        num = int(mat_id.split("-")[2])
        key = f"{prefix.upper()}-{num:03d}"
        title = TITLE_MAP.get(key, f"批次 04 资料 {num}")
        src = src_map.get(mat_id, f"SRC-{prefix.upper()}-{num:03d}")
        main_lines.append(
            f"| {mat_id} | {title} | v1.0 | {src} | teacher | indexed | 待跑 | 时效 |"
        )
        applicable, _ = TYPE_META[prefix]
        extra_lines.append(
            f"| {mat_id} | {fname} | — | md | {applicable} | — | — | 2026-08-09 | — | 见 chunks/audit_{prefix}_{num:03d}.md | 见 evaluation/ | — | — |"
        )
    main_path = os.path.join(BASE, "inventory", "_batch04_main.md")
    extra_path = os.path.join(BASE, "inventory", "_batch04_extra.md")
    with open(main_path, "w", encoding="utf-8") as f:
        f.write("\n".join(main_lines) + "\n")
    with open(extra_path, "w", encoding="utf-8") as f:
        f.write("\n".join(extra_lines) + "\n")
    # 抽样
    for l in main_lines[:3]:
        print(l)
    print("...")
    for l in main_lines[-3:]:
        print(l)
    print("---")
    for l in extra_lines[:3]:
        print(l)
    print("---")
    print(f"written: {main_path}, {extra_path}")


if __name__ == "__main__":
    main()
