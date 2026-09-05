# CPU 性能模式

一个面向 Ubuntu/Linux 桌面的原生 GTK 4 小工具。打开开关时把 CPUFreq governor 设为 `performance`，关闭时恢复开启前的 governor。

它只修改 CPU 自身的调频策略，不调用 `powerprofilesctl`，不会切换整机电源模式，也不会改变屏幕、显卡或其他设备的电源策略。

## 安装到桌面

```bash
cd cpu-performance-mode
./install.sh
```

安装后可从应用列表搜索“CPU 性能模式”；如果系统存在桌面目录，也会创建桌面快捷方式。安装过程不需要管理员权限。

## 工作方式

- 通过 `pkexec cpupower frequency-set --governor ...` 修改 Linux CPUFreq governor，系统会显示管理员授权窗口。
- 开启前会记录当前 governor，因此关闭性能策略时可以恢复，而不是固定覆盖为某个策略。
- 性能模式通常会增加功耗、温度和风扇噪声。

Ubuntu 通常已包含 GTK 4。如果系统没有 `cpupower`，可安装：

```bash
sudo apt install linux-tools-common linux-tools-generic
```

## 直接运行与卸载

```bash
/usr/bin/python3 app.py
./uninstall.sh
```

## 测试

```bash
PYTHONPATH=. /usr/bin/python3 -m unittest discover -s tests -v
```
