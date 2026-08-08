"""Agent 工具域（蓝图 §9）：注册表与各工具实现。

工具命名/权限与蓝图 §9 逐字对齐；跨域依赖（rag/graphx/diagnosis/mastery/
telemetry/providers）全部在 handler 内惰性导入，保证其它域缺席时
`bhzd_py.tools` 依旧可导入。
"""
