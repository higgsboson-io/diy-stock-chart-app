# chart_plotly.py
import calendar
from datetime import timedelta
from typing import List, Tuple
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pytz

EASTERN = pytz.timezone("America/New_York")


class PlotlyChartBuilder:
    """
    Builds an interactive Plotly Figure with full parity to the original Matplotlib plotter:
    - Gapless integer X-axis with Backtrack Collision Resolution date labels
    - Candlestick or Line main price series
    - 8 configurable SMAs (MA5..MA250) + Bollinger Bands
    - Bottom-25% Volume overlay on secondary Y-axis (y9)
    - Left- or Right-aligned horizontal Volume Profile on secondary X-axis (x9)
    - Synchronized MACD and RSI indicator sub-panes
    - 1D fixed trading-session grid + Pre/Post market shading
    - Browser-side synchronized crosshairs and a movable OHLC/indicator readout
    """

    def __init__(self, app):
        self.app = app

    def build_options(self) -> dict:
        """Keep image export, with horizontal panning as the only chart gesture."""
        options = self.build_figure().to_plotly_json()
        options['config'] = dict(
            modeBarButtons=[['toImage']],
            displaylogo=False,
            scrollZoom=False,
            doubleClick=False,
            showAxisDragHandles=False,
            showAxisRangeEntryBoxes=False,
            responsive=True,
        )
        return options

    @staticmethod
    def _fit_range(columns, include_zero=False, logarithmic=False):
        values = pd.concat([pd.Series(column, dtype=float) for column in columns], ignore_index=True)
        values = values[np.isfinite(values)]
        if logarithmic:
            # Plotly log-axis ranges use base-10 exponents, while traces retain prices.
            values = np.log10(values[values > 0])
        if values.empty:
            return [0.0, 1.0]
        low, high = float(values.min()), float(values.max())
        if include_zero:
            low, high = min(low, 0.0), max(high, 0.0)
        padding = (high - low) * 0.06 if high != low else max(abs(high) * 0.01, 0.01)
        return [low - padding, high + padding]

    def _intraday_grid(self, df, is_global):
        """Retain earlier sessions so a fixed-width 1D view can pan into them."""
        if is_global:
            start_time, end_time = '00:00:00', '23:59:59'
        elif self.app.show_prepost:
            start_time, end_time = '04:00:00', '20:00:00'
        else:
            start_time, end_time = '09:30:00', '16:00:00'
        sessions = []
        for day in df.index.normalize().unique():
            start = pd.Timestamp(f'{day.date()} {start_time}').tz_localize(EASTERN)
            end = pd.Timestamp(f'{day.date()} {end_time}').tz_localize(EASTERN)
            session = df.reindex(pd.date_range(start=start, end=end, freq='1min'))
            first_trade, last_trade = session['close'].first_valid_index(), session['close'].last_valid_index()
            if first_trade is not None and last_trade is not None:
                selected = slice(first_trade, last_trade)
                closes = session.loc[selected, 'close'].ffill()
                session.loc[selected, 'close'] = closes
                for column in ('open', 'high', 'low', 'adj close'):
                    if column in session.columns:
                        session.loc[selected, column] = session.loc[selected, column].fillna(closes)
                session.loc[selected, 'volume'] = session.loc[selected, 'volume'].fillna(0)
            sessions.append(session)
        return pd.concat(sessions) if sessions else df

    @staticmethod
    def _raw_view_bounds(df, start, stop, raw_df):
        def period_start(row):
            value = df['period_start'].iloc[row] if 'period_start' in df.columns else None
            return pd.Timestamp(value) if pd.notna(value) else df.index[row]
        lower = period_start(start)
        upper = period_start(stop) - pd.Timedelta(nanoseconds=1) if stop < len(df) else raw_df.index.max()
        return lower, upper

    def _filter_data_by_window(self, df: pd.DataFrame, window: str) -> pd.DataFrame:
        end_date = df.index.max()
        if window == "20Y":
            start_date = end_date - pd.DateOffset(years=20)
        elif window == "10Y":
            start_date = end_date - pd.DateOffset(years=10)
        elif window == "5Y":
            start_date = end_date - pd.DateOffset(years=5)
        elif window == "3Y":
            start_date = end_date - pd.DateOffset(years=3)
        elif window == "2Y":
            start_date = end_date - pd.DateOffset(years=2)
        elif window == "1Y":
            start_date = end_date - pd.DateOffset(years=1)
        elif window == "YTD":
            start_date = pd.Timestamp(year=end_date.year, month=1, day=1)
            if end_date.tz is not None:
                start_date = start_date.tz_localize(end_date.tz)
        elif window == "6M":
            start_date = end_date - pd.DateOffset(months=6)
        elif window == "3M":
            start_date = end_date - pd.DateOffset(months=3)
        elif window == "1M":
            start_date = end_date - pd.DateOffset(months=1)
        elif window == "1WK":
            start_date = end_date - pd.DateOffset(weeks=1)
        elif window == "1D":
            start_date = end_date.normalize()
        else:
            start_date = df.index.min()

        return df[df.index >= pd.Timestamp(start_date)].copy()

    def _compute_date_ticks(self, df: pd.DataFrame, window: str) -> Tuple[List[int], List[str]]:
        """
        Port of the Backtrack Collision Resolution axis labeler.
        Returns (major_indices, major_labels).
        """
        major_indices: List[int] = []
        major_labels: List[str] = []

        dates = df.index
        years = dates.year
        months = dates.month
        days = dates.day

        is_long_term = window in ["20Y", "10Y", "5Y", "3Y", "2Y"]
        is_hourly = (self.app.current_data_interval == '1h') or (window == "1WK")

        prev_year = -1
        prev_month = -1
        prev_day = -1
        prev_hour = -1

        for i, (date, y, m, d) in enumerate(zip(dates, years, months, days)):
            # 1D MODE
            if window == "1D":
                curr_hour = date.hour
                if curr_hour != prev_hour:
                    major_indices.append(i)
                    major_labels.append(date.strftime("%H:%M"))
                    prev_hour = curr_hour
                continue

            # SMART MODE: 3M to 5Y
            w_norm = window.strip().upper()
            if w_norm in ["3M", "6M", "1Y", "1YTD", "YTD", "2Y", "3Y", "5Y"]:
                is_dense = w_norm in ["3M", "6M"]
                min_collision_gap = 6 if is_dense else 10
                min_density_gap = 5

                if m != prev_month:
                    should_show = True
                    is_year_change = (y != prev_year) or (len(major_indices) == 0)

                    if not is_dense and not is_year_change:
                        if w_norm == "3Y" and m not in [1, 4, 7, 10]:
                            should_show = False
                        elif w_norm == "5Y" and m not in [1, 7]:
                            should_show = False

                    if should_show:
                        if major_indices and (i - major_indices[-1] < min_collision_gap):
                            major_indices.pop()
                            major_labels.pop()

                        if is_dense:
                            label_text = date.strftime("%b %d")
                        else:
                            label_text = date.strftime("%b '%y") if is_year_change else date.strftime("%b")

                        major_indices.append(i)
                        major_labels.append(label_text)

                        if is_dense:
                            current_month_indices = []
                            for k in range(i, len(dates)):
                                if dates[k].month == m and dates[k].year == y:
                                    current_month_indices.append(k)
                                else:
                                    break
                            n_days = len(current_month_indices)
                            ticks_to_add = []
                            if n_days >= 15:
                                ticks_to_add.extend([i + n_days // 3, i + n_days * 2 // 3])
                            elif n_days >= 7:
                                ticks_to_add.append(i + n_days // 2)

                            last_idx_local = i
                            for t_idx in ticks_to_add:
                                if t_idx - last_idx_local >= min_density_gap:
                                    major_indices.append(t_idx)
                                    major_labels.append(dates[t_idx].strftime("%d"))
                                    last_idx_local = t_idx

                    prev_month = m
                    prev_year = y
                    prev_day = d
                continue

            # HOURLY MODE
            if is_hourly:
                if d != prev_day:
                    if i == 0 and date.hour >= 10:
                        prev_day = d
                        prev_month = m
                        prev_year = y
                        continue

                    min_hourly_gap = 8
                    is_priority = (m != prev_month) or (len(major_indices) == 0)

                    if major_indices and (i - major_indices[-1] < min_hourly_gap):
                        if is_priority:
                            major_indices.pop()
                            major_labels.pop()
                        else:
                            prev_day = d
                            prev_month = m
                            prev_year = y
                            continue

                    major_indices.append(i)
                    if window in ["1M", "YTD"]:
                        major_labels.append(date.strftime("%b %d") if m != prev_month else date.strftime("%d"))
                    else:
                        major_labels.append(date.strftime("%a %d"))

                    prev_day = d
                    prev_month = m
                    prev_year = y
                continue

            # LONG TERM MODE (10Y / 20Y)
            if y != prev_year:
                if is_long_term and i > 5:
                    major_indices.append(i)
                    major_labels.append(str(y))
                prev_year = y

            if m != prev_month:
                if not is_long_term:
                    major_indices.append(i)
                    major_labels.append(dates[i].strftime('%b'))
                prev_month = m

        return major_indices, major_labels

    def _format_hover_dates(self, df: pd.DataFrame, window: str) -> List[str]:
        """Formats per-bar date/interval strings matching the crosshair tooltip."""
        interval = self.app.current_data_interval
        has_period_start = 'period_start' in df.columns
        labels: List[str] = []

        for idx, dt in enumerate(df.index):
            if window == '1WK':
                dt_end = dt + timedelta(minutes=10)
                labels.append(f"{dt.strftime('%Y-%m-%d %H:%M')} / {dt_end.strftime('%H:%M')}")
            elif window in ['1M', '3M', 'YTD'] and ('h' in interval):
                dt_end = dt + (timedelta(minutes=30) if (dt.hour == 15 and dt.minute == 30) else timedelta(hours=1))
                labels.append(f"{dt.strftime('%Y-%m-%d %H:%M')} / {dt_end.strftime('%H:%M')}")
            elif window == 'YTD':
                labels.append(dt.strftime('%Y-%m-%d'))
            elif window in ['10Y', '20Y'] or interval == '1mo':
                last_day = calendar.monthrange(dt.year, dt.month)[1]
                dt_start = dt.replace(day=1)
                dt_end = dt.replace(day=last_day)
                labels.append(f"{dt_start.strftime('%Y-%m-%d')} / {dt_end.strftime('%Y-%m-%d')}")
            elif window == '5Y':
                dt_start = dt - timedelta(days=dt.weekday())
                dt_end = dt_start + timedelta(days=4)
                labels.append(f"{dt_start.strftime('%Y-%m-%d')} / {dt_end.strftime('%Y-%m-%d')}")
            elif window in ['2Y', '3Y'] and has_period_start:
                ps = df['period_start'].iloc[idx]
                if pd.notna(ps):
                    start_ts = pd.Timestamp(ps)
                    labels.append(f"{start_ts.strftime('%Y-%m-%d')} / {dt.strftime('%Y-%m-%d')}")
                else:
                    labels.append(dt.strftime('%Y-%m-%d'))
            elif 'm' in interval or 'h' in interval:
                labels.append(dt.strftime('%Y-%m-%d %H:%M'))
            else:
                labels.append(dt.strftime('%Y-%m-%d'))

        return labels

    def _compute_volume_profile(self, df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray, float]:
        """Vectorized Volume Profile calculation across N price bins."""
        valid = df[['low', 'high', 'volume']].dropna()
        if valid.empty:
            return np.array([]), np.array([]), 0.0

        price_min = float(valid['low'].min())
        price_max = float(valid['high'].max())

        try:
            num_bins = int(self.app.vp_mode.split()[0])
        except Exception:
            num_bins = 200
        if num_bins <= 0:
            num_bins = 200

        bin_height = (price_max - price_min) / num_bins
        if bin_height <= 0:
            return np.array([]), np.array([]), 0.0

        volume_profile = np.zeros(num_bins, dtype=np.float64)
        lows = valid['low'].to_numpy()
        highs = valid['high'].to_numpy()
        vols = valid['volume'].to_numpy()

        start_bins = np.clip(((lows - price_min) / bin_height).astype(int), 0, num_bins - 1)
        end_bins = np.clip(((highs - price_min) / bin_height).astype(int), 0, num_bins - 1)

        for sb, eb, v in zip(start_bins, end_bins, vols):
            if v <= 0:
                continue
            if sb == eb:
                volume_profile[sb] += v
            else:
                volume_profile[sb:eb + 1] += v / (eb - sb + 1)

        bin_centers = price_min + (np.arange(num_bins) + 0.5) * bin_height
        return bin_centers, volume_profile, bin_height

    def build_figure(self) -> go.Figure:
        dark = getattr(self.app, 'dark_mode', True)
        bg_color = '#131722' if dark else '#ffffff'
        paper_color = '#131722' if dark else '#ffffff'
        grid_color = 'rgba(255,255,255,0.08)' if dark else 'rgba(0,0,0,0.08)'
        text_color = '#d1d4dc' if dark else '#1e222d'
        spike_color = '#787b86' if dark else '#555555'
        font_size = max(8, int(getattr(self.app, 'font_size', 12)))
        logarithmic = bool(getattr(self.app, 'log_scale', False))
        price_scale = 'log' if logarithmic else 'linear'

        if self.app.history_df.empty:
            fig = go.Figure()
            fig.update_layout(
                paper_bgcolor=paper_color,
                plot_bgcolor=bg_color,
                font=dict(color=text_color, size=font_size),
                xaxis=dict(visible=False),
                yaxis=dict(visible=False),
                annotations=[dict(
                    text="No chart data available",
                    xref="paper", yref="paper", x=0.5, y=0.5,
                    showarrow=False, font=dict(size=font_size + 4, color=text_color)
                )]
            )
            return fig

        window = self.app.time_window
        df = self.app.history_df.copy()
        if df.empty:
            return go.Figure()

        # Full history remains in the figure for immediate horizontal panning.
        q_type = self.app.stock_info.get('quoteType', '').upper()
        is_global = q_type in ['CRYPTOCURRENCY', 'CURRENCY', 'FUTURE']

        if window == "1D":
            df = self._intraday_grid(df, is_global)

        span = len(self._filter_data_by_window(df, window))
        span = max(1, min(span, len(df)))
        latest_start = len(df) - span
        requested_start = getattr(self.app, 'view_start', None)
        view_start = latest_start if requested_start is None else max(0, min(int(requested_start), latest_start))
        view_stop = view_start + span
        visible_df = df.iloc[view_start:view_stop]
        view_range = [view_start - 0.5, view_stop - 0.5]
        is_latest = view_start == latest_start

        # Active subplot panels
        panels = ['price']
        if self.app.show_macd:
            panels.append('macd')
        if self.app.show_rsi:
            panels.append('rsi')

        num_panels = len(panels)
        num_others = num_panels - 1
        other_weight = 0.16
        price_weight = 1.0 - (other_weight * num_others)
        row_heights = [price_weight] + [other_weight] * num_others

        fig = make_subplots(
            rows=num_panels,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.025,
            row_heights=row_heights
        )

        x_indices = np.arange(len(df))
        hover_dates = self._format_hover_dates(df, window)

        # Stats & Header Title
        company = getattr(self.app, 'company_name', self.app.current_ticker)
        valid_closes = visible_df['close'].dropna()
        if not valid_closes.empty:
            start_price = float(valid_closes.iloc[0])
            end_price = float(valid_closes.iloc[-1])
            if window == "1D" and is_latest:
                if self.app.previous_close > 0:
                    start_price = self.app.previous_close
                if self.app.current_price > 0:
                    end_price = self.app.current_price
        else:
            start_price, end_price = 0.0, 0.0

        change = end_price - start_price
        pct_change = (change / start_price) * 100 if start_price != 0 else 0.0
        sign = "+" if change >= 0 else ""
        title_color = "#26a69a" if change >= 0 else "#ef5350"
        fmt = ".4f" if abs(end_price) < 2.0 else ".2f"
        title_text = f"<b>{company} ({window})   {end_price:{fmt}} {sign}{change:{fmt}} ({sign}{pct_change:.2f}%)</b>"
        if window == "1D" and is_latest:
            title_text += "   <span style='font-size:0.8em;opacity:0.75'>(15min Delayed)</span>"

        # 1. Volume Overlay (Bottom 25% of Main Price Pane on y9)
        max_vol = float(visible_df['volume'].max()) if visible_df['volume'].notna().any() else 0.0
        if self.app.show_volume and max_vol > 0:
            vol_colors = [
                'rgba(38, 166, 154, 0.30)' if (pd.notna(c) and pd.notna(o) and c >= o) else 'rgba(239, 83, 80, 0.30)'
                for c, o in zip(df['close'], df['open'])
            ]
            fig.add_trace(
                go.Bar(
                    x=x_indices,
                    y=df['volume'],
                    name='Volume',
                    marker_color=vol_colors,
                    yaxis='y9',
                    showlegend=False,
                    hoverinfo='skip'
                )
            )

        # 2. Horizontal Volume Profile (Left or Right on x9)
        max_vp = 0.0
        profile_source = None
        if self.app.show_vp:
            if not self.app.raw_df.empty:
                profile_source = self.app.raw_df
                if self.app.current_data_interval == '1m' and not self.app.show_prepost and not is_global:
                    try:
                        profile_source = profile_source.between_time('09:30', '16:00')
                    except Exception:
                        pass
                start_dt, end_dt = self._raw_view_bounds(df, view_start, view_stop, self.app.raw_df)
                vp_data = profile_source[
                    (profile_source.index >= start_dt) & (profile_source.index <= end_dt)
                ]
            else:
                profile_source = df
                vp_data = visible_df

            bin_centers, vp_vols, bin_height = self._compute_volume_profile(vp_data)
            if len(vp_vols) > 0 and vp_vols.max() > 0:
                max_vp = float(vp_vols.max())
                fig.add_trace(
                    go.Bar(
                        x=vp_vols,
                        y=bin_centers,
                        orientation='h',
                        width=bin_height * 0.92,
                        name='Vol Profile',
                        marker=dict(
                            color='rgba(41, 98, 255, 0.22)',
                            line=dict(color='rgba(41, 98, 255, 0.45)', width=0.5)
                        ),
                        xaxis='x9',
                        yaxis='y',
                        showlegend=False,
                        hoverinfo='skip'
                    )
                )

        # 3. Main Price Series (Candlestick or Line)
        if self.app.chart_type == "Line":
            fig.add_trace(
                go.Scatter(
                    x=x_indices,
                    y=df['close'],
                    mode='lines',
                    name='Close',
                    line=dict(color='#2962ff', width=1.8),
                    showlegend=False,
                    hoverinfo='skip'
                ),
                row=1, col=1
            )
        else:
            fig.add_trace(
                go.Candlestick(
                    x=x_indices,
                    open=df['open'],
                    high=df['high'],
                    low=df['low'],
                    close=df['close'],
                    name='Price',
                    increasing=dict(line=dict(color='#26a69a', width=1), fillcolor='#26a69a' if dark else '#ffffff'),
                    decreasing=dict(line=dict(color='#ef5350', width=1), fillcolor='#ef5350'),
                    showlegend=False,
                    hoverinfo='skip'
                ),
                row=1, col=1
            )

        # 4. Bollinger Bands
        if self.app.show_bbands and 'bb_upper' in df.columns:
            fig.add_trace(
                go.Scatter(
                    x=x_indices,
                    y=df['bb_upper'],
                    mode='lines',
                    name='BB Upper',
                    line=dict(color='rgba(150, 150, 150, 0.55)', width=1, dash='dash'),
                    showlegend=False,
                    hoverinfo='skip'
                ),
                row=1, col=1
            )
            fig.add_trace(
                go.Scatter(
                    x=x_indices,
                    y=df['bb_lower'],
                    mode='lines',
                    name='BB Lower',
                    line=dict(color='rgba(150, 150, 150, 0.55)', width=1, dash='dash'),
                    fill='tonexty',
                    fillcolor='rgba(150, 150, 150, 0.10)',
                    showlegend=False,
                    hoverinfo='skip'
                ),
                row=1, col=1
            )

        # 5. Moving Averages (MA5..MA250)
        ma_specs = [
            ('show_ma5', 'ma5', 'MA5', '#00bcd4'),
            ('show_ma20', 'ma20', 'MA20', '#4caf50'),
            ('show_ma50', 'ma50', 'MA50', '#ff9800'),
            ('show_ma60', 'ma60', 'MA60', '#2196f3'),
            ('show_ma100', 'ma100', 'MA100', '#9c27b0'),
            ('show_ma120', 'ma120', 'MA120', '#e91e63'),
            ('show_ma200', 'ma200', 'MA200', '#f44336'),
            ('show_ma250', 'ma250', 'MA250', '#8d6e63'),
        ]
        for attr, col, label, color in ma_specs:
            if getattr(self.app, attr, False) and col in df.columns:
                fig.add_trace(
                    go.Scatter(
                        x=x_indices,
                        y=df[col],
                        mode='lines',
                        name=label,
                        line=dict(color=color, width=1.2),
                        showlegend=self.app.show_legend,
                        hoverinfo='skip',
                    ),
                    row=1, col=1
                )

        # 6. Pre/Post Market Shading on 1D
        if window == "1D" and self.app.show_prepost and not is_global:
            cutoff_open = 9 * 60 + 30
            cutoff_close = 16 * 60
            mins = [t.hour * 60 + t.minute for t in df.index]
            pre_idx = [i for i, m in enumerate(mins) if m < cutoff_open]
            post_idx = [i for i, m in enumerate(mins) if m >= cutoff_close]
            shade_color = 'rgba(255,255,255,0.04)' if dark else 'rgba(0,0,0,0.04)'

            for indices in (pre_idx, post_idx):
                # Each session gets its own band; shading cannot cross days.
                if not indices:
                    continue
                group_start = previous = indices[0]
                for index in indices[1:] + [None]:
                    if index is not None and index == previous + 1 and df.index[index].date() == df.index[previous].date():
                        previous = index
                        continue
                    fig.add_vrect(
                        x0=group_start - 0.5, x1=previous + 0.5,
                        fillcolor=shade_color, layer='below', line_width=0, row=1, col=1,
                    )
                    group_start = previous = index

        # 7. MACD Sub-Pane
        current_row = 2
        if self.app.show_macd and 'macd' in df.columns:
            hist = df['macd'] - df['signal']
            hist_colors = ['#26a69a' if (pd.notna(v) and v >= 0) else '#ef5350' for v in hist]
            fig.add_trace(
                go.Bar(
                    x=x_indices,
                    y=hist,
                    name='MACD Hist',
                    marker_color=hist_colors,
                    showlegend=False,
                    hoverinfo='skip',
                ),
                row=current_row, col=1
            )
            fig.add_trace(
                go.Scatter(
                    x=x_indices,
                    y=df['macd'],
                    mode='lines',
                    name='MACD',
                    line=dict(color='#2962ff', width=1.2),
                    showlegend=False,
                    hoverinfo='skip',
                ),
                row=current_row, col=1
            )
            fig.add_trace(
                go.Scatter(
                    x=x_indices,
                    y=df['signal'],
                    mode='lines',
                    name='Signal',
                    line=dict(color='#ff9800', width=1.2),
                    showlegend=False,
                    hoverinfo='skip',
                ),
                row=current_row, col=1
            )
            fig.update_yaxes(
                title_text="MACD", autorange=False,
                range=self._fit_range([
                    visible_df['macd'], visible_df['signal'], visible_df['macd'] - visible_df['signal'],
                ], include_zero=True),
                row=current_row, col=1, gridcolor=grid_color,
            )
            current_row += 1

        # 8. RSI Sub-Pane
        if self.app.show_rsi and 'rsi' in df.columns:
            fig.add_trace(
                go.Scatter(
                    x=x_indices,
                    y=df['rsi'],
                    mode='lines',
                    name='RSI',
                    line=dict(color='#ab47bc', width=1.4),
                    showlegend=False,
                    hoverinfo='skip',
                ),
                row=current_row, col=1
            )
            fig.add_hline(y=70, line_dash="dash", line_color="rgba(239,83,80,0.6)", line_width=1, row=current_row, col=1)
            fig.add_hline(y=30, line_dash="dash", line_color="rgba(38,166,154,0.6)", line_width=1, row=current_row, col=1)
            fig.update_yaxes(title_text="RSI", range=[0, 100], row=current_row, col=1, gridcolor=grid_color)

        # Smart Date Ticks on Bottom X-Axis
        tick_vals, tick_texts = self._compute_date_ticks(df, window)

        # Plain JSON arrays let the browser inspect the displayed bar without
        # sending a server request or decoding Plotly's typed-array wire format.
        moving_averages = [
            dict(key=col, label=label, color=color)
            for attr, col, label, color in ma_specs
            if getattr(self.app, attr, False) and col in df.columns
        ]
        columns = ['open', 'high', 'low', 'close', 'volume']
        columns.extend(ma['key'] for ma in moving_averages)
        if self.app.show_macd:
            columns.extend(['macd', 'signal'])
        if self.app.show_rsi:
            columns.append('rsi')
        if self.app.show_bbands:
            columns.extend(['bb_upper', 'bb_lower'])
        series = {}
        for column in columns:
            if column in df.columns:
                values = pd.to_numeric(df[column], errors='coerce')
                series[column] = [
                    float(value) if pd.notna(value) and np.isfinite(value) else None
                    for value in values
                ]
        interaction_meta = dict(
            dates=hover_dates,
            series=series,
            moving_averages=moving_averages,
            panels=[dict(
                key=panel,
                xaxis='xaxis' if row == 1 else f'xaxis{row}',
                yaxis='yaxis' if row == 1 else f'yaxis{row}',
            ) for row, panel in enumerate(panels, start=1)],
            dark=dark,
            font_size=font_size,
            price_scale=price_scale,
            navigation=dict(
                range=view_range, span=span, total=len(df), latest=is_latest,
                visible_start=visible_df.index[0].isoformat(),
                visible_end=visible_df.index[-1].isoformat(),
                context='|'.join([
                    self.app.current_ticker, window, self.app.current_data_interval,
                    str(self.app.show_prepost), price_scale, df.index[0].isoformat(),
                    str(len(df)), str(span),
                ]),
            ),
        )
        if profile_source is not None:
            starts = pd.DatetimeIndex(df['period_start']) if 'period_start' in df.columns else df.index
            try:
                bins = int(self.app.vp_mode.split()[0])
                if bins <= 0:
                    bins = 200
            except (ValueError, AttributeError, IndexError):
                bins = 200
            interaction_meta['profile'] = dict(
                starts=profile_source.index.searchsorted(starts).tolist(),
                bins=bins, position=self.app.vp_position,
                **{key: [float(value) if pd.notna(value) and np.isfinite(value) else None
                         for value in pd.to_numeric(profile_source[key], errors='coerce')]
                   for key in ('low', 'high', 'volume')},
            )

        layout_updates = dict(
            title=dict(
                text=title_text,
                x=0.5,
                xanchor='center',
                y=0.98,
                font=dict(size=font_size + 4, color=title_color)
            ),
            paper_bgcolor=paper_color,
            plot_bgcolor=bg_color,
            font=dict(color=text_color, size=font_size),
            hovermode=False,
            dragmode=False,
            clickmode='none',
            margin=dict(l=max(88, font_size * 7), r=25, t=48, b=36),
            meta=dict(stock_chart=interaction_meta),
            xaxis_rangeslider_visible=False,
            # Reset saved axis state when panel IDs or the price scale change.
            uirevision=f"{self.app.current_ticker}_{window}_{self.app.chart_type}_{'_'.join(panels)}_{price_scale}",
            legend=dict(
                orientation='h',
                yanchor='top',
                y=0.99,
                xanchor='left',
                x=0.01,
                bgcolor='rgba(19,23,34,0.65)' if dark else 'rgba(255,255,255,0.75)',
                font=dict(size=max(9, font_size - 1))
            ),
            # Secondary Y-axis for Volume Overlay
            yaxis9=dict(
                overlaying='y',
                type='linear',
                range=[0, max_vol * 4] if max_vol > 0 else [0, 1],
                showticklabels=False,
                showgrid=False,
                zeroline=False,
                fixedrange=True,
            ),
            # Secondary X-axis for Volume Profile
            xaxis9=dict(
                overlaying='x',
                side='top',
                range=([max_vp * 4, 0] if self.app.vp_position == "Right" else [0, max_vp * 4]) if max_vp > 0 else [0, 1],
                showticklabels=False,
                showgrid=False,
                zeroline=False,
                fixedrange=True,
            ),
        )

        fig.update_layout(**layout_updates)

        price_columns = [visible_df['low'], visible_df['high']]
        price_columns.extend(visible_df[ma['key']] for ma in moving_averages)
        if self.app.show_bbands:
            price_columns.extend(visible_df[key] for key in ('bb_upper', 'bb_lower') if key in visible_df.columns)
        fig.update_yaxes(
            type=price_scale,
            range=self._fit_range(price_columns, logarithmic=logarithmic),
            autorange=False, row=1, col=1,
        )

        # Configure trading-bar axes without changing the volume overlay axes.
        for row in range(1, num_panels + 1):
            fig.update_xaxes(
                range=view_range,
                minallowed=-0.5,
                maxallowed=len(df) - 0.5,
                fixedrange=True,
                gridcolor=grid_color,
                showspikes=False,
                spikemode='across',
                spikesnap='cursor',
                spikethickness=1,
                spikedash='dot',
                spikecolor=spike_color,
                rangeslider_visible=False,
                row=row, col=1,
            )
            fig.update_yaxes(
                fixedrange=True,
                gridcolor=grid_color,
                showspikes=False,
                spikemode='across',
                spikesnap='cursor',
                spikethickness=1,
                spikedash='dot',
                spikecolor=spike_color,
                row=row, col=1,
            )

        # Apply smart date labels to the bottom-most subplot axis
        fig.update_xaxes(
            tickmode='array',
            tickvals=tick_vals,
            ticktext=tick_texts,
            tickfont=dict(size=font_size, color=text_color),
            row=num_panels,
            col=1
        )

        return fig
