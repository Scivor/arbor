"""
core/cost/landed_cost.py
到库成本计算器 — 咖啡生豆进口商完整采购成本

从 CYP (Cost, Insurance, Freight) 到岸价的全链路成本拆解，
包含运费、关税、汇率、融资、仓储等中间环节费用。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Cost structure
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CostLine:
    """单条成本明细"""
    label: str          # 显示名称
    value: float       # 金额（美元）
    unit: str          # 单位: USD/MT, USD/lb, pct, days
    notes: str = ""    # 说明

    @property
    def is_pct(self) -> bool:
        return self.unit == "pct"

    @property
    def is_per_lb(self) -> bool:
        return "lb" in self.unit.lower()


@dataclass
class LandedCostBreakdown:
    """到库成本完整明细"""
    # ── 原始价格 ──────────────────────────────────────────────
    cyp_price_usd_lb: float       # CYP 价格 (美元/磅)
    fx_rate_usd_cny: float        # 美元汇率 (USD/CNY)

    # ── 价格换算 ──────────────────────────────────────────────
    cyp_price_usd_mt: float       # CYP 折美元/吨
    cyp_price_cny_mt: float       # CYP 折人民币/吨
    cyp_price_cny_jin: float      # CYP 折人民币/斤

    # ── 运输与保险 ─────────────────────────────────────────────
    ocean_freight_usd_mt: float    # 海运费 (美元/吨)
    insurance_pct: float          # 保险费率 (货值%)
    insurance_usd_mt: float       # 保险费 (美元/吨)

    # ── 关税与税赋 ─────────────────────────────────────────────
    import_tariff_pct: float      # 关税税率
    tariff_usd_mt: float          # 关税 (美元/吨)
    vat_pct: float               # 增值税率
    vat_usd_mt: float            # 增值税 (美元/吨)
    other_taxes_usd_mt: float     # 其他税费 (检疫等)

    # ── 物流与港口 ─────────────────────────────────────────────
    port_charges_usd_mt: float    # 港口费用 (美元/吨)
    demurrage_usd: float          # 滞港费估算 (美元/票)
    domestic_logistics_usd_mt: float  # 境内物流 (美元/吨)

    # ── 融资成本 ──────────────────────────────────────────────
    financing_days: int           # 融资天数
    financing_rate_pct: float     # 年化融资利率 (%)
    financing_cost_usd_mt: float  # 融资利息 (美元/吨)

    # ── 损耗 ─────────────────────────────────────────────────
    moisture_loss_pct: float     # 含水量损耗率
    shrinkage_usd_mt: float       # 损耗折美元/吨

    # ── 汇总 ──────────────────────────────────────────────────
    subtotal_usd_mt: float       # 小计 (美元/吨，到岸前)
    total_cost_usd_mt: float     # 到库总成本 (美元/吨)
    total_cost_cny_mt: float    # 到库总成本 (人民币/吨)
    total_cost_cny_jin: float   # 到库总成本 (人民币/斤)

    # ── 风险敞口 ──────────────────────────────────────────────
    cyp_fraction_pct: float      # CYP 在总成本中占比
    hedge_ratio_pct: float       # 当前套保比率

    # ── 元数据 ─────────────────────────────────────────────────
    timestamp: datetime = field(default_factory=datetime.now)
    origin: str = "Brazil Santos"  # 产地
    contract_size_mt: float = 20.0  # 集装箱标准净重 (吨/TEU)


# ─────────────────────────────────────────────────────────────────────────────
# Calculator
# ─────────────────────────────────────────────────────────────────────────────

# 行业默认值（可配置）
DEFAULTS = {
    "ocean_freight_usd_mt": 85.0,       # 巴西→中国 海运费
    "insurance_pct": 0.003,              # 保险 0.3%
    "import_tariff_pct": 0.08,           # 咖啡生豆关税 8%
    "vat_pct": 0.13,                     # 增值税 13%
    "other_taxes_usd_mt": 8.0,           # 检疫+检验 8美元/吨
    "port_charges_usd_mt": 12.0,         # 港口THC+仓租 12美元/吨
    "demurrage_usd": 500.0,              # 滞港费估算 (美元/票)
    "domestic_logistics_usd_mt": 25.0,   # 港口→仓库 25美元/吨
    "moisture_loss_pct": 0.02,           # 含水量损耗 2%
    "financing_days": 60,                # 信用证融资天数
    "financing_rate_pct": 6.5,           # 年化利率 6.5% (SOFR+spread)
    "contract_size_mt": 20.0,             # 20尺集装箱净重约 20MT
}


class LandedCostCalculator:
    """
    咖啡生豆到库成本计算器。

    用法:
        calc = LandedCostCalculator()
        breakdown = calc.calculate(
            cyp_price_usd_lb=285.0,    # CYP价格 (美分/磅)
            fx_rate_usd_cny=7.25,      # 美元汇率
            hedge_ratio=0.75,           # 当前套保比率
        )
        print(calc.format_report(breakdown))
    """

    MT_PER_LB = 2204.62  # 1 MT = 2204.62 lbs

    def __init__(self, **overrides):
        """
        传入覆盖默认值。

        示例:
            LandedCostCalculator(ocean_freight_usd_mt=95.0, vat_pct=0.09)
        """
        self._d = {**DEFAULTS, **overrides}

    # ── 基础换算 ──────────────────────────────────────────────────────────────

    def _usd_lb_to_usd_mt(self, price_usd_lb: float) -> float:
        return price_usd_lb * self.MT_PER_LB

    def _usd_mt_to_cny_mt(self, price_usd_mt: float, fx: float) -> float:
        return price_usd_mt * fx

    # ── 计算核心 ──────────────────────────────────────────────────────────────

    def calculate(
        self,
        cyp_price_usd_lb: float,
        fx_rate_usd_cny: float,
        hedge_ratio: float = 0.0,
    ) -> LandedCostBreakdown:
        """
        计算完整到库成本。

        Args:
            cyp_price_usd_lb: CYP 价格（美元/磅）。
                              KC=F 行情软件通常以"美分/磅"报价（例：285.25），
                              此时等价于 2.8525 USD/lb，无需额外换算。
            fx_rate_usd_cny: 美元兑人民币汇率（USD/CNY）
            hedge_ratio: 当前套保比率（0.0~1.0）

        Returns:
            LandedCostBreakdown
        """
        d = self._d

        # ── 价格换算 ────────────────────────────────────────────
        # KC=F 以 美分/磅 报价（例：285.25），转换为 USD/lb
        price_usd_lb = cyp_price_usd_lb / 100.0 if cyp_price_usd_lb > 100 else cyp_price_usd_lb
        cyp_usd_mt = self._usd_lb_to_usd_mt(price_usd_lb)
        cyp_cny_mt = self._usd_mt_to_cny_mt(cyp_usd_mt, fx_rate_usd_cny)
        cyp_cny_jin = cyp_cny_mt / 2000.0  # 1 MT = 2000 斤

        # ── 运输与保险 ──────────────────────────────────────────
        freight = d["ocean_freight_usd_mt"]
        insurance_pct = d["insurance_pct"]
        insurance_usd_mt = cyp_usd_mt * insurance_pct

        # ── 关税与税赋 ──────────────────────────────────────────
        tariff_pct = d["import_tariff_pct"]
        tariff_usd_mt = cyp_usd_mt * tariff_pct

        vat_pct = d["vat_pct"]
        # 增值税基数 = CIF(货值+运费+保险) + 关税
        cif_usd_mt = cyp_usd_mt + freight + insurance_usd_mt
        vat_usd_mt = (cif_usd_mt + tariff_usd_mt) * vat_pct

        other_taxes = d["other_taxes_usd_mt"]

        # ── 物流 ───────────────────────────────────────────────
        port_charges = d["port_charges_usd_mt"]
        demurrage = d["demurrage_usd"] / d["contract_size_mt"]  # 分摊到每吨
        domestic = d["domestic_logistics_usd_mt"]

        # ── 融资 ───────────────────────────────────────────────
        financing_days = d["financing_days"]
        fin_rate = d["financing_rate_pct"]
        # 融资利息 = CIF × 年化利率 × 融资天数/360
        financing_cost_usd_mt = cif_usd_mt * (fin_rate / 100) * (financing_days / 360)

        # ── 损耗 ──────────────────────────────────────────────
        moisture_loss_pct = d["moisture_loss_pct"]
        shrinkage_usd_mt = cyp_usd_mt * moisture_loss_pct

        # ── 汇总 ───────────────────────────────────────────────
        # 到岸前小计 (CIF + 关税 + 增值税 + 港口 + 滞港分摊 + 境内物流 + 融资 + 损耗)
        subtotal = (
            cif_usd_mt
            + tariff_usd_mt
            + vat_usd_mt
            + other_taxes
            + port_charges
            + demurrage
            + domestic
            + financing_cost_usd_mt
            + shrinkage_usd_mt
        )

        total_usd_mt = subtotal
        total_cny_mt = total_usd_mt * fx_rate_usd_cny
        total_cny_jin = total_cny_mt / 2000.0

        # CYP 占比
        cyp_fraction = cyp_usd_mt / total_usd_mt if total_usd_mt else 0.0

        return LandedCostBreakdown(
            cyp_price_usd_lb=cyp_price_usd_lb,
            fx_rate_usd_cny=fx_rate_usd_cny,
            cyp_price_usd_mt=cyp_usd_mt,
            cyp_price_cny_mt=cyp_cny_mt,
            cyp_price_cny_jin=cyp_cny_jin,
            ocean_freight_usd_mt=freight,
            insurance_pct=insurance_pct,
            insurance_usd_mt=insurance_usd_mt,
            import_tariff_pct=tariff_pct,
            tariff_usd_mt=tariff_usd_mt,
            vat_pct=vat_pct,
            vat_usd_mt=vat_usd_mt,
            other_taxes_usd_mt=other_taxes,
            port_charges_usd_mt=port_charges,
            demurrage_usd=demurrage * d["contract_size_mt"],
            domestic_logistics_usd_mt=domestic,
            financing_days=financing_days,
            financing_rate_pct=fin_rate,
            financing_cost_usd_mt=financing_cost_usd_mt,
            moisture_loss_pct=moisture_loss_pct,
            shrinkage_usd_mt=shrinkage_usd_mt,
            subtotal_usd_mt=subtotal,
            total_cost_usd_mt=total_usd_mt,
            total_cost_cny_mt=total_cny_mt,
            total_cost_cny_jin=total_cny_jin,
            cyp_fraction_pct=cyp_fraction,
            hedge_ratio_pct=hedge_ratio,
            origin=d.get("origin", "Brazil Santos"),
            contract_size_mt=d["contract_size_mt"],
        )

    # ── 报告格式化 ────────────────────────────────────────────────────────────

    @staticmethod
    def format_report(b: LandedCostBreakdown) -> str:
        """生成到库成本报告（多行字符串）"""
        now = b.timestamp.strftime("%Y-%m-%d %H:%M")

        lines = [
            "=" * 62,
            f"  到库成本计算  {now}",
            "=" * 62,
            "",
            "[原始价格]",
            f"  CYP价格    {b.cyp_price_usd_lb:.4f} USD/lb",
            f"  汇率       {b.fx_rate_usd_cny:.4f} USD/CNY",
            "",
            "[价格换算]",
            f"  CYP       {b.cyp_price_usd_mt:>10.2f} USD/MT",
            f"           {b.cyp_price_cny_mt:>10.2f} CNY/MT",
            f"           {b.cyp_price_cny_jin:>10.4f} CNY/斤",
            "",
            "[运输与保险]",
            f"  海运费    {b.ocean_freight_usd_mt:>10.2f} USD/MT",
            f"  保险费    {b.insurance_usd_mt:>10.2f} USD/MT  (货值{b.insurance_pct:.1%})",
            "",
            "[关税与税赋]",
            f"  进口关税  {b.tariff_usd_mt:>10.2f} USD/MT  ({b.import_tariff_pct:.0%})",
            f"  增值税    {b.vat_usd_mt:>10.2f} USD/MT  ({b.vat_pct:.0%})",
            f"  检验/检疫  {b.other_taxes_usd_mt:>9.2f} USD/MT",
            "",
            "[物流与港口]",
            f"  港口费用  {b.port_charges_usd_mt:>10.2f} USD/MT",
            f"  滞港费    {b.demurrage_usd:>10.2f} USD/票",
            f"  境内物流  {b.domestic_logistics_usd_mt:>10.2f} USD/MT",
            "",
            "[融资与损耗]",
            f"  融资利息  {b.financing_cost_usd_mt:>10.2f} USD/MT  ({b.financing_days}d @{b.financing_rate_pct:.1f}%)",
            f"  含水损耗  {b.shrinkage_usd_mt:>10.2f} USD/MT  ({b.moisture_loss_pct:.0%})",
            "",
            f"{'─' * 62}",
            f"  CYP 在总成本中占比: {b.cyp_fraction_pct:.1%}  |  当前套保比率: {b.hedge_ratio_pct:.0%}",
            "",
            f"  {'到库小计':<12}  {b.subtotal_usd_mt:>10.2f} USD/MT",
            f"  {'═' * 1} 到库总成本  {b.total_cost_usd_mt:>10.2f} USD/MT",
            f"                 {b.total_cost_cny_mt:>10.2f} CNY/MT",
            f"                 {b.total_cost_cny_jin:>10.4f} CNY/斤",
            "=" * 62,
        ]
        return "\n".join(lines)

    @staticmethod
    def format_compact(b: LandedCostBreakdown) -> str:
        """紧凑单行格式（用于 get_report 嵌入）"""
        return (
            f"到库成本: {b.total_cost_cny_jin:.4f} CNY/斤  "
            f"({b.total_cost_usd_mt:.2f} USD/MT)  "
            f"[CYP {b.cyp_price_usd_lb:.2f} USD/lb × {b.fx_rate_usd_cny:.4f}]  "
            f"| 占比: CYP {b.cyp_fraction_pct:.0%}  运费+税 {1-b.cyp_fraction_pct:.0%}"
        )
