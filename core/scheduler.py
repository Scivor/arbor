"""
core/scheduler.py
PeriodicScheduler — 替代 while True 循环的定时调度

Sherlock 等价设计:
  Sherlock: sherlock.py --interval 参数控制轮询频率
  → PeriodicScheduler 的 run_mode=FIXED_DELAY 等价于 --interval

  Sherlock: cron-like site checking 每天固定时间点
  → PeriodicScheduler 的 run_mode=EXACT_CRON 等价于每天固定时间点检查

技术约束:
  - 使用 threading 而非 multiprocessing (EventBus 是线程安全的)
  - 调度线程是 daemon=True，Ctrl+C 可立即退出
  - 精确到秒级，不需要分钟级 cron 解析
  - 错误隔离：单个 job 错误不影响其他 job
"""

import time
import threading
from datetime import datetime, timedelta
from typing import Callable, Optional, TYPE_CHECKING
from dataclasses import dataclass, field
from enum import Enum

if TYPE_CHECKING:
    from core.events.bus import EventBus
    from core.types.event import CoffeeEvent


class RunMode(Enum):
    FIXED_DELAY = "fixed_delay"    # 每次运行后等固定秒数
    EXACT_CRON = "exact_cron"       # 精确 cron 风格（每天9:00, 12:00 等）


@dataclass
class ScheduledJob:
    """
    单个定时任务

    Attributes:
        name: 任务名称，唯一标识
        func: 可调用对象，返回 CoffeeEvent 列表
        interval_seconds: 运行间隔秒数 (FIXED_DELAY 模式)
        enabled: 是否启用
        last_run: 上次运行时间
        last_result: 上次运行产生的事件列表
        error: 上次运行的错误信息
    """
    name: str
    func: Callable[[], list]  # 返回 CoffeeEvent 列表
    interval_seconds: int = 300
    enabled: bool = True
    last_run: Optional[datetime] = None
    last_result: list = field(default_factory=list)
    error: Optional[str] = None


class PeriodicScheduler:
    """
    定时调度器 — 替代 while True + time.sleep() 轮询

    Sherlock 等价设计:
      - run_mode=FIXED_DELAY 等价于 Sherlock 的 --interval 参数
      - run_mode=EXACT_CRON 等价于每天固定时间点检查

    使用方式:
        scheduler = PeriodicScheduler(bus, run_mode=RunMode.FIXED_DELAY)
        scheduler.add_job(make_supply_job(scanner))
        scheduler.add_job(make_finance_job(scanner))
        scheduler.add_job(make_policy_job(scanner))
        scheduler.start()  # 后台运行

        # 或者单次运行
        results = scheduler.run_once()

        # 查看状态
        print(scheduler.status())

        # 停止
        scheduler.stop()
    """

    def __init__(self, bus: "EventBus", run_mode: RunMode = RunMode.FIXED_DELAY):
        self.bus = bus
        self.run_mode = run_mode
        self.jobs: dict[str, ScheduledJob] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def add_job(self, job: ScheduledJob) -> None:
        """注册一个定时任务"""
        if not isinstance(job, ScheduledJob):
            raise TypeError(f"Expected ScheduledJob, got {type(job).__name__}")
        self.jobs[job.name] = job

    def remove_job(self, name: str) -> None:
        """移除一个定时任务"""
        self.jobs.pop(name, None)

    def get_job(self, name: str) -> Optional[ScheduledJob]:
        """获取指定任务"""
        return self.jobs.get(name)

    def run_once(self) -> dict[str, list]:
        """
        立即运行所有 enabled 的 job 一次
        返回 {job_name: [CoffeeEvent, ...]} 字典
        错误隔离：单个 job 异常不影响其他 job
        """
        results: dict[str, list] = {}
        for job in self.jobs.values():
            if not job.enabled:
                continue
            try:
                events = job.func()
                if events is None:
                    events = []
                job.last_result = events
                job.last_run = datetime.now()
                job.error = None
            except Exception as e:
                job.error = str(e)
                job.last_result = []
            results[job.name] = job.last_result
        return results

    def _run_loop_fixed_delay(self, interval: int) -> None:
        """FIXED_DELAY 模式的主循环"""
        while not self._stop_event.is_set():
            self._stop_event.wait(interval)
            if self._stop_event.is_set():
                break
            self.run_once()

    def _run_loop_exact_cron(self, hour: int, minute: int) -> None:
        """
        EXACT_CRON 模式的主循环
        每天在指定 hour:minute 时刻运行所有 job
        """
        while not self._stop_event.is_set():
            now = datetime.now()
            # 计算下一个目标时刻
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if now >= target:
                target += timedelta(days=1)
            seconds_until = (target - now).total_seconds()
            if seconds_until > 0:
                self._stop_event.wait(seconds_until)
            if self._stop_event.is_set():
                break
            self.run_once()
            # 等待一天后再继续
            self._stop_event.wait(60)  # 每分钟检查是否停止

    def start(self, background: bool = True, interval: int = 300,
              cron_hour: int = 9, cron_minute: int = 0) -> None:
        """
        启动调度器

        Args:
            background: True=后台线程运行，False=阻塞当前线程
            interval: FIXED_DELAY 模式的间隔秒数 (默认 300)
            cron_hour: EXACT_CRON 模式的小时 (默认 9)
            cron_minute: EXACT_CRON 模式的分钟 (默认 0)
        """
        if self._running:
            return

        self._running = True
        self._stop_event.clear()

        if background:
            self._thread = threading.Thread(
                target=self._thread_target,
                args=(interval, cron_hour, cron_minute),
                name="PeriodicScheduler",
                daemon=True,
            )
            self._thread.start()
        else:
            self._thread_target(interval, cron_hour, cron_minute)

    def _thread_target(self, interval: int, cron_hour: int, cron_minute: int) -> None:
        """调度线程的目标函数"""
        try:
            if self.run_mode == RunMode.EXACT_CRON:
                self._run_loop_exact_cron(cron_hour, cron_minute)
            else:
                self._run_loop_fixed_delay(interval)
        except Exception as e:
            print(f"[PeriodicScheduler] Unexpected error in scheduler loop: {e}")
        finally:
            self._running = False

    def stop(self) -> None:
        """停止调度器"""
        if not self._running:
            return
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        self._running = False

    def status(self) -> str:
        """
        返回调度器状态字符串
        格式:
            PeriodicScheduler Status
            ========================================
              [OK] supply_job: every 300s, last=10:30:45
              [ERR: Network timeout...] finance_job: every 300s, last=never
        """
        lines = ["PeriodicScheduler Status", "=" * 40]
        mode_str = f"mode={self.run_mode.value}"
        run_str = "running" if self._running else "stopped"
        lines.append(f"  {mode_str}, {run_str}")
        lines.append("-" * 40)
        for name, job in self.jobs.items():
            status = "OK" if not job.error else f"ERR: {job.error[:30]}"
            last = job.last_run.strftime("%H:%M:%S") if job.last_run else "never"
            enabled_str = "" if job.enabled else " [DISABLED]"
            lines.append(f"  [{status}] {name}: every {job.interval_seconds}s, last={last}{enabled_str}")
        return "\n".join(lines)

    def is_running(self) -> bool:
        """检查调度器是否正在运行"""
        return self._running


# ─────────────────────────────────────────────────────────────────────────────
# 预定义 Job 工厂函数
# ─────────────────────────────────────────────────────────────────────────────

def make_supply_job(scanner) -> ScheduledJob:
    """
    创建供给域定时任务

    Args:
        scanner: SupplyOrchestrator 实例，scan_all() 返回 CoffeeEvent 列表

    Returns:
        ScheduledJob 实例
    """
    def job_func():
        return scanner.scan_all()

    return ScheduledJob(
        name="supply_job",
        func=job_func,
        interval_seconds=300,
        enabled=True,
    )


def make_finance_job(scanner) -> ScheduledJob:
    """
    创建金融域定时任务

    Args:
        scanner: FinanceDomainScanner 实例，scan_all() 返回 CoffeeEvent 列表

    Returns:
        ScheduledJob 实例
    """
    def job_func():
        return scanner.scan_all()

    return ScheduledJob(
        name="finance_job",
        func=job_func,
        interval_seconds=300,
        enabled=True,
    )


def make_policy_job(scanner) -> ScheduledJob:
    """
    创建政策域定时任务

    Args:
        scanner: PolicyDomainScanner 实例，scan_all() 返回 CoffeeEvent 列表

    Returns:
        ScheduledJob 实例
    """
    def job_func():
        return scanner.scan_all()

    return ScheduledJob(
        name="policy_job",
        func=job_func,
        interval_seconds=300,
        enabled=True,
    )


def make_ml_job(engine, bus) -> ScheduledJob:
    """
    创建 ML Advisor 定时任务

    Args:
        engine: DecisionEngine 实例
        bus: EventBus 实例

    Returns:
        ScheduledJob 实例
    """
    def job_func():
        from models.ml_advisor import MLAdvisor
        advisor = MLAdvisor(engine, bus)
        advice = advisor.run()
        # MLAdvisor.run() already calls engine.update_ml_signal() internally
        # and publishes to bus. Return events so scheduler can track results.
        return []

    return ScheduledJob(
        name="ml_job",
        func=job_func,
        interval_seconds=3600,  # ML 计算较重，每小时一次
        enabled=True,
    )
