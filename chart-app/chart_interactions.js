export function formatReading(value, digits = 2) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return value.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function clampPanel(position, viewport, panel) {
  return {
    left: Math.max(0, Math.min(position.left, Math.max(0, viewport.width - panel.width))),
    top: Math.max(0, Math.min(position.top, Math.max(0, viewport.height - panel.height))),
  };
}

export function historyRange(navigation, start) {
  const span = Math.min(navigation.span, navigation.total);
  const left = Math.max(-0.5, Math.min(start, navigation.total - span - 0.5));
  return [left, left + span];
}

export function historyWheelPixels(event, width) {
  const delta = Math.abs(event.deltaX) > 0.5 ? event.deltaX : event.shiftKey ? event.deltaY : 0;
  return delta * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? width : 1);
}

function fitSeries(columns, includeZero = false, logarithmic = false) {
  let low = Infinity, high = -Infinity;
  for (const column of columns) {
    for (const value of column) {
      if (typeof value !== "number" || !Number.isFinite(value)) continue;
      if (logarithmic && value <= 0) continue;
      const coordinate = logarithmic ? Math.log10(value) : value;
      low = Math.min(low, coordinate);
      high = Math.max(high, coordinate);
    }
  }
  if (!Number.isFinite(low)) return [0, 1];
  if (includeZero) { low = Math.min(low, 0); high = Math.max(high, 0); }
  const padding = high !== low ? (high - low) * 0.06 : Math.max(Math.abs(high) * 0.01, 0.01);
  return [low - padding, high + padding];
}

export function visibleRanges(metadata, startCoordinate) {
  const navigation = metadata.navigation;
  const start = Math.max(0, Math.min(Math.round(startCoordinate + 0.5), navigation.total - navigation.span));
  const stop = start + navigation.span;
  const slice = (key) => metadata.series[key]?.slice(start, stop) ?? [];
  const priceKeys = ["low", "high", "bb_upper", "bb_lower", ...metadata.moving_averages.map((ma) => ma.key)];
  const macd = slice("macd"), signal = slice("signal");
  const histogram = macd.map((value, i) => value !== null && signal[i] != null ? value - signal[i] : null);
  let volume = 0;
  for (const value of slice("volume")) if (typeof value === "number" && Number.isFinite(value)) volume = Math.max(volume, value);
  const result = {
    price: fitSeries(priceKeys.map(slice), false, metadata.price_scale === "log"),
    macd: fitSeries([macd, signal, histogram], true),
    volume: [0, volume > 0 ? volume * 4 : 1],
  };
  const source = metadata.profile;
  if (!source) return result;
  const from = source.starts[start], to = source.starts[stop] ?? source.low.length;
  let low = Infinity, high = -Infinity;
  const rows = [];
  for (let i = from; i < to; i++) {
    const row = [source.low[i], source.high[i], source.volume[i]];
    if (!row.every((value) => typeof value === "number" && Number.isFinite(value))) continue;
    low = Math.min(low, row[0]); high = Math.max(high, row[1]);
    rows.push(row);
  }
  const height = (high - low) / source.bins;
  const volumes = [], centers = [];
  if (Number.isFinite(height) && height > 0) {
    volumes.push(...Array(source.bins).fill(0));
    for (const [rowLow, rowHigh, rowVolume] of rows) {
      if (rowVolume <= 0) continue;
      const first = Math.max(0, Math.min(source.bins - 1, Math.floor((rowLow - low) / height)));
      const last = Math.max(0, Math.min(source.bins - 1, Math.floor((rowHigh - low) / height)));
      const share = rowVolume / (last - first + 1);
      for (let bin = first; bin <= last; bin++) volumes[bin] += share;
    }
    for (let bin = 0; bin < source.bins; bin++) centers.push(low + (bin + 0.5) * height);
  }
  const maximum = Math.max(0, ...volumes) * 4;
  result.profile = {
    volumes, centers, height: Number.isFinite(height) && height > 0 ? height : 1,
    range: maximum > 0 ? source.position === "Right" ? [maximum, 0] : [0, maximum] : [0, 1],
  };
  return result;
}

// Plotly's axis offsets and conversion functions already account for zoom,
// reversed ranges, subplot domains, and the gapless integer trading-bar axis.
export function locateHover(layout, metadata, x, y) {
  if (!layout || !metadata?.dates?.length) return null;
  const panes = metadata.panels.map((panel) => ({
    ...panel,
    x: layout[panel.xaxis],
    y: layout[panel.yaxis],
  })).filter((panel) => panel.x && panel.y);
  const active = panes.find((panel) =>
    x >= panel.x._offset && x <= panel.x._offset + panel.x._length &&
    y >= panel.y._offset && y <= panel.y._offset + panel.y._length);
  if (!active) return null;
  const index = Math.max(0, Math.min(
    metadata.dates.length - 1,
    Math.round(active.x.p2l(x - active.x._offset)),
  ));
  if (!Number.isFinite(index)) return null;
  let value = active.y.p2l(y - active.y._offset);
  if (active.y.type === "log") value = Math.pow(10, value);
  return {
    index,
    pane: active.key,
    value,
    width: layout.width,
    height: layout.height,
    verticals: panes.map((panel) => ({
      pane: panel.key,
      x: panel.x._offset + panel.x.l2p(index),
      y1: panel.y._offset,
      y2: panel.y._offset + panel.y._length,
    })),
    horizontal: {
      x1: active.x._offset,
      x2: active.x._offset + active.x._length,
      y,
    },
  };
}

export function buildReading(metadata, index, pane) {
  const value = (key) => metadata.series[key]?.[index] ?? null;
  const close = value("close");
  const digits = close !== null && Math.abs(close) < 2 ? 4 : 2;
  const ohlc = [
    ["Open", "open"], ["High", "high"], ["Low", "low"], ["Close", "close"],
  ].map(([label, key]) => ({ label, value: formatReading(value(key), digits) }));
  const indicators = [];
  if (pane === "macd") {
    const macd = value("macd");
    const signal = value("signal");
    indicators.push(
      { label: "MACD", value: formatReading(macd, 3), color: "#2962ff" },
      { label: "Signal", value: formatReading(signal, 3), color: "#ff9800" },
      { label: "Histogram", value: formatReading(
        macd !== null && signal !== null ? macd - signal : null, 3,
      ) },
    );
  } else if (pane === "rsi") {
    indicators.push({ label: "RSI", value: formatReading(value("rsi")), color: "#ab47bc" });
  }
  return {
    date: metadata.dates[index],
    pane: pane === "price" ? "Price" : pane.toUpperCase(),
    noTrade: close === null,
    ohlc,
    volume: formatReading(value("volume"), 0),
    movingAverages: pane === "price" ? metadata.moving_averages.map((ma) => ({
      label: ma.label, color: ma.color, value: formatReading(value(ma.key), digits),
    })) : [],
    indicators,
  };
}

export default {
  template: `
    <div class="stock-chart-interactions" :class="{ 'stock-readout-light': !isDark }"
         :style="{ '--stock-reading-font': fontSize + 'px' }">
      <svg v-if="hover" class="stock-crosshair-layer" aria-hidden="true"
           :style="plotStyle" :viewBox="'0 0 ' + hover.width + ' ' + hover.height"
           preserveAspectRatio="none">
        <line v-for="line in hover.verticals" :key="line.pane"
              class="stock-crosshair-vertical" :data-pane="line.pane"
              :x1="line.x" :x2="line.x" :y1="line.y1" :y2="line.y2" />
        <line class="stock-crosshair-horizontal" :data-pane="hover.pane"
              :x1="hover.horizontal.x1" :x2="hover.horizontal.x2"
              :y1="hover.horizontal.y" :y2="hover.horizontal.y" />
      </svg>
      <div v-if="hover" class="stock-axis-reading" :data-pane="hover.pane"
           :style="axisStyle">{{ axisReading }}</div>
      <section ref="readout" class="stock-reading-frame" aria-label="Chart readings"
               :style="{ left: position.left + 'px', top: position.top + 'px' }">
        <div class="stock-reading-handle" tabindex="0" aria-label="Move chart readings with the arrow keys"
             @pointerdown.stop.prevent="startDrag" @pointermove.stop="drag"
             @pointerup.stop="endDrag" @pointercancel.stop="endDrag"
             @keydown="moveByKey">
          <span class="stock-reading-grip" aria-hidden="true">⠿</span>
          <span>Chart readings</span>
          <span class="stock-reading-pane">{{ reading?.pane || '' }}</span>
          <button type="button" :aria-label="collapsed ? 'Expand readings' : 'Collapse readings'"
                  @pointerdown.stop @click.stop="toggleCollapsed">{{ collapsed ? '+' : '−' }}</button>
        </div>
        <div v-show="!collapsed" class="stock-reading-body">
          <template v-if="reading">
            <div class="stock-reading-date">{{ reading.date }}</div>
            <div v-if="reading.noTrade" class="stock-reading-hint">No trade at this time</div>
            <div class="stock-reading-grid stock-reading-ohlc">
              <div v-for="item in reading.ohlc" :key="item.label">
                <span>{{ item.label }}</span><strong>{{ item.value }}</strong>
              </div>
            </div>
            <div class="stock-reading-volume"><span>Volume</span><strong>{{ reading.volume }}</strong></div>
            <div v-if="reading.movingAverages.length" class="stock-reading-grid stock-reading-ma">
              <div v-for="item in reading.movingAverages" :key="item.label">
                <span :style="{ color: item.color }">{{ item.label }}</span><strong>{{ item.value }}</strong>
              </div>
            </div>
            <div v-if="reading.indicators.length" class="stock-reading-indicators">
              <div v-for="item in reading.indicators" :key="item.label">
                <span :style="{ color: item.color }">{{ item.label }}</span><strong>{{ item.value }}</strong>
              </div>
            </div>
          </template>
          <div v-else class="stock-reading-hint">Hover over a chart to inspect a bar.</div>
        </div>
      </section>
    </div>
  `,
  props: { dark: { type: Boolean, default: true } },
  data() {
    return {
      hover: null,
      reading: null,
      geometry: null,
      position: { left: 0, top: 60 },
      positioned: false,
      collapsed: false,
      isDark: this.dark,
      fontSize: 12,
    };
  },
  computed: {
    plotStyle() {
      return {
        left: this.geometry.left + "px", top: this.geometry.top + "px",
        width: this.geometry.width + "px", height: this.geometry.height + "px",
      };
    },
    axisStyle() {
      return {
        left: (this.geometry.left + this.hover.horizontal.x1 * this.geometry.scaleX - 1) + "px",
        top: (this.geometry.top + this.hover.horizontal.y * this.geometry.scaleY) + "px",
      };
    },
    axisReading() {
      return formatReading(this.hover.value,
        this.hover.pane === "macd" ? 3 : this.hover.pane === "price" && Math.abs(this.hover.value) < 2 ? 4 : 2);
    },
  },
  mounted() {
    this.disposed = false;
    this.wrapper = this.$el.parentElement;
    this.wrapper.addEventListener("pointerdown", this.startHistory);
    this.wrapper.addEventListener("pointermove", this.queuePointer, { passive: true });
    this.wrapper.addEventListener("pointerup", this.finishHistory);
    this.wrapper.addEventListener("pointercancel", this.finishHistory);
    this.wrapper.addEventListener("pointerleave", this.clearHover);
    this.wrapper.addEventListener("wheel", this.panWithWheel, { passive: false });
    this.resizeObserver = new ResizeObserver(() => {
      this.clampFrame();
      this.refreshPlot();
    });
    this.resizeObserver.observe(this.wrapper);
    this.attachPlot();
  },
  beforeUnmount() {
    this.disposed = true;
    clearTimeout(this.retry);
    cancelAnimationFrame(this.animation);
    cancelAnimationFrame(this.panAnimation);
    clearTimeout(this.navigationTimer);
    this.resizeObserver?.disconnect();
    this.wrapper?.removeEventListener("pointermove", this.queuePointer);
    this.wrapper?.removeEventListener("pointerdown", this.startHistory);
    this.wrapper?.removeEventListener("pointerup", this.finishHistory);
    this.wrapper?.removeEventListener("pointercancel", this.finishHistory);
    this.wrapper?.removeEventListener("pointerleave", this.clearHover);
    this.wrapper?.removeEventListener("wheel", this.panWithWheel);
    for (const name of ["plotly_afterplot", "plotly_relayout", "plotly_restyle"]) {
      this.plot?.removeListener(name, this.refreshPlot);
    }
    this.plot?.removeListener("plotly_relayout", this.historyRelayout);
  },
  methods: {
    startHistory(event) {
      if (event.button !== 0 || event.target.closest?.(".stock-reading-frame")) return;
      const metadata = this.plot?.layout?.meta?.stock_chart;
      const layout = this.plot?._fullLayout;
      if (!metadata?.navigation || !layout) return;
      const rect = this.plot.getBoundingClientRect();
      const hovered = locateHover(layout, metadata,
        (event.clientX - rect.left) * layout.width / rect.width,
        (event.clientY - rect.top) * layout.height / rect.height);
      if (!hovered) return;
      const pane = metadata.panels.find((panel) => panel.key === hovered.pane);
      const axis = layout[pane.xaxis];
      this.historyDrag = {
        pointerId: event.pointerId, x: event.clientX,
        start: axis.range[0], range: [...axis.range],
        width: axis._length * rect.width / layout.width,
        navigation: metadata.navigation,
      };
      this.lastWheel = null;
      clearTimeout(this.navigationTimer);
      this.pendingNavigation = null;
      this.clearHover();
      event.preventDefault();
      this.wrapper.setPointerCapture(event.pointerId);
    },
    dragHistory(event) {
      const drag = this.historyDrag;
      if (!drag || drag.pointerId !== event.pointerId) return;
      drag.range = historyRange(drag.navigation,
        drag.start + (drag.x - event.clientX) * drag.navigation.span / drag.width);
      this.pendingPan = { range: drag.range, context: drag.navigation.context };
      this.queuePan();
    },
    finishHistory(event) {
      const drag = this.historyDrag;
      if (drag && drag.pointerId === event.pointerId) {
        this.historyDrag = null;
        if (this.wrapper.hasPointerCapture(event.pointerId)) this.wrapper.releasePointerCapture(event.pointerId);
        this.scheduleHistory(drag.range[0], drag.navigation.context);
      }
      this.queuePointer(event);
    },
    attachPlot() {
      if (this.disposed) return;
      const plot = this.wrapper.querySelector(".js-plotly-plot");
      if (!plot?._fullLayout || typeof plot.on !== "function") {
        this.retry = setTimeout(this.attachPlot, 50);
        return;
      }
      this.plot = plot;
      for (const name of ["plotly_afterplot", "plotly_relayout", "plotly_restyle"]) {
        plot.on(name, this.refreshPlot);
      }
      plot.on("plotly_relayout", this.historyRelayout);
      this.refreshPlot();
    },
    async plotlyApi() {
      if (window.Plotly) return window.Plotly;
      this.plotlyPromise ??= import("nicegui-plotly").then((module) => module.Plotly);
      return this.plotlyPromise;
    },
    historyRelayout(event) {
      if (this.applyingHistory || this.historyDrag) return;
      const metadata = this.plot?.layout?.meta?.stock_chart;
      if (!metadata?.navigation) return;
      for (const pane of metadata.panels) {
        const range = event[pane.xaxis + ".range"];
        const start = Array.isArray(range) ? range[0] : event[pane.xaxis + ".range[0]"];
        if (typeof start !== "number") continue;
        this.scheduleHistory(historyRange(metadata.navigation, start)[0], metadata.navigation.context);
        return;
      }
    },
    scheduleHistory(start, context) {
      this.pendingNavigation = { start: Math.round(start + 0.5), context };
      clearTimeout(this.navigationTimer);
      this.navigationTimer = setTimeout(() => {
        if (this.disposed || !this.pendingNavigation) return;
        const navigation = this.plot?.layout?.meta?.stock_chart?.navigation;
        const pending = this.pendingNavigation;
        this.pendingNavigation = null;
        if (!navigation || pending.context !== navigation.context) return;
        if (pending.start !== Math.round(navigation.range[0] + 0.5)) {
          this.$emit("history", pending);
        }
      }, 100);
    },
    panWithWheel(event) {
      if (event.ctrlKey || event.metaKey || event.target.closest?.(".stock-reading-frame")) return;
      const metadata = this.plot?.layout?.meta?.stock_chart;
      const layout = this.plot?._fullLayout;
      if (!metadata?.navigation || !layout) return;
      const rect = this.plot.getBoundingClientRect();
      const x = (event.clientX - rect.left) * layout.width / rect.width;
      const y = (event.clientY - rect.top) * layout.height / rect.height;
      const hovered = locateHover(layout, metadata, x, y);
      if (!hovered) return;
      const pane = metadata.panels.find((panel) => panel.key === hovered.pane);
      const axis = layout[pane.xaxis];
      const pixels = historyWheelPixels(event, axis._length);
      if (!pixels) return;
      event.preventDefault();
      const navigation = metadata.navigation;
      if (!this.lastWheel || event.timeStamp - this.lastWheel > 200 || this.wheelContext !== navigation.context) {
        this.wheelStart = axis.range[0];
      }
      this.lastWheel = event.timeStamp;
      this.wheelContext = navigation.context;
      const range = historyRange(navigation, this.wheelStart + pixels * navigation.span / axis._length);
      this.wheelStart = range[0];
      this.pendingPan = { range, context: navigation.context };
      this.queuePan();
    },
    queuePan() {
      if (this.panAnimation || this.applyingHistory || this.disposed) return;
      this.panAnimation = requestAnimationFrame(this.flushPan);
    },
    async flushPan() {
      this.panAnimation = null;
      const pending = this.pendingPan;
      this.pendingPan = null;
      const metadata = this.plot?.layout?.meta?.stock_chart;
      if (this.disposed || !pending || pending.context !== metadata?.navigation?.context) return;
      this.applyingHistory = true;
      try {
        const Plotly = await this.plotlyApi();
        if (this.disposed || pending.context !== this.plot?.layout?.meta?.stock_chart?.navigation?.context) return;
        const update = {};
        for (const pane of metadata.panels) update[pane.xaxis + ".range"] = pending.range;
        const visible = visibleRanges(metadata, pending.range[0]);
        for (const pane of metadata.panels) {
          if (pane.key === "price") update[pane.yaxis + ".range"] = visible.price;
          if (pane.key === "macd") update[pane.yaxis + ".range"] = visible.macd;
        }
        update['yaxis9.range'] = visible.volume;
        const profileIndex = this.plot.data.findIndex((trace) => trace.name === "Vol Profile");
        if (visible.profile && profileIndex >= 0) {
          update['xaxis9.range'] = visible.profile.range;
          await Plotly.update(this.plot, {
            x: [visible.profile.volumes], y: [visible.profile.centers], width: [visible.profile.height * 0.92],
          }, update, [profileIndex]);
        } else {
          await Plotly.relayout(this.plot, update);
        }
        if (!this.historyDrag) this.scheduleHistory(pending.range[0], pending.context);
      } finally {
        this.applyingHistory = false;
        if (this.pendingPan) this.queuePan();
      }
    },
    refreshPlot() {
      if (this.disposed || !this.plot) return;
      const metadata = this.plot.layout?.meta?.stock_chart;
      if (metadata !== this.lastMetadata) {
        this.reading = null;
        this.lastMetadata = metadata;
        this.lastReadingIndex = null;
      }
      this.isDark = metadata?.dark ?? this.dark;
      this.fontSize = metadata?.font_size ?? 12;
      if (!this.positioned && metadata?.dates?.length && this.wrapper.clientWidth > 310) {
        const axis = this.plot._fullLayout.yaxis;
        this.position = {
          left: Math.max(0, this.wrapper.clientWidth - 310),
          top: (axis?._offset ?? 48) + 10,
        };
        this.positioned = true;
      }
      if (this.lastPointer) this.updatePointer(this.lastPointer);
      else this.hover = null;
      this.$nextTick(this.clampFrame);
    },
    queuePointer(event) {
      if (this.historyDrag) {
        if (event.type === "pointermove") this.dragHistory(event);
        return;
      }
      if (event.target.closest?.(".stock-reading-frame")) return;
      this.lastPointer = { clientX: event.clientX, clientY: event.clientY, buttons: event.buttons };
      if (this.animation) return;
      this.animation = requestAnimationFrame(() => {
        this.animation = null;
        if (!this.disposed && this.lastPointer) this.updatePointer(this.lastPointer);
      });
    },
    updatePointer(pointer) {
      if (!this.plot?._fullLayout || pointer.buttons) {
        this.hover = null;
        return;
      }
      const rect = this.plot.getBoundingClientRect();
      const host = this.$el.getBoundingClientRect();
      const layout = this.plot._fullLayout;
      const metadata = this.plot.layout?.meta?.stock_chart;
      if (!rect.width || !rect.height) return;
      this.geometry = {
        left: rect.left - host.left, top: rect.top - host.top,
        width: rect.width, height: rect.height,
        scaleX: rect.width / layout.width, scaleY: rect.height / layout.height,
      };
      this.hover = locateHover(layout, metadata,
        (pointer.clientX - rect.left) / this.geometry.scaleX,
        (pointer.clientY - rect.top) / this.geometry.scaleY);
      if (!this.hover) return;
      if (this.lastReadingIndex !== this.hover.index || this.lastReadingPane !== this.hover.pane || !this.reading) {
        this.reading = buildReading(metadata, this.hover.index, this.hover.pane);
        this.lastReadingIndex = this.hover.index;
        this.lastReadingPane = this.hover.pane;
        this.$nextTick(this.clampFrame);
      }
    },
    clearHover() {
      this.lastPointer = null;
      this.hover = null;
      cancelAnimationFrame(this.animation);
      this.animation = null;
    },
    clampFrame() {
      if (this.disposed || !this.$refs.readout) return;
      this.position = clampPanel(this.position,
        { width: this.wrapper.clientWidth, height: this.wrapper.clientHeight },
        { width: this.$refs.readout.offsetWidth, height: this.$refs.readout.offsetHeight });
    },
    startDrag(event) {
      this.positioned = true;
      this.dragState = {
        pointerId: event.pointerId, x: event.clientX, y: event.clientY,
        left: this.position.left, top: this.position.top,
      };
      event.currentTarget.setPointerCapture(event.pointerId);
      this.clearHover();
    },
    drag(event) {
      if (!this.dragState || event.pointerId !== this.dragState.pointerId) return;
      this.position = {
        left: this.dragState.left + event.clientX - this.dragState.x,
        top: this.dragState.top + event.clientY - this.dragState.y,
      };
      this.clampFrame();
    },
    endDrag(event) {
      if (event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId);
      }
      this.dragState = null;
    },
    moveByKey(event) {
      const directions = { ArrowLeft: [-8, 0], ArrowRight: [8, 0], ArrowUp: [0, -8], ArrowDown: [0, 8] };
      const direction = directions[event.key];
      if (!direction) return;
      event.preventDefault();
      this.position = { left: this.position.left + direction[0], top: this.position.top + direction[1] };
      this.clampFrame();
    },
    toggleCollapsed() {
      this.collapsed = !this.collapsed;
      this.$nextTick(this.clampFrame);
    },
  },
};
