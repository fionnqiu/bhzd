# Document Change Log

> BHZD RAG 资料库治理过程记录。每完成一批资料（候选 → 台账 → 入库 → 切片 → 评测 → 发布），在此追加一条目。

## [2026-08-09 01:02] Build BHZD RAG knowledge base - batch 01 (8 sample materials)

**Changed files:**

- `docs/ragData/README.md` (new)
- `docs/ragData/_process/SOP.md` (new)
- `docs/ragData/sources/README.md` (new)
- `docs/ragData/sources/_template.md` (new)
- `docs/ragData/sources/SRC-GB-21023-2007__chinese-speech-recognition-spec.md` (new)
- `docs/ragData/sources/SRC-GB-43708-2025__scientific-data-security.md` (new)
- `docs/ragData/sources/SRC-TBK-ZONG-2013__statistical-nlp.md` (new)
- `docs/ragData/sources/SRC-TBK-ZHANG-2023__ai-data-annotation-practice.md` (new)
- `docs/ragData/sources/SRC-COM-2025-CCC__innovation-contest.md` (new)
- `docs/ragData/sources/SRC-COM-2024-WLDC__big-data-challenge.md` (new)
- `docs/ragData/sources/SRC-ENT-ALIBABA-DAMO__speech-ai-2022.md` (new)
- `docs/ragData/sources/SRC-ENT-BAIDU-PADDLESPEECH__paddlespeech-docs.md` (new)
- `docs/ragData/candidates/_candidates.md` (new)
- `docs/ragData/inventory/_inventory.md` (new)
- `docs/ragData/chunks/_chunk_audit_template.md` (new)
- `docs/ragData/chunks/audit_mat_std_001.md` (new)
- `docs/ragData/evaluation/_eval_cases_template.md` (new)
- `docs/ragData/evaluation/_eval_cases_batch_01.md` (new)
- `docs/ragData/evaluation/_eval_results.md` (new)
- `docs/ragData/risks/_risk_register.md` (new)
- `docs/ragData/materials/mat_std_001_gb_t_21023_terms_v1_0.md` (new)
- `docs/ragData/materials/mat_std_002_gb_t_43708_lifecycle_v1_0.md` (new)
- `docs/ragData/materials/mat_tbk_001_statistical_nlp_toc_v1_0.md` (new)
- `docs/ragData/materials/mat_tbk_002_data_annotation_toolkit_v1_0.md` (new)
- `docs/ragData/materials/mat_com_001_ccc_2025_overview_v1_0.md` (new)
- `docs/ragData/materials/mat_com_002_wldc_2024_topics_v1_0.md` (new)
- `docs/ragData/materials/mat_ent_001_damo_speech_ai_v1_0.md` (new)
- `docs/ragData/materials/mat_ent_002_paddlespeech_cheatsheet_v1_0.md` (new)

**Reason:**

- Implement the BHZD RAG knowledge base structure mandated by `docs/资料库构建规则.md` (v1.0).
- Build the governance skeleton (sources / candidates / inventory / chunks / evaluation / risks / _process) before any data is indexed.
- Produce batch 01: 8 sample materials (2 each of standard / textbook / competition / enterprise) covering public sources reachable via web search:
  - **standard**: GB/T 21023-2007 (Chinese speech recognition spec), GB/T 43708-2025 (scientific data security).
  - **textbook**: 宗成庆《统计自然语言处理》第 2 版, 张波《人工智能数据标注实战教程》.
  - **competition**: 中国国际大学生创新大赛 2025, "未来杯" 2024 高校大数据挑战赛.
  - **enterprise**: 阿里达摩院语音 AI 公开技术总结, 百度 PaddleSpeech 工具速查.
- All materials are public excerpts or structural summaries; no full PDFs, no copyrighted bodies, no client data, no secrets.

**Verification:**

- Created 8 source-ledger files; each lists source code, version, license basis, expiry, scope, risk, and owner.
- Created 8 material files under `materials/`; each contains frontmatter (id / version / source / visibility) and a 5-section structured body.
- Wrote 8 rows into `candidates/_candidates.md` (status: indexed).
- Wrote 8 rows into `inventory/_inventory.md` (status: indexed; visibility: teacher).
- Wrote 1 sample chunk-audit record (MAT-STD-001) and 13 eval-case records covering all 5 required categories (direct / conditioned / confusing / cross-scenario / refuse).
- Recorded 12 open risks in `risks/_risk_register.md`, including time-decay (6 sources pre-2015/2022), missing eval results, missing file hashes, missing scenario/capability IDs, missing owner, and the 8 vs 200 gap.
- All sensitive information checks passed (no ID card, phone, email, customer data, secret, or unauthorized content).

**Remaining verification:**

- 7 of 8 chunk-audit records are not yet written; the template is in place and the structure is the same as `audit_mat_std_001.md`.
- Evaluation cases are drafted but not yet executed; the project has no RAG management API, so actual retrieval runs are blocked.
- No SHA-256 file hashes registered (RISK-009 open).
- No scenario/capability IDs filled (RISK-010 open).
- No acceptance owner assigned (RISK-011 open).
- 200-target progress: 8/200 (4%, RISK-012 open).

---

## [2026-08-09 01:30] Build BHZD RAG knowledge base - batch 02 (32 materials, 40 total)

**Changed files:**

- `docs/ragData/candidates/_candidates.md` (追加 CAND-009~040 共 32 行)
- `docs/ragData/sources/SRC-GB-21024-2007__chinese-tts.md` (new)
- `docs/ragData/sources/SRC-GB-35312-2017__terminal-api.md` (new)
- `docs/ragData/sources/SRC-GB-37988-2019__dsmm.md` (new)
- `docs/ragData/sources/SRC-GB-25069-2022__terms.md` (new)
- `docs/ragData/sources/SRC-ISO-IEC-27001-2022__iso27001.md` (new, 1 对 2 共享)
- `docs/ragData/sources/SRC-GB-35273-2020__pii-security.md` (new)
- `docs/ragData/sources/SRC-GB-31168-2023__cloud-security.md` (new)
- `docs/ragData/sources/SRC-TBK-MANNING-1999__foundation-slp.md` (new)
- `docs/ragData/sources/SRC-TBK-ZHOU-2016__watermelon-ml.md` (new)
- `docs/ragData/sources/SRC-TBK-LI-2019__statistical-learning.md` (new)
- `docs/ragData/sources/SRC-TBK-JURAFSKY-3__slp.md` (new)
- `docs/ragData/sources/SRC-TBK-LIMU-2021__d2l.md` (new)
- `docs/ragData/sources/SRC-TBK-QIU-2020__nn-dl.md` (new)
- `docs/ragData/sources/SRC-COM-2025-CCC-INTL__intl-track.md` (new)
- `docs/ragData/sources/SRC-COM-2025-BDCI__bdci.md` (new)
- `docs/ragData/sources/SRC-COM-KAGGLE-PLATFORM__kaggle.md` (new)
- `docs/ragData/sources/SRC-COM-TIANCHI-PLATFORM__tianchi.md` (new)
- `docs/ragData/sources/SRC-COM-MATHCUP-2024__mathcup.md` (new)
- `docs/ragData/sources/SRC-COM-TAIDICUP-2024__taidibei.md` (new)
- `docs/ragData/sources/SRC-ENT-TENCENT-AILAB__tencent-ailab.md` (new)
- `docs/ragData/sources/SRC-ENT-MINDSPORE__mindspore.md` (new)
- `docs/ragData/sources/SRC-ENT-VOLCENGINE-SPEECH__volcengine.md` (new)
- `docs/ragData/sources/SRC-ENT-IFLYTEK-OPEN__iflytek.md` (new)
- `docs/ragData/sources/SRC-ENT-WHISPER-TRANS__whisper.md` (new)
- `docs/ragData/sources/SRC-ENT-CSDN-2024__csdn-ai.md` (new)
- `docs/ragData/inventory/_inventory.md` (追加主表 32 行 + 补充字段 32 行)
- `docs/ragData/chunks/audit_mat_std_004.md` (new)
- `docs/ragData/chunks/audit_mat_tbk_006.md` (new)
- `docs/ragData/chunks/audit_mat_com_005.md` (new)
- `docs/ragData/chunks/audit_mat_ent_007.md` (new)
- `docs/ragData/evaluation/_eval_cases_batch_02.md` (new, 12 题)
- `docs/ragData/evaluation/_eval_results.md` (追加批次 02 占位)
- `docs/ragData/risks/_risk_register.md` (12 → 15 项；RISK-007/012 状态升级)
- 32 份 `docs/ragData/materials/mat_*.md` 正文 (new, MAT-XXX-003~010 + 008a/008b 等)

**Reason:**

- 批次 01 跑通模板后，扩展到 4 类各 8 份（共 32 份）。
- 选题：8 份国标（中文语音合成/终端 API/DSMM/术语/ISO 27001 双文档/隐私/云安全）+ 8 份教材（NLP/ML 教材与索引）+ 8 份赛事（CCC 国际/CCF BDCI/Kaggle/天池/Math Cup/泰迪杯 + 2 补）+ 8 份企业（腾讯 AI/MindSpore/火山/讯飞/Whisper/CSDN/通义/文心）。
- 全部引用严格按"条款摘录 / 目录索引 / 公开页面引用"三档处理。
- ISO 27001 一对二（总览 + 控制项详表）。

**Verification:**

- 32 份资料对应 31 份台账（ISO 27001 共享）。
- 主表 40 行 + 补充字段 40 行，可见范围 teacher 40 / student 0。
- 切片抽查新增 4 份：STD-004 / TBK-006 / COM-005 / ENT-007。
- 评测用例新增 12 题（5 类全覆盖），总计 25 题。
- 风险登记从 12 项扩展到 15 项；RISK-007（版权）从 open → mitigating；RISK-012（200 份目标）状态新增。
- 未通过"上传"环节（无 RAG 管理端 API），所有 40 份状态 = indexed（FSL 演示）。

**Remaining verification:**

- 40 份资料的"实际评测"必须在 RAG 管理端/向量库就位后补跑（RISK-008 仍然 open）。
- 40 份资料的文件 SHA-256 哈希未登记（RISK-009）。
- 40 份资料的"场景 ID / 能力 ID"为空（RISK-010）。
- 验收负责人未指定（RISK-011）。
- 200 份目标当前完成 20%（RISK-012 open）。

---

## [2026-08-09 01:50] Build BHZD RAG knowledge base - batch 03 (60 materials, 100 total)

**Changed files:**

- `docs/ragData/candidates/_candidates.md` (追加 CAND-041~100 共 60 行)
- `docs/ragData/sources/SRC-GB-35273-2020__pii-security.md` 等 17 份国标台账 (new)
- `docs/ragData/sources/SRC-GB-22239-2019__graded-protection.md` (new)
- `docs/ragData/sources/SRC-GB-22240-2020__classification-guide.md` (new)
- `docs/ragData/sources/SRC-GB-28448-2019__graded-test.md` (new)
- `docs/ragData/sources/SRC-GB-25058-2019__graded-impl.md` (new)
- `docs/ragData/sources/SRC-GB-36073-2018__dcmm.md` (new)
- `docs/ragData/sources/SRC-GB-39725-2020__health-data.md` (new)
- `docs/ragData/sources/SRC-GB-41871-2022__vehicle-data.md` (new)
- `docs/ragData/sources/SRC-GB-40660-2021__biometric.md` (new)
- `docs/ragData/sources/SRC-GB-18336-2023__cc-eval.md` (new)
- `docs/ragData/sources/SRC-GB-40092-2021__privacy-computing.md` (new)
- `docs/ragData/sources/SRC-GB-41391-2022__app-privacy.md` (new)
- `docs/ragData/sources/SRC-GB-39786-2021__ops-guide.md` (new)
- `docs/ragData/sources/SRC-GB-20273-2019__db-security.md` (new)
- `docs/ragData/sources/SRC-GB-20945-2023__ops-mgmt.md` (new)
- `docs/ragData/sources/SRC-GB-42884-2023__ics-security.md` (new)
- `docs/ragData/sources/SRC-TBK-BISHOP-2006__prml.md` (new)
- `docs/ragData/sources/SRC-TBK-GOODFELLOW-2016__dl-original.md` (new)
- `docs/ragData/sources/SRC-TBK-ZHOU-2016__watermelon-ml.md` (new)
- `docs/ragData/sources/SRC-TBK-MANNING-2008__ir-book.md` (new)
- `docs/ragData/sources/SRC-TBK-CS224N-STANFORD__nlp-course.md` (new)
- `docs/ragData/sources/SRC-TBK-CS231N-STANFORD__cv-course.md` (new)
- `docs/ragData/sources/SRC-TBK-FASTAI-2020__dl-coders.md` (new)
- `docs/ragData/sources/SRC-TBK-GERON-2022__hands-on-ml.md` (new)
- `docs/ragData/sources/SRC-TBK-LESKOVEC-2014__mmds.md` (new)
- `docs/ragData/sources/SRC-TBK-XIANG-2012__recsys-practice.md` (new)
- `docs/ragData/sources/SRC-TBK-WANG-2020__knowledge-graph.md` (new)
- `docs/ragData/sources/SRC-TBK-RAG-2024__rag-practice.md` (new)
- `docs/ragData/sources/SRC-TBK-CHEN-2018__everyone-alg.md` (new)
- `docs/ragData/sources/SRC-TBK-LI-2020__ntu-ml.md` (new)
- `docs/ragData/sources/SRC-TBK-WANG-2020__deep-rl.md` (new)
- `docs/ragData/sources/SRC-TBK-LIMU-2021__d2l.md` (new)
- `docs/ragData/sources/SRC-COM-2025-CCC-INTL__intl-track.md` (new)
- `docs/ragData/sources/SRC-COM-DF-2024__datafountain.md` (new)
- `docs/ragData/sources/SRC-COM-ALIYUN-AILAB-2024__ailab.md` (new)
- `docs/ragData/sources/SRC-COM-TENCENT-GAME-2024__game-ai.md` (new)
- `docs/ragData/sources/SRC-COM-HUAWEI-2024__huawei-cloud.md` (new)
- `docs/ragData/sources/SRC-COM-BAIDU-STAR-2024__baidu.md` (new)
- `docs/ragData/sources/SRC-COM-JD-JDATA-2024__jd-jdata.md` (new)
- `docs/ragData/sources/SRC-COM-MEITUAN-2024__meituan.md` (new)
- `docs/ragData/sources/SRC-COM-ATEC-2024__ant-atec.md` (new)
- `docs/ragData/sources/SRC-COM-INTERNETPLUS-2024__internetplus.md` (new)
- `docs/ragData/sources/SRC-COM-ASC-2024__supercomputer.md` (new)
- `docs/ragData/sources/SRC-COM-IMC-2024__imc.md` (new)
- `docs/ragData/sources/SRC-COM-MCMICM-2024__mcm-icm.md` (new)
- `docs/ragData/sources/SRC-COM-CODA-2024__coda-cup.md` (new)
- `docs/ragData/sources/SRC-COM-NEURIPS-2024__neurips.md` (new)
- `docs/ragData/sources/SRC-COM-ACL-2024__acl.md` (new)
- `docs/ragData/sources/SRC-COM-ICPC-2024__icpc.md` (new)
- `docs/ragData/sources/SRC-COM-CCSP-2024__ccsp.md` (new)
- `docs/ragData/sources/SRC-ENT-ALIYUN-TONGYI__qwen.md` (new)
- `docs/ragData/sources/SRC-ENT-BAIDU-WENXIN__ernie.md` (new)
- `docs/ragData/sources/SRC-ENT-TENCENT-HUNYUAN__hunyuan.md` (new)
- `docs/ragData/sources/SRC-ENT-BYTEDANCE-DOUBAO__doubao.md` (new)
- `docs/ragData/sources/SRC-ENT-SENSETIME-SHANGLIANG__sensetime.md` (new)
- `docs/ragData/sources/SRC-ENT-ZHIPU-GLM__glm.md` (new)
- `docs/ragData/sources/SRC-ENT-MOONSHOT-KIMI__kimi.md` (new)
- `docs/ragData/sources/SRC-ENT-BAAIZHINENG__baichuan.md` (new)
- `docs/ragData/sources/SRC-ENT-DEEPSEEK__deepseek.md` (new)
- `docs/ragData/sources/SRC-ENT-ALIYUN-PAI__pai.md` (new)
- `docs/ragData/sources/SRC-ENT-BAIDU-BML__bml.md` (new)
- `docs/ragData/sources/SRC-ENT-TENCENT-TIONE__tione.md` (new)
- `docs/ragData/sources/SRC-ENT-AWS-SAGEMAKER__sagemaker.md` (new)
- `docs/ragData/sources/SRC-ENT-GCP-VERTEX__vertex.md` (new)
- `docs/ragData/sources/SRC-ENT-AZURE-ML__azure.md` (new)
- `docs/ragData/sources/SRC-ENT-HUGGINGFACE-SPACES__hf-spaces.md` (new)
- `docs/ragData/sources/SRC-ENT-REPLICATE__replicate.md` (new)
- `docs/ragData/inventory/_inventory.md` (追加主表 60 行 + 补充字段 60 行，可见范围 40 → 100)
- `docs/ragData/chunks/audit_mat_std_009.md` (new)
- `docs/ragData/chunks/audit_mat_tbk_011.md` (new)
- `docs/ragData/chunks/audit_mat_com_014.md` (new)
- `docs/ragData/chunks/audit_mat_ent_017.md` (new)
- `docs/ragData/evaluation/_eval_cases_batch_03.md` (new, 12 题)
- `docs/ragData/evaluation/_eval_results.md` (追加批次 03 占位)
- `docs/ragData/risks/_risk_register.md` (RISK-008/009/010 扩到 100 份；RISK-012 状态 open → mitigating 50%；新增 RISK-016/017/018 三个时效风险)
- `docs/ragData/README.md` (更新批次 03 状态、目录结构、来源分布、下一阶段建议)
- 60 份 `docs/ragData/materials/mat_*.md` 正文 (new, MAT-XXX-011~025)

**Reason:**

- 用户决定批次 02 后继续推进，目标 100 份 (4 类各 25)。
- 全部引用严格按"条款摘录 / 目录索引 / 公开页面引用"三档处理。
- 4 类齐平，每类 25 份。
- 100 份资料对应 99 份台账（ISO 27001 共享）。

**Verification:**

- 主表行数核对：candidates 100 行；inventory 主表 100 + 补充字段 100 = 200 行；4 类每类恰好 25 份。
- 文件存在性核对：materials/ 100 份正文（4 类各 25 份）；sources/ 99 份台账。
- 切片抽查新增 4 份样例：STD-009 / TBK-011 / COM-014 / ENT-017，覆盖 4 类。
- 评测用例新增 12 题（5 类全覆盖），总计 37 题。
- 风险登记从 15 项扩展到 18 项。
- 未通过"上传"环节（无 RAG 管理端 API），所有 100 份状态 = indexed（FSL 演示）。

**Remaining verification:**

- 100 份资料的"实际评测"必须在 RAG 管理端/向量库就位后补跑（RISK-008 仍然 open）。
- 100 份资料的文件 SHA-256 哈希未登记（RISK-009），可用 Get-FileHash 在 materials/ 下计算并回填。
- 100 份资料的"场景 ID / 能力 ID"为空（RISK-010），需在 BHZD 项目中梳理通用场景和能力体系。
- 验收负责人未指定（RISK-011，整批仍不满足规则 12 完成定义）。
- 200 份目标当前完成 50%（RISK-012 处于 mitigating），需继续批次 04+ 扩展。
- RISK-016/017/018 为批次 03 新增时效风险（国标版本、大模型版本、教材旧版），需季度复核。

---

## [2026-08-09 02:10] Build BHZD RAG knowledge base - batch 04 (100 materials, 200 total)

**Changed files:**

- `docs/ragData/candidates/_candidates.md` (rebuild 200 行主表，批次 04 追加 CAND-101~200)
- `docs/ragData/candidates/_batch04_rows.md` (new, 临时生成器产物)
- `docs/ragData/inventory/_inventory.md` (追加主表 100 行 + 补充字段 100 行，可见范围 100 → 200)
- `docs/ragData/inventory/_batch04_main.md` (new, 临时生成器产物)
- `docs/ragData/inventory/_batch04_extra.md` (new, 临时生成器产物)
- `docs/ragData/chunks/audit_mat_std_026.md` (new)
- `docs/ragData/chunks/audit_mat_tbk_026.md` (new)
- `docs/ragData/chunks/audit_mat_com_026.md` (new)
- `docs/ragData/chunks/audit_mat_ent_026.md` (new)
- `docs/ragData/evaluation/_eval_cases_batch_04.md` (new, 12 题)
- `docs/ragData/evaluation/_eval_results.md` (追加批次 04 占位)
- `docs/ragData/risks/_risk_register.md` (RISK-012 → resolved 200/200；新增 RISK-019/020/021)
- `docs/ragData/README.md` (更新为批次 04 状态 / 200 份达成)
- `E:\AgentWorkspaces\bhzd\scripts\gen_candidates_batch04.py` (new, 批次 04 CAND 101-200 生成器)
- `E:\AgentWorkspaces\bhzd\scripts\gen_candidates_all.py` (new, 全量 200 行 CAND 主表生成器)
- `E:\AgentWorkspaces\bhzd\scripts\gen_inventory_batch04.py` (new)
- `E:\AgentWorkspaces\bhzd\scripts\build_src_map.py` (new)
- `E:\AgentWorkspaces\bhzd\scripts\merge_inventory_batch04.py` (new)
- 100 份 `docs/ragData/materials/mat_*.md` 正文 (new, MAT-XXX-026~050)

**Reason:**

- 用户决定一次推完 200 份（4 类各 50 份），达成资料库构建初始目标。
- 批次 04 选题：25 份国标（GB/T 20274/30276/28458/31509/33132/33133 + SM 系列 + 等保 2.0 + 风险评估 + 漏洞 + 密码应用 + 移动安全 + CA + 云三件套 + 事件应急 + 1999 旧版对照 + ICS 安全）+ 25 份教材（Murphy PML / ESL / Sutton RL / Koller PGM / Boyd 凸优化 / Mitchell / Shalev / PML Advanced / Theodoridis PR/ML / Marsland / Kubat / Bishop NN / Ripley / ISLR / Duda / Witten DM / Han DM / Larose DM / Tan IDM / CMU 10-606 / SLP3 / CV / Agent / Prompt）+ 25 份赛事（SIGIR / KDD / CVPR / AAAI/IJCAI / ICLR / ICML / WWW / IoT / 软件创新 / 统计建模 / 市场调查 / 节能减排 / 蓝桥杯 / CCPC / RoboCom / 挑战赛 / 三创 / 机器人大赛 / 集创 / 睿抗 / RoboMaster / 数字媒体 / 物联网 / 智能机器人 / 信安）+ 25 份企业（NeMo / Gemini / Claude / Mistral / Llama / Cohere / Together / Anyscale / Databricks / Snowflake / Pinecone / Weaviate / Qdrant / Milvus / Chroma / LangSmith / LlamaIndex / LlamaCloud / Ollama / LM Studio / SD / Midjourney / ElevenLabs / Suno / 奇安信）。
- 全部引用严格按"条款摘录 / 目录索引 / 公开页面引用"三档处理。
- 风险登记 RISK-012（200 份数量目标）→ resolved。

**Verification:**

- materials/ 文件存在性：200 份正文（4 类各 50 份），与 inventory 主表 200 行一一对应。
- candidates 主表 200 行（CAND-001~200），4 类各 50 份。
- inventory 主表 200 行 + 补充字段 200 行，可见范围 teacher 200 / student 0。
- 切片抽查新增 4 份：STD-026 / TBK-026 / COM-026 / ENT-026，覆盖 4 类；总计 13 份样例。
- 评测用例新增 12 题（5 类全覆盖），总计 49 题（直接 16 + 条件 7 + 易混淆 8 + 跨场景 8 + 拒答 8 + 复核记录 2）。
- 风险登记从 18 项扩展到 21 项（新增 RISK-019 国标时效 / RISK-020 企业版本时效 / RISK-021 200 份哈希未登记）。
- 未通过"上传"环节（无 RAG 管理端 API），所有 200 份状态 = indexed（FSL 演示）。

**Remaining verification:**

- 200 份资料的"实际评测"必须在 RAG 管理端/向量库就位后补跑（RISK-008 仍然 open）。
- 200 份资料的文件 SHA-256 哈希未登记（RISK-009/021），可用 `Get-FileHash` 在 materials/ 下计算并回填。
- 200 份资料的"场景 ID / 能力 ID"为空（RISK-010），需在 BHZD 项目中梳理通用场景和能力体系。
- 验收负责人未指定（RISK-011，整批仍不满足规则 12 完成定义；RISK-012 数量目标已达成但流程未闭环）。
- RISK-016/017/018/019/020 为批次 03/04 新增时效风险（国标版本、大模型版本、教材旧版、企业平台版本），需季度复核。

---

## [2026-08-09 13:15] Prepare controlled teacher RAG pilot package with MiniMax M3

**Changed files:**

- `docs/ragData/_process/teacher_pilot_import_package.md` (new, 8-material controlled import manifest)
- `docs/ragData/evaluation/_teacher_pilot_runbook.md` (new, execution and acceptance record template)
- `docs/ragData/README.md` (clarify local `indexed` marker versus real system processing)
- `docs/ragData/risks/_risk_register.md` (add RISK-022 for remote ledger UUID and taxonomy mapping)
- `docs/ragData/evaluation/_eval_results.md` (link the blocked PILOT-01 run gate without fabricating results)

**Reason:**

- The user requested that MiniMax complete the existing RAG data-governance brief. MiniMax M3 reviewed the supplied pilot metadata, source-ledger evidence, import contract and risks; its conclusion was that all eight candidates remain blocked until governance and real runtime gates are met.
- The local `SRC-*` source codes cannot be passed as BHZD `source_ledger_id`; the remote source-ledger UUID must be created and captured first.

**Verification:**

- Calculated SHA-256 snapshots for all eight pilot files and recorded them in the manifest.
- Checked the actual RAG upload contract: required metadata, supported data types, draft-to-review status progression and UUID-based ledger association.
- Confirmed the changes do not upload documents, publish documents, alter database records or mark any evaluation as passed.

**Remaining verification:**

- A data steward must recheck authorization, validity and remote ledger UUIDs; an approved scenario/capability registry and named acceptance owner are still required.
- The eight documents still require actual parse/chunk/index, chunk sampling and all 49 evaluation cases before any review or publication decision.

---

## [2026-08-09 14:00] Import all 200 teacher RAG materials

**Changed files:**

- `server/bhzd_py/routers/rag_admin.py` (admin and CSRF-protected local package import endpoint)
- `app/src/pages/rag/UploadPage.tsx` (local package import command and result summary)
- `server/tests/test_rag_admin.py` (authorization, idempotency, ledger mapping and teacher-only import coverage)
- `app/tests/rag-admin-pages.test.tsx` (frontend request and summary coverage)

**Reason:**

- The user explicitly authorized importing all 200 Markdown materials from `docs/ragData/materials/` into the system RAG library for teachers only, without student publication.

**Verification:**

- Actual administrator import: 196 source ledgers created, 3 existing ledgers skipped, and all 200 materials imported with no failures.
- All 200 imported documents reached `teacher/indexed`; 600 jobs succeeded, 1,704 chunks were created, all documents are ledger-linked, and none is published.
- Administrator retrieval correctly cited the imported knowledge-graph chapter material. Backend RAG tests (17), frontend RAG tests (18), typecheck, production build and `/api/health` all passed.

**Remaining verification:**

- The 49 existing evaluation questions still need a formal recorded evaluation run. Authorization and freshness remain subject to the existing periodic governance review.

---

## [2026-08-09 14:10] Remove one-time RAG batch build artifacts

**Changed files:**

- Deleted `docs/ragData/candidates/_batch04_rows.md`
- Deleted `docs/ragData/inventory/_batch04_main.md`
- Deleted `docs/ragData/inventory/_batch04_extra.md`
- Deleted six one-time batch generation scripts under `scripts/`
- Retained `scripts/build_src_map.py` because it remains useful for source-code verification

**Reason:**

- The listed files were intermediate outputs or one-off generators from the completed 200-material build and are no longer part of the runtime RAG package.

**Verification:**

- Confirmed all nine targeted paths are absent; no recursive cleanup was performed.
- Confirmed `docs/ragData/materials` still contains 200 Markdown files and `sources/SRC-*.md` still contains 199 ledgers.
- Confirmed database state is unchanged: 200 teacher/indexed documents, 1,704 chunks, 203 total ledgers, and the existing 4 student-published documents.

**Remaining verification:**

- Runtime caches and dependency directories were intentionally retained because cache cleanup was not part of the confirmed scope.

---

## [2026-08-09 14:35] Record Batch 05 RAG import and publication status

**Changed files:**

- `docs/ragData/README.md` (replace superseded batch-04-only status with the factual Batch 05 package, import, indexing, visibility and publication state)

**Reason:**

- The user approved generation, database import and automatic student publication of 1,000 original teaching materials, and requested that every existing material also be visible to students. The repository documentation needed to distinguish those completed operations from the remaining formal evaluation gate.

**Verification:**

- Confirmed the recorded database outcome: 1,204 total `student`-visible materials, 1,202 `published/student/authorized` materials, and two `review_pending/student` materials correctly blocked by expired existing source ledgers.
- Confirmed the Batch 05 manifest contains 1,000 materials across four categories, and the completed parse, chunk and index jobs total 2,400 successful jobs each with 8,504 current chunks.
- Confirmed student retrieval cites new material without leaking Markdown front matter; backend RAG tests (34), frontend RAG page tests (18), typecheck, production build and `git diff --check` passed before this documentation update.

**Remaining verification:**

- The existing 49 formal retrieval-evaluation cases have not been run under a fixed retrieval configuration.
- The two materials with expired historic source ledgers remain unpublished until their ledger evidence is renewed and reviewed.

---

## [2026-08-09 16:21] Remove mandatory email verification

**Changed files:**

- `docs/dev/rewrite-blueprint.md`
- `docs/标航智导-PRD/标航智导-PRD-00总览.md`
- `docs/标航智导-PRD/标航智导-PRD-05技术与研发拆解.md`
- `docs/标航智导-PRD/标航智导-PRD-06研发可落地补充与边界条件.md`
- `docs/标航智导-PRD/标航智导-完整PRD-RAG与页面交互版.md`

**Reason:**

- The user removed the global email-verification requirement. Product and technical documents now state that registration activates accounts immediately, while legacy verification links are compatibility-only and never gate application capabilities.

**Verification:**

- Targeted backend regression tests passed: 63 tests covering authentication, Agent runs, diagnostics, and RAG access.
- Frontend tests passed: 187 tests. Typecheck, production build, targeted Ruff checks, and `git diff --check` passed.

**Remaining verification:**

- The retained `/api/auth/verify-email` and `/api/auth/resend-verification` endpoints are compatibility-only; their historical-link behavior was not exercised against a live SMTP service because registration no longer sends verification email.

---

## [2026-08-09 18:15] Document private layered memory configuration

**Changed files:**

- `.env.example` (private L1-L3 memory enablement, retrieval limits, and storage bounds)

**Reason:**

- The user requested a memory mechanism informed by TencentDB Agent Memory. The new configuration documents the private cross-session memory boundary separately from existing same-conversation L0 recall, so deployment operators can tune or disable it without changing application code.

**Verification:**

- Full backend suite passed: 399 tests, including migration, privacy isolation, deduplication, source-deletion, bounded recall, and embedding-fallback coverage.
- Full frontend suite passed: 190 tests; TypeScript production build, scoped Prettier check, and `git diff --check` also passed.

**Remaining verification:**

- Production embedding-provider availability remains environment-specific. The implementation falls back to keyword recall when vector generation is unavailable, and that degradation path is covered by tests.

---

## [2026-08-10 19:19] Remove teacher-registration invite requirement

**Changed files:**

- `docs/dev/rewrite-blueprint.md`
- `docs/标航智导-PRD/标航智导-PRD-06研发可落地补充与边界条件.md`
- `docs/logs/document-changelog.md`

**Reason:**

- The user approved public self-registration for teachers without an invite code. The product and technical contracts now state that teachers can register directly, while administrator self-registration and the separate student class-invite flow remain closed and unchanged.

**Verification:**

- Backend authentication and production-configuration regression tests passed: `21 passed`.
- The focused frontend authentication suite passed: `7 passed`; TypeScript typecheck and production build also passed.
- Scoped Ruff checks and `git diff --check` passed. A source search confirmed the retired teacher-registration configuration is absent from active runtime code; remaining `INVITE_CODE_INVALID` handling belongs to the unchanged class-join flow.

**Remaining verification:**

- The running local backend has not been reloaded, so live browser/API confirmation of the new registration behavior still requires separate authorization to restart the confirmed `127.0.0.1:8787` service.

---

## [2026-08-10 19:26] Verify teacher registration runtime after authorized reload

**Changed files:**

- `docs/logs/document-changelog.md`

**Reason:**

- The user separately authorized reloading the confirmed BHZD backend so the teacher-registration change could be verified against the serving process rather than only through isolated tests.

**Verification:**

- Confirmed the old `127.0.0.1:8787` listener was PID `53852`, running `E:\DevTools\Python311\python.exe -m bhzd_py.main` from `E:\AgentWorkspaces\bhzd\server`; only that process was stopped.
- Started the replacement from the same executable and working directory as PID `69596`.
- `GET /api/health` returned `{"status":"ok","version":"0.1.0"}`.
- The serving OpenAPI document contains `/api/auth/register`, marks the compatibility-only `teacher_invite` property as deprecated, and still exposes the teacher Agent, task-detail, and task-publish routes.

**Remaining verification:**

- No persistent test registration was submitted to the shared local database. The no-invite registration and immediate-login behavior remain covered by the completed isolated authentication regression tests.

---

## [2026-08-12] Add complete local Windows migration deployment runbook

**Changed files:**

- `docs/deployment/windows-deployment.md` (new)

**Reason:**

- Provide an operator-facing procedure for moving the complete BHZD system to another Windows computer for local-only use, including source export, secure configuration transfer, dependency installation, SQLite recovery, startup, verification, backups, and troubleshooting.

**Verification:**

- Cross-checked the guide against the current React/Vite frontend lockfile, FastAPI/uv backend lockfile, `BHZD_` configuration defaults, SQLite migration/seed entry point, and existing `var/`/`data/` runtime layout.
- The deployment helper scripts referenced by the guide are validated separately through PowerShell parsing and temporary SQLite backup/restore checks.

**Remaining verification:**

- An end-to-end import on the actual receiving computer, including the separately transferred encryption key and its real provider configuration, remains environment-specific and must be performed by the operator.

---

## [2026-08-12] Translate the local Windows deployment runbook into Chinese

**Changed files:**

- `docs/deployment/windows-deployment.md`

**Reason:**

- Replace the English operator-facing wording with a complete Chinese deployment guide while retaining the already-reviewed local-only deployment scope and executable command blocks unchanged.

**Verification:**

- Confirmed every deployment script name, configuration identifier, port, local URL, and migration term referenced by the guide remains present after translation.
- Confirmed no English prose headings or sentence prefixes remain; code, paths, environment variables, script names, and PowerShell commands intentionally remain unchanged.

**Remaining verification:**

- The complete migration still requires an operator-run acceptance on the receiving computer with the separately transferred configuration encryption key.

---

## [2026-08-15] Remove retired scenario requirements from trial and environment documentation

**Changed files:**

- `evidence/user-trials/trial-protocol.md`
- `evidence/user-trials/trial-record-template.md`
- `evidence/user-trials/session-summary.schema.json`
- `.env.example`
- `docs/logs/document-changelog.md`

**Reason:**

- Remove the retired scenario-comparison trial step and schema requirement so active validation artifacts no longer prescribe a removed product capability.
- Remove scenario wording from the sample data-directory and private-memory configuration comments while retaining the graph and teaching-unit data-directory contract.

**Verification:**

- Parsed `session-summary.schema.json` successfully after reducing the required task count from eight to seven and removing `scenario_comparison` from the enum and required `contains` clauses.
- Searched active trial and environment documentation to confirm no scenario-comparison requirement or scenario-directory/private-summary configuration wording remains.

**Remaining verification:**

- Historical changelog entries, migration history, and approved lazy graph `SCN/INSCN` references remain intentionally retained for auditability and data integrity.

---

## [2026-08-15] Complete master checklist evidence and implementation status

**Changed files:**

- `docs/master-checklist.md`
- `docs/logs/document-changelog.md`

**Reason:**

- Replace the pre-execution status with the approved implementation state, actual migration filenames (`017`-`019`), automated verification evidence, and explicit boundaries for real Provider/browser/student validation.
- Mark only acceptance items supported by current code and tests, and document why the P2-3~7 tuning claims remain pending without a real corpus or baseline.

**Verification:**

- Cross-checked the checklist against the final provider, task-content, RAG-admin, admin-metrics, and frontend test contracts.
- Recorded backend `457 passed`, frontend `31 files / 249 passed` before the final P0-7 test additions, plus the added P0-7 focused tests and final rerun results in the external work log.

**Remaining verification:**

- A real Responses/Provider connection, browser visual flow, student trial, and corpus-based RAG tuning benchmark remain environment-specific and are intentionally not claimed as complete.

---

## [2026-08-15] Correct final frontend regression count in the master checklist

**Changed files:**

- `docs/master-checklist.md`
- `docs/logs/document-changelog.md`

**Reason:**

- The final post-integration frontend run included the P0-7 student-detail tests and completed with `251 passed`; the checklist still contained the earlier pre-integration count of `249 passed`.

**Verification:**

- Re-ran `cd app; pnpm test:run`: 31 test files and 251 tests passed.
- Re-ran `cd server; uv run pytest -q`: 457 tests passed with one existing Starlette/httpx deprecation warning.

**Remaining verification:**

- Real Responses Provider connectivity, browser visual flow, student trial, and corpus-based RAG tuning remain environment-specific and are not claimed by this documentation correction.

---

## [2026-08-15] Record local browser visual review and isolated corpus baseline

**Changed files:**

- `evidence/real-validation/2026-08-15/validation-report.md`
- `docs/master-checklist.md`
- `docs/logs/document-changelog.md`

**Reason:**

- Record the approved browser visual checks, the blocked real-participant preconditions, and the read-only Top-K/threshold baseline run against the isolated SQLite backup.
- Update the master checklist to distinguish local/isolated evidence from still-pending real Provider, production-corpus, and formal student-trial acceptance.

**Verification:**

- Playwright E2E rerun completed with `4 passed`; fresh desktop/mobile graph screenshots showed 166 rendered nodes and no console errors after data settled.
- Read-only retrieval matrix covered 20 evaluation cases at Top-K `3/5/7/8`; each reached 20/20 target-document hits, with threshold sensitivity recorded separately.
- Confirmed the trial protocol is still blocked by missing release approval, participant authorization, and recorder identity; no participant record was synthesized.

**Remaining verification:**

- Responses Provider connectivity and live stream acceptance, authorized participant sessions, and real annotated-corpus parameter tuning remain outstanding.

---

## [2026-08-15] Record automatic learning-content queue and teacher browser regression

**Changed files:**

- `docs/master-checklist.md`
- `evidence/real-validation/2026-08-15/validation-report.md`
- `evidence/real-validation/2026-08-15/screenshots/teacher-task-publish-regression.png`
- `evidence/real-validation/2026-08-15/screenshots/student-task-auto-generation.png`
- `evidence/real-validation/2026-08-15/screenshots/student-task-content-status.png`

**Reason:**

- Replace the obsolete manual-generation acceptance wording with the automatic queue contract, include teacher creation/publish coverage, and refresh the final automated test counts.
- Record the local browser regression and its evidence while keeping real Provider, formal Responses, and authorized student-trial boundaries explicit.

**Verification:**

- Browser created and published a teacher task to one student; SQLite read-only check found `content_status=done` on the source and student copy.
- Desktop and mobile browser measurements confirmed the Agent send button shares the input shell's right and lower boundary, with no horizontal overflow.
- Frontend full suite: 31 test files / 256 passed; backend full suite: 460 passed with one existing Starlette/httpx deprecation warning.

**Remaining verification:**

- Real Provider connectivity, formal Responses protocol/stream acceptance, and authorized participant trial/corpus tuning remain environment-specific and not accepted in this change.

---

## [2026-08-15] Align checklist examples with automatic tasks and flat navigation

**Changed files:**

- docs/master-checklist.md
- docs/logs/document-changelog.md

**Reason:**

- Replace the obsolete manual content-generation examples, including the P0-8 graph entry, with automatic queueing and failure-only retry.
- Reflect the approved flat system-management navigation rather than the removed three-group labels.

**Verification:**

- Focused teacher create/publish queue regression passed; browser regression confirmed source and student-copy content reached done.
- Existing full frontend and backend regressions completed with 31 test files / 256 passed and 460 passed respectively.

**Remaining verification:**

- Real Provider connectivity, formal Responses protocol/stream acceptance, and authorized participant trial/corpus tuning remain outside this documentation correction.

---

## [2026-08-15] Align final checklist with built-in RAG controls and latest regression counts

**Changed files:**

- `docs/master-checklist.md`
- `docs/logs/document-changelog.md`

**Reason:**

- Apply the latest approved product wording: RAG uploads automatically parse, chunk, index, and publish; review and ledger pages are no longer active UI; historical backend compatibility remains explicit.
- Document that `top_k`, `temperature`, and `top_p` are the operator-adjustable fields on the RAG parameters page, while generation settings, Prompt templates, and publication policy stay system built-in.
- Correct the checklist evidence to the final rerun counts (`468` backend tests, `257` frontend tests, `51` existing lint warnings) and include migration `020_rag_sampling_settings.sql`.

**Verification:**

- `cd server; uv run pytest -q`: `468 passed`, one existing Starlette/httpx deprecation warning.
- `cd app; pnpm test:run`: `31` test files / `257 passed`.
- `cd app; pnpm run typecheck`, `pnpm run lint`, and `pnpm run build`: all passed; lint `0 errors / 51 warnings`, build only reported the existing chunk-size advisory.
- Confirmed the RAG layout exposes three active entries and that the legacy publish/ledger URLs redirect without rendering an active review workflow.

**Remaining verification:**

- Real Provider connectivity, formal Responses protocol/stream acceptance, authorized student trial, and production-corpus parameter tuning remain intentionally unaccepted.

---

## [2026-08-15] Enforce backend self-test and automatic restart lifecycle

**Changed files:**

- `AGENTS.md`
- `docs/logs/document-changelog.md`

**Reason:**

- Add the approved project rule that backend changes must pass focused and full self-checks before an automatic restart.
- Require listener PID, command line, parent chain, and working-directory ownership checks before touching `127.0.0.1:8787`, followed by health and affected-route verification.

**Verification:**

- Focused task-content and startup-recovery tests: `17 passed`.
- Backend full suite: `468 passed`, with one existing Starlette/httpx deprecation warning; Python compile and `git diff --check` passed.
- Restarted the confirmed BHZD listener from PID `39244` to PID `47804`; the new process runs from `E:\AgentWorkspaces\bhzd\server`.
- `GET /api/health` returned status `ok`, version `0.1.0`; OpenAPI exposes task detail and `start-learning` routes; restart logs contain no errors.

**Remaining verification:**

- Real Provider connectivity, formal Responses protocol/stream acceptance, authorized student trial, and production-corpus parameter tuning remain outside this task.

---

## [2026-08-15 22:23] Move RAG management into system administration

**Changed files:**

- `app/src/app/router.tsx`
- `app/src/app/LegacyRagAdminRedirect.tsx`
- `app/src/app/legacyRagRoutes.ts`
- `app/src/layouts/RagAdminLayout.tsx` (deleted)
- `app/src/layouts/AdminLayout.tsx`
- `app/src/layouts/ShellLayout.tsx`
- Active RAG pages, route/navigation tests, and `tests/e2e/enhancements.spec.ts`
- `docs/master-checklist.md`
- `docs/logs/document-changelog.md`

**Reason:**

- Make system administration the sole RAG management portal while retaining all RAG backend APIs, data, and system-administrator permission boundaries.
- Replace the separate RAG layout with guarded `/rag-admin/*` compatibility redirects that preserve document deep links and normalize return paths to `/admin/rag/*`.

**Verification:**

- Focused route, navigation, and RAG component tests: `47 passed`.
- Full frontend suite: `31` test files / `257 passed`; `pnpm typecheck` and production build passed.
- ESLint completed with `0` errors and `51` existing warnings; `git diff --check` passed.
- Confirmed no production import or build artifact references `RagAdminLayout`; remaining `/rag-admin` references are only the compatibility redirect and its regression tests.

**Remaining verification:**

- Playwright E2E source was updated for the system-admin route but was not run because it requires the local seeded backend/browser environment; real Provider connectivity and authorized participant trials remain outside this UI migration.

---
