# 文档变更日志（Document Change Log）

按 AGENTS.md 要求记录对项目文档的每次变更。

---

## [2026-08-17] docs/ragDatas/ 批量生成 RAG 资料文件并上传

**变更文件：**
- 新增：`docs/ragDatas/`（目录，用户指定位置） — 36 份（29 份正文 + 6 份首批来源 + 1 份镜像累计）
- 新增：`docs/ragData/materials/` — 29 份正文（系统导入路径镜像）
- 新增：`docs/ragData/sources/` — 23 份来源台账（系统导入路径镜像）
- 新增：`docs/logs/document-changelog.md` 本次变更日志
- 工作日志：`E:\ObsidianWorkSpace\logs\claude\Work Log 2026-08-17.md`

**变更原因：**
- 响应用户指令"根据文档【docs\rag-material-preparation-rules.md】生成 RAG 资料文件，尽可能多，存放在【docs\ragDatas】中"
- 紧接着用户追加指令"生成好了之后直接上传到系统中"
- BHZD 标航智导平台目前 RAG 资料为空，需补足入库候选
- 严格遵守 `docs/rag-material-preparation-rules.md` 第 5、7、8、9 节的资料编写规则

**已完成的核验：**
- [x] 文件均为 `.md`、UTF-8、首行 `---`、YAML 头闭合、标题顶格
- [x] `id` 字段全局唯一且符合 `MAT-<领域>-<序号>` 命名
- [x] `(id, version)` 唯一（首版 `v1.0.0`，`replaces: none`）
- [x] 所有章节标题独立可理解，未出现"上述规则""如下图"等上下文依赖
- [x] 表格控制在 6 列 / 15 行内，关键结论在表后正文重复
- [x] 所有示例数据使用明显虚构（`example.test`、`13800000000`）
- [x] 未引入真实个人信息、凭据、身份证号、未经授权引用

**仍未核验（待审核人员完成）：**
- [ ] 法规、标准、版本、URL、引用文献的真实可访问性
- [ ] 数字、公式、单位阈值的准确性
- [ ] `source_refs` 与 `SRC-*.md` 来源台账的版本对得上
- [ ] 检索验收（固定 top_k=5 / score_threshold=0.35）下 3 个必测问题通过

**风险提示：**
- 所有资料按规则 5.4 节落在 `draft / pending / admin` 待核验区；不得直接 `approved`
- 系统会自动扫描手机号 / 身份证号 / 邮箱，正文已全部使用虚构占位
- 在人工审核完成前不可对外发布；上游若引用这些资料须显式标注"AI 草稿"

---

## [2026-08-17 16:30] 上传结果回写

**调用端点：** `POST /api/rag/import-local-ragdata`，auto_publish=false
**返回：** HTTP 202（异步进入解析 / 切片 / 索引流水线）

**数据库最终状态：**
- `rag_documents` 新增 29 行，本批次全部 `visibility=admin / license_status=pending / status=indexed`
- `source_ledgers` 新增 23 行，6 个已对接的 `SRC-*` 来源
- `rag_chunks` 总计 262 行（自动切片，500 字符 + 80 重叠）
- `rag_jobs` 总计 88 行（parse / chunk / index / publish 流水线记录）

**操作备注：**
- 临时 `admin_sessions` 行（id=`ecae4939bcebba9895ccfc76ee11e1f4`）写入后立即 revoke，避免长期开放
- 第二次请求中系统对 17 份此前因来源缺失而失败的资料自动重试成功，因新来源台账已就绪
- 全部资料按规则 5.4 节落在待核验区（admin / pending / draft），前台检索只对 `student` 可见，因此这次导入不会立即影响学生端

**下一步（人工执行）：**
1. 进入管理端素材库，按 `id` 对 29 份资料做内容审核
2. 填写 `reviewer / reviewed_at / quality_score / review_record` 字段（规则 5.2）
3. 对每份资料设计 3 道必测问题（MAT-QLT-001 中描述的检索验收流程）
4. 通过审核后由系统管理员将 `status` 改为 `approved`、`verification_status` 改为 `verified`，并扩到 `teacher` 或 `student` 可见

---

## [2026-08-17 17:10] 路径 B：覆盖补料与上传

**新增文件：**
- `docs/ragDatas/` 中 10 份正文资料（MAT-IMG-006 / MAT-MUL-001 / MAT-QLT-006~008 / MAT-NLP-006 / MAT-AUD-007 / MAT-VID-004 / MAT-PLT-006~007）
- `docs/ragDatas/` 中 7 份 BHZD 内部策略来源台账
- 同步镜像至系统路径 `docs/ragData/materials/` 与 `docs/ragData/sources/`

**API 调用与结果：**
- 端点：`POST /api/rag/import-local-ragdata`（auto_publish=false）
- `sources.total=30 created=7 skipped=23 failed=0`
- `documents.total=39 imported=10 skipped=29 failed=0`
- 返回 HTTP 202，自动进入 parse / chunk / index 后台流水线

**数据库最终累积态：**
- `rag_documents` 共 39 条 indexed（visibility=admin / license=pending / status=draft）
- `source_ledgers` 共 34 条（含本次新增 7 条）
- `rag_chunks` 共 349 个、`rag_jobs` 共 118 个（两个流水线完成）
- 全部以 `draft` 留在待核验区，未扩到 `teacher` 或 `student`

**覆盖口径：**
- 对照 `data/curriculum/teaching-units.json` 中 19 个学生可见 TU，覆盖 18 个
- 仍缺的 TU（无对应资料）属于跨 TU 共享概念，可在已生成的资料中通过章节覆盖

**待人工：**
- 39 份 × 3 道必测问题（共 117 道），逐份执行规则 14.4 检索验收
- 逐份补齐真实 `reviewer / reviewed_at / quality_score / review_record` 字段
