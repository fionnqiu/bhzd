# -*- coding: utf-8 -*-
"""生成参赛产品文档配图（架构图 / Agent 运行流 / RAG 生命周期 / 学习闭环）。"""
import os
from matplotlib import font_manager
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle, Polygon
import matplotlib.patches as mpatches

OUT = r"E:\AgentWorkspaces\bhzd\var\doc-assets"
os.makedirs(OUT, exist_ok=True)

# ---- 中文字体 ----
for fp in [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc",
           r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\simsun.ttc"]:
    if os.path.exists(fp):
        font_manager.fontManager.addfont(fp)
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "SimSun"]
plt.rcParams["axes.unicode_minus"] = False

# ---- 配色 ----
C_MAIN   = "#1f6feb"   # 主蓝
C_MAIN_L = "#dbeafe"   # 浅蓝填充
C_GREEN  = "#2f9e44"
C_GREEN_L= "#e6f4ea"
C_ORANGE = "#e8590c"
C_ORANGE_L= "#fff0e6"
C_GRAY   = "#495057"
C_GRAY_L = "#f1f3f5"
C_DARK   = "#212529"
C_BORDER = "#adb5bd"


def box(ax, x, y, w, h, text, fc=C_MAIN_L, ec=C_MAIN, tc=C_DARK, fs=10, lw=1.4, bold=False, style="round,pad=0.02"):
    p = FancyBboxPatch((x, y), w, h, boxstyle=style, linewidth=lw,
                       edgecolor=ec, facecolor=fc, mutation_aspect=1.0)
    ax.add_patch(p)
    ax.text(x + w/2, y + h/2, text, ha="center", va="center",
            fontsize=fs, color=tc, fontweight="bold" if bold else "normal", linespacing=1.5)


def arrow(ax, x1, y1, x2, y2, color=C_MAIN, lw=1.8, style="-|>", rad=0.0, ls="-"):
    a = FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style, mutation_scale=16,
                        linewidth=lw, color=color, linestyle=ls,
                        connectionstyle=f"arc3,rad={rad}")
    ax.add_patch(a)


def new_fig(w, h, title=None):
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")
    if title:
        ax.text(50, 98.2, title, ha="center", va="center", fontsize=13,
                color=C_DARK, fontweight="bold")
    return fig, ax


def save(fig, name):
    path = os.path.join(OUT, name)
    fig.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("saved:", path)


def new_fig_top(w, h, title=None, top_band=12):
    """顶部留 title 空间（不与内容重叠）"""
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")
    if title:
        ax.text(50, 100 - top_band/2, title, ha="center", va="center", fontsize=13,
                color=C_DARK, fontweight="bold")
    return fig, ax, 100 - top_band  # 返回内容 y 顶


# ============ 图 3-1 系统总体架构图 ============
fig, ax, top_y = new_fig_top(12.5, 7.8, "图 3-1  标航智导系统总体架构", top_band=10)
# 内容坐标系：top_y → 0
T = lambda y: y * (top_y / 100)  # 0-100 坐标 → 实际 y
box(ax, 40, T(86), 20, 5, "用户（学生 / 教师 / 系统管理员）", C_GRAY_L, C_GRAY, fs=11, bold=True)
# 前端层
box(ax, 6, T(66), 88, 16, "", C_GRAY_L, C_GRAY, lw=1.2)
ax.text(50, T(79), "前端展示层（React 19 + TypeScript + Vite）", ha="center", va="center",
        fontsize=11, color=C_DARK, fontweight="bold")
box(ax, 10, T(68.5), 26, 9, "学生门户\n智能驾驶舱 / 图谱 / 任务 / 诊断", fc="white", ec=C_BORDER, fs=9)
box(ax, 40, T(68.5), 24, 9, "教师门户\n班级 / 任务编排 / 学情分析", fc="white", ec=C_BORDER, fs=9)
box(ax, 68, T(68.5), 22, 9, "系统管理门户\nProvider / RAG / 用户 / 审计", fc="white", ec=C_BORDER, fs=9)
arrow(ax, 50, T(86), 50, T(82))
# 同源 /api 代理
box(ax, 36, T(58), 28, 5.5, "同源 /api 代理 + SSE 客户端", C_ORANGE_L, C_ORANGE, fs=9.5, bold=True)
arrow(ax, 50, T(66), 50, T(63.5))
arrow(ax, 50, T(58), 50, T(54))
# 后端层
box(ax, 4, T(22), 92, 30, "", C_MAIN_L, C_MAIN, lw=1.4)
ax.text(50, T(48.5), "后端服务层（FastAPI + LangGraph Agent 编排）", ha="center", va="center",
        fontsize=11, color=C_MAIN, fontweight="bold")
box(ax, 8, T(25), 20, 8.5, "会话认证 / 角色依赖\nCSRF / 限流", fc="white", ec=C_BORDER, fs=9)
box(ax, 30, T(25), 20, 8.5, "Agent 编排\n意图识别 / 工具注册 / 确认门", fc="white", ec=C_BORDER, fs=9)
box(ax, 52, T(25), 20, 8.5, "业务路由\n任务 / 图谱 / 诊断 / 掌握度 / 评测", fc="white", ec=C_BORDER, fs=9)
box(ax, 74, T(25), 18, 8.5, "RAG 管线\n解析 / 切片 / 索引 / 发布守卫", fc="white", ec=C_BORDER, fs=9)
box(ax, 8, T(36), 20, 8.5, "SSE 事件流\n持久化 + 断线回放", fc="white", ec=C_BORDER, fs=9)
box(ax, 30, T(36), 20, 8.5, "图谱推理 graphx\n前置路径 / 环检测", fc="white", ec=C_BORDER, fs=9)
box(ax, 52, T(36), 20, 8.5, "诊断 / 掌握度引擎\n弱项归因 / 事件记录", fc="white", ec=C_BORDER, fs=9)
box(ax, 74, T(36), 18, 8.5, "安全投影 / 记忆\n隐私过滤 / 分层记忆", fc="white", ec=C_BORDER, fs=9)
# 数据层
box(ax, 4, T(0), 92, 17, "", C_GREEN_L, C_GREEN, lw=1.3)
ax.text(50, T(13.5), "数据与外部资源层", ha="center", va="center", fontsize=11, color=C_GREEN, fontweight="bold")
box(ax, 7, T(2), 19, 9, "SQLite 业务库\n29 个版本化迁移", fc="white", ec=C_GREEN, fs=9)
box(ax, 28, T(2), 19, 9, "LangGraph\n检查点 sidecar", fc="white", ec=C_GREEN, fs=9)
box(ax, 49, T(2), 17, 9, "能力图谱 / 课程\nJSON 受控数据", fc="white", ec=C_GREEN, fs=9)
box(ax, 68, T(2), 12, 9, "上传文件\nvar/uploads", fc="white", ec=C_GREEN, fs=9)
box(ax, 82, T(2), 12, 9, "模型 Provider\n（按配置启用）", fc="white", ec=C_ORANGE, fs=9)
# 后端到数据层连线
for x in (16.5, 37.5, 57.5, 74, 88):
    arrow(ax, x, T(22), x, T(18.5), color=C_GREEN, lw=1.5)
arrow(ax, 88, T(22), 88, T(11), color=C_ORANGE, lw=1.5)
arrow(ax, 50, T(54), 50, T(52), color=C_ORANGE, lw=1.8)
save(fig, "fig3-1_architecture.png")


# ============ 图 3-2 Agent 运行与事件流 ============
fig, ax = new_fig(12, 7.2, "图 3-2  Agent 运行与 SSE 事件流")
rows = [
    ("用户浏览器", "输入问题 / 上传附件 / 确认写操作"),
    ("API 接入层", "POST /api/runs → 创建消息与运行 → 202 + run_id"),
    ("后台 Agent loop", "LangGraph 图编排：prepare / intake / plan / execute / finalize"),
    ("工具注册表", "读工具自动执行；写工具生成 preview + 待确认单"),
    ("业务与数据层", "图谱 / RAG / 诊断 / 掌握度 / SQLite 持久化"),
    ("SSE 事件流", "progress / activity / delta / completed，支持 after_seq 回放"),
]
y = 88
for name, desc in rows:
    box(ax, 8, y - 6.5, 84, 8, f"{name}\n{desc}", fc="white", ec=C_MAIN, fs=9.5, bold=(name == "后台 Agent loop"))
    y -= 14.5
# 箭头连接
for i in range(5):
    arrow(ax, 50, 88 - i*14.5 - 6.5, 50, 88 - (i+1)*14.5, color=C_MAIN, lw=1.6)
# 右侧注释：确认门
box(ax, 62, 18, 32, 12, "确认门（写操作安全边界）\n预览 → 确认 → 原子应用\n拒绝 / 过期不产生业务写入", C_ORANGE_L, C_ORANGE, fs=9)
arrow(ax, 60, 24, 50, 27, color=C_ORANGE, rad=-0.25)
save(fig, "fig3-2_agent_flow.png")


# ============ 图 3-3 RAG 知识库生命周期 ============
fig, ax = new_fig(12.5, 6.6, "图 3-3  RAG 知识库生命周期与发布治理")
steps = [
    ("上传 / 导入", "管理员上传或本地 ragData 导入"),
    ("解析 parse", "类型 / 编码 / 空内容 / 敏感信息检查"),
    ("切片 chunk", "标题继承 / 表格保护 / 窗口切分"),
    ("索引 index", "embedding 或本地向量"),
    ("自动发布守卫", "非空 / 来源 / 敏感 / 可见性检查"),
]
x = 3
for name, desc in steps:
    box(ax, x, 60, 17.5, 12, f"{name}\n{desc}", fc="white", ec=C_MAIN, fs=8.8)
    if x < 71:
        arrow(ax, x + 17.5, 66, x + 20.5, 66, color=C_MAIN, lw=1.6)
    x += 20.5

box(ax, 3, 34, 30, 11, "发布守卫通过 → published\n（学生可见、授权有效、未过期）", C_GREEN_L, C_GREEN, fs=9)
box(ax, 38, 34, 30, 11, "发布守卫阻断 → indexed/failed\n（保留状态，提示管理员处置）", C_ORANGE_L, C_ORANGE, fs=9)
arrow(ax, 20, 60, 18, 45.5, color=C_GREEN, lw=1.6)
arrow(ax, 50, 60, 53, 45.5, color=C_ORANGE, lw=1.6)

box(ax, 73, 34, 24, 11, "检索与回答\nhybrid / rerank / 引用卡 / 拒答", fc="white", ec=C_MAIN, fs=9)
arrow(ax, 33, 39.5, 73, 39.5, color=C_MAIN, lw=1.6)
box(ax, 38, 14, 30, 11, "来源台账 source_ledgers\n来源 / 版本 / 有效期 / 授权状态", C_GRAY_L, C_GRAY, fs=9)
box(ax, 73, 14, 24, 11, "评测集 eval_runs\nrecall / 引用准确率 / 拒答准确率", C_GRAY_L, C_GRAY, fs=9)
arrow(ax, 53, 34, 53, 25.5, color=C_GRAY, lw=1.5)
arrow(ax, 85, 34, 85, 25.5, color=C_GRAY, lw=1.5)
save(fig, "fig3-3_rag_lifecycle.png")


# ============ 图 6-1 学生自适应学习闭环 ============
fig, ax = new_fig(11, 8.2, "图 6-1  学生“目标—诊断—学习—练习—掌握度”自适应学习闭环")
# 主环 6 节点（环形）
nodes = [
    ("学习目标\n/ 预设",            50, 80),
    ("诊断 / 初测\n上传标注样本", 84, 64),
    ("图谱前置路径\n弱能力补强",   84, 32),
    ("推荐学习任务\n任务卡+安全要点",50, 16),
    ("练习提交\n与评分",         16, 32),
    ("掌握度事件\n达标判定",     16, 64),
]
for name, cx, cy in nodes:
    box(ax, cx-16, cy-7, 32, 14, name, fc="white", ec=C_MAIN, fs=9.5, bold=True)
# 主环箭头
arrow(ax, 50, 80-7, 76, 64+7, color=C_MAIN, lw=1.7)              # 目标→诊断
arrow(ax, 84, 64-7, 84, 32+7, color=C_MAIN, lw=1.7)              # 诊断→图谱
arrow(ax, 76, 32-7, 50, 16+7, color=C_MAIN, lw=1.7)              # 图谱→任务
arrow(ax, 50-16, 16+7, 16+16, 32-7, color=C_MAIN, lw=1.7)        # 任务→练习
arrow(ax, 16, 32-7, 16, 64+7, color=C_MAIN, lw=1.7)              # 练习→掌握度
arrow(ax, 16+16, 64+7, 50-16, 80-7, color=C_MAIN, lw=1.7)        # 掌握度→目标
# 达标判定（主环右外侧）
box(ax, 88, 47, 11, 8, "达标？", fc=C_GRAY_L, ec=C_GRAY, fs=9, bold=True)
arrow(ax, 84, 64-7, 91, 55, color=C_MAIN, lw=1.3)
# 否：回流到图谱前置路径
box(ax, 66, 48, 18, 8, "否：补强", C_ORANGE_L, C_ORANGE, fs=8.5)
arrow(ax, 88, 51, 84, 51, color=C_ORANGE, lw=1.3)
arrow(ax, 84, 48, 84, 32+5, color=C_ORANGE, lw=1.2)
# 是：进入进阶任务（独立终点）
box(ax, 66, 22, 18, 8, "是：进阶", C_GREEN_L, C_GREEN, fs=8.5)
arrow(ax, 88, 48, 84, 27, color=C_GREEN, lw=1.2)
# 教师反馈
box(ax, 4, 4, 42, 9, "教师班级分析：完成率 / 薄弱点\n反哺教学组织与培养方案", C_GRAY_L, C_GRAY, fs=8.5)
arrow(ax, 16, 25, 16, 13.5, color=C_GRAY, lw=1.5)
save(fig, "fig6-1_learning_loop.png")

print("ALL DONE")
