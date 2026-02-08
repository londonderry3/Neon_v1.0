"""
Backward-compatibility module.

Historically this project exposed a `krx_collector.py` helper. The data backend has
been migrated to KIS OpenAPI, but some scripts may still import `krx_collector.DataCollector`.
"""

from collector import DataCollector  # noqa: F401
