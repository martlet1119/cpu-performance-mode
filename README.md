# CPU 性能模式

面向 Ubuntu 24.04 桌面的 GTK 4 工具。应用提供三个独立页面，可切换 CPU 调频策略、调整 NVIDIA GPU 功率上限，以及查看和控制本机入站 SSH。

| 页面 | 功能 |
| --- | --- |
| **CPU** | 查看当前及可用的 CPUFreq governor。开启性能策略时切换为 `performance`，关闭时恢复此前保存的策略。 |
| **GPU** | 选择 NVIDIA 显卡，查看当前上限、驱动报告的可调范围和范围条，输入目标瓦数并应用。 |
| **SSH 与防挖矿** | 开关入站 SSH，查看登录日志、GPU 0 实时功耗和已识别矿工的自动处置记录。 |

## 安装与打开

在本项目目录执行以下命令。桌面部分安装到当前用户的数据目录。完成后，从应用菜单打开「CPU 性能模式」。

~~~bash
./install.sh
~~~

也可以从源码直接打开界面。

~~~bash
/usr/bin/python3 app.py
~~~

首次使用「SSH 与防挖矿」页时，安装系统监控服务和 SSH 开关助手。后台随系统启动，窗口关闭后仍会监控和处置已识别矿工。

~~~bash
sudo ./manage-monitor.sh install
~~~

如果界面提示无法读取后台状态，确认桌面用户属于 `adm` 组。添加后注销并重新登录，使组权限生效。

~~~bash
id -nG
sudo usermod -aG adm "$(id -un)"
~~~

### 依赖

- 界面使用系统 Python、PyGObject 和 GTK 4。CPU、GPU 和 SSH 设置通过 `pkexec` 请求桌面管理员授权。缺少组件时可安装 `python3-gi`、`gir1.2-gtk-4.0` 和 `pkexec`。
- CPU 调频需要内核提供 CPUFreq，以及与当前内核匹配的 `cpupower`。Ubuntu 通用内核可安装 `linux-tools-common` 和 `linux-tools-$(uname -r)`。
- GPU 功率上限需要 NVIDIA 驱动自带的 `nvidia-smi`，并且显卡和驱动支持设置功率上限。
- 入站 SSH 开关依赖 Ubuntu 的 `openssh-server` 和 systemd 套接字激活。安装 OpenSSH 服务端时可能自动启动入站监听，安装后可在本应用关闭。

## CPU 调频

在「CPU」页点击开关并完成管理员授权。应用通过 Linux CPUFreq 读取当前策略，并用 `cpupower` 应用 `performance`。开启前保存各核心中出现最多的 governor，关闭时统一恢复该值。没有保存值时，应用从驱动支持的非性能策略中选择恢复值。点击「刷新状态」可重新读取当前策略。

CPU 策略备份位于 `~/.config/cpu-performance-mode/previous-state.json`。

## NVIDIA GPU 功率上限

1. 从下拉列表选择显卡，核对当前、最小和最大功率上限。
2. 在「目标上限」中输入瓦数，点击「应用上限」并完成授权。
3. 界面重新读取驱动的上限，显示实际应用值。点击「刷新 GPU」可同步外部工具的改动。

范围条表示当前上限在允许区间中的位置。要查看实际运行功耗，请看「SSH 与防挖矿」页的 GPU 0 读数。

## 入站 SSH

开启前，把对方的公钥加入本机目标账号的 `~/.ssh/authorized_keys`。在「SSH 与防挖矿」点「开启入站 SSH」，完成管理员授权。开启流程会写入并验证公钥认证配置，禁用密码、键盘交互和 root 登录，然后启动 `ssh.socket` 并设置开机启动。自定义 SSH 配置覆盖这些全局设置时，界面会显示错误。

开启后，对方可在可信网络连接本机。关闭时点同一个按钮「关闭入站 SSH」并授权。应用会停止 `ssh.socket` 和 `ssh.service` 并屏蔽其再次启动，已配置的公钥可用于下次开启。本机仍可主动 SSH 到其他电脑。

~~~bash
# 对方连接本机
ssh 本机用户名@本机局域网IP

# 本机连接其他主机
ssh 远程用户名@远程主机地址
~~~

也可以在本机终端选择执行开启或关闭命令，再核对默认 22 端口的监听。

~~~bash
sudo /usr/local/libexec/cpu-performance-mode-monitor/ssh-control enable
sudo /usr/local/libexec/cpu-performance-mode-monitor/ssh-control disable
ss -ltn '( sport = :22 )'
~~~

公钥认证片段位于 `/etc/ssh/sshd_config.d/00-cpu-performance-mode-key-only.conf`。如果配置包含针对账户或地址的 `Match` 规则，开启前也要核对对应连接的生效配置。

## SSH 日志与防挖矿

- SSH 日志来自 systemd journal。筛选项包括「成功登录」「全部记录」「失败与无效账号」，读取近 14 天内最近的记录，成功和失败类各最多读取 150 条。
- 后台以 SHA-256 核对已知样本。其他受支持的矿工需要同时匹配程序名、ELF 格式和文件特征。确认后，后台会终止对应进程，并在文件仅有一个硬链接时移除执行权限。处置不以 GPU 利用率作为判据。
- 状态文件为 `/run/cpu-performance-mode-monitor/status.json`，处置历史为 `/var/lib/cpu-performance-mode-monitor/actions.json`。系统监控按特征识别和处置矿工。已遭到 root 入侵的系统仍需从可信介质恢复。

~~~bash
systemctl status cpu-performance-mode-monitor.service
sudo journalctl -u cpu-performance-mode-monitor.service -n 50
~~~

## 更新、迁移与卸载

修改源码后，重新运行 `./install.sh`，关闭并重新打开应用以更新桌面版本。修改监控或 SSH 助手后，再运行 `sudo ./manage-monitor.sh install` 更新系统安装副本。

如果之前使用独立的 `ssh-login-monitor.service`，可用 `sudo ./manage-monitor.sh migrate` 迁移处置记录并切换到当前后台。

~~~bash
sudo ./manage-monitor.sh remove
./uninstall.sh
~~~

卸载后台会移除服务和助手。如需关闭本机入站 SSH，请先在界面上关闭。处置历史保存在 `/var/lib/cpu-performance-mode-monitor/`。

## 源码与测试

| 文件 | 用途 |
| --- | --- |
| [app.py](app.py) | GTK 窗口、三个独立页面的导航、CPU 与 GPU 界面以及主题样式。 |
| [cpu_mode_backend.py](cpu_mode_backend.py) | 读取、修改和恢复 CPUFreq governor。 |
| [gpu_power_backend.py](gpu_power_backend.py) | 查询 NVIDIA 显卡、校验并设置功率上限。 |
| [monitor_panel.py](monitor_panel.py) | SSH 开关、登录日志筛选和矿工处置界面。 |
| [ssh_control.py](ssh_control.py) | 管理员 SSH 开关助手。 |
| [system_monitor.py](system_monitor.py) | 后台 SSH 日志读取、GPU 采样与矿工处置。 |
| [install.sh](install.sh)、[manage-monitor.sh](manage-monitor.sh) | 分别部署当前用户的桌面应用和系统后台。 |

项目目录是源码的维护位置。桌面菜单运行用户数据目录下的副本，默认位于 `~/.local/share/cpu-performance-mode/`。系统后台和 SSH 助手安装在 `/usr/local/libexec/cpu-performance-mode-monitor/`，由 root 管理。

~~~bash
PYTHONPATH=. /usr/bin/python3 -m unittest discover -s tests -v
~~~
