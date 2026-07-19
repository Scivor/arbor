"""
sources/coffee/ico_spot.py
ICO 每日现货指标（I-CIP）数据源

公开 PDF: https://icocoffee.org/documents/I-CIP.pdf（当月逐日表，每日更新）。
结构: 每行 "16-Jul 286.87 382.66 352.91 321.88 186.27"
（日期 + I-CIP 综合价 + Colombian Milds + Other Milds + Brazilian Naturals + Robustas），
另有 Average（月均）与 DoD Change（日变动）行；未来日期行为空行。
缓存 ~/.arbor/cache/icip.pdf（TTL 12h，按 mtime，参照 kc_history 模式）。
"""

from __future__ import annotations

import io
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

_URL = "https://icocoffee.org/documents/I-CIP.pdf"
_CACHE_PATH = Path.home() / ".arbor" / "cache" / "icip.pdf"
_CACHE_TTL = timedelta(hours=12)

# 日行: "16-Jul 286.87 382.66 352.91 321.88 186.27"
_DAY_RE = re.compile(
    r"^(\d{1,2}-\w{3})\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*$"
)
_AVG_RE = re.compile(r"^Average\s+([\d.]+)", re.M)
_DOD_RE = re.compile(r"DoD Change\s+([+-]?[\d.]+)%")


class ICOSpotSource:
    """ICO I-CIP 每日现货指标"""

    name = "ico_spot"

    def fetch(self) -> dict:
        """获取最新一个交易日的 I-CIP 指标；任何一步失败抛异常（消费层兜底）。"""
        src = self._cached_pdf()
        text = self._extract_text(src)
        return self._parse(text)

    def _cached_pdf(self):
        """读缓存（TTL 12h）；过期/缺失则下载。返回路径或内存字节流。"""
        if _CACHE_PATH.exists():
            age = datetime.now() - datetime.fromtimestamp(_CACHE_PATH.stat().st_mtime)
            if age < _CACHE_TTL:
                logger.info("ICOSpot: 使用缓存（age %s）", age)
                return _CACHE_PATH

        import requests
        resp = requests.get(_URL, timeout=30)
        resp.raise_for_status()
        content = resp.content
        try:
            _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            _CACHE_PATH.write_bytes(content)
        except Exception as e:
            logger.warning("ICOSpot: 缓存写入失败: %s", e)
            return io.BytesIO(content)
        return _CACHE_PATH

    @staticmethod
    def _extract_text(src) -> str:
        """pdfplumber 提取第一页文本（pdfplumber 惰性导入）。"""
        import pdfplumber
        with pdfplumber.open(src) as pdf:
            if not pdf.pages:
                raise RuntimeError("ICOSpot: PDF 无页面")
            text = pdf.pages[0].extract_text() or ""
        if not text.strip():
            raise RuntimeError("ICOSpot: PDF 文本提取为空")
        return text

    @staticmethod
    def _parse(text: str) -> dict:
        """解析逐日表：取最后一个非空日行 + Average 月均 + DoD Change。"""
        last_day = None
        for line in text.splitlines():
            m = _DAY_RE.match(line.strip())
            if m:
                last_day = m  # 逐行覆盖，最后命中的即最新交易日（空行自然跳过）

        if last_day is None:
            raise RuntimeError("ICOSpot: 未解析到任何日行")

        avg = _AVG_RE.search(text)
        dod = _DOD_RE.search(text)
        return {
            "date": last_day.group(1),
            "icip": float(last_day.group(2)),
            "colombian_milds": float(last_day.group(3)),
            "other_milds": float(last_day.group(4)),
            "brazilian_naturals": float(last_day.group(5)),
            "robustas": float(last_day.group(6)),
            "month_avg": float(avg.group(1)) if avg else None,
            "dod_change_pct": float(dod.group(1)) if dod else None,
            "source": "ICO I-CIP",
        }
