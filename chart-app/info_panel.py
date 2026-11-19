# info_panel.py
from datetime import datetime
from typing import Any, List, Optional, Tuple
from nicegui import ui


class InfoPanel:
    """Collapsible/floating Stock & ETF fundamental and intraday stats card."""

    def __init__(self, app):
        self.app = app
        self.container = None

    def build(self):
        """Builds the NiceGUI container inside the main workspace."""
        self.container = ui.card().classes(
            'w-full max-w-4xl mx-auto my-2 p-4 shadow-md border'
        )
        self.container.set_visibility(self.app.show_info)
        self.update_content()

    def toggle(self):
        if self.container is None:
            return
        self.container.set_visibility(self.app.show_info)
        if self.app.show_info:
            self.update_content()

    def close_info_panel(self):
        self.app.show_info = False
        if hasattr(self.app, 'info_checkbox') and self.app.info_checkbox is not None:
            self.app.info_checkbox.value = False
        self.toggle()
        self.app.save_settings()

    def _fmt(self, num: Any, is_percent: bool = False, trim_large: bool = False) -> str:
        if num is None or num == '' or num == 'None':
            return "-"
        try:
            val = float(num)
            if is_percent:
                return f"{val * 100:.2f}%" if abs(val) < 1.0 else f"{val:.2f}%"

            abs_val = abs(val)
            if abs_val >= 1e12:
                return f"{val / 1e12:.2f}T"
            if abs_val >= 1e9:
                return f"{val / 1e9:.2f}B"
            if abs_val >= 1e6:
                return f"{val / 1e6:.2f}M"
            if trim_large and abs_val >= 10000:
                return f"{val:,.0f}"
            return f"{val:,.2f}"
        except Exception:
            return str(num)

    def _safe_float(self, v: Any) -> Optional[float]:
        if v is None or v == '':
            return None
        try:
            return float(str(v).replace(';', '').replace(',', ''))
        except Exception:
            return None

    def _safe_timestamp(self, v: Any) -> Optional[int]:
        if v is None or v == '' or v == '-':
            return None
        try:
            return int(float(str(v).replace(';', '')))
        except Exception:
            return None

    def update_content(self):
        if self.container is None:
            return
        self.container.clear()

        if not self.app.show_info:
            return

        with self.container:
            name = getattr(self.app, 'company_name', '') or self.app.current_ticker or 'Stock Info'
            with ui.row().classes('w-full items-center justify-between mb-1'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('analytics', color='primary')
                    ui.label(f"{name} ({self.app.current_ticker})").classes('text-base font-bold')
                    q_type = self.app.stock_info.get('quoteType', '')
                    if q_type:
                        ui.badge(q_type, color='primary').props('outline')
                ui.button(icon='close', on_click=self.close_info_panel).props('flat round dense')

            if not self.app.stock_info:
                ui.label('Loading fundamental info...').classes('text-sm italic opacity-70 py-2')
                return

            i = self.app.stock_info
            q_type = i.get('quoteType', '').upper()

            # Session / Day Summary Strip
            day_strip = [
                ("Prev Close", self._fmt(i.get('previousClose'))),
                ("Open", self._fmt(i.get('open'))),
                ("Day High", self._fmt(i.get('dayHigh'))),
                ("Day Low", self._fmt(i.get('dayLow'))),
                ("Volume", self._fmt(i.get('volume'), trim_large=True)),
            ]
            with ui.row().classes('w-full justify-between bg-slate-500/10 rounded px-3 py-1.5 my-1 text-xs'):
                for lbl, val in day_strip:
                    with ui.column().classes('gap-0'):
                        ui.label(lbl).classes('opacity-70')
                        ui.label(val).classes('font-bold')

            # Prepare Key Statistics (Left Column)
            earn_ts = self._safe_timestamp(i.get('earningsTimestamp') or i.get('earningsTimestampStart'))
            earn_str = "-"
            if earn_ts:
                try:
                    earn_str = datetime.fromtimestamp(earn_ts).strftime('%Y-%m-%d')
                except Exception:
                    pass

            div_str = "-"
            div_rate = self._safe_float(i.get('dividendRate') or i.get('trailingAnnualDividendRate'))
            price = self._safe_float(i.get('currentPrice') or i.get('regularMarketPrice'))
            etf_yield = self._safe_float(i.get('yield'))

            if q_type == 'ETF' and etf_yield is not None:
                rate_str = f"{div_rate}" if div_rate else ""
                div_str = f"{rate_str} ({etf_yield * 100:.2f}%)" if rate_str else f"{etf_yield * 100:.2f}%"
            elif div_rate and price and price > 0:
                calc_yield = (div_rate / price) * 100
                div_str = f"{div_rate} ({calc_yield:.2f}%)"
            else:
                raw_yield = self._safe_float(i.get('dividendYield'))
                if raw_yield:
                    div_str = f"{raw_yield:.2f}%" if raw_yield > 0.5 else f"{self._fmt(raw_yield, True)}"

            ex_div_ts = self._safe_timestamp(i.get('exDividendDate'))
            ex_div_str = datetime.fromtimestamp(ex_div_ts).strftime('%Y-%m-%d') if ex_div_ts else "-"

            beta_key = 'beta3Year' if q_type == 'ETF' else 'beta'
            beta_val = i.get(beta_key) or i.get('beta')

            left_data: List[Tuple[str, str]] = [
                ("52W Range", f"{self._fmt(i.get('fiftyTwoWeekLow'), trim_large=True)} - {self._fmt(i.get('fiftyTwoWeekHigh'), trim_large=True)}"),
                ("Avg Vol", self._fmt(i.get('averageVolume'))),
                ("Beta", self._fmt(beta_val)),
                ("Fwd Div & Yield", div_str),
                ("Ex-Div Date", ex_div_str),
                ("Target Est", self._fmt(i.get('targetMeanPrice'))),
                ("Earnings Date", earn_str),
            ]

            if q_type == 'ETF':
                right_title = "ETF Profile"
                exp_ratio = i.get('netExpenseRatio') or i.get('annualReportExpenseRatio') or i.get('expenseRatio')
                exp_str = f"{exp_ratio}%" if exp_ratio not in (None, '') else "-"
                right_data = [
                    ("Net Assets", self._fmt(i.get('totalAssets'))),
                    ("NAV", self._fmt(i.get('navPrice'))),
                    ("Expense Ratio", exp_str),
                    ("PE (TTM)", self._fmt(i.get('trailingPE'))),
                    ("Beta (3Y)", self._fmt(beta_val)),
                ]
            else:
                right_title = "Valuation & Earnings"
                right_data = [
                    ("Market Cap", self._fmt(i.get('marketCap'))),
                    ("Trailing PE", self._fmt(i.get('trailingPE'))),
                    ("Forward PE", self._fmt(i.get('forwardPE'))),
                    ("PEG Ratio", self._fmt(i.get('pegRatio') or i.get('trailingPegRatio'))),
                    ("Price / Book", self._fmt(i.get('priceToBook'))),
                    ("Price / Sales", self._fmt(i.get('priceToSalesTrailing12Months'))),
                    ("EV / EBITDA", self._fmt(i.get('enterpriseToEbitda'))),
                ]

            with ui.grid(columns=2).classes('w-full gap-6 mt-2'):
                self._render_section("Key Statistics", left_data)
                self._render_section(right_title, right_data)

    def _render_section(self, title: str, items: List[Tuple[str, str]]):
        with ui.column().classes('w-full gap-1'):
            ui.label(title).classes('text-xs font-bold uppercase tracking-wider opacity-80')
            ui.separator()
            for label, val in items:
                with ui.row().classes('w-full justify-between text-xs py-0.5 border-b border-slate-500/10'):
                    ui.label(label).classes('opacity-75')
                    ui.label(val).classes('font-semibold')
