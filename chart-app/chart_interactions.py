"""Client-side chart crosshairs and the draggable readings frame."""

from pathlib import Path

from nicegui import ui
from nicegui.element import Element


class ChartInteractions(Element, component='chart_interactions.js'):
    def __init__(self, dark: bool = True, on_history_change=None):
        super().__init__()
        self._props['dark'] = dark
        if on_history_change is not None:
            self.on('history', on_history_change)
        ui.add_css(Path(__file__).with_suffix('.css').read_text(encoding='utf-8'))
