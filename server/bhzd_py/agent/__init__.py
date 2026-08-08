"""Agent 域包：编排/意图/合成等模块按蓝图 §2.1 逐个落地，providers 先行。

注意（为什么保持 __init__ 为空）：B3 域的 orchestrator/intents/composer 等由
其它任务并行开发，本包初始化不得 import 它们，否则半成品的兄弟模块会让
providers 也无法导入。
"""
