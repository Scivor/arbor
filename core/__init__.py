"""
Arbor Event-Driven Architecture
事件驱动 + 三域模型

架构:
  sources/     → 数据源 (Polymarket, NOAA, ICE, etc.)
  domains/     → 三域 (supply, finance, policy)
  core/        → 事件总线 + 决策引擎
  output/      → 输出报告
  config/      → 配置文件
"""

__version__ = "3.0.0"
