"""
sources/noaa_oni.py
NOAA ONI (Oceanic Niño Index) 自动抓取

数据源: https://psl.noaa.gov/data/correlation/oni.data
格式: 年份 + 12个月值 (DJF, JFM, FMA, ... SON, OND, NDJ)
更新时间: 每月 2nd 周左右

Phase 判定:
  EL_NINO:  ONI >= +0.5  (连续 5 个月以上)
  LA_NINA:  ONI <= -0.5  (连续 5 个月以上)
  NEUTRAL:  其他
"""

from __future__ import annotations
import requests
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Optional
import io


# NOAA ONI 列名对应 12 个 3 月滑动窗口
# DJF=JAN-FEB-MAR, JFM=FEB-MAR-APR, ..., NDJ=DEC-JAN-FEB
ONI_COLS = [
    'DJF', 'JFM', 'FMA', 'MAM', 'AMJ', 'MJJ',
    'JJA', 'JAS', 'ASO', 'SON', 'OND', 'NDJ',
]

# NOAA 官方阈值
EL_NINO_THRESHOLD = +0.5
LA_NINA_THRESHOLD = -0.5
MIN_DURATION = 5  # 至少 5 个月才认定为事件


class ONIScraper:
    """
    自动抓取并解析 NOAA ONI 数据。

    用法:
        scraper = ONIScraper()
        oni_df = scraper.fetch()           # 获取最新数据
        current_oni = scraper.get_current()  # 最新 ONI 值
        phase = scraper.get_phase()         # 'EL_NINO' / 'LA_NINA' / 'NEUTRAL'
        print(f'当前 ONI: {current_oni:.2f} ({phase})')
    """

    URL = 'https://psl.noaa.gov/data/correlation/oni.data'

    def __init__(self, cache_ttl: int = 3600):
        """
        Args:
            cache_ttl: 缓存有效期(秒)，默认 1 小时
        """
        self._cache_ttl = cache_ttl
        self._cache: Optional[pd.DataFrame] = None
        self._cache_time: Optional[datetime] = None

    def _is_stale(self) -> bool:
        if self._cache is None or self._cache_time is None:
            return True
        age = (datetime.now() - self._cache_time).total_seconds()
        return age > self._cache_ttl

    def fetch(self, force: bool = False) -> pd.DataFrame:
        """
        抓取并解析 ONI 数据。

        Returns:
            DataFrame, index=timestamp(MidMonth), columns=['year','season','oni','phase']
        """
        if not force and not self._is_stale():
            return self._cache

        r = requests.get(self.URL, timeout=10)
        r.raise_for_status()
        text = r.text

        # 解析
        rows = []
        lines = text.strip().split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 13:
                continue
            try:
                year = int(parts[0])
            except ValueError:
                continue

            for i, col in enumerate(ONI_COLS):
                val_str = parts[i + 1]
                # -99.0 或 -99 是 NOAA 缺失值标记
                try:
                    val = float(val_str)
                    if val <= -90:
                        continue
                except ValueError:
                    continue

                # 确定该窗口的中心月份
                # ONI 是 3 个月滑动平均
                # DJF = Dec-Jan-Feb → 中心月 = JAN (month 1)
                # 索引 i: 0=DJF, 1=JFM, ..., 11=NDJ
                # 月份 = i + 1
                center_month = i + 1

                if center_month == 1:
                    # DJF 跨年: Dec(year-1) - Jan(year) - Feb(year)
                    # 但作为时间戳，我们记为该窗口的"代表月"= January
                    ts = pd.Timestamp(year=year, month=1, day=15)
                elif center_month == 12:
                    # NDJ: Dec-Jan-Feb of next year → 代表月 = December
                    ts = pd.Timestamp(year=year, month=12, day=15)
                else:
                    ts = pd.Timestamp(year=year, month=center_month, day=15)

                rows.append({
                    'year': year,
                    'season': col,
                    'oni': val,
                    'phase': self._classify(val),
                    'timestamp': ts,
                })

        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values('timestamp').reset_index(drop=True)
            df.set_index('timestamp', inplace=True)

        self._cache = df
        self._cache_time = datetime.now()
        return df

    def _classify(self, oni: float) -> str:
        """单个 ONI 值分类"""
        if oni >= EL_NINO_THRESHOLD:
            return 'EL_NINO'
        elif oni <= LA_NINA_THRESHOLD:
            return 'LA_NINA'
        return 'NEUTRAL'

    def get_current(self, as_of: Optional[datetime] = None) -> tuple[float, str]:
        """
        获取最新可用 ONI 值。

        Args:
            as_of: 可选，指定截止时间（用于回测）

        Returns:
            (oni_value, phase) 元组
        """
        df = self.fetch()
        if df.empty:
            raise RuntimeError('No ONI data available')

        cutoff = as_of or datetime.now()
        available = df[df.index <= cutoff]

        if available.empty:
            latest = df.iloc[-1]
            return float(latest['oni']), latest['phase']

        latest = available.iloc[-1]
        return float(latest['oni']), latest['phase']

    def get_phase(self, as_of: Optional[datetime] = None) -> str:
        """获取当前气候阶段（考虑持续性）"""
        df = self.fetch()
        cutoff = as_of or datetime.now()
        available = df[df.index <= cutoff]

        if available.empty:
            return 'NEUTRAL'

        # 取最近 5 个月滑动窗口
        recent = available.tail(MIN_DURATION)
        if len(recent) < MIN_DURATION:
            recent = available.tail(1)

        oni_values = recent['oni'].values

        # 全部 >= +0.5 → EL_NINO
        if all(v >= EL_NINO_THRESHOLD for v in oni_values):
            return 'EL_NINO'
        # 全部 <= -0.5 → LA_NINA
        if all(v <= LA_NINA_THRESHOLD for v in oni_values):
            return 'LA_NINA'
        return 'NEUTRAL'

    def get_series(
        self,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> pd.Series:
        """
        获取 ONI 时间序列。

        Args:
            start: 起始日期 (YYYY-MM-DD)
            end: 结束日期 (YYYY-MM-DD)

        Returns:
            Series, index=timestamp, values=ONI
        """
        df = self.fetch()
        if start:
            df = df[df.index >= pd.Timestamp(start)]
        if end:
            df = df[df.index <= pd.Timestamp(end)]
        return df['oni']

    def get_oni_for_date(self, dt: datetime) -> tuple[float, str]:
        """获取指定日期对应的 ONI 值（取最近可用）"""
        df = self.fetch()
        available = df[df.index <= dt]
        if available.empty:
            latest = df.iloc[0]
            return float(latest['oni']), latest['phase']
        latest = available.iloc[-1]
        return float(latest['oni']), latest['phase']

    def get_climate_report(self, as_of: Optional[datetime] = None) -> dict:
        """
        生成气候状态报告。

        Returns:
            包含 ONI 值、阶段、事件、趋势的 dict
        """
        df = self.fetch()
        cutoff = as_of or datetime.now()
        available = df[df.index <= cutoff]

        if available.empty:
            return {'error': 'No data available'}

        current = available.iloc[-1]
        recent = available.tail(6)

        # 趋势
        if len(recent) >= 2:
            trend = recent['oni'].iloc[-1] - recent['oni'].iloc[0]
        else:
            trend = 0.0

        # 持续时间
        phase = self.get_phase(as_of)
        duration = 0
        for v in reversed(available['oni'].values):
            if phase == 'EL_NINO' and v >= EL_NINO_THRESHOLD:
                duration += 1
            elif phase == 'LA_NINA' and v <= LA_NINA_THRESHOLD:
                duration += 1
            else:
                break

        return {
            'current_oni': round(float(current['oni']), 2),
            'current_season': current['season'],
            'phase': phase,
            'phase_duration_months': duration,
            'trend': round(trend, 2),
            'threshold_el_nino': EL_NINO_THRESHOLD,
            'threshold_la_nina': LA_NINA_THRESHOLD,
            'last_updated': str(available.index[-1].date()),
            'data_start': str(available.index[0].date()),
            'data_end': str(available.index[-1].date()),
            'recent_6_values': [round(v, 2) for v in recent['oni'].tolist()],
        }

    def __repr__(self) -> str:
        try:
            oni, phase = self.get_current()
            return f'ONIScraper(current_oni={oni:.2f}, phase={phase})'
        except Exception:
            return 'ONIScraper(unavailable)'

    def check_and_publish(self, bus=None) -> list:
        """
        检查当前 ONI 状态并在超阈值时发布 CoffeeEvent。

        Args:
            bus: EventBus to publish to. If None, fetches bus from get_event_bus().

        Returns:
            List of published CoffeeEvents (0 or 1).
        """
        from core.types.event import CoffeeEvent
        from core.types.enums import EventType, Domain
        from core.event_bus import get_event_bus

        if bus is None:
            bus = get_event_bus()

        try:
            oni, phase = self.get_current()
        except Exception:
            return []

        events: list = []
        severity = 1
        narrative = f"ONI = {oni:+.2f} ({phase})"

        if phase == 'LA_NINA' and oni <= LA_NINA_THRESHOLD:
            severity = 4
            narrative += f" — La Niña确认 (阈值 {LA_NINA_THRESHOLD})"
            event = CoffeeEvent(
                event_type=EventType.LA_NINA,
                domain=Domain.SUPPLY,
                timestamp=datetime.now(),
                severity=severity,
                value=oni,
                narrative=narrative,
                source="ONIScraper",
            )
            bus.publish(event)
            events.append(event)

        elif phase == 'EL_NINO' and oni >= EL_NINO_THRESHOLD:
            severity = 4
            narrative += f" — El Niño确认 (阈值 {EL_NINO_THRESHOLD})"
            event = CoffeeEvent(
                event_type=EventType.EL_NINO,
                domain=Domain.SUPPLY,
                timestamp=datetime.now(),
                severity=severity,
                value=oni,
                narrative=narrative,
                source="ONIScraper",
            )
            bus.publish(event)
            events.append(event)

        return events


# ─── 兼容 sources/__init__.py 的 ONISource 别名 ──────────────────────────────
ONISource = ONIScraper


# ─── CLI ──────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys

    scraper = ONIScraper()

    print('Fetching ONI data from NOAA PSL...')
    try:
        df = scraper.fetch()
        report = scraper.get_climate_report()

        print()
        print('╔══════════════════════════════════════════════════╗')
        print('║         NOAA ONI Climate Report                   ║')
        print('╚══════════════════════════════════════════════════╝')
        print(f"  Data period:    {report['data_start']} → {report['data_end']}")
        print(f"  Last ONI:      {report['current_oni']:+.2f}  ({report['current_season']})")
        print(f"  Phase:          {report['phase']}")
        print(f"  Duration:       {report['phase_duration_months']} months")
        print(f"  Trend (6m):    {report['trend']:+.2f}")
        print(f"  Recent values: {report['recent_6_values']}")

        if len(sys.argv) > 1 and sys.argv[1] == '--series':
            print()
            print('Recent ONI series:')
            print(df.tail(24)[['oni', 'phase']].to_string())

    except Exception as e:
        print(f'Error: {e}')
        sys.exit(1)
