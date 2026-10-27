<div align="center">

<img src="assets/icon.png" width="120" alt="ColorHide 图标">

# ColorHide

**把彩色照片打印成看起来普通的黑白照片；扫描后，颜色又回来了。**

[English](README.md) · [下载](https://github.com/TonyD365/ColorHide/releases/latest)

<img src="assets/compare.png" alt="原图、黑白打印件、扫描还原的彩色">

</div>

## 这是什么

黑白打印便宜又随处可见，彩色打印却不是。ColorHide 把照片的颜色藏在**打印网点的微观排列**里：
肉眼看到的只是一张普通的灰度照片，扫描仪却能把颜色读回来。没有密钥，也不加密，格式完全公开，任何人都能解码。

## 功能

- 🖨️ 打印机外观的桌面应用，支持 macOS、Windows、Linux
- 🎨 **隐藏颜色**：生成黑白打印页；**还原颜色**：从扫描件恢复彩色
- 🖨️ 带实时预览的内置打印面板：目标打印机（或另存为 PDF）、份数、布局、颜色、纸张、每张纸页数、页边距、缩放、双面、页眉页脚，以及打印机驱动的全部选项；按 100% 比例直接打印
- 🔍 直接从扫描仪或打印扫描一体机扫描，也能导入 PDF 或图片
- 💾 还原后的彩色图可导出为 PDF、PNG、JPEG、TIFF、WebP、HEIC 等格式
- 🧠 可选的神经网络精修（ONNX，CPU 即可运行）
- 🛡️ Reed-Solomon 纠错码加冗余，扛得住污渍、歪斜和扫描噪声
- 📦 真正的安装包：Mac `.pkg`（装进「应用程序」）、Windows 安装程序、Linux `.deb`
- 🔄 自动更新到最新的 Release（使用同样的安装包），并校验 SHA-256

## 安装

从 [Releases](https://github.com/TonyD365/ColorHide/releases/latest) 下载对应系统的安装包：

| 系统 | 安装包 | 安装位置 |
|---|---|---|
| macOS（Apple 芯片 / Intel） | `ColorHide-版本-macos-arm64.pkg` / `-macos-x64.pkg` | 「应用程序」文件夹 |
| Windows 10/11 | `ColorHide-版本-windows-x64-setup.exe` | 当前用户的程序目录（也可选所有用户），带开始菜单和卸载程序 |
| Ubuntu / Debian | `ColorHide-版本-linux-x64.deb` | `/opt/ColorHide`，带应用菜单图标 |

**macOS**：打开 `.pkg`，第一次会被系统拦截。到「系统设置 → 隐私与安全性」往下找到「仍要打开」，然后按安装器提示完成，应用会装进「应用程序」。只需要一次，之后的自动更新不用输密码。

**Windows**：运行 `setup.exe`。如果出现 SmartScreen 提示，点「更多信息 → 仍要运行」。

**Ubuntu / Debian**：`sudo apt install ./ColorHide-*.deb`，或直接双击安装。扫描功能需要 `sudo apt install sane-utils`；自动更新时会请你输入密码。

## 打印和扫描建议

- 用打印机的原生分辨率（600 dpi）、**100% 缩放**打印，关闭「适合页面」和照片增强。激光打印机效果最好。
- 扫描时选**灰度、1200 dpi**（至少 900），关闭锐化和去网纹。

## 原理

| 层 | 作用 |
|---|---|
| 数据网点 | 每个像素对应一个 4×4 的打印点格子。墨点**数量**决定灰度，墨点重心偏向**哪个角**携带 2 bit 数据；格子内的墨点按原图细节摆放，边缘更清晰 |
| 色度载荷 | 颜色压到 1/8 分辨率、6 bit，加 Reed-Solomon 纠错码，在整页重复多次，并用固定公开的置乱分散到各处 |
| 神经网络精修 | 用 DIV2K 数据集、经过模拟打印扫描训练的小型 U-Net。逐个打印点读取扫描件，输出 **2 倍分辨率**的彩色图（600 dpi 打印对应 300 ppi），并去颗粒、修正墨粉扩散、锐化颜色 |

技术细节、命令行用法和训练方法见[英文说明](README.md)。

## 许可证

[Apache-2.0](LICENSE)。可以自由使用、修改和分发，包括商业用途。
