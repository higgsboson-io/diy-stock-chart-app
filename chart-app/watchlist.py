# watchlist.py
import logging
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd
from nicegui import ui, run

import stock_util

logger = logging.getLogger(__name__)
APP_DIR = Path(__file__).resolve().parent
DEFAULT_WATCHLIST_PATH = APP_DIR / "conf" / "watchlist.csv"


class WatchListManager:
    """Manages grouped watchlists backed by app/conf/watchlist.csv."""

    def __init__(self, filepath: Optional[Path] = None):
        self.filepath = Path(filepath) if filepath else DEFAULT_WATCHLIST_PATH
        self.data: Dict[str, List[Dict[str, str]]] = {}
        self._group_order: List[str] = []
        self.load()

    def load(self):
        self.data = {}
        self._group_order = []
        if not self.filepath.exists():
            return

        try:
            df = pd.read_csv(self.filepath, keep_default_na=False)
            if not all(col in df.columns for col in ['WatchList', 'Ticker', 'Name']):
                return

            for _, row in df.iterrows():
                group_name = str(row['WatchList']).strip()
                if not group_name or group_name == 'nan':
                    continue
                if group_name not in self.data:
                    self.data[group_name] = []
                    self._group_order.append(group_name)
                ticker = str(row['Ticker']).strip()
                if not ticker:
                    continue  # A blank ticker persists an empty group.
                self.data[group_name].append({
                    'ticker': ticker,
                    'name': str(row['Name']).strip()
                })
        except Exception as e:
            logger.error(f"Failed to load watchlist: {e}")

    def save(self):
        try:
            rows = []
            for group in self._group_order:
                if group in self.data:
                    if not self.data[group]:
                        rows.append({'WatchList': group, 'Ticker': '', 'Name': ''})
                    for item in self.data[group]:
                        rows.append({
                            'WatchList': group,
                            'Ticker': item['ticker'],
                            'Name': item['name']
                        })

            df = pd.DataFrame(rows, columns=['WatchList', 'Ticker', 'Name'])
            self.filepath.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(self.filepath, index=False)
        except Exception as e:
            logger.error(f"Failed to save watchlist: {e}")

    def create_group(self, group_name: str) -> bool:
        group_name = group_name.strip()
        if group_name and group_name not in self.data:
            self.data[group_name] = []
            self._group_order.append(group_name)
            self.save()
            return True
        return False

    def add_ticker(self, group: str, ticker: str, name: str):
        group = group.strip()
        ticker = ticker.upper().strip()
        if not group or not ticker:
            return
        if group not in self.data:
            self.data[group] = []
            self._group_order.append(group)

        for item in self.data[group]:
            if item['ticker'] == ticker:
                return

        self.data[group].append({'ticker': ticker, 'name': name or ticker})
        self.save()

    def update_ticker_name(self, group: str, ticker: str, new_name: str) -> bool:
        if group not in self.data:
            return False
        changed = False
        for item in self.data[group]:
            if item['ticker'] == ticker:
                if item['name'] != new_name:
                    item['name'] = new_name
                    changed = True
                break
        if changed:
            self.save()
        return changed

    def get_groups(self) -> List[str]:
        return list(self._group_order)

    def get_items(self, group: str) -> List[Dict[str, str]]:
        return self.data.get(group, [])

    def is_watched(self, ticker: str) -> bool:
        t = ticker.upper().strip()
        for items in self.data.values():
            for item in items:
                if item['ticker'] == t:
                    return True
        return False

    def rename_group(self, old_name: str, new_name: str) -> bool:
        new_name = new_name.strip()
        if not new_name or old_name not in self.data or new_name in self.data:
            return False
        self.data[new_name] = self.data.pop(old_name)
        idx = self._group_order.index(old_name)
        self._group_order[idx] = new_name
        self.save()
        return True

    def delete_group(self, group_name: str) -> bool:
        if group_name in self.data:
            del self.data[group_name]
            self._group_order.remove(group_name)
            self.save()
            return True
        return False

    def move_group(self, group_name: str, delta: int) -> bool:
        if group_name not in self._group_order:
            return False
        idx = self._group_order.index(group_name)
        new_idx = idx + delta
        if new_idx < 0 or new_idx >= len(self._group_order):
            return False
        self._group_order[idx], self._group_order[new_idx] = self._group_order[new_idx], self._group_order[idx]
        self.save()
        return True

    def move_ticker(self, group: str, ticker: str, delta: int) -> bool:
        if group not in self.data:
            return False
        items = self.data[group]
        idx = next((i for i, item in enumerate(items) if item['ticker'] == ticker), None)
        if idx is None:
            return False
        new_idx = idx + delta
        if new_idx < 0 or new_idx >= len(items):
            return False
        items[idx], items[new_idx] = items[new_idx], items[idx]
        self.save()
        return True

    def remove_ticker(self, group: str, ticker: str) -> bool:
        if group in self.data:
            initial_len = len(self.data[group])
            self.data[group] = [item for item in self.data[group] if item['ticker'] != ticker]
            if len(self.data[group]) < initial_len:
                self.save()
                return True
        return False

    def remove_ticker_entirely(self, ticker: str) -> bool:
        removed_any = False
        for group in list(self.data.keys()):
            if self.remove_ticker(group, ticker):
                removed_any = True
        return removed_any


class WatchListDialogs:
    """Modern NiceGUI dialogs for adding to watchlists and managing groups/tickers."""

    def __init__(self, app):
        self.app = app
        self.selected_group: Optional[str] = None
        self.selected_ticker: Optional[str] = None

    def open_add_dialog(self):
        ticker = self.app.current_ticker
        if not ticker:
            return
        name = getattr(self.app, 'company_name', ticker) or ticker
        groups = self.app.watchlist_manager.get_groups()
        selected_groups: Dict[str, bool] = {g: False for g in groups}

        with ui.dialog() as dlg, ui.card().classes('w-96 p-4'):
            with ui.row().classes('w-full items-center justify-between'):
                ui.label('Add to Watch List').classes('text-base font-bold')
                ui.button(icon='close', on_click=dlg.close).props('flat round dense')

            ui.separator().classes('my-2')
            ui.label(f"{ticker} — {name}").classes('text-sm font-medium text-primary mb-2')

            if groups:
                ui.label('Select Watch Lists:').classes('text-xs opacity-75 mb-1')
                with ui.column().classes('w-full max-h-48 overflow-y-auto gap-1 border rounded p-2'):
                    for g in groups:
                        ui.checkbox(
                            g,
                            value=False,
                            on_change=lambda e, grp=g: selected_groups.__setitem__(grp, e.value)
                        ).props('dense')

            new_list_input = ui.input(
                label='Or Create New List',
                placeholder='e.g. Semiconductors'
            ).classes('w-full mt-2').props('dense outlined')

            def handle_save():
                new_name = (new_list_input.value or '').strip()
                chosen = [g for g, checked in selected_groups.items() if checked]
                if not new_name and not chosen:
                    ui.notify('Select at least one list or enter a new list name.', type='warning')
                    return

                if new_name:
                    self.app.watchlist_manager.add_ticker(new_name, ticker, name)
                for g in chosen:
                    self.app.watchlist_manager.add_ticker(g, ticker, name)

                self.app.refresh_watchlist_menu()
                self.app.update_star_state()
                ui.notify(f'Added {ticker} to Watch List', type='positive')
                dlg.close()

            with ui.row().classes('w-full justify-end gap-2 mt-4'):
                ui.button('Cancel', on_click=dlg.close).props('flat')
                ui.button('Save', on_click=handle_save, color='primary')

        dlg.open()

    def open_manage_dialog(self):
        self.app.watchlist_menu.close()
        groups = self.app.watchlist_manager.get_groups()
        if groups and (self.selected_group not in groups):
            self.selected_group = groups[0]
        elif not groups:
            self.selected_group = None
        self.selected_ticker = None

        # Menu refreshes must not delete the dialog's lifetime anchor.
        with ui.context.client, ui.dialog() as dlg, ui.card().classes('w-[780px] max-w-[95vw] p-4'):
            with ui.row().classes('w-full items-center justify-between'):
                ui.label('Manage Watch Lists').classes('text-lg font-bold')
                ui.button(icon='close', on_click=dlg.close).props('flat round dense')

            ui.separator().classes('my-2')

            with ui.grid(columns=2).classes('w-full gap-4'):
                # LEFT COLUMN: Watch List Groups
                with ui.card().classes('w-full p-3').props('flat bordered'):
                    ui.label('Watch Lists').classes('text-sm font-bold mb-2')

                    with ui.row().classes('w-full items-center gap-1 mb-2'):
                        new_grp_input = ui.input(placeholder='New group name...').classes('flex-grow').props('dense outlined')

                        def create_grp():
                            gname = (new_grp_input.value or '').strip()
                            if not gname:
                                return
                            if self.app.watchlist_manager.create_group(gname):
                                self.selected_group = gname
                                new_grp_input.value = ''
                                refresh_all()
                            else:
                                ui.notify('Group already exists.', type='warning')

                        ui.button(icon='add', on_click=create_grp).props('dense color=primary')

                    group_list_container = ui.column().classes('w-full h-56 overflow-y-auto gap-1 border rounded p-1')

                    rename_input = ui.input(label='Rename Selected Group').classes('w-full mt-2').props('dense outlined')

                    with ui.row().classes('w-full justify-between gap-1 mt-2'):
                        def do_rename():
                            if not self.selected_group:
                                return
                            new_n = (rename_input.value or '').strip()
                            if new_n and self.app.watchlist_manager.rename_group(self.selected_group, new_n):
                                self.selected_group = new_n
                                refresh_all()

                        def do_delete():
                            if not self.selected_group:
                                return
                            if self.app.watchlist_manager.delete_group(self.selected_group):
                                rem = self.app.watchlist_manager.get_groups()
                                self.selected_group = rem[0] if rem else None
                                self.selected_ticker = None
                                refresh_all()

                        def do_move_grp(delta: int):
                            if self.selected_group and self.app.watchlist_manager.move_group(self.selected_group, delta):
                                refresh_all()

                        ui.button('Rename', on_click=do_rename).props('dense outline')
                        ui.button('Delete', on_click=do_delete, color='negative').props('dense outline')
                        ui.button(icon='arrow_upward', on_click=lambda: do_move_grp(-1)).props('dense outline')
                        ui.button(icon='arrow_downward', on_click=lambda: do_move_grp(1)).props('dense outline')

                # RIGHT COLUMN: Tickers in Selected Group
                with ui.card().classes('w-full p-3').props('flat bordered'):
                    tickers_header = ui.label('Tickers').classes('text-sm font-bold mb-2')

                    with ui.row().classes('w-full items-center gap-1 mb-2'):
                        add_ticker_input = ui.input(placeholder='Add ticker (e.g. AAPL)...').classes('flex-grow').props('dense outlined')

                        async def do_add_ticker():
                            if not self.selected_group:
                                ui.notify('Select a Watch List first.', type='warning')
                                return
                            sym = (add_ticker_input.value or '').upper().strip()
                            if not sym:
                                return
                            add_ticker_input.disable()
                            try:
                                full_name = await run.io_bound(stock_util.get_ticker_name, sym)
                                self.app.watchlist_manager.add_ticker(self.selected_group, sym, full_name)
                                self.selected_ticker = sym
                                add_ticker_input.value = ''
                                refresh_all()
                            finally:
                                add_ticker_input.enable()

                        add_ticker_input.on('keydown.enter', do_add_ticker)
                        ui.button(icon='add', on_click=do_add_ticker).props('dense color=primary')

                    ticker_list_container = ui.column().classes('w-full h-56 overflow-y-auto gap-1 border rounded p-1')

                    with ui.row().classes('w-full justify-between gap-1 mt-8'):
                        def do_remove_tkr():
                            if self.selected_group and self.selected_ticker:
                                if self.app.watchlist_manager.remove_ticker(self.selected_group, self.selected_ticker):
                                    self.selected_ticker = None
                                    refresh_all()

                        def do_move_tkr(delta: int):
                            if self.selected_group and self.selected_ticker:
                                if self.app.watchlist_manager.move_ticker(self.selected_group, self.selected_ticker, delta):
                                    refresh_all()

                        ui.button('Remove', on_click=do_remove_tkr, color='negative').props('dense outline')
                        with ui.row().classes('gap-1'):
                            ui.button(icon='arrow_upward', on_click=lambda: do_move_tkr(-1)).props('dense outline')
                            ui.button(icon='arrow_downward', on_click=lambda: do_move_tkr(1)).props('dense outline')

            def select_group(g: str):
                self.selected_group = g
                self.selected_ticker = None
                refresh_all()

            def select_ticker(t: str):
                self.selected_ticker = t
                refresh_tickers()

            def refresh_groups():
                group_list_container.clear()
                grps = self.app.watchlist_manager.get_groups()
                rename_input.value = self.selected_group or ''
                with group_list_container:
                    if not grps:
                        ui.label('No watch lists yet.').classes('text-xs opacity-60 p-2')
                    for g in grps:
                        active = (g == self.selected_group)
                        btn = ui.button(
                            g,
                            on_click=lambda grp=g: select_group(grp)
                        ).classes('w-full justify-start text-left normal-case')
                        if active:
                            btn.props('unelevated color=primary dense')
                        else:
                            btn.props('flat dense')

            def refresh_tickers():
                ticker_list_container.clear()
                if not self.selected_group:
                    tickers_header.text = 'Tickers'
                    return
                tickers_header.text = f"Tickers in '{self.selected_group}'"
                items = self.app.watchlist_manager.get_items(self.selected_group)
                with ticker_list_container:
                    if not items:
                        ui.label('Empty list. Add a ticker above.').classes('text-xs opacity-60 p-2')
                    for item in items:
                        tkr = item['ticker']
                        lbl = f"{tkr} — {item['name']}"
                        active = (tkr == self.selected_ticker)
                        btn = ui.button(
                            lbl,
                            on_click=lambda t=tkr: select_ticker(t)
                        ).classes('w-full justify-start text-left normal-case truncate')
                        if active:
                            btn.props('unelevated color=primary dense')
                        else:
                            btn.props('flat dense')

            def refresh_all():
                refresh_groups()
                refresh_tickers()
                self.app.refresh_watchlist_menu()
                self.app.update_star_state()

            refresh_all()

        dlg.open()
