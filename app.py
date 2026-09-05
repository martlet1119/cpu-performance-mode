#!/usr/bin/python3
"""GTK desktop application for toggling Linux CPU performance mode."""

from __future__ import annotations

import threading

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from cpu_mode_backend import CpuModeBackend, ModeError, ModeState  # noqa: E402


CSS = b"""
window { background: #0b1020; }
.root { padding: 26px; }
.eyebrow { color: #8d9abb; font-size: 11px; font-weight: 700; letter-spacing: 1.5px; }
.title { color: #f7f9ff; font-size: 28px; font-weight: 800; }
.subtitle { color: #9ba7c3; font-size: 13px; }
.mode-card { background: #151c31; border: 1px solid #29324d; border-radius: 22px; padding: 24px; }
.mode-name { color: #f7f9ff; font-size: 22px; font-weight: 750; }
.mode-detail { color: #94a0bc; font-size: 12px; }
.status-on { color: #52e4a3; font-size: 12px; font-weight: 700; }
.status-off { color: #9ba7c3; font-size: 12px; font-weight: 700; }
.status-busy { color: #ffc96b; font-size: 12px; font-weight: 700; }
.bolt { color: #09121a; background: #52e4a3; border-radius: 18px; font-size: 22px; font-weight: 900; padding: 14px; }
.bolt-off { color: #8995b1; background: #222a42; border-radius: 18px; font-size: 22px; font-weight: 900; padding: 14px; }
.info-card { background: #10172a; border-radius: 16px; padding: 16px; }
.info-title { color: #dfe5f5; font-size: 12px; font-weight: 700; }
.info-text { color: #8490aa; font-size: 11px; }
.refresh { color: #bac5dc; background: #1a2238; border: 1px solid #303a56; border-radius: 10px; padding: 8px 14px; }
.refresh:hover { background: #222c46; }
switch { background: #2b344d; border-radius: 18px; min-width: 54px; min-height: 30px; }
switch:checked { background: #32cc89; }
switch slider { background: #ffffff; border-radius: 50%; min-width: 24px; min-height: 24px; margin: 3px; }
"""


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, application: Gtk.Application) -> None:
        super().__init__(application=application, title="CPU 性能模式")
        self.set_default_size(460, 520)
        self.set_resizable(False)
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
        self.set_child(root)

        eyebrow = Gtk.Label(label="SYSTEM CONTROL", xalign=0)
        eyebrow.add_css_class("eyebrow")
        root.append(eyebrow)

        title = Gtk.Label(label="CPU 调频策略", xalign=0)
        title.add_css_class("title")
        root.append(title)

        subtitle = Gtk.Label(label="只切换 CPUFreq governor，不改变整机电源模式", xalign=0)
        subtitle.add_css_class("subtitle")
        root.append(subtitle)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        card.add_css_class("mode-card")
        root.append(card)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        card.append(top)

        self.bolt = Gtk.Label(label="⚡", width_chars=2)
        self.bolt.add_css_class("bolt-off")
        top.append(self.bolt)

        names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        names.set_hexpand(True)
        names.set_valign(Gtk.Align.CENTER)
        top.append(names)

        self.mode_name = Gtk.Label(label="正在检测…", xalign=0)
        self.mode_name.add_css_class("mode-name")
        names.append(self.mode_name)

        self.status = Gtk.Label(label="读取系统状态", xalign=0)
        self.status.add_css_class("status-busy")
        names.append(self.status)

        self.toggle = Gtk.Switch()
        self.toggle.set_valign(Gtk.Align.CENTER)
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
            label="将所有 CPU 核心的调频 governor 设为 performance；关闭后恢复开启前的 governor。",
            xalign=0,
        )
        info_text.set_wrap(True)
        info_text.add_css_class("info-text")
        info.append(info_text)

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        root.append(footer)
        source = Gtk.Label(label="Linux · CPUFreq governor", xalign=0)
        source.add_css_class("info-text")
        source.set_hexpand(True)
        footer.append(source)

        refresh = Gtk.Button(label="刷新状态")
        refresh.add_css_class("refresh")
        refresh.connect("clicked", lambda _button: self.refresh())
        footer.append(refresh)

        GLib.idle_add(self.refresh)

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
