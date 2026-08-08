"""标注诊断域（蓝图 §11，PRD-06 §9）：四种格式的确定性诊断，绝不调用 LLM 评分。

模块分层：detect（格式识别+错误类型）→ parsers（规范化记录）→ rules（确定性
规则引擎）→ engine（编排成 DiagnosticReportDTO）。原文件纯内存处理，绝不落盘（NF3）。
"""
