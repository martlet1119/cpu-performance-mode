"""GTK view of the local SSH audit and miner containment service."""

import json
import time
from datetime import datetime
from pathlib import Path

from gi.repository import Gio, GLib, GObject, Gtk, Pango


STATUS = Path("/run/cpu-performance-mode-monitor/status.json")
SSH_HELPER = Path("/usr/local/libexec/cpu-performance-mode-monitor/ssh-control")

GUIDE = """Ubuntu 24.04 · SSH 操作

本机 SSH 客户端可以主动连接其他主机
    ssh 用户名@远程主机地址

开启入站 SSH
1. 把对方的公钥加入本机登录账号的 ~/.ssh/authorized_keys。
2. 点击「开启入站 SSH」并在系统弹窗中完成管理员认证。按钮会配置公钥认证，并禁用密码和 root 登录。
3. 让对方从可信网络连接
    ssh 本机用户名@本机局域网地址

关闭入站 SSH
点击「关闭入站 SSH」并完成管理员认证。关闭会停止入站监听，并保留已配置的公钥。

本软件持续读取 SSH 系统日志。即使入站关闭，历史记录仍可查看。
自动处置已识别的矿工。未知高负载程序需要人工查看。"""


def page_heading(title, icon_name, subtitle):
    row = Gtk.Box(spacing=12)
    icon = Gtk.Image.new_from_icon_name(icon_name)
    icon.set_pixel_size(24)
    icon.set_valign(Gtk.Align.CENTER)
    icon.add_css_class("page-icon")
    row.append(icon)

    copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, hexpand=True)
    row.append(copy)
    heading = Gtk.Label(label=title, xalign=0, wrap=True)
    heading.add_css_class("title")
    copy.append(heading)
    subtitle.add_css_class("subtitle")
    copy.append(subtitle)
    return row


def stamp(timestamp):
    return datetime.fromtimestamp(timestamp).strftime("%m-%d %H:%M:%S")


class MonitorRow(GObject.Object):
    def __init__(self, values):
        super().__init__()
        self.values = values


class SystemMonitorPanel(Gtk.Box):
    def __init__(self, *, status_path=STATUS):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.add_css_class("root")
        self.status_path = status_path
        self.snapshot = {}
        self._table_data = None
        self._poll_id = None
        self._ssh_action = None
        self._ssh_state = "状态未知"
        self._status_after = 0.0

        self.health = Gtk.Label(label="正在读取监控状态…", xalign=0, wrap=True)
        header = page_heading("SSH 与防挖矿", "security-high-symbolic", self.health)
        self.append(header)
        guide = Gtk.Button(label="SSH 操作指南", valign=Gtk.Align.CENTER)
        guide.add_css_class("refresh")
        guide.connect("clicked", self._show_guide)
        header.append(guide)

        control = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        control.add_css_class("mode-card")
        self.append(control)
        control_row = Gtk.Box(spacing=12)
        control.append(control_row)

        state = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
        control_row.append(state)
        state_label = Gtk.Label(label="入站 SSH", xalign=0)
        state_label.add_css_class("metric-label")
        state.append(state_label)
        self.summary = Gtk.Label(xalign=0, wrap=True)
        self.summary.add_css_class("mode-name")
        state.append(self.summary)

        self.ssh_button = Gtk.Button(label="开启入站 SSH", valign=Gtk.Align.CENTER)
        self.ssh_button.connect("clicked", self._toggle_ssh)
        control_row.append(self.ssh_button)

        footer = Gtk.Box(spacing=12)
        control.append(footer)
        hint = Gtk.Label(label="仅允许已授权的公钥登录。", xalign=0, hexpand=True, wrap=True)
        hint.add_css_class("mode-detail")
        footer.append(hint)
        self.gpu_summary = Gtk.Label(xalign=1)
        self.gpu_summary.add_css_class("mode-detail")
        footer.append(self.gpu_summary)
        self.ssh_feedback = Gtk.Label(xalign=0, wrap=True)
        self.ssh_feedback.add_css_class("mode-detail")
        self.ssh_feedback.set_visible(False)
        control.append(self.ssh_feedback)
        self._sync_ssh_button()

        tabs = Gtk.Notebook(vexpand=True)
        tabs.add_css_class("audit-tabs")
        self.append(tabs)
        ssh_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        ssh_page.add_css_class("audit-page")
        tabs.append_page(ssh_page, Gtk.Label(label="SSH 登录"))

        filter_row = Gtk.Box(spacing=12)
        filter_row.add_css_class("audit-filter")
        ssh_page.append(filter_row)
        self.event_filter = Gtk.DropDown.new_from_strings(["成功登录", "全部记录", "失败与无效账号"])
        self.event_filter.update_property([Gtk.AccessibleProperty.LABEL], ["筛选登录记录"])
        self.event_filter.connect("notify::selected", self._filter_changed)
        filter_row.append(self.event_filter)

        self.ssh_note = Gtk.Label(xalign=0, wrap=True, hexpand=True)
        self.ssh_note.add_css_class("mode-detail")
        filter_row.append(self.ssh_note)
        self.ssh_rows = self._append_table(ssh_page, ("时间", "结果", "账号", "来源 IP", "端口", "认证方式"))

        miner_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        miner_page.add_css_class("audit-page")
        tabs.append_page(miner_page, Gtk.Label(label="矿工处置"))
        self.miner_note = Gtk.Label(xalign=0, wrap=True)
        self.miner_note.add_css_class("mode-detail")
        self.miner_note.add_css_class("audit-filter")
        miner_page.append(self.miner_note)
        self.miner_rows = self._append_table(miner_page, ("时间", "矿工", "PID", "处置结果", "可执行文件"))

        self.connect("map", self._start_polling)
        self.connect("unmap", self._stop_polling)

    def _start_polling(self, _widget):
        self.refresh()
        self._poll_id = GLib.timeout_add_seconds(2, self.refresh)

    def _stop_polling(self, _widget):
        if self._poll_id is not None:
            GLib.source_remove(self._poll_id)
            self._poll_id = None

    def refresh(self):
        try:
            self.snapshot = json.loads(self.status_path.read_text(encoding="utf-8"))
            updated = self.snapshot["time"]
            ssh_state = self.snapshot["ssh_state"]
            status = f"上次检查 {stamp(updated)}"
            stale = time.time() - updated > 45
            self.health.set_text(f"监控数据已过期 · {status}" if stale else f"监控运行中 · {status}")
            self._set_health_style("status-busy" if stale else "status-on")

            gpu = self.snapshot.get("gpu")
            gpu_text = f'{gpu["power"]:.0f} W · {gpu["utilization"]}%' if gpu else "不可读"
            if not stale and updated >= self._status_after:
                self._ssh_state = ssh_state
            self.gpu_summary.set_text(f"GPU 0 实时功耗  {gpu_text}")
            self._sync_ssh_button()
            self._update_tables()
        except PermissionError:
            self._show_unavailable("当前用户无权读取后台状态，需要属于 adm 组。")
        except FileNotFoundError:
            self._show_unavailable("后台未就绪，请检查 cpu-performance-mode-monitor.service。")
        except (OSError, ValueError, KeyError, TypeError, OverflowError, AttributeError):
            self._show_unavailable("无法读取监控数据。")
        return GLib.SOURCE_CONTINUE

    def _set_health_style(self, style):
        for css_class in ("status-on", "status-busy", "status-error"):
            self.health.remove_css_class(css_class)
        self.health.add_css_class(style)

    def _show_unavailable(self, message):
        self.snapshot = {}
        self.health.set_text(message)
        self._set_health_style("status-error")
        self.gpu_summary.set_text("")
        self._sync_ssh_button()
        self._update_tables()

    def _sync_ssh_button(self):
        available = SSH_HELPER.is_file() and GLib.find_program_in_path("pkexec") is not None
        if self._ssh_action is not None:
            label = "正在开启…" if self._ssh_action == "enable" else "正在关闭…"
        else:
            label = "关闭入站 SSH" if self._ssh_state == "已开启" else "开启入站 SSH"
        self.summary.set_text(self._ssh_state)
        self.ssh_button.set_label(label)
        self.ssh_button.remove_css_class("danger")
        self.ssh_button.remove_css_class("primary")
        self.ssh_button.add_css_class("danger" if self._ssh_state == "已开启" else "primary")
        self.ssh_button.set_sensitive(available and self._ssh_action is None)
        self.ssh_button.set_tooltip_text(None if available else "请先安装系统监控后台")

    def _toggle_ssh(self, _button):
        action = "disable" if self._ssh_state == "已开启" else "enable"
        self._ssh_action = action
        self._sync_ssh_button()
        self._set_ssh_feedback("等待系统管理员授权…")
        try:
            process = Gio.Subprocess.new(
                ["/usr/bin/pkexec", "--disable-internal-agent", str(SSH_HELPER), action],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE,
            )
        except GLib.Error as error:
            self._ssh_action = None
            self._sync_ssh_button()
            self._set_ssh_feedback(str(error), error=True)
            return
        process.communicate_utf8_async(None, None, self._ssh_finished, action)

    def _ssh_finished(self, process, result, action):
        self._ssh_action = None
        try:
            _, stdout, stderr = process.communicate_utf8_finish(result)
            if process.get_successful():
                self._status_after = time.time()
                self._ssh_state = "已开启" if action == "enable" else "已关闭"
                self._set_ssh_feedback(stdout.strip() or f"入站 SSH {self._ssh_state}。")
            elif process.get_if_exited() and process.get_exit_status() == 126:
                self._set_ssh_feedback("已取消管理员授权。")
            else:
                self._set_ssh_feedback(stderr.strip() or "无法变更入站 SSH 状态。", error=True)
        except GLib.Error as error:
            self._set_ssh_feedback(str(error), error=True)
        self.refresh()

    def _set_ssh_feedback(self, message, *, error=False):
        self.ssh_feedback.set_text(message)
        self.ssh_feedback.set_visible(bool(message))
        if error:
            self.ssh_feedback.add_css_class("status-error")
        else:
            self.ssh_feedback.remove_css_class("status-error")

    def _update_tables(self):
        data = (self.snapshot.get("ssh_events"), self.snapshot.get("ssh_error"), self.snapshot.get("actions"))
        if data == self._table_data:
            return
        self._fill_ssh_rows()
        actions = self.snapshot.get("actions", [])
        self.miner_rows.splice(0, self.miner_rows.get_n_items(), [
            MonitorRow((stamp(event["time"]), event["name"], str(event["pid"]), event["action"], event["path"]))
            for event in actions
        ])
        self.miner_note.set_text(f"自动处置已识别矿工 · {len(actions)} 条记录")
        self._table_data = data

    def _filter_changed(self, _dropdown, _param):
        self._fill_ssh_rows()

    def _fill_ssh_rows(self):
        selected_filter = self.event_filter.get_selected()
        rows = []
        for event in self.snapshot.get("ssh_events", []):
            successful = event["result"] == "成功"
            if (selected_filter == 0 and not successful) or (selected_filter == 2 and successful):
                continue
            rows.append(MonitorRow((
                stamp(event["time"]), event["result"], event["user"], event["address"], event["port"], event["method"],
            )))
        self.ssh_rows.splice(0, self.ssh_rows.get_n_items(), rows)
        self.ssh_note.set_text(self.snapshot.get("ssh_error") or f"近 14 天 · 显示 {len(rows)} 条")

    @staticmethod
    def _append_table(parent, headers):
        rows = Gio.ListStore(item_type=MonitorRow)
        view = Gtk.ColumnView(model=Gtk.NoSelection(model=rows), show_row_separators=True)
        view.add_css_class("audit-table")
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_child(view)
        parent.append(scroll)

        def setup(_factory, item, header):
            label = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, selectable=True)
            label.add_css_class("table-cell")
            if header in ("时间", "来源 IP", "端口", "PID"):
                label.add_css_class("mono")
            item.set_child(label)

        def bind(_factory, item, index):
            text = item.get_item().values[index]
            label = item.get_child()
            label.set_text(text)
            label.set_tooltip_text(text)
            if headers[index] == "结果":
                label.remove_css_class("status-on")
                label.remove_css_class("status-busy")
                label.add_css_class("status-on" if text == "成功" else "status-busy")

        for index, header in enumerate(headers):
            factory = Gtk.SignalListItemFactory()
            factory.connect("setup", setup, header)
            factory.connect("bind", bind, index)
            column = Gtk.ColumnViewColumn(title=header, factory=factory, resizable=True)
            if header in ("来源 IP", "可执行文件"):
                column.set_expand(True)
            elif header == "时间":
                column.set_fixed_width(122)
            elif header == "结果":
                column.set_fixed_width(98)
            elif header in ("账号", "端口"):
                column.set_fixed_width(66)
            elif header == "认证方式":
                column.set_fixed_width(104)
            view.append_column(column)
        return rows

    def _show_guide(self, _button):
        window = Gtk.Window(title="SSH 操作指南", transient_for=self.get_root(), modal=True)
        window.set_default_size(640, 520)
        window.add_css_class("control-window")
        scroll = Gtk.ScrolledWindow()
        text = Gtk.TextView(editable=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        text.set_top_margin(16)
        text.set_bottom_margin(16)
        text.set_left_margin(16)
        text.set_right_margin(16)
        text.get_buffer().set_text(GUIDE)
        scroll.set_child(text)
        window.set_child(scroll)
        window.present()
