#!/usr/bin/python3
"""GTK controls for Linux CPU performance mode and NVIDIA GPU power limits."""

from __future__ import annotations

import math
import threading
from typing import Callable

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from cpu_mode_backend import CpuModeBackend, ModeError, ModeState  # noqa: E402
from gpu_power_backend import GpuPowerBackend, GpuPowerState  # noqa: E402
from monitor_panel import SystemMonitorPanel, page_heading  # noqa: E402


CSS = b"""
@define-color surface #0d1420;
@define-color panel #141f2f;
@define-color line #29374b;
@define-color text #eef4ff;
@define-color muted #a7b7cb;
@define-color accent #a2bdff;
@define-color green #8fe3bc;
@define-color amber #f8ca87;
@define-color red #ffabb9;

window.control-window { background: @surface; color: @text; }
.control-window .root { padding: 24px 28px 28px; }

.navigation {
  margin: 18px 28px 0;
  padding: 4px;
  background: #101a29;
  border: 1px solid @line;
  border-radius: 12px;
}
.navigation button {
  min-height: 22px;
  padding: 6px 17px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  box-shadow: none;
  text-shadow: none;
  color: @muted;
  font-weight: 600;
}
.navigation button:hover { background: #1b2a40; color: @text; }
.navigation button:checked {
  background: #253853;
  border-color: #3a5173;
  color: #e6eeff;
}
.navigation button:focus-visible, .control-window .refresh:focus-visible,
.control-window .primary:focus-visible, .control-window .danger:focus-visible {
  outline: 2px solid @accent;
  outline-offset: -2px;
}

.page-icon {
  background: #1b2b42;
  border: 1px solid #304561;
  border-radius: 12px;
  color: @accent;
  padding: 11px;
}
.title { color: @text; font-size: 25px; font-weight: 800; }
.subtitle, .mode-detail { color: @muted; font-size: 12px; }
.mode-card, .info-card {
  border: 1px solid @line;
  border-radius: 16px;
  background: @panel;
}
.mode-card { padding: 20px; }
.info-card { padding: 16px; }
.mode-name { color: @text; font-size: 19px; font-weight: 750; }
.info-title { color: @text; font-size: 13px; font-weight: 700; }
.info-text { color: @muted; font-size: 12px; }
.control-window separator { background: @line; min-height: 1px; }
.status-on { color: @green; }
.status-off { color: @muted; }
.status-busy { color: @amber; }
.status-error { color: @red; }
.status-chip { padding: 4px 9px; border-radius: 7px; font-size: 11px; font-weight: 700; }
.status-chip.status-on { background: #19382f; }
.status-chip.status-off { background: #253347; }
.status-chip.status-busy { background: #362f29; }
.bolt, .bolt-off { border-radius: 11px; padding: 10px; }
.bolt { color: @green; background: #193d36; }
.bolt-off { color: @accent; background: #243853; }

.control-window .refresh, .control-window .primary, .control-window .danger {
  background: #1d2b41;
  color: @text;
  border: 1px solid #344760;
  border-radius: 9px;
  padding: 7px 12px;
  min-height: 22px;
  box-shadow: none;
  text-shadow: none;
  font-weight: 650;
}
.control-window .refresh:hover { background: #293e5a; }
.control-window .primary { background: @accent; color: #111c2f; border-color: @accent; }
.control-window .primary:hover { background: #bacdff; }
.control-window .danger { background: #3e2834; border-color: #714254; color: #ffd8df; }
.control-window .danger:hover { background: #553041; }
.control-window button:disabled { opacity: 0.55; }

.control-window switch {
  background: #29374b;
  border: 1px solid #526580;
  border-radius: 18px;
  min-width: 49px;
  min-height: 26px;
}
.control-window switch:checked { background: #2e816a; border-color: #64b99d; }
.control-window switch slider {
  background: #e2eaf8;
  border: 0;
  border-radius: 50%;
  min-width: 20px;
  min-height: 20px;
  margin: 3px;
}

.control-window dropdown > button, .control-window entry {
  background: #101a2a;
  color: @text;
  border: 1px solid #334762;
  border-radius: 8px;
  padding: 5px 9px;
  min-height: 24px;
  box-shadow: none;
  text-shadow: none;
}
.control-window dropdown > button:hover, .control-window entry:focus {
  border-color: #7294cd;
}
.control-window dropdown popover > contents {
  background: #152236;
  color: @text;
  border: 1px solid @line;
}
.control-window dropdown popover row:hover, .control-window dropdown popover row:selected {
  background: #273e5d;
  color: @text;
}
.metric {
  padding: 10px 12px;
  border-radius: 9px;
  background: #111c2c;
  border: 1px solid #26364b;
}
.metric-label { color: @muted; font-size: 11px; }
.metric-value { color: @text; font-size: 19px; font-weight: 750; }
.metric-current .metric-value { color: @accent; }
.power-range trough, .power-range progress {
  border: 0;
  border-radius: 4px;
  min-width: 2px;
  min-height: 6px;
  margin: 0;
  padding: 0;
  box-shadow: none;
  background-image: none;
}
.power-range trough { background-color: #25364a; }
.power-range progress { background-color: @accent; }

.audit-tabs {
  background: @panel;
  border: 1px solid @line;
  border-radius: 13px;
}
.audit-tabs > header {
  background: #111b2a;
  border: 0;
  border-bottom: 1px solid @line;
}
.audit-tabs > header > tabs > tab {
  background: transparent;
  color: @muted;
  border: 0;
  padding: 6px 13px;
  min-height: 25px;
}
.audit-tabs > header > tabs > tab:checked {
  color: @text;
  box-shadow: inset 0 -2px @accent;
}
.audit-tabs > stack, .audit-page { background: @panel; color: @text; }
.audit-filter { margin: 10px 12px 0; }
.audit-table, .audit-table > listview { color: @text; background: @panel; }
.audit-table header button {
  background: #1a293e;
  color: #bbcee7;
  border: 0;
  padding: 6px 7px;
  box-shadow: none;
  font-size: 11px;
  font-weight: 700;
}
.audit-table row { min-height: 29px; border-color: @line; }
.audit-table row:nth-child(even) { background: #172438; }
.audit-table row:hover { background: #20324b; }
.audit-table .table-cell { padding: 3px 6px; }
.audit-table .mono { font-family: monospace; font-size: 11px; }
.audit-table .status-on, .audit-table .status-busy { font-weight: 700; }
.control-window scrollbar slider { background: #45617d; border-radius: 8px; }
.control-window textview, .control-window textview text { background: @panel; color: @text; }
"""


class GpuPowerPanel(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=13)
        self.backend = GpuPowerBackend()
        self._states: list[GpuPowerState] = []
        self._busy = False

        self.refresh_button = Gtk.Button(label="刷新 GPU", valign=Gtk.Align.CENTER)
        self.refresh_button.add_css_class("refresh")
        self.refresh_button.connect("clicked", lambda _button: self.refresh())
        heading = page_heading("GPU 功率上限", "video-display-symbolic",
                               Gtk.Label(label="设置 NVIDIA 显卡的功率限制", xalign=0, wrap=True))
        heading.append(self.refresh_button)
        self.append(heading)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        card.add_css_class("mode-card")
        self.append(card)
        devices_label = Gtk.Label(label="显卡", xalign=0)
        devices_label.add_css_class("info-title")
        card.append(devices_label)
        self.devices = Gtk.DropDown()
        self.devices.update_property([Gtk.AccessibleProperty.LABEL], ["显卡"])
        self.devices.connect("notify::selected", self._on_device_changed)
        card.append(self.devices)

        metrics = Gtk.Box(spacing=9, homogeneous=True)
        card.append(metrics)
        self.current = self._metric(metrics, "当前上限", current=True)
        self.minimum = self._metric(metrics, "最小值")
        self.maximum = self._metric(metrics, "最大值")
        self.range_bar = Gtk.ProgressBar()
        self.range_bar.add_css_class("power-range")
        self.range_bar.set_visible(False)
        self.range_bar.update_property([Gtk.AccessibleProperty.LABEL], ["当前设置在可调功率范围中的位置"])
        card.append(self.range_bar)

        settings = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        settings.add_css_class("info-card")
        self.append(settings)
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=9)
        settings.append(controls)
        self.target = Gtk.Entry(width_chars=8, max_width_chars=12, input_purpose=Gtk.InputPurpose.NUMBER)
        self.target.set_placeholder_text("瓦数")
        self.target.connect("activate", self._on_apply)
        target_label = Gtk.Label(label="目标上限", mnemonic_widget=self.target, xalign=0, hexpand=True)
        target_label.add_css_class("info-title")
        controls.append(target_label)
        controls.append(self.target)
        unit = Gtk.Label(label="W")
        unit.add_css_class("mode-detail")
        controls.append(unit)
        self.apply_button = Gtk.Button(label="应用上限")
        self.apply_button.add_css_class("primary")
        self.apply_button.connect("clicked", self._on_apply)
        controls.append(self.apply_button)

        self.message = Gtk.Label(xalign=0, wrap=True)
        self.message.add_css_class("mode-detail")
        self.message.set_visible(False)
        settings.append(self.message)
        self._sync_controls()
        GLib.idle_add(self.refresh)

    def refresh(self) -> bool:
        if not self._busy:
            self._run_async(self.backend.get_states)
        return False

    def _selected_gpu(self) -> GpuPowerState | None:
        index = self.devices.get_selected()
        return self._states[index] if index < len(self._states) else None

    def _on_device_changed(self, _dropdown: Gtk.DropDown, _param: object) -> None:
        if not self._busy:
            self._render_selection()

    @staticmethod
    def _metric(parent: Gtk.Box, title: str, *, current: bool = False) -> Gtk.Label:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.add_css_class("metric")
        if current:
            box.add_css_class("metric-current")
        label = Gtk.Label(label=title, xalign=0)
        label.add_css_class("metric-label")
        box.append(label)
        value = Gtk.Label(label="—", xalign=0)
        value.add_css_class("metric-value")
        box.append(value)
        parent.append(box)
        return value

    def _render_selection(self) -> None:
        state = self._selected_gpu()
        self._sync_controls()
        if state is None:
            for metric in (self.current, self.minimum, self.maximum):
                metric.set_text("—")
            self.range_bar.set_visible(False)
            self.target.set_text("")
            self._set_message("未检测到 NVIDIA GPU。")
            return

        self.current.set_text(self._format_watts(state.limit_watts))
        self.minimum.set_text(self._format_watts(state.min_watts))
        self.maximum.set_text(self._format_watts(state.max_watts))
        available = state.allowed_range
        if available is not None and available[0] < available[1] and state.limit_watts is not None:
            minimum, maximum = available
            fraction = (state.limit_watts - minimum) / (maximum - minimum)
            self.range_bar.set_fraction(max(0.0, min(1.0, fraction)))
            self.range_bar.set_visible(True)
        else:
            self.range_bar.set_visible(False)
        self.target.set_text(f"{state.limit_watts:.2f}" if state.limit_watts is not None else "")
        self._set_message("驱动未报告可设置的功率范围。" if available is None else "")

    def _sync_controls(self) -> None:
        state = self._selected_gpu()
        can_edit = not self._busy and state is not None and state.allowed_range is not None
        self.refresh_button.set_sensitive(not self._busy)
        self.devices.set_sensitive(not self._busy and bool(self._states))
        self.target.set_sensitive(can_edit)
        self.apply_button.set_sensitive(can_edit)

    def _on_apply(self, _widget: Gtk.Widget) -> None:
        state = self._selected_gpu()
        if self._busy or state is None or state.allowed_range is None:
            return
        try:
            watts = float(self.target.get_text())
        except ValueError:
            self._set_message("请输入有效的功率值（W）。", error=True)
            return
        self._run_async(lambda: self.backend.set_limit(state.uuid, watts), requested_watts=watts)

    def _run_async(
        self, operation: Callable[[], list[GpuPowerState]], *, requested_watts: float | None = None
    ) -> None:
        applying = requested_watts is not None
        self._busy = True
        self._sync_controls()
        self._set_message("正在设置 GPU 功率上限…" if applying else "正在读取 GPU 功率上限…")

        def worker() -> None:
            try:
                states = operation()
            except Exception as exc:
                GLib.idle_add(self._show_error, exc, applying)
            else:
                GLib.idle_add(self._apply_states, states, requested_watts)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_states(self, states: list[GpuPowerState], requested_watts: float | None) -> bool:
        previous = self._selected_gpu()
        self._states = states
        labels = [f"GPU {state.index} · {state.name}" for state in states]
        self.devices.set_model(Gtk.StringList.new(labels))
        selected = 0 if states else Gtk.INVALID_LIST_POSITION
        if previous is not None:
            selected = next((i for i, state in enumerate(states) if state.uuid == previous.uuid), selected)
        self.devices.set_selected(selected)

        self._busy = False
        self._render_selection()
        if requested_watts is not None:
            state = self._selected_gpu()
            applied_watts = state.limit_watts if state is not None else None
            if applied_watts is None:
                self._set_message("设置命令已执行，驱动未报告当前上限。", error=True)
            elif not math.isclose(applied_watts, requested_watts, rel_tol=0, abs_tol=0.005):
                self._set_message(f"请求 {requested_watts:g} W，驱动回读 {applied_watts:.2f} W。", error=True)
            else:
                self._set_message(f"已应用 {applied_watts:.2f} W。")
        return False

    def _show_error(self, error: Exception, applying: bool) -> bool:
        if not applying:
            self._states = []
            self.devices.set_model(None)
        self._busy = False
        if applying:
            self._sync_controls()
        else:
            self._render_selection()
        self._set_message(str(error), error=True)
        return False

    def _set_message(self, text: str, *, error: bool = False) -> None:
        self.message.set_text(text)
        self.message.set_visible(bool(text))
        if error:
            self.message.add_css_class("status-error")
        else:
            self.message.remove_css_class("status-error")

    @staticmethod
    def _format_watts(value: float | None) -> str:
        return f"{value:.2f} W" if value is not None else "不可用"


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, application: Gtk.Application) -> None:
        super().__init__(application=application, title="CPU 性能模式")
        self.set_default_size(720, 680)
        self.add_css_class("control-window")
        self.backend = CpuModeBackend()
        self._updating_switch = False
        self._busy = False

        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        root.add_css_class("root")

        layout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        pages = Gtk.Stack(vexpand=True)
        navigation = Gtk.StackSwitcher(stack=pages, halign=Gtk.Align.START)
        navigation.add_css_class("navigation")
        layout.append(navigation)
        layout.append(pages)
        self.set_child(layout)
        pages.add_titled(self._scroll_page(root), "cpu", "CPU")
        pages.add_titled(self._gpu_page(), "gpu", "GPU")
        pages.add_titled(SystemMonitorPanel(), "monitor", "SSH 与防挖矿")

        subtitle = Gtk.Label(label="切换 Linux CPUFreq 调频策略", xalign=0, wrap=True)
        heading = page_heading("CPU 调频策略", "computer-symbolic", subtitle)
        refresh = Gtk.Button(label="刷新状态", valign=Gtk.Align.CENTER)
        refresh.add_css_class("refresh")
        refresh.connect("clicked", lambda _button: self.refresh())
        heading.append(refresh)
        root.append(heading)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        card.add_css_class("mode-card")
        root.append(card)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        card.append(top)

        self.bolt = Gtk.Image.new_from_icon_name("power-profile-performance-symbolic")
        self.bolt.set_pixel_size(22)
        self.bolt.set_valign(Gtk.Align.CENTER)
        self.bolt.add_css_class("bolt-off")
        top.append(self.bolt)

        names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        names.set_hexpand(True)
        names.set_valign(Gtk.Align.CENTER)
        top.append(names)

        self.mode_name = Gtk.Label(label="正在检测…", xalign=0)
        self.mode_name.add_css_class("mode-name")
        names.append(self.mode_name)

        self.status = Gtk.Label(label="读取系统状态", xalign=0, halign=Gtk.Align.START)
        self.status.add_css_class("status-chip")
        self.status.add_css_class("status-busy")
        names.append(self.status)

        self.toggle = Gtk.Switch()
        self.toggle.set_valign(Gtk.Align.CENTER)
        self.toggle.update_property([Gtk.AccessibleProperty.LABEL], ["CPU 性能模式"])
        self.toggle.connect("notify::active", self._on_toggle)
        top.append(self.toggle)

        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        card.append(separator)

        self.detail = Gtk.Label(label="正在读取 CPU 调速器…", xalign=0)
        self.detail.add_css_class("mode-detail")
        self.detail.set_wrap(True)
        card.append(self.detail)

        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        info.add_css_class("info-card")
        root.append(info)

        info_title = Gtk.Label(label="性能模式会做什么？", xalign=0)
        info_title.add_css_class("info-title")
        info.append(info_title)

        info_text = Gtk.Label(
            label="开启后，调频策略切换为 performance。关闭后恢复开启前的策略。",
            xalign=0,
        )
        info_text.set_wrap(True)
        info_text.add_css_class("info-text")
        info.append(info_text)

        GLib.idle_add(self.refresh)

    @staticmethod
    def _scroll_page(content: Gtk.Widget) -> Gtk.ScrolledWindow:
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_child(content)
        return scroll

    def _gpu_page(self) -> Gtk.ScrolledWindow:
        page = GpuPowerPanel()
        page.add_css_class("root")
        return self._scroll_page(page)

    def refresh(self) -> bool:
        if not self._busy:
            self._run_async(self.backend.get_state)
        return False

    def _on_toggle(self, _switch: Gtk.Switch, _param: object) -> None:
        if self._updating_switch or self._busy:
            return
        operation = self.backend.enable_performance if self.toggle.get_active() else self.backend.disable_performance
        self._run_async(operation)

    def _run_async(self, operation: object) -> None:
        self._busy = True
        self.toggle.set_sensitive(False)
        self._set_status("正在应用设置…", "status-busy")

        def worker() -> None:
            try:
                state = operation()  # type: ignore[operator]
            except Exception as exc:
                GLib.idle_add(self._show_error, exc)
            else:
                GLib.idle_add(self._apply_state, state)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_state(self, state: ModeState) -> bool:
        self._busy = False
        self._updating_switch = True
        self.toggle.set_active(state.performance)
        self._updating_switch = False
        self.toggle.set_sensitive(True)
        self.mode_name.set_text(state.mode)
        self.detail.set_text(f"{state.detail}  ·  来源：{state.source}")
        self._set_status("已开启 · 高性能运行" if state.performance else "已关闭 · 日常模式", "status-on" if state.performance else "status-off")
        self.bolt.remove_css_class("bolt")
        self.bolt.remove_css_class("bolt-off")
        self.bolt.add_css_class("bolt" if state.performance else "bolt-off")
        return False

    def _show_error(self, error: Exception) -> bool:
        self._busy = False
        self.toggle.set_sensitive(True)
        self._set_status("操作未完成", "status-off")
        dialog = Gtk.AlertDialog()
        dialog.set_message("无法切换 CPU 模式")
        dialog.set_detail(str(error) if isinstance(error, ModeError) else f"发生未知错误：{error}")
        dialog.set_buttons(["知道了"])
        dialog.show(self)
        self.refresh()
        return False

    def _set_status(self, text: str, style: str) -> None:
        for item in ("status-on", "status-off", "status-busy"):
            self.status.remove_css_class(item)
        self.status.add_css_class(style)
        self.status.set_text(text)


class CpuModeApplication(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="io.github.cpuperformancemode", flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self) -> None:
        window = self.props.active_window
        if window is None:
            window = MainWindow(self)
        window.present()


if __name__ == "__main__":
    raise SystemExit(CpuModeApplication().run())
