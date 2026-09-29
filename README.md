# aseprite-PerfectPixel

> **AI 像素画点阵逆向还原、智能抠图与色彩量化工具**  
> 原生集成 **Aseprite 官方扩展插件** 与 **独立高性能 CLI 命令行工具**。

---

## 🌟 核心特性

- **🎯 AI 点阵逆向 1:1 还原**：基于频域与边缘梯度检测（Sobel），将 Midjourney、DALL-E、Gemini 等 AI 生成的模糊抗锯齿“假大图”，精准还原为对齐的 1:1 真实像素原稿。
- **🎨 Aseprite 原生插件集成**：
  - 在 Aseprite 中点击顶栏【图像 (Sprite)】或【编辑 (Edit)】即可随时唤起。
  - 支持 **“新建 Sprite 打开”** 或 **“作为新图层插入当前画布”**。
  - **100% 纯静默后台执行**：彻底消除 Windows 终端弹窗与黑框闪烁。
  - **免解压秒级运行**：响应速度快达 300 毫秒以内，消除任何界面假死感。
- **🪄 智能外部连通抠图（保护内部同色）**：
  - 基于边界连通泛洪算法，只扣除与画面边缘相通的外部背景。
  - **绝不掏空角色内部的眼白、高光、牙齿或白色衣服**！
- **✨ 边缘晕染杂边清理（Defringe）**：
  - 自动识别并切除 AI 扩散模型在外轮廓与背景之间产生的半透明浅灰/过渡光晕，保证导出后轮廓线纯净锋利。
- **🌈 OKLab 感知色彩量化**：
  - 支持指定调色板最大颜色数（如 16 色、32 色），优先保证角色主体色相精度。
- **⚡ 跨平台 & 批处理 CLI**：
  - 提供独立命令行接口，便于接入 CI/CD 流水线、游戏引擎（Unity/Godot）自动化导入工具或批处理脚本。

---

## 📦 Aseprite 扩展安装与使用

### 1. 下载与安装

1. 前往本仓库的 [Releases 页面](https://github.com/myrootwxs/aseprite-PerfectPixel/releases) 下载最新的 `perfect-pixel-v1.0.0.aseprite-extension`；
2. **方法 A（推荐）**：直接在操作系统中双击 `.aseprite-extension` 文件，Aseprite 会自动弹窗询问安装，点击 **“启用 (Enable)”** 即可；
3. **方法 B**：打开 Aseprite，进入菜单 **编辑 (Edit) $\rightarrow$ 首选项 (Preferences) $\rightarrow$ 扩展 (Extensions)**，点击 **添加扩展 (Add Extension)** 并选择该文件。

### 2. 在 Aseprite 中使用

1. 打开需要处理的图片（例如一张 AI 生成的 2048×2048 像素风图片）；
2. 点击顶栏菜单：
   - **【图像 (Sprite)】 $\rightarrow$ 【PerfectPixel 像素精修...】**（最顺手位置）
   - 或 **【文件 (File)】 $\rightarrow$ 【脚本 (Scripts)】 $\rightarrow$ 【PerfectPixel 像素精修...】**
   - 快捷键：随时按 <kbd>Ctrl</kbd> + <kbd>Space</kbd> 输入 `PerfectPixel` 唤出；
3. 根据需要调节网格宽/高（留 0 为自动检测）、采样方式、最大颜色数与智能背景抠图选项；
4. 点击 **【开始精修】**，后台瞬间完成处理并载入！

---

## 💻 命令行 CLI 用法

无需打开任何绘图软件，直接在终端中进行单图精修或批量处理。

### 常用命令示例

```bash
# 1. 基础自动精修（自动检测真实点阵网格，输出 1:1 原稿）
perfect_pixel_cli.exe input.png -o output.png

# 2. 强制指定目标网格尺寸（例如 128x128）并限制 16 色
perfect_pixel_cli.exe input.png -o output.png --grid-w 128 --grid-h 128 --max-colors 16

# 3. 自动吸取背景色 + 仅外部连通抠图（保护内部白眼球）+ 消除边缘白边
perfect_pixel_cli.exe input.png -o output.png --bg-color auto --bg-mode contiguous --bg-defringe

# 4. 指定放大倍数导出（例如 4x 最近邻放大，便于社交平台清晰展示）
perfect_pixel_cli.exe input.png -o output_4x.png --scale 4

# 5. 输出 JSON 元数据供脚本/工作流读取
perfect_pixel_cli.exe input.png -o output.png --json
```

### CLI 参数完整列表

| 参数 | 说明 | 默认值 |
| :--- | :--- | :--- |
| `input` | 输入图片路径 | 必填 |
| `-o, --output` | 输出图片 PNG 路径 | 必填 |
| `--grid-w, --grid-h` | 目标网格宽和高（`0` 为全自动检测） | `0` |
| `--sample-method` | 单元格内取样方式（`center`、`majority`、`median`） | `center` |
| `--max-colors` | 调色板最大颜色数上限（`0` 为不限制） | `0` |
| `--color-space` | 色彩感知空间（`OKLab` 或 `RGB`） | `OKLab` |
| `--scale` | 输出图像放大倍数（`1` 为 1:1 物理像素点阵，`>1` 为最近邻无损放大） | `1` |
| `--bg-color` | 目标背景颜色（十六进制如 `#ffffff`，或 `auto` 自动检测） | 无 |
| `--bg-tolerance` | 背景色判定容差 | `30.0` |
| `--bg-mode` | 抠图模式：`contiguous`（仅外部连通）或 `global`（全图匹配） | `contiguous` |
| `--bg-defringe` | 消除外轮廓边缘半透明过渡晕染（`--no-bg-defringe` 关闭） | 开启 |
| `--json` | 以 JSON 格式输出处理后的尺寸、颜色数等信息 | 否 |

---

## 🛠️ 本地开发与打包

### 环境准备

```powershell
# 1. 创建虚拟环境并安装依赖
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\pip install pyinstaller
```

### 编译 CLI 与重新生成 Aseprite 扩展包

```powershell
# 1. 编译高性能免解压的 CLI 二进制目录
.\.venv\Scripts\pyinstaller --noconfirm perfect_pixel_cli.spec

# 2. 一键打包生成 official .aseprite-extension
.\.venv\Scripts\python tools/build_extension.py
```

打包成功后，输出文件位于：
`out/perfect-pixel-v1.0.0.aseprite-extension`

---

## 📄 开源许可

- 本项目遵循 **MIT License**。
- 核心点阵检测算法基于 [theamusing/perfectPixel](https://github.com/theamusing/perfectPixel) 改进扩展。
