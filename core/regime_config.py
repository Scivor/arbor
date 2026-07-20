"""
core/regime_config.py
Sherlock SiteInformation + SitesInformation 的 coffee 版本

类比:
  Sherlock.sites.SiteInformation  →  RegimeInformation
  Sherlock.sites.SitesInformation →  RegimeConfigLoader
  Sherlock.sherlock.data.json     →  config/regimes.yaml

核心设计:
  - 规则完全外部化到 YAML，运营人员可独立修改阈值而无需改代码
  - 支持本地文件和远程 URL (类似 Sherlock 的 --local / --json)
  - 保留硬编码默认值作为回退
  - 三种检测类型: threshold | pattern | cross
  - Hedge adjustment 规则也从 YAML 读取 (DecisionEngine._EVENT_CONFIG 等价)
"""

from __future__ import annotations

import os
import yaml
import requests
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, TYPE_CHECKING
from enum import Enum

from core.state.scoring import EventRule, ScoringConfig
from core.types.enums import EventType

if TYPE_CHECKING:
    pass


# ============================================================
# Regime 检测类型 — Sherlock errorType 的等价类比
# ============================================================

class DetectType(Enum):
    """检测类型 — 等价 Sherlock 的 errorType"""
    THRESHOLD = "threshold"   # 指标突破阈值 (Sherlock status_code)
    PATTERN   = "pattern"     # 字符串/regex 匹配    (Sherlock errorMsg)
    CROSS     = "cross"       # 技术指标交叉          (Sherlock response_url)


class Condition(Enum):
    """比较条件"""
    ABOVE          = "above"
    BELOW          = "below"
    AT_OR_ABOVE    = "at_or_above"
    AT_OR_BELOW    = "at_or_below"
    IN_WINDOW      = "in_window"
    NOT_IN_WINDOW  = "not_in_window"
    EQUALS         = "equals"


# ============================================================
# RegimeInformation — 等价 Sherlock 的 SiteInformation
# ============================================================

@dataclass
class RegimeInformation:
    """
    单个 Regime 的元数据容器.

    等价 Sherlock: SiteInformation
    对应 YAML: regimes[].name
    """
    name: str
    domain: str                          # "SUPPLY" | "FINANCE" | "POLICY"
    detect_type: DetectType               # threshold | pattern | cross
    source: str                          # 数据源: "oni_index" | "kc_price" | "cot_report" | ...
    field: str                           # 检测字段: "temperature_celsius" | "prob" | ...

    # 检测参数 (detect_type == threshold)
    threshold: Optional[float] = None
    condition: Condition = Condition.ABOVE

    # 检测参数 (detect_type == pattern)
    patterns: list[str] = field(default_factory=list)
    regex: Optional[str] = None

    # 检测参数 (detect_type == cross)
    window: Optional[list[int]] = None   # [10, 11, 12] 月份窗口

    # 严重度
    severity: int = 3
    severity_extreme: Optional[int] = None  # 极端情况下的更高 severity

    # 套保动作
    hedge_action: str = "MONITOR"        # INCREASE_HEDGE | REDUCE_HEDGE | FULL_HEDGE | MONITOR | ...

    # 叙事模板 (Sherlock 无等价物)
    narrative_template: str = "{name}: {field}={value}"

    # 启用标志 (Sherlock: enabled ≈ site not in nsfw exclusion list)
    enabled: bool = True

    def resolve_severity(self, value: float) -> int:
        """根据检测值确定最终 severity"""
        if self.severity_extreme is None:
            return self.severity
        # 检查极端条件
        if self.detect_type == DetectType.THRESHOLD and self.threshold is not None:
            extreme_ratio = abs(value / self.threshold) if self.threshold != 0 else 0
            if extreme_ratio > 2.0:
                return self.severity_extreme
        return self.severity

    def resolve_narrative(self, value: float, matched: Optional[str] = None) -> str:
        """渲染 narrative_template，支持 Python 格式说明符

        支持:
          {name}           → regime 名称
          {value}          → 检测值
          {value:.1%}      → 百分比格式
          {value:,.0f}     → 千分位整数格式
          {threshold}       → 阈值原始值
          {threshold:.2f}  → 带精度的阈值
          {matched}        → pattern 匹配到的字符串
        """
        tpl = self.narrative_template

        def fmt(v, spec):
            if v is None:
                return "N/A"
            try:
                v = float(v)
            except (TypeError, ValueError):
                return str(v)
            return format(v, spec) if spec else str(v)

        def repl(m):
            inner = m.group(1)
            if ":" in inner:
                fld, _, spec = inner.partition(":")
            else:
                fld, spec = inner, ""
            if fld == "value":
                return fmt(value, spec)
            elif fld == "threshold":
                return fmt(self.threshold, spec)
            elif fld == "matched":
                return str(matched or "")
            elif fld == "name":
                return self.name
            return m.group(0)

        import re as _re
        return _re.sub(r"\{(\w+(?::[^\}]+)?)\}", repl, tpl)

    def detect(self, raw_data: dict) -> Optional[dict]:
        """
        在 raw_data 上执行检测.
        返回 dict: {"detected": bool, "value": float, "matched": str|None}
        如果未触发检测返回 None.
        """
        field_value = self._extract_field(raw_data)
        if field_value is None:
            return None

        if self.detect_type == DetectType.THRESHOLD:
            return self._detect_threshold(field_value)
        elif self.detect_type == DetectType.PATTERN:
            return self._detect_pattern(field_value)
        elif self.detect_type == DetectType.CROSS:
            return self._detect_cross(field_value)
        return None

    def _extract_field(self, raw_data: dict) -> Optional[float]:
        """从 raw_data 字典中提取检测字段的值

        字段格式: "field_name" (但实际存储在 raw_data[source][field_name])
        因此 lookup 路径是: source.field
        例如: source="oni_index", field="oni_value"
             → raw_data["oni_index"]["oni_value"]
        """
        # Sherlock 的 urlProbe 等价: source 是 URL/路径前缀
        # 这里 source 是 market_data 的顶级 key
        keys = f"{self.source}.{self.field}".split(".")
        val = raw_data
        for k in keys:
            if isinstance(val, dict):
                val = val.get(k)
            else:
                return None
            if val is None:
                return None
        try:
            return float(val)
        except (TypeError, ValueError):
            # 可能是字符串，用于 pattern 检测
            return val if isinstance(val, str) else None

    def _detect_threshold(self, value: float) -> Optional[dict]:
        cond = self.condition
        thr = self.threshold

        if cond == Condition.ABOVE and value > thr:
            return {"detected": True, "value": value, "matched": None}
        elif cond == Condition.BELOW and value < thr:
            return {"detected": True, "value": value, "matched": None}
        elif cond == Condition.AT_OR_ABOVE and value >= thr:
            return {"detected": True, "value": value, "matched": None}
        elif cond == Condition.AT_OR_BELOW and value <= thr:
            return {"detected": True, "value": value, "matched": None}
        elif cond == Condition.EQUALS and abs(value - thr) < 1e-9:
            return {"detected": True, "value": value, "matched": None}
        elif cond in (Condition.IN_WINDOW, Condition.NOT_IN_WINDOW):
            # value 是月份整数
            in_win = int(value) in self.window if self.window else False
            if (cond == Condition.IN_WINDOW and in_win) or \
               (cond == Condition.NOT_IN_WINDOW and not in_win):
                return {"detected": True, "value": value, "matched": None}
        return None

    def _detect_pattern(self, value: str) -> Optional[dict]:
        if not isinstance(value, str):
            return None
        value_lower = value.lower()
        for p in self.patterns:
            if p.lower() in value_lower:
                return {"detected": True, "value": value, "matched": p}
        return None

    def _detect_cross(self, value: float) -> Optional[dict]:
        # cross 检测用于窗口/交叉类型
        return self._detect_threshold(value)

    def __str__(self):
        return f"RegimeInformation({self.name}, {self.detect_type.value}, {self.source}.{self.field})"


# ============================================================
# HedgeAdjustmentRule — DecisionEngine._EVENT_CONFIG 的等价
# 完全外部化到 config/regimes.yaml 的 adjustment_rules 部分
# ============================================================

@dataclass
class HedgeAdjustmentRule:
    """
    单个 EventType → hedge ratio 调整规则

    等价 DecisionEngine._EVENT_CONFIG 中的 dict 条目:
      EventType.FROST_WARNING: dict(adjustment=0.20, min_severity=3, ...)

    Sherlock 等价:
      QueryStatus.CLAIMED → adjustment 触发的 severity 判定
    """
    adjustment: float          # 调整量 (正=增套保，负=减)
    min_severity: int = 3      # 最低 severity 才生效
    cooldown_seconds: int = 600  # 同事件冷却时间；现由 reports.pipeline._dedupe_events 用作去重窗口
    multiplier_sev4: float = 1.5  # severity >= 4 的额外乘数（评分重构后仅供旧路径 get_adjustment_for_event 参考）
    reason: str = ""           # 调整原因描述
    cluster: str = "misc"      # 所属因子簇 —— 簇内递减求和防重复计数
    half_life_days: float = 30.0  # 信息寿命 —— 贡献衰减一半所需天数

    # 回退默认值 (当 YAML 中没有定义时)
    DEFAULT = None  # None → 表示未定义，调用方应使用 DecisionEngine 硬编码回退


# ============================================================
# RegimeConfigLoader — 等价 Sherlock 的 SitesInformation
# ============================================================

@dataclass
class RegimeConfigLoader:
    """
    从 YAML 文件或远程 URL 加载 regime 配置.

    等价 Sherlock: SitesInformation
    支持:
      - 本地文件路径: "config/regimes.yaml"
      - 远程 URL:     "https://raw.githubusercontent.com/.../regimes.yaml"
      - PR 编号:      "2824" (从 GitHub PR 获取数据)

    Sherlock 等价参数:
      --local              → local_only=True
      --json FILE/URL/PR#  → data_file_path
      --site NAME          → get_regime(name)
      --timeout            → remote_fetch_timeout
    """

    data_file_path: Optional[str] = None
    honor_exclusions: bool = True
    do_not_exclude: list[str] = field(default_factory=list)   # Sherlock: --site 过滤
    local_only: bool = False
    remote_fetch_timeout: int = 10

    # Sherlock 等价: MANIFEST_URL
    MANIFEST_URL: str = field(default="",
        init=False)

    _regimes: Optional[dict[str, RegimeInformation]] = field(default=None, init=False)
    _settings: dict = field(default_factory=dict, init=False)
    _adjustment_rules: Optional[dict[str, HedgeAdjustmentRule]] = field(default=None, init=False)
    _scoring: Optional[ScoringConfig] = field(default=None, init=False)
    _loaded: bool = field(default=False, init=False)

    def __post_init__(self):
        # 设置默认 manifest URL
        object.__setattr__(self, 'MANIFEST_URL',
            "https://raw.githubusercontent.com/HKUDS/Vibe-Trading/main/config/regimes.yaml")

    # ----------------------------------------------------------
    # 加载入口
    # ----------------------------------------------------------

    def load(self) -> None:
        """
        加载配置. 兼容 Sherlock 的加载语义:
          1. 优先用 data_file_path (本地文件或远程 URL)
          2. 否则用 MANIFEST_URL
          3. 支持 PR 编号作为 --json 参数
        """
        if self._loaded:
            return

        raw_data: dict

        if self.data_file_path:
            raw_data = self._load_from_path(self.data_file_path)
        elif not self.local_only:
            raw_data = self._load_from_url(self.MANIFEST_URL)
        else:
            # Sherlock: --local 模式
            base = os.path.dirname(os.path.abspath(__file__))
            local_path = os.path.join(base, "..", "config", "regimes.yaml")
            raw_data = self._load_from_path(local_path)

        self._parse(raw_data)
        self._loaded = True

    def _load_from_path(self, path: str) -> dict:
        """从本地文件或远程 URL 加载"""
        if path.isdigit():
            # Sherlock --json 支持 PR 编号
            return self._load_from_pr(int(path))

        if path.startswith("http://") or path.startswith("https://"):
            return self._load_from_url(path)

        # 本地文件
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _load_from_url(self, url: str) -> dict:
        """从远程 URL 加载，带超时"""
        try:
            resp = requests.get(url, timeout=self.remote_fetch_timeout)
            resp.raise_for_status()
            return yaml.safe_load(resp.text) or {}
        except Exception as e:
            print(f"[RegimeConfigLoader] 远程加载失败 ({url}): {e}")
            print("  → 回退到本地默认配置")
            return self._default_config()

    def _load_from_pr(self, pr_number: int) -> dict:
        """从 GitHub PR 获取配置 (Sherlock --json PR# 模式)"""
        api_url = f"https://api.github.com/repos/HKUDS/Vibe-Trading/pulls/{pr_number}"
        try:
            resp = requests.get(api_url, timeout=self.remote_fetch_timeout)
            resp.raise_for_status()
            pr_data = resp.json()
            head_sha = pr_data["head"]["sha"]
            file_url = (f"https://raw.githubusercontent.com/HKUDS/Vibe-Trading/"
                       f"{head_sha}/config/regimes.yaml")
            return self._load_from_url(file_url)
        except Exception as e:
            raise FileNotFoundError(f"无法从 PR #{pr_number} 加载配置: {e}")

    def _parse(self, raw: dict) -> None:
        """解析 YAML dict → RegimeInformation 字典"""
        settings = raw.get("settings", {})
        self._settings = settings

        regimes_raw = raw.get("regimes", [])
        self._regimes = {}

        for r in regimes_raw:
            name = r.get("name", "")
            if not name:
                continue

            # 解析 detect_type
            dt_str = r.get("detect_type", "threshold")
            try:
                detect_type = DetectType(dt_str)
            except ValueError:
                detect_type = DetectType.THRESHOLD

            # 解析 condition
            cond_str = r.get("condition", "above")
            try:
                condition = Condition(cond_str)
            except ValueError:
                condition = Condition.ABOVE

            # 解析 severity (支持 severity: 3 或 severity: {default: 3, extreme: 5})
            sev_raw = r.get("severity", 3)
            if isinstance(sev_raw, dict):
                sev = sev_raw.get("default", 3)
                sev_extreme = sev_raw.get("extreme")
            else:
                sev = sev_raw if isinstance(sev_raw, int) else 3
                sev_extreme = r.get("severity_extreme")

            regime = RegimeInformation(
                name=name,
                domain=r.get("domain", "SUPPLY"),
                detect_type=detect_type,
                source=r.get("source", ""),
                field=r.get("field", ""),
                threshold=r.get("threshold"),
                condition=condition,
                patterns=r.get("patterns", []),
                regex=r.get("regex"),
                window=r.get("window"),
                severity=sev,
                severity_extreme=sev_extreme,
                hedge_action=r.get("hedge_action", "MONITOR"),
                narrative_template=r.get("narrative_template", "{name}: {value}"),
                enabled=r.get("enabled", True),
            )

            self._regimes[name] = regime

        # ── 解析 adjustment_rules — DecisionEngine._EVENT_CONFIG 的等价 ──
        self._adjustment_rules = {}
        adj_raw = raw.get("adjustment_rules", {})
        for et_name, cfg in adj_raw.items():
            if isinstance(cfg, dict):
                self._adjustment_rules[et_name] = HedgeAdjustmentRule(
                    adjustment=cfg.get("adjustment", 0.0),
                    min_severity=cfg.get("min_severity", 3),
                    cooldown_seconds=cfg.get("cooldown_seconds", 600),
                    multiplier_sev4=cfg.get("multiplier_sev4", 1.5),
                    reason=cfg.get("reason", ""),
                    cluster=cfg.get("cluster", "misc"),
                    half_life_days=float(cfg.get("half_life_days", 30.0)),
                )

        # ── 解析 scoring 块 — 评分全局参数 ──────────────────────────────────
        sc = raw.get("scoring", {}) or {}
        default = ScoringConfig()
        self._scoring = ScoringConfig(
            baseline=float(sc.get("baseline", default.baseline)),
            span_up=float(sc.get("span_up", default.span_up)),
            span_down=float(sc.get("span_down", default.span_down)),
            tanh_k=float(sc.get("tanh_k", default.tanh_k)),
            rank_decay=float(sc.get("rank_decay", default.rank_decay)),
        )

    def _default_config(self) -> dict:
        """硬编码默认配置 — Sherlock 的等价位: 当 data.json 全部失效时的回退"""
        return {
            "regimes": [],
            "adjustment_rules": {},
            "settings": {"enabled_by_default": True, "debug": False}
        }

    # ----------------------------------------------------------
    # 查询接口 — 等价 Sherlock 的 site_data 查询方法
    # ----------------------------------------------------------

    @property
    def regimes(self) -> dict[str, RegimeInformation]:
        self.load()
        return self._regimes

    def get_regime(self, name: str) -> Optional[RegimeInformation]:
        """按名称获取 regime — 等价 Sherlock: site_data["Twitter"]"""
        self.load()
        return self._regimes.get(name)

    def get_regimes_by_domain(self, domain: str) -> dict[str, RegimeInformation]:
        """获取指定域的所有 regime"""
        self.load()
        return {
            k: v for k, v in self._regimes.items()
            if v.domain.upper() == domain.upper()
        }

    def get_regimes_by_action(self, action: str) -> dict[str, RegimeInformation]:
        """获取指定套保动作的所有 regime"""
        self.load()
        return {
            k: v for k, v in self._regimes.items()
            if v.hedge_action.upper() == action.upper()
        }

    def list_enabled(self) -> list[str]:
        """列出所有启用的 regime 名称"""
        self.load()
        return [k for k, v in self._regimes.items() if v.enabled]

    def list_disabled(self) -> list[str]:
        """列出所有禁用的 regime 名称"""
        self.load()
        return [k for k, v in self._regimes.items() if not v.enabled]

    @property
    def settings(self) -> dict:
        self.load()
        return self._settings

    # ─────────────────────────────────────────────────────────────────────────
    # HedgeAdjustmentRule 查询 — DecisionEngine._EVENT_CONFIG 的等价查询
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def adjustment_rules(self) -> dict[str, HedgeAdjustmentRule]:
        """获取所有 adjustment rules"""
        self.load()
        return self._adjustment_rules or {}

    def get_adjustment_rule(self, event_type_name: str) -> Optional[HedgeAdjustmentRule]:
        """
        按 EventType 名称获取 adjustment rule

        等价 DecisionEngine._EVENT_CONFIG[event_type]
        Sherlock 无直接等价: Sherlock 的 errorCode 是静态的
        """
        self.load()
        return self._adjustment_rules.get(event_type_name)

    @property
    def scoring(self) -> ScoringConfig:
        """评分全局参数；YAML 无 scoring 块时返回默认值。"""
        self.load()
        return self._scoring or ScoringConfig()

    def event_rules(self) -> dict[EventType, EventRule]:
        """
        产出 core.state.scoring.compute_score 直接可用的规则表。
        非 EventType 成员的键（如 regime 名 DROUGHT_ONI）静默跳过。
        """
        out: dict[EventType, EventRule] = {}
        for name, rule in self.adjustment_rules.items():
            if name not in EventType.__members__:
                continue
            out[EventType[name]] = EventRule(
                adjustment=rule.adjustment,
                cluster=rule.cluster,
                half_life_days=rule.half_life_days,
                min_severity=rule.min_severity,
            )
        return out

    def get_adjustment_for_event(self, event_type_name: str,
                                  severity: int,
                                  current_time=None) -> Optional[dict]:
        """
        获取事件触发后的实际 adjustment 值

        Returns dict with:
          - adjustment: 实际调整量（含 multiplier）
          - rule: HedgeAdjustmentRule
          - blocked: bool (cooldown 中)
          - reason: str
        """
        rule = self.get_adjustment_rule(event_type_name)
        if not rule:
            return None

        # 检查 min_severity
        if severity < rule.min_severity:
            return None

        # 计算最终 adjustment（含 severity 乘数）
        final_adj = rule.adjustment
        if severity >= 4:
            final_adj *= rule.multiplier_sev4

        return {
            "adjustment": final_adj,
            "rule": rule,
            "blocked": False,  # cooldown 检查由调用方负责
            "reason": rule.reason,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Sherlock --site / --nsfw 等价的运行时过滤
    # ─────────────────────────────────────────────────────────────────────────

    # ----------------------------------------------------------
    # Sherlock --site / --nsfw 等价的运行时过滤
    # ----------------------------------------------------------

    def filter_regimes(self, names: Optional[list[str]] = None,
                       domains: Optional[list[str]] = None,
                       enabled_only: bool = True) -> dict[str, RegimeInformation]:
        """
        运行时过滤 regime.

        等价 Sherlock:
          --site Twitter GitHub     → names=["Twitter", "GitHub"]
          --nsfw                    → enabled_only=False
        """
        self.load()
        result = dict(self._regimes)

        if names:
            result = {k: v for k, v in result.items() if k in names}
        if domains:
            result = {k: v for k, v in result.items()
                     if v.domain.upper() in [d.upper() for d in domains]}
        if enabled_only:
            result = {k: v for k, v in result.items() if v.enabled}

        return result

    # ----------------------------------------------------------
    # 批量检测接口 — RegimeDetectEngine 的核心
    # ----------------------------------------------------------

    def detect_all(self, market_data: dict,
                   regime_names: Optional[list[str]] = None) -> list[dict]:
        """
        对 market_data 批量运行所有 (或指定) regime 检测.

        返回格式:
          [{"regime": RegimeInformation, "detected": bool, "value": float, "matched": str|None}, ...]
        """
        self.load()
        results = []
        regimes_to_check = (regime_names or list(self._regimes.keys()))

        for name in regimes_to_check:
            regime = self._regimes.get(name)
            if not regime or not regime.enabled:
                continue

            detected = regime.detect(market_data)
            if detected:
                results.append({
                    "regime": regime,
                    **detected
                })

        return results

    def detect_and_build_events(self, market_data: dict,
                                 regime_names: Optional[list[str]] = None) -> list[dict]:
        """
        detect_all 的高层封装: 返回可直接构建 CoffeeEvent 的 dict 列表.
        等价于 Sherlock 的最终 results_total 构建逻辑.
        """
        from core.types.enums import Domain, EventType

        detections = self.detect_all(market_data, regime_names)
        events = []

        for det in detections:
            regime = det["regime"]
            value = det["value"]
            matched = det["matched"]

            try:
                domain = Domain[regime.domain]
            except KeyError:
                domain = Domain.SUPPLY

            # 尝试从 EventType 找匹配
            event_type_name = regime.name.upper()
            try:
                event_type = EventType[event_type_name]
            except KeyError:
                # 没有对应的 EventType，用通用类型
                event_type = EventType.PRICE_SHOCK_UP  # fallback

            event = {
                "event_type": event_type,
                "domain": domain,
                "timestamp": datetime.now(),
                "severity": regime.resolve_severity(value),
                "value": value,
                "narrative": regime.resolve_narrative(value, matched),
                "source": f"RegimeConfig/{regime.source}",
                "metadata": {
                    "regime_name": regime.name,
                    "hedge_action": regime.hedge_action,
                    "detect_type": regime.detect_type.value,
                    "matched": matched,
                }
            }
            events.append(event)

        return events

    def __iter__(self):
        """支持 for r in loader: 遍历所有 regime"""
        self.load()
        return iter(self._regimes.values())

    def __len__(self):
        self.load()
        return len(self._regimes)

    def __repr__(self):
        self.load()
        return f"RegimeConfigLoader(regimes={len(self._regimes)}, loaded={self._loaded})"


# ============================================================
# 全局默认实例 — Sherlock sites = SitesInformation() 的等价
# ============================================================

_default_loader: Optional[RegimeConfigLoader] = None

def get_regime_loader() -> RegimeConfigLoader:
    """全局默认 loader — 延迟初始化，本地文件优先"""
    global _default_loader
    if _default_loader is None:
        # Sherlock 等价: --local 优先，远程作为 fallback
        # 尝试本地 config/regimes.yaml
        base = os.path.dirname(os.path.abspath(__file__))
        local_path = os.path.join(base, "..", "config", "regimes.yaml")
        if os.path.exists(local_path):
            _default_loader = RegimeConfigLoader(
                data_file_path=local_path,
                local_only=True,   # 本地文件存在时，不尝试远程
            )
        else:
            # 本地不存在，尝试远程 manifest
            _default_loader = RegimeConfigLoader()
    return _default_loader
