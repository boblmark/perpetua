# Perpetua 编译版分发说明

## 防源码泄露方案

本包使用 **Nuitka** 将 Python 源码编译为机器码二进制文件：
- 源码（.py）→ C 代码 → 机器码可执行文件
- 二进制中不包含可读的 Python 源码
- 反编译难度极高（需从汇编逆向，与手写 C 程序相当）

### 安全级别
| 方案 | 源码可见性 | 逆向难度 |
|---|---|---|
| 直接发 .py | 完全可见 | 无 |
| PyInstaller 打包 | 字节码 .pyc 可提取 | 中（有反编译工具） |
| **Nuitka 编译（本方案）** | 无源码，仅机器码 | 极高 |

### 注意事项
1. Nuitka 不是 100% 防逆向，但已达到商业软件常规保护水平
2. 字符串常量（如 API 端点、提示词模板）仍可见于二进制中，敏感 key 不要硬编码
3. 建议配合：Token 轮换机制 + 服务端鉴权 + 法律协议（授权许可）

## 包结构

```
perpetua-linux/
├── perpetua-mcp          # 主程序（二进制，MCP 服务器）
├── perpetua-trend         # 趋势检测（二进制）
├── install.sh            # 一键安装脚本
├── systemd/
│   └── perpetua-mcp-binary.service
└── README.md             # 本文件

perpetua-windows/
├── perpetua-mcp.exe      # 主程序（需在 Windows 上构建）
├── install.bat           # 一键安装脚本
└── README_WINDOWS.md
```

## 构建方法

### Linux（本机可构建）
```bash
cd /home/hatch/data/perpetua/deploy
bash build_binary.sh
```

### Windows（需在 Windows 机器上）
```cmd
cd perpetua\deploy\windows
build.bat
```

## 版本管理
- 每次发版重新编译，更新 VERSION
- 二进制与源码版本一一对应，记录在案
