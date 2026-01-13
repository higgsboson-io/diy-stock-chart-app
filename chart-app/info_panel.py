# info_panel.py
import tkinter as tk
from tkinter import ttk
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class InfoPanel:
    def __init__(self, app_state):
        self.app = app_state
        self.panel_x = None
        self.panel_y = None
        
        # Create UI immediately but hide it
        self._create_ui()

    def _create_ui(self):
        # Floating Info Frame (Child of ROOT)
        self.frame = ttk.Frame(self.app.root, relief="raised", borderwidth=2)
        self.app.info_frame = self.frame # Back reference if needed
        
        # --- Header for Dragging ---
        header = ttk.Frame(self.frame, style="Header.TFrame")
        header.pack(fill="x", side="top")
        
        # Title in Header
        self.info_title_label = ttk.Label(header, text="Stock Info", font=('Arial', 9, 'bold'))
        self.info_title_label.pack(side="left", padx=5, pady=2)
        
        # Close Button
        close_btn = ttk.Label(header, text="X", font=('Arial', 9, 'bold'), cursor="hand2")
        close_btn.pack(side="right", padx=5, pady=2)
        close_btn.bind("<Button-1>", lambda e: self.close_info_panel())
        
        # Bind Drag
        for w in [header, self.info_title_label]:
            w.bind("<Button-1>", self.start_drag)
            w.bind("<B1-Motion>", self.do_drag)

        # Content Frame
        self.info_content = ttk.Frame(self.frame, padding=10)
        self.info_content.pack(fill="both", expand=True)

    def toggle(self, event=None):
        if self.app.show_info.get():
             self._apply_panel_position()
             self.update_content()
        else:
             self.frame.place_forget()

    def _apply_panel_position(self):
        if not self.app.show_info.get():
             return
        
        # First Time Show? Center it.
        if self.panel_x is None or self.panel_y is None:
            self.app.root.update_idletasks()
            
            rw = self.app.root.winfo_width()
            rh = self.app.root.winfo_height()
            
            current_font = self.app.font_size_var.get()
            pw = 600 + (current_font * 25)
            
            ph = self.frame.winfo_reqheight() or 200 
            
            self.panel_x = (rw - pw) // 2
            self.panel_y = (rh - ph) // 10 
            
        current_font = self.app.font_size_var.get()
        target_width = 600 + (current_font * 25)
            
        self.frame.place(
            x=self.panel_x, 
            y=self.panel_y, 
            width=target_width
        )
        self.frame.lift()

    def _fmt(self, num, is_percent=False, trim_large=False):
        if num is None or num == 'None': return "-"
        try:
            val = float(num)
            if is_percent:
                return f"{val*100:.2f}%" if abs(val) < 1.0 else f"{val:.2f}%"
            
            abs_val = abs(val)
            if abs_val >= 1e12: return f"{val/1e12:.2f}T"
            if abs_val >= 1e9: return f"{val/1e9:.2f}B"
            if abs_val >= 1e6: return f"{val/1e6:.2f}M"
            if trim_large and abs_val >= 10000:
                return f"{val:,.0f}"
            return f"{val:,.2f}"
        except:
             return str(num)

    def _add_section(self, parent, title, items):
        try:
            base_size = int(self.app.font_size_var.get())
        except:
            base_size = 8
            
        title_font = ('Arial', base_size + 2, 'bold')
        label_font = ('Arial', base_size)
        val_font   = ('Arial', base_size, 'bold')
        
        ttk.Label(parent, text=title, font=title_font, foreground="#333").pack(anchor="w", pady=(10, 5))
        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=(0, 10))
        
        frame = ttk.Frame(parent)
        frame.pack(fill="x")
        row = 0
        for label, val in items:
            ttk.Label(frame, text=label, font=label_font).grid(row=row, column=0, sticky="w", padx=(0, 15), pady=2)
            ttk.Label(frame, text=val, font=val_font).grid(row=row, column=1, sticky="w", pady=2)
            row += 1

    def update_content(self):
        # Clear existing content
        for widget in self.info_content.winfo_children():
            widget.destroy()
            
        if not self.app.show_info.get() or not self.app.stock_info:
             if self.app.show_info.get():
                 base_size = self.app.font_size_var.get() or 9
                 ttk.Label(self.info_content, text="Loading Info...", font=('Arial', base_size, 'italic')).pack(pady=10)
             return

        i = self.app.stock_info
        q_type = i.get('quoteType', '').upper()

        # --- Prepare Data ---
        earn_ts = i.get('earningsTimestamp') or i.get('earningsTimestampStart')
        earn_str = "-"
        if earn_ts:
             earn_str = datetime.fromtimestamp(earn_ts).strftime('%Y-%m-%d')
             
        div_str = "-"
        div_rate = i.get('dividendRate') or i.get('trailingAnnualDividendRate')
        price = i.get('currentPrice') or i.get('regularMarketPrice')
        
        etf_yield = i.get('yield')
        if q_type == 'ETF' and etf_yield is not None:
             rate_str = f"{div_rate}" if div_rate else ""
             if rate_str:
                 div_str = f"{rate_str} ({etf_yield * 100:.2f}%)"
             else:
                 div_str = f"{etf_yield * 100:.2f}%"
        elif div_rate and price and price > 0:
             calc_yield = (div_rate / price) * 100
             div_str = f"{div_rate} ({calc_yield:.2f}%)"
        else:
             raw_yield = i.get('dividendYield')
             if raw_yield:
                 if raw_yield > 0.5: 
                     div_str = f"{raw_yield:.2f}%"
                 else:
                     div_str = f"{self._fmt(raw_yield, True)}"
        
        beta_key = 'beta3Year' if q_type == 'ETF' else 'beta'
        beta_val = i.get(beta_key) or i.get('beta')
        left_data = [
            ("52W Range", f"{self._fmt(i.get('fiftyTwoWeekLow'), trim_large=True)} - {self._fmt(i.get('fiftyTwoWeekHigh'), trim_large=True)}"),
            ("Avg Vol", self._fmt(i.get('averageVolume'))),
            ("Beta", self._fmt(beta_val)), 
            ("Fwd Div&Yield", div_str),
            ("Ex-Div Date", datetime.fromtimestamp(i.get('exDividendDate', 0)).strftime('%Y-%m-%d') if i.get('exDividendDate') else "-"),
            ("Target Est", self._fmt(i.get('targetMeanPrice'))),
            ("Earnings Date", earn_str)
        ]
        
        right_title = "Valuation"
        right_data = []
        
        if q_type == 'ETF':
            right_title = "ETF Profile"
            beta_val = i.get('beta3Year') or i.get('beta')
            
            exp_ratio = i.get('netExpenseRatio') or i.get('annualReportExpenseRatio') or i.get('expenseRatio')
            exp_str = "-"
            if exp_ratio is not None:
                exp_str = f"{exp_ratio}%"

            pe_val = i.get('trailingPE')
            
            right_data = [
                ("Net Assets", self._fmt(i.get('totalAssets'))),
                ("NAV", self._fmt(i.get('navPrice'))),
                ("Expense Ratio", exp_str),
                ("PE (TTM)", self._fmt(pe_val)),
                ("Beta (3Y)", self._fmt(beta_val))
            ]
        else:
             right_title = "Valuation & Earnings"
             right_data = [
                ("Market Cap", self._fmt(i.get('marketCap'))),
                ("Trailing PE", self._fmt(i.get('trailingPE'))),
                ("Forward PE", self._fmt(i.get('forwardPE'))),
                ("PEG Ratio", self._fmt(i.get('pegRatio') or i.get('trailingPegRatio'))),
                ("Price/Book", self._fmt(i.get('priceToBook'))),
                ("Price/Sales", self._fmt(i.get('priceToSalesTrailing12Months'))),
                ("EV/EBITDA", self._fmt(i.get('enterpriseToEbitda'))),
             ]

        # --- Render Layout ---
        col_frame = ttk.Frame(self.info_content)
        col_frame.pack(fill="both", expand=True, padx=5, pady=5)
        
        col_frame.columnconfigure(0, weight=1, uniform="group1")
        col_frame.columnconfigure(1, weight=1, uniform="group1")
        
        left_frame = ttk.Frame(col_frame)
        left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self._add_section(left_frame, "Key Statistics", left_data)
        
        right_frame = ttk.Frame(col_frame)
        right_frame.grid(row=0, column=1, sticky="nsew")
        self._add_section(right_frame, right_title, right_data)
        
        self._apply_panel_position()
        
        # Update Header Title
        if hasattr(self, 'info_title_label'):
             name = self.app.company_name if hasattr(self.app, 'company_name') and self.app.company_name else "Stock Info"
             self.info_title_label.config(text=name)

        # Update Font of Header
        base_size = self.app.font_size_var.get()
        self.info_title_label.configure(font=('Arial', base_size + 2, 'bold'))

    def start_drag(self, event):
        self.drag_start_x = event.x_root
        self.drag_start_y = event.y_root
        self.drag_start_win_x = self.frame.winfo_x()
        self.drag_start_win_y = self.frame.winfo_y()

    def do_drag(self, event):
        dx = event.x_root - self.drag_start_x
        dy = event.y_root - self.drag_start_y
        
        new_x = self.drag_start_win_x + dx
        new_y = self.drag_start_win_y + dy
        
        self.panel_x = new_x
        self.panel_y = new_y
        
        self.frame.place(x=new_x, y=new_y)
        
    def close_info_panel(self):
        self.app.show_info.set(False)
        self.toggle()
