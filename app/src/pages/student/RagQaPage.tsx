/**
 * RAG 知识问答页（PRD-01 §8）。
 *
 * 关键决策（为什么）：
 * - 「仅检索已发布资料」开关固定开启且禁用：学生端 published_only 由后端
 *   强制（rag_query.py，PRD-06 §4.4），UI 如实呈现该约束而非假装可调。
 * - 拒答（refused=true）只展示后端拒答说明 + 学习建议，绝不本地补写
 *   "看起来专业"的内容（AC6：无依据不编造）。
 * - 引用卡点击上报 citation_clicked（前端唯一需要埋的点：后端看不到
 *   UI 点击；其余 rag_query_submitted 等由后端端点上报）。
 * - 引用卡 ★ 收藏写 /api/profile/favorites（item_type='citation'），
 *   初始填充态来自收藏列表；个人中心收藏区是它的展示端。
 * - 「加入学习任务」是学生手动动作（非 Agent 写操作），直接 POST /api/tasks，
 *   不走确认门；答案区引用随任务保存为学习材料（rag_citation 资源）。
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import type { Citation, RagAnswer, TaskSummary } from "../../api/types";
import {
  Button,
  Card,
  CitationCard,
  Drawer,
  PageHeader,
  Select,
  Spinner,
  Tag,
  Textarea,
  useToast,
} from "../../components";
import { useScenario } from "../../app/ScenarioContext";
import {
  capNameOf,
  errMsg,
  trackEvent,
  useCapNames,
} from "./shared";

/** 空态示例问题（PRD-06 §7.2：知识问答页展示常见规范问题示例） */
const EXAMPLE_QUESTIONS = [
  "NER 标注中实体边界应该如何划分？",
  "图像框选标注的贴边要求是什么？",
  "客服语音情感标注中副语言事件如何记录？",
  "1+X 数据标注考试包含哪些内容？",
];

const DATA_TYPE_OPTIONS = [
  { value: "", label: "全部类型" },
  { value: "text", label: "文本" },
  { value: "image", label: "图像" },
  { value: "audio", label: "语音" },
  { value: "video", label: "视频" },
];

/**
 * 收藏条目（profile.py `_favorite_dto`，页内声明防并行改 types）。
 * 收藏引用以 item_type='citation' + item_id=document_id 落库，
 * document_id → 收藏行 id 的映射用于取消收藏（DELETE 按行 id）。
 */
interface FavoriteItem {
  id: string;
  item_type: string;
  item_id: string;
  title: string;
}

export default function RagQaPage() {
  const toast = useToast();
  const { scenarioId: globalScenarioId, scenarios } = useScenario();
  const capNames = useCapNames();

  const [question, setQuestion] = useState("");
  const [scenarioId, setScenarioId] = useState(globalScenarioId);
  const [dataType, setDataType] = useState("");
  const [asking, setAsking] = useState(false);
  const [answer, setAnswer] = useState<RagAnswer | null>(null);
  const [askedQuestion, setAskedQuestion] = useState("");
  const [citationDetail, setCitationDetail] = useState<Citation | null>(null);
  const [creatingTask, setCreatingTask] = useState(false);
  const [createdTaskId, setCreatedTaskId] = useState<string | null>(null);
  // 引用收藏态：document_id → 收藏行 id（行 id 是 DELETE 的依据，见 FavoriteItem 注释）
  const [favorites, setFavorites] = useState<Map<string, string>>(new Map());

  // 挂载时拉一次收藏列表：引用卡 ★ 的初始填充态以服务端为准（跨设备一致）
  useEffect(() => {
    const controller = new AbortController();
    api
      .get<{ items: FavoriteItem[] }>("/api/profile/favorites", undefined, { signal: controller.signal })
      .then((res) => {
        if (controller.signal.aborted) return;
        const map = new Map<string, string>();
        for (const fav of res.items) {
          if (fav.item_type === "citation") map.set(fav.item_id, fav.id);
        }
        setFavorites(map);
      })
      .catch(() => {
        /* 收藏态加载失败降级为全未收藏，不阻断问答主流程 */
      });
    return () => controller.abort();
  }, []);

  /** 提问：场景/类型默认取当前上下文；空问题前端先拦（后端也校验 422） */
  const ask = async (raw?: string) => {
    const text = (raw ?? question).trim();
    if (!text) {
      toast.error("请先输入问题");
      return;
    }
    setAsking(true);
    setCreatedTaskId(null);
    try {
      const res = await api.post<RagAnswer>("/api/rag/query", {
        question: text,
        scenario_id: scenarioId || undefined,
        data_type: dataType || undefined,
        published_only: true,
      });
      setAnswer(res);
      setAskedQuestion(text);
      setQuestion(text);
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setAsking(false);
    }
  };

  /** 引用点击：埋点（后端不可见该交互）+ 抽屉详情 */
  const openCitation = (citation: Citation) => {
    trackEvent("citation_clicked", { document_id: citation.document_id });
    setCitationDetail(citation);
  };

  /**
   * 引用收藏开关（PRD-01 §9 收藏资料的录入端）：
   * 收藏 item_type='citation'、item_id=document_id，meta 记录章节/版本便于
   * 个人中心列表展示上下文；取消收藏按收藏行 id DELETE。后端重复收藏幂等
   * upsert，本地仍以服务端返回的行 id 为准刷新映射。
   */
  const toggleFavorite = async (citation: Citation) => {
    const existingId = favorites.get(citation.document_id);
    try {
      if (existingId) {
        await api.delete(`/api/profile/favorites/${existingId}`);
        setFavorites((prev) => {
          const next = new Map(prev);
          next.delete(citation.document_id);
          return next;
        });
        toast.success("已取消收藏");
      } else {
        const res = await api.post<{ favorite: FavoriteItem }>("/api/profile/favorites", {
          item_type: "citation",
          item_id: citation.document_id,
          title: citation.title,
          meta: { section: citation.section_title, version: citation.version },
        });
        setFavorites((prev) => new Map(prev).set(citation.document_id, res.favorite.id));
        toast.success("已收藏，可在个人中心查看");
      }
    } catch (err) {
      toast.error(errMsg(err));
    }
  };

  /** 一键生成学习任务（PRD-01 §8 验收：问答结果可转任务卡） */
  const addToTasks = async () => {
    if (!answer) return;
    setCreatingTask(true);
    try {
      const short =
        askedQuestion.length > 24 ? `${askedQuestion.slice(0, 24)}…` : askedQuestion;
      const task = await api.post<TaskSummary>("/api/tasks", {
        title: `答疑学习：${short}`,
        goal: `理解并掌握问题「${askedQuestion}」涉及的知识`,
        cap_ids: answer.related_cap_ids,
        steps: [{ title: "学习答疑内容", description: askedQuestion }],
        resources: answer.citations.map((citation) => ({
          type: "rag_citation",
          title: citation.title,
          ref_id: citation.document_id,
          citation,
        })),
        source: "agent",
      });
      toast.success("已加入学习任务");
      setCreatedTaskId(task.id);
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setCreatingTask(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="知识问答"
        sub="基于已发布规范资料的可靠问答，回答均附引用来源"
      />

      {/* 问答输入区（PRD-01 §8：问题/场景/类型/仅检索已发布） */}
      <Card className="mb-4">
        <div className="flex flex-col gap-3">
          <Textarea
            aria-label="问题输入"
            placeholder="输入你的规范问题，例如：NER 标注中实体边界如何划分？"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
          />
          <div className="flex items-center gap-3 flex-wrap">
            <Select
              aria-label="场景筛选"
              style={{ width: 200 }}
              value={scenarioId}
              options={scenarios.map((s) => ({ value: s.id, label: s.name }))}
              onChange={(e) => setScenarioId(e.target.value)}
            />
            <Select
              aria-label="数据类型筛选"
              style={{ width: 160 }}
              value={dataType}
              options={DATA_TYPE_OPTIONS}
              onChange={(e) => setDataType(e.target.value)}
            />
            <label
              className="flex items-center gap-2 text-sm text-secondary"
              title="学生端固定只检索已发布资料（PRD-06 §4.4），不可关闭"
            >
              <input type="checkbox" checked disabled readOnly />
              仅检索已发布资料
            </label>
            <Button loading={asking} onClick={() => ask()}>
              提问
            </Button>
          </div>
        </div>
      </Card>

      {/* 空态：示例问题引导（PRD-06 §7.2） */}
      {!answer && !asking ? (
        <Card title="试试这些常见规范问题">
          <div className="flex items-center gap-2 flex-wrap">
            {EXAMPLE_QUESTIONS.map((example) => (
              <Button key={example} variant="secondary" size="sm" onClick={() => ask(example)}>
                {example}
              </Button>
            ))}
          </div>
        </Card>
      ) : null}

      {asking ? (
        <div className="loading-block">
          <Spinner large /> 正在检索知识库…
        </div>
      ) : null}

      {answer && !asking ? (
        <>
          {answer.refused ? (
            /* 拒答（AC6）：如实说明 + 可执行建议，绝不编造答案 */
            <Card title="暂未找到可靠依据" className="mb-4">
              <div className="form-alert form-alert-error" role="alert">
                知识库暂无可靠依据，暂不能给出专业结论。
              </div>
              {answer.answer ? (
                <p className="text-sm text-secondary mb-3">{answer.answer}</p>
              ) : null}
              {answer.notice ? (
                <p className="text-sm text-secondary mb-3">{answer.notice}</p>
              ) : null}
              <div className="flex items-center gap-2 flex-wrap">
                <Link to="/presets" className="btn btn-secondary btn-sm">
                  去预设学习打基础
                </Link>
                <span className="text-sm text-secondary">
                  或联系教师上传该领域的规范资料后再提问
                </span>
              </div>
            </Card>
          ) : (
            /* 答案区：直接回答 + 分步骤 + 注意事项 + 追问 */
            <Card title="回答" className="mb-4">
              <div className="flex flex-col gap-4">
                <p className="text-sm">{answer.answer}</p>
                {answer.notice ? (
                  <p className="text-sm" style={{ color: "var(--color-warning)" }}>
                    {answer.notice}
                  </p>
                ) : null}
                {answer.steps.length > 0 ? (
                  <div>
                    <h3 className="mb-2" style={{ fontSize: "var(--font-size-base)" }}>
                      分步骤说明
                    </h3>
                    <ol className="flex flex-col gap-2">
                      {answer.steps.map((step, index) => (
                        <li key={index} className="text-sm text-secondary">
                          {index + 1}. {step}
                        </li>
                      ))}
                    </ol>
                  </div>
                ) : null}
                {answer.notes.length > 0 ? (
                  <div>
                    <h3 className="mb-2" style={{ fontSize: "var(--font-size-base)" }}>
                      注意事项
                    </h3>
                    <ul className="flex flex-col gap-2">
                      {answer.notes.map((note, index) => (
                        <li key={index} className="text-sm text-secondary">
                          · {note}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {answer.followups.length > 0 ? (
                  <div>
                    <h3 className="mb-2" style={{ fontSize: "var(--font-size-base)" }}>
                      追问建议
                    </h3>
                    <div className="flex items-center gap-2 flex-wrap">
                      {answer.followups.map((followup) => (
                        <Button
                          key={followup}
                          variant="ghost"
                          size="sm"
                          onClick={() => ask(followup)}
                        >
                          {followup}
                        </Button>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            </Card>
          )}

          {/* 引用来源区（PRD-01 §8：专业回答必须展示引用；★ 收藏进个人中心） */}
          {answer.citations.length > 0 ? (
            <Card title="引用来源" className="mb-4">
              {answer.citations.map((citation, index) => (
                <div key={`${citation.document_id}-${index}`} className="flex items-start gap-2">
                  <div style={{ flex: 1 }}>
                    <CitationCard
                      citation={citation}
                      index={index + 1}
                      onClick={() => openCitation(citation)}
                    />
                  </div>
                  {/* 收藏开关：★ 已收藏 / ☆ 未收藏；按钮独立在卡片外，避免触发卡片的详情点击 */}
                  <button
                    type="button"
                    className="icon-btn"
                    aria-label={
                      favorites.has(citation.document_id)
                        ? `取消收藏 ${citation.title}`
                        : `收藏 ${citation.title}`
                    }
                    aria-pressed={favorites.has(citation.document_id)}
                    title={favorites.has(citation.document_id) ? "取消收藏" : "收藏该资料"}
                    onClick={() => toggleFavorite(citation)}
                    style={{
                      fontSize: 18,
                      color: favorites.has(citation.document_id)
                        ? "var(--color-warning)"
                        : "var(--color-text-muted, currentColor)",
                    }}
                  >
                    {favorites.has(citation.document_id) ? "★" : "☆"}
                  </button>
                </div>
              ))}
              <p className="text-xs text-muted">
                引用均来自已发布且授权有效的资料；相关度分数越高越可信。
              </p>
            </Card>
          ) : null}

          {/* 关联学习：相关能力 → 图谱；一键转学习任务 */}
          {answer.related_cap_ids.length > 0 ? (
            <Card title="关联学习" className="mb-4">
              <div className="flex flex-col gap-3">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm text-secondary">相关能力</span>
                  {answer.related_cap_ids.map((capId) => (
                    <Link key={capId} to={`/graph?node=${capId}`}>
                      <span className="badge badge-primary">{capNameOf(capNames, capId)}</span>
                    </Link>
                  ))}
                </div>
                <div className="flex items-center gap-3">
                  <Button
                    variant="secondary"
                    loading={creatingTask}
                    disabled={createdTaskId !== null}
                    onClick={addToTasks}
                  >
                    加入学习任务
                  </Button>
                  {createdTaskId ? (
                    <Link to={`/tasks/${createdTaskId}`} className="text-sm">
                      已创建，查看任务 →
                    </Link>
                  ) : null}
                </div>
              </div>
            </Card>
          ) : null}
        </>
      ) : null}

      {/* 引用详情抽屉：文档/章节/页码/版本/相关度（PRD-06 §4.5 学生口径） */}
      <Drawer
        open={citationDetail !== null}
        title="引用详情"
        onClose={() => setCitationDetail(null)}
      >
        {citationDetail ? (
          <div className="flex flex-col gap-3">
            <strong>{citationDetail.title}</strong>
            <div className="flex items-center gap-2 flex-wrap">
              {citationDetail.section_title ? <Tag>章节：{citationDetail.section_title}</Tag> : null}
              {citationDetail.page_start != null ? (
                <Tag>
                  {citationDetail.page_end != null && citationDetail.page_end !== citationDetail.page_start
                    ? `第 ${citationDetail.page_start}-${citationDetail.page_end} 页`
                    : `第 ${citationDetail.page_start} 页`}
                </Tag>
              ) : null}
              <Tag>版本：v{citationDetail.version}</Tag>
            </div>
            <p className="text-sm text-secondary">
              相关度分数：{citationDetail.score.toFixed(2)}（越高表示该资料与问题的匹配越可靠）
            </p>
            <p className="text-xs text-muted">
              学生端引用不含切片编号与上传人信息（PRD-06 §4.5 展示口径）。
            </p>
          </div>
        ) : null}
      </Drawer>
    </div>
  );
}
