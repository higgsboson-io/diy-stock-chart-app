# app_stock_chart.py
import json
import logging
from math import isfinite
from pathlib import Path
from typing import Dict
import pandas as pd
from nicegui import background_tasks, ui, run

from stock_util import (
    fetch_stock_data_with_cache,
    get_interval_settings,
    resample_data,
    calculate_indicators,
    cleanup_old_cache,
)
from watchlist import WatchListManager, WatchListDialogs
from chart_plotly import PlotlyChartBuilder
from chart_interactions import ChartInteractions
from info_panel import InfoPanel

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = APP_DIR / "conf" / "settings.json"


class StockChartSession:
    """Per-client state and UI controller for the NiceGUI + Plotly Stock Chart app."""

    TIME_WINDOWS = ["20Y", "10Y", "5Y", "3Y", "2Y", "1Y", "YTD", "6M", "3M", "1M", "1WK", "1D"]

    MA_OPTIONS = [
        ("show_ma5", "MA 5 (Cyan)"),
        ("show_ma20", "MA 20 (Green)"),
        ("show_ma50", "MA 50 (Orange)"),
        ("show_ma60", "MA 60 (Blue)"),
        ("show_ma100", "MA 100 (Purple)"),
        ("show_ma120", "MA 120 (Magenta)"),
        ("show_ma200", "MA 200 (Red)"),
        ("show_ma250", "MA 250 (Brown)"),
    ]

    def __init__(self):
        # Data State
        self.current_ticker: str = "SPY"
        self.company_name: str = "SPY"
        self.raw_df: pd.DataFrame = pd.DataFrame()
        self.history_df: pd.DataFrame = pd.DataFrame()
        self.current_data_interval: str = "1d"
        self.current_resample_rule = None
        self.previous_close: float = 0.0
        self.current_price: float = 0.0
        self.stock_info: dict = {}
        self.is_loading: bool = False
        self._fetch_request_id: int = 0
        self.view_start = None  # None follows the latest fixed-width window.

        # Control State (defaults, overridden by settings.json)
        self.time_window: str = "1Y"
        self.font_size: int = 12
        self.dark_mode: bool = True
        self.auto_refresh: bool = True

        self.show_ma5: bool = True
        self.show_ma20: bool = True
        self.show_ma50: bool = True
        self.show_ma60: bool = False
        self.show_ma100: bool = True
        self.show_ma120: bool = False
        self.show_ma200: bool = True
        self.show_ma250: bool = True

        self.show_volume: bool = True
        self.show_macd: bool = True
        self.show_rsi: bool = True
        self.show_bbands: bool = True
        self.show_vp: bool = True
        self.vp_mode: str = "200 Bins"
        self.vp_position: str = "Right"
        self.chart_type: str = "Candle"
        self.show_prepost: bool = False
        self.show_legend: bool = True
        self.show_info: bool = False
        self.log_scale: bool = False

        # Services
        self.watchlist_manager = WatchListManager()
        self.watchlist_dialogs = WatchListDialogs(self)
        self.chart_builder = PlotlyChartBuilder(self)
        self.info_panel = InfoPanel(self)

        # UI Refs
        self.dark_controller = None
        self.ticker_input = None
        self.star_btn = None
        self.watchlist_menu = None
        self.window_buttons: Dict[str, ui.button] = {}
        self.prepost_checkbox = None
        self.info_checkbox = None
        self.status_label = None
        self.plotly_widget = None

        self.load_settings()

    def load_settings(self):
        try:
            if not SETTINGS_PATH.exists():
                return
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                s = json.load(f)

            self.show_ma5 = s.get("ma5", True)
            self.show_ma20 = s.get("ma20", True)
            self.show_ma50 = s.get("ma50", True)
            self.show_ma60 = s.get("ma60", False)
            self.show_ma100 = s.get("ma100", True)
            self.show_ma120 = s.get("ma120", False)
            self.show_ma200 = s.get("ma200", True)
            self.show_ma250 = s.get("ma250", True)

            self.show_volume = s.get("volume", True)
            self.show_macd = s.get("macd", True)
            self.show_rsi = s.get("rsi", True)
            self.show_bbands = s.get("bbands", True)
            self.show_vp = s.get("vp", True)
            self.show_legend = s.get("legend", True)
            self.show_info = s.get("show_info", False)
            self.log_scale = s.get("log_scale", False)
            self.show_prepost = s.get("show_prepost", False)
            self.auto_refresh = s.get("auto_refresh", True)
            self.dark_mode = s.get("dark_mode", True)

            self.time_window = s.get("time_window", "1Y")
            self.vp_mode = s.get("vp_mode", "200 Bins")
            self.vp_position = s.get("vp_pos", "Right")
            self.chart_type = s.get("chart_type", "Candle")
            self.font_size = max(8, min(24, int(s.get("font_size", 12))))
        except Exception as e:
            logger.error(f"Failed to load settings: {e}")

    def save_settings(self):
        try:
            settings = {
                "ma5": self.show_ma5,
                "ma20": self.show_ma20,
                "ma50": self.show_ma50,
                "ma60": self.show_ma60,
                "ma100": self.show_ma100,
                "ma120": self.show_ma120,
                "ma200": self.show_ma200,
                "ma250": self.show_ma250,
                "volume": self.show_volume,
                "macd": self.show_macd,
                "rsi": self.show_rsi,
                "bbands": self.show_bbands,
                "vp": self.show_vp,
                "legend": self.show_legend,
                "show_info": self.show_info,
                "log_scale": self.log_scale,
                "show_prepost": self.show_prepost,
                "auto_refresh": self.auto_refresh,
                "dark_mode": self.dark_mode,
                "time_window": self.time_window,
                "vp_mode": self.vp_mode,
                "vp_pos": self.vp_position,
                "chart_type": self.chart_type,
                "font_size": self.font_size,
            }
            SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to save settings: {e}")

    def build_ui(self):
        self.dark_controller = ui.dark_mode(self.dark_mode)

        # Top Navigation & Toolbar
        with ui.header().classes('px-3 py-1.5 shadow-sm border-b').style('background-color: var(--q-dark-page)' if self.dark_mode else ''):
            with ui.column().classes('w-full gap-1.5'):
                # ROW 1: Ticker, Watchlist, Time Windows, Font Size, Theme
                with ui.row().classes('w-full items-center justify-between flex-wrap gap-2'):
                    with ui.row().classes('items-center gap-1.5'):
                        ui.icon('candlestick_chart', size='sm', color='primary')
                        ui.label('DIY Stock Chart').classes('font-bold text-sm mr-2')

                        self.ticker_input = ui.input(
                            value=self.current_ticker,
                            placeholder='Ticker'
                        ).classes('w-28').props('dense outlined input-class="uppercase font-bold"')
                        self.ticker_input.on('keydown.enter', lambda: self.trigger_fetch())

                        ui.button('Go', on_click=lambda: self.trigger_fetch(), color='primary').props('dense unelevated')

                        # Star Button (Watchlist toggle)
                        self.star_btn = ui.button(
                            icon='star_border',
                            on_click=self.on_star_click
                        ).props('flat round dense')
                        self.star_btn.tooltip('Add / Remove from Watch List')

                        # Watch List Dropdown Menu
                        with ui.button('Watch List', icon='bookmarks').props('dense outline'):
                            self.watchlist_menu = ui.menu()
                            self.refresh_watchlist_menu()

                        fullscreen = ui.fullscreen()
                        ui.button(icon='fullscreen', on_click=fullscreen.toggle).props(
                            'dense outline aria-label="Toggle fullscreen"'
                        ).bind_icon_from(
                            fullscreen, 'value',
                            backward=lambda active: 'fullscreen_exit' if active else 'fullscreen',
                        ).tooltip('Toggle fullscreen (Esc to exit)')

                    # Time Window Segmented Buttons
                    with ui.row().classes('items-center gap-0.5 flex-wrap'):
                        for w in self.TIME_WINDOWS:
                            btn = ui.button(
                                w,
                                on_click=lambda win=w: self.on_window_change(win)
                            ).classes('px-2 min-w-0 text-xs')
                            self.window_buttons[w] = btn
                        self._sync_window_buttons()

                    # Right Controls: Font Size + Dark Mode
                    with ui.row().classes('items-center gap-2'):
                        self.status_label = ui.label('').classes('text-xs opacity-70')
                        ui.number(
                            label='Font',
                            value=self.font_size,
                            min=8,
                            max=22,
                            step=1,
                            on_change=self.on_font_change
                        ).classes('w-20').props('dense outlined')

                        ui.button(
                            icon='dark_mode' if not self.dark_mode else 'light_mode',
                            on_click=self.toggle_theme
                        ).props('flat round dense').tooltip('Toggle Dark / Light Theme')

                # ROW 2: Technical Indicators, Volume Profile, Chart Type, Panels
                with ui.row().classes('w-full items-center justify-between flex-wrap gap-2 text-xs'):
                    with ui.row().classes('items-center gap-2 flex-wrap'):
                        # Moving Averages Popover Menu
                        with ui.button('Moving Avg', icon='show_chart').props('dense outline size=sm'):
                            with ui.menu().props('persistent') as ma_menu:
                                with ui.column().classes('p-2 gap-1 min-w-44'):
                                    for attr, label in self.MA_OPTIONS:
                                        ui.checkbox(
                                            label,
                                            value=getattr(self, attr),
                                            on_change=lambda e, a=attr: self.on_toggle_setting(a, e.value)
                                        ).props('dense')
                                    ui.separator()
                                    ui.button('Close', on_click=ma_menu.close).props('flat dense size=sm').classes('w-full')

                        ui.checkbox('Volume', value=self.show_volume,
                                    on_change=lambda e: self.on_toggle_setting('show_volume', e.value)).props('dense')
                        ui.checkbox('MACD', value=self.show_macd,
                                    on_change=lambda e: self.on_toggle_setting('show_macd', e.value)).props('dense')
                        ui.checkbox('RSI', value=self.show_rsi,
                                    on_change=lambda e: self.on_toggle_setting('show_rsi', e.value)).props('dense')
                        ui.checkbox('BBands', value=self.show_bbands,
                                    on_change=lambda e: self.on_toggle_setting('show_bbands', e.value)).props('dense')

                        ui.separator().props('vertical')

                        ui.checkbox('Vol Profile', value=self.show_vp,
                                    on_change=lambda e: self.on_toggle_setting('show_vp', e.value)).props('dense')
                        ui.select(
                            options=['Left', 'Right'],
                            value=self.vp_position,
                            label='Pos',
                            on_change=lambda e: self.on_toggle_setting('vp_position', e.value)
                        ).classes('w-20').props('dense outlined options-dense')
                        ui.select(
                            options=['100 Bins', '200 Bins', '400 Bins'],
                            value=self.vp_mode,
                            label='Res',
                            on_change=lambda e: self.on_toggle_setting('vp_mode', e.value)
                        ).classes('w-28').props('dense outlined options-dense')

                        ui.select(
                            options=['Candle', 'Line'],
                            value=self.chart_type,
                            label='Type',
                            on_change=lambda e: self.on_toggle_setting('chart_type', e.value)
                        ).classes('w-24').props('dense outlined options-dense')

                    with ui.row().classes('items-center gap-2 flex-wrap'):
                        self.prepost_checkbox = ui.checkbox(
                            'Pre/Post',
                            value=self.show_prepost,
                            on_change=self.on_prepost_change
                        ).props('dense')

                        self.info_checkbox = ui.checkbox(
                            'Show Info',
                            value=self.show_info,
                            on_change=self.on_info_toggle
                        ).props('dense')

                        ui.checkbox(
                            'Log',
                            value=self.log_scale,
                            on_change=lambda e: self.on_toggle_setting('log_scale', e.value)
                        ).props('dense').tooltip('Use a logarithmic price scale; unchecked uses linear prices')

                        ui.checkbox(
                            'Legend',
                            value=self.show_legend,
                            on_change=lambda e: self.on_toggle_setting('show_legend', e.value)
                        ).props('dense')

                        ui.checkbox(
                            'Auto 1D',
                            value=self.auto_refresh,
                            on_change=lambda e: self.on_toggle_setting('auto_refresh', e.value)
                        ).props('dense').tooltip(
                            'Refresh the latest 1D chart every 60 seconds. '
                            'Paused in other time windows and while browsing older history.'
                        )

        # Main Workspace
        with ui.column().classes('w-full px-2 pt-1 pb-2 gap-1'):
            # Collapsible Stock/ETF Info Panel
            self.info_panel.build()

            # Main Interactive Plotly Chart
            options = self.chart_builder.build_options()
            with ui.element('div').classes('stock-chart-workspace relative w-full').style(
                'height: calc(100vh - 118px); min-height: 540px;'
            ):
                self.plotly_widget = ui.plotly(options).classes('w-full h-full')
                ChartInteractions(dark=self.dark_mode, on_history_change=self.on_history_change)

        # Background 60s Timer for 1D Auto-Refresh
        ui.timer(60.0, self._auto_refresh_tick)

        # Initial Data Load
        ui.timer(0.1, lambda: self.trigger_fetch(), once=True)

    def _sync_window_buttons(self):
        for w, btn in self.window_buttons.items():
            if w == self.time_window:
                btn.props('unelevated color=primary dense')
            else:
                btn.props('flat dense')

    def toggle_theme(self):
        self.dark_mode = not self.dark_mode
        if self.dark_controller:
            self.dark_controller.set_value(self.dark_mode)
        self.save_settings()
        self.update_chart()

    def on_font_change(self, e):
        if e.value is not None:
            self.font_size = max(8, min(24, int(e.value)))
            self.save_settings()
            self.update_chart()

    def on_toggle_setting(self, attr: str, value):
        setattr(self, attr, value)
        self.save_settings()
        self.update_chart()

    def on_prepost_change(self, e):
        self.show_prepost = bool(e.value)
        self.view_start = None
        self.save_settings()
        self._apply_resampling()

    def on_info_toggle(self, e):
        self.show_info = bool(e.value)
        self.save_settings()
        self.info_panel.toggle()

    def on_window_change(self, window: str):
        self.time_window = window
        self.view_start = None
        self._sync_window_buttons()
        self.save_settings()

        target_interval, resample_rule = get_interval_settings(window)
        self.current_resample_rule = resample_rule

        if target_interval != self.current_data_interval or self.raw_df.empty or self.is_loading:
            self.trigger_fetch(interval=target_interval)
        else:
            self._apply_resampling()

    def trigger_fetch(self, interval=None, silent: bool = False):
        ticker = (self.ticker_input.value if self.ticker_input else self.current_ticker) or ''
        ticker = ticker.upper().strip()
        if not ticker:
            return
        self.view_start = None
        self._fetch_request_id += 1
        self.is_loading = True
        background_tasks.create(self.fetch_data(
            interval=interval, silent=silent, ticker=ticker, request_id=self._fetch_request_id
        ))

    async def fetch_data(self, interval=None, silent: bool = False, *, ticker=None, request_id=None):
        if ticker is None:
            ticker = (self.ticker_input.value if self.ticker_input else self.current_ticker) or ''
        ticker = ticker.upper().strip()
        if not ticker:
            return

        if request_id is None:
            self._fetch_request_id += 1
            request_id = self._fetch_request_id
        elif request_id != self._fetch_request_id:
            return

        window = self.time_window
        target_interval, rule = get_interval_settings(window)
        interval = interval or target_interval

        self.is_loading = True
        if not silent and self.status_label:
            self.status_label.text = f"Loading {ticker}..."

        try:
            df, company_name, actual_interval, prev_close, curr_price, info_dict = await run.io_bound(
                fetch_stock_data_with_cache, ticker, interval
            )

            # A slower request must not replace a newer ticker or time-window selection.
            if request_id != self._fetch_request_id or window != self.time_window:
                return

            if df is not None and not df.empty:
                if ticker != self.current_ticker or actual_interval != self.current_data_interval:
                    self.view_start = None
                self.current_ticker = ticker
                self.raw_df = df
                self.current_data_interval = actual_interval
                self.current_resample_rule = rule
                self.company_name = company_name
                self.previous_close = prev_close
                self.current_price = curr_price
                self.stock_info = info_dict or {}

                # Inject Dynamic Day Stats
                self.stock_info['currentPrice'] = curr_price
                self.stock_info['regularMarketPrice'] = curr_price
                self.stock_info['previousClose'] = prev_close

                try:
                    last_dt = df.index[-1]
                    if not self.current_data_interval.lower().endswith(('m', 'h')):
                        row = df.iloc[-1]
                        self.stock_info['dayHigh'] = row.get('high')
                        self.stock_info['dayLow'] = row.get('low')
                        self.stock_info['volume'] = int(row.get('volume', 0))
                        self.stock_info['open'] = row.get('open')
                    else:
                        last_day_acc = last_dt.normalize()
                        today_data = df[df.index >= last_day_acc]
                        if not today_data.empty:
                            self.stock_info['dayHigh'] = today_data['high'].max()
                            self.stock_info['dayLow'] = today_data['low'].min()
                            self.stock_info['volume'] = int(today_data['volume'].sum())
                            self.stock_info['open'] = today_data.iloc[0]['open']
                except Exception as e:
                    logger.error(f"Failed to compute dynamic stats: {e}")

                self.update_star_state()

                # Disable Pre/Post for 24/7 Global Assets
                q_type = self.stock_info.get('quoteType', '').upper()
                if q_type in ['CRYPTOCURRENCY', 'CURRENCY', 'FUTURE']:
                    self.show_prepost = False
                    if self.prepost_checkbox:
                        self.prepost_checkbox.value = False
                        self.prepost_checkbox.disable()
                else:
                    if self.prepost_checkbox:
                        self.prepost_checkbox.enable()

                self._apply_resampling()
                self.info_panel.update_content()
            else:
                if not silent:
                    with self.ticker_input.client:
                        ui.notify(f"No data found for {ticker}", type='warning')
        except Exception as e:
            logger.error(f"Fetch error: {e}")
            if not silent and request_id == self._fetch_request_id:
                with self.ticker_input.client:
                    ui.notify(f"Error loading {ticker}: {e}", type='negative')
        finally:
            if request_id == self._fetch_request_id:
                self.is_loading = False
                if self.status_label:
                    self.status_label.text = ""

    def _apply_resampling(self):
        if self.raw_df.empty:
            return

        df = resample_data(self.raw_df, self.current_resample_rule)
        q_type = self.stock_info.get('quoteType', '').upper()
        is_global_asset = q_type in ['CRYPTOCURRENCY', 'CURRENCY', 'FUTURE']

        # Retain earlier sessions for history navigation and indicator warmup.
        # Equities: filter regular market hours when Pre/Post is unchecked.
        if self.current_data_interval == '1m' and not self.show_prepost and not is_global_asset:
            if not df.empty and isinstance(df.index, pd.DatetimeIndex):
                try:
                    df = df.between_time('09:30', '16:00').copy()
                except Exception as e:
                    logger.warning(f"Failed to filter market hours: {e}")

        if df.empty:
            self.history_df = df
            self.update_chart()
            return

        # Indicators use observed bars; the chart fills visual gaps after calculation.
        self.history_df = calculate_indicators(df)
        self.update_chart()

    def update_chart(self):
        if self.plotly_widget is None:
            return
        self.plotly_widget.update_figure(self.chart_builder.build_options())

    def on_history_change(self, event):
        if self.plotly_widget is None or self.is_loading or not isinstance(event.args, dict):
            return
        options = self.plotly_widget.figure
        navigation = options.get('layout', {}).get('meta', {}).get('stock_chart', {}).get('navigation')
        if not navigation or event.args.get('context') != navigation['context']:
            return
        try:
            requested = float(event.args['start'])
            if not isfinite(requested):
                return
            latest = navigation['total'] - navigation['span']
            start = max(0, min(int(requested), latest))
        except (KeyError, TypeError, ValueError, OverflowError):
            return
        selected = None if start == latest else start
        if selected != self.view_start:
            self.view_start = selected
            self.update_chart()

    async def _auto_refresh_tick(self):
        if (self.auto_refresh and self.current_ticker and self.time_window == "1D"
                and not self.is_loading and self.view_start is None):
            logger.info(f"Auto-refreshing {self.current_ticker} (1D)...")
            await self.fetch_data(silent=True, ticker=self.current_ticker)

    # Watch List Menu & Star Helpers
    def refresh_watchlist_menu(self):
        if self.watchlist_menu is None:
            return
        self.watchlist_menu.clear()
        groups = self.watchlist_manager.get_groups()
        with self.watchlist_menu:
            if not groups:
                ui.menu_item('(Empty)').props('disable')
            else:
                for group in groups:
                    with ui.menu_item(group, auto_close=False):
                        with ui.menu().props('anchor="top end" self="top start"'):
                            items = self.watchlist_manager.get_items(group)
                            if not items:
                                ui.menu_item('(No tickers)').props('disable')
                            for item in items:
                                tkr = item['ticker']
                                lbl = f"{tkr} - {item['name']}"
                                ui.menu_item(lbl, on_click=lambda t=tkr: self.load_ticker_from_watchlist(t))
            ui.separator()
            ui.menu_item('Manage Watch Lists...', on_click=self.watchlist_dialogs.open_manage_dialog)

    def load_ticker_from_watchlist(self, ticker: str):
        if self.ticker_input:
            self.ticker_input.value = ticker
        self.trigger_fetch()

    def update_star_state(self):
        if self.star_btn is None:
            return
        watched = bool(self.current_ticker) and self.watchlist_manager.is_watched(self.current_ticker)
        if watched:
            self.star_btn.props('icon=star color=amber')
        else:
            self.star_btn.props('icon=star_border color=grey')

    def on_star_click(self):
        ticker = self.current_ticker
        if not ticker:
            return
        if self.watchlist_manager.is_watched(ticker):
            if self.watchlist_manager.remove_ticker_entirely(ticker):
                self.refresh_watchlist_menu()
                self.update_star_state()
                ui.notify(f'Removed {ticker} from all Watch Lists', type='info')
        else:
            self.watchlist_dialogs.open_add_dialog()


@ui.page('/')
def index_page():
    session = StockChartSession()
    session.build_ui()


if __name__ in {"__main__", "__mp_main__"}:
    cleanup_old_cache()
    ui.run(
        title="DIY - Interactive Stock Chart",
        reload=False,
        port=8080,
        show=True,
    )
