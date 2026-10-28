<p align="center">
  <img src="docs/images/social-preview.png" alt="YTKTV：把任何电脑变成 KTV" width="820">
</p>

<p align="center">
  <a href="https://github.com/TonyD365/YTKTV/releases/latest"><img alt="最新版本" src="https://img.shields.io/github/v/release/TonyD365/YTKTV?color=ff2d95"></a>
  <a href="https://github.com/TonyD365/YTKTV/releases"><img alt="下载量" src="https://img.shields.io/github/downloads/TonyD365/YTKTV/total?color=8a5cff"></a>
  <img alt="平台" src="https://img.shields.io/badge/platform-macOS%20%7C%20Windows%20%7C%20Linux-22d3ee">
  <a href="LICENSE"><img alt="许可证：免费使用，不得出售" src="https://img.shields.io/badge/license-free%20to%20use%2C%20not%20for%20sale-ffc94a"></a>
</p>

<p align="center">
  <a href="https://github.com/TonyD365/YTKTV/releases/latest"><b>⬇️ 下载</b></a> ·
  <a href="https://tonyd365.github.io/YTKTV/">官网</a> ·
  <a href="docs/guide/README.md">使用指南（英文）</a> ·
  <a href="#快速开始">快速开始</a> ·
  <a href="#功能">功能</a> ·
  <a href="#常见问题">常见问题</a> ·
  <a href="README.md">English</a> ·
  <a href="https://github.com/TonyD365/YTKTV/issues/new/choose">反馈问题</a>
</p>

**YTKTV 把一台电脑和一台电视变成 KTV 包厢。** YouTube 上的每一首歌都在点歌本里。电视上放 MV 和卡拉 OK 歌词，AI 把原唱的人声从歌里去掉，朋友们用手机扫码点歌（不用装 App），一台外观和用法都像真硬件的调音台把你的麦克风叠加上去，带回声和混响。免费，支持 macOS、Windows 和 Linux。

> 程序界面目前是英文的，中文界面在[计划](#计划)里。

<p align="center">
  <img src="docs/images/demo.gif" alt="唱歌时的 MV 屏幕：歌词逐字变色、音高线上画出歌声、弹幕飘过、氛围灯闪动" width="860">
  <br><sub>MV 屏幕：跟着歌手逐字变色的歌词、音高线、实时分数、弹幕和氛围灯。</sub>
</p>

## 亮点

| | |
|---|---|
| 🎵 **YouTube 上的歌都能唱**<br>搜索、粘贴链接或看热门榜，播放没有广告。 | 🎤 **任何歌都有原唱和伴奏**<br>AI 在后台分离人声，有显卡就用显卡。切换无缝。 |
| 📱 **手机就是遥控器，也能当麦克风**<br>扫码点歌；手机还能直接接进调音台当麦克风。 | 🎚️ **像真的一样的调音台**<br>四路麦克风，带 EQ、压缩、回声、混响和防啸叫。 |
| 🏆 **实时音高和打分**<br>边唱边看自己的音高线，唱完看本场排行榜；对唱时各自打分。 | ✨ **KTV 氛围**<br>卡拉 OK 歌词、导唱、升降调和变速、弹幕、鼓掌欢呼音效、氛围灯。 |

| 点歌台 | 调音台 |
|---|---|
| ![点歌台首页：正在播放、下一首和功能大瓷砖](docs/images/console.png) | ![四个通道的调音台](docs/images/mixer.png) |
| ![派对页：弹幕、表情和气氛音效](docs/images/party.png) | ![小游戏：骰子、谁唱下一首、真心话大冒险](docs/images/games.png) |

<p align="center">
  <img src="docs/images/phone.png" alt="手机页面：我点的歌和等待时间、本场最佳；以及播放、歌词和人声控制" width="560">
  <br><sub>手机页面：我点的歌和要等多久、本场最佳，以及遥控。</sub>
</p>

## 快速开始

1. 从[最新版本](https://github.com/TonyD365/YTKTV/releases/latest)下载对应系统的安装包并安装（macOS 需要先执行一条 `xattr` 命令，见下面的[安装](#安装)）。
2. 把电视作为第二块屏幕接上，**尽量用 HDMI 线**（原因见[常见问题](#常见问题)），然后打开 YTKTV。第一次启动会有一个简短的向导，选音箱、选屏幕、试麦克风。
3. 用手机扫屏幕上的二维码，点首歌，开唱。

如果 YTKTV 让你们的聚会更开心，在 GitHub 上点个 ⭐ 能帮更多人找到它。

## 安装

| 系统 | 文件 |
|---|---|
| macOS（Apple 芯片和 Intel） | `YTKTV-<版本>-macos-universal.pkg` |
| Windows 10/11（64 位） | `YTKTV-<版本>-windows-x64-setup.exe` |
| Linux（x86-64） | `YTKTV-<版本>-linux-x86_64.AppImage` |

安装包还没有付费签名。**macOS** 上打开安装包前，先在"终端"里去掉下载隔离标记：

```bash
xattr -d com.apple.quarantine ~/Downloads/YTKTV-<版本>-macos-universal.pkg
```

装好后如果仍提示"已损坏"或"无法打开"，再执行 `sudo xattr -dr com.apple.quarantine /Applications/YTKTV.app`。**Windows** 上如果 SmartScreen 拦截，点"更多信息 → 仍要运行"。

**YTKTV 会提示安装 mpv。** YTKTV 用 [mpv](https://mpv.io) 播放视频，它是另一个以 GPL 发布的免费软件，不属于 YTKTV，也不在 Release 里。启动时如果找不到 mpv，程序会提示用你系统惯用的方式安装：macOS 用 [Homebrew](https://brew.sh) 执行 `brew install mpv`（没有 Homebrew 会告诉你怎么装，装好后点"Check Again"）；Windows 从 [mpv.io](https://mpv.io/installation/) 列出的 Windows 版下载；Linux 用系统的包管理器安装（会要求输入密码）。已经下载过 mpv 的 1.4、1.5 版用户不受影响。

人声分离：Apple 芯片的 Mac 内置，用 GPU；Windows 和 Linux 第一次运行时按显卡自动下载（NVIDIA、Windows 上的其他 DirectX 12 显卡，或者纯 CPU）；Intel Mac 暂不支持 AI 分离，但"消人声"和左右声道模式可用。

## 功能

- **点歌**：搜索有联想和历史记录，歌手页按地区分类，热门榜，YouTube 链接直接点，歌单和导入 YouTube 播放列表。
- **原唱 / 伴奏**：AI 分离，两条音轨同时播放，切换无缝；导唱滑块可以保留一部分原唱。分离好的伴奏会缓存，同一首歌下次不用再等。
- **歌词**：用视频的字幕，没有就用 YouTube 自动字幕；颜色逐字跟随演唱，歌词偏早偏晚可以按 0.1 秒微调，按歌记住。
- **打分**：边唱边显示音高线，金色表示唱准了；唱完显示分数和本场排行榜，对唱时每支麦克风单独打分。不同八度唱也算对。
- **调音台**：四路麦克风，增益、三段 EQ、压缩、回声、混响、声像、推子、静音；效果预设（流行、抒情、摇滚、KTV 大厅、干声，以及自己保存的）；防啸叫分关、低、中、高四档。
- **手机**：扫码点歌、遥控、调麦克风；每部手机能看到自己点的歌还要等多久；手机还能直接当麦克风用。
- **氛围**：弹幕（电脑和手机都能发）、鼓掌欢呼等音效按钮、随音乐变化的氛围灯。
- **其他**：升降调（±6 个半音）、变速、播放队列拖动排序、自动更新。

## 常见问题

**免费吗？可以拿来开 KTV 或酒吧吗？**
都可以。YTKTV 免费，[许可证](LICENSE)允许商用，比如开 KTV；不允许的是出售这个软件本身或它的修改版。另外，在公开场所放音乐通常需要向版权方取得许可，这和软件许可证是两回事。

**需要联网吗？**
需要，歌曲来自 YouTube。队列里接下来的几首会提前下载，所以网络短暂断一下一般听不出来。

**我的声音从音箱出来有延迟，怎么回事？**
几乎都是因为用了无线音箱。AirPlay 本身会延迟 1–2 秒，蓝牙会延迟几百毫秒，这是它们的工作方式，任何设置都改不了。用线把音箱或电视接上（HDMI、USB 或耳机口），然后在 **Mixer → MAIN OUT** 里选它。

**没有显卡能用伴奏吗？**
能。Apple 芯片的 Mac 用自带 GPU；Windows 和 Linux 没有合适的显卡就用 CPU，慢一些，但能用。

**手机打开麦克风页面时提示证书不安全？**
浏览器只允许在加密（HTTPS）页面上使用麦克风，而家庭网络里没法拿到手机信任的证书，所以 YTKTV 自己生成了一个。页面只在你的局域网里，选择继续访问一次即可。

**遇到问题？**
请[提交一个 issue](https://github.com/TonyD365/YTKTV/issues/new/choose)，写上版本、系统和发生了什么。中文英文都可以。

## 计划

- 房间 PIN：只有包厢里的人能切歌和调音
- 离线歌库：把唱过的歌连同伴奏留在本机，没网也能唱
- 录音：把刚唱的歌带走
- 中文界面
- 签名的安装包，不再需要 `xattr` 和 SmartScreen 确认

## 许可证与声明

YTKTV 按 [YTKTV License](LICENSE) 发布：可以免费使用、复制、修改和分享，也可以商用（比如开 KTV）；不能出售软件本身、修改版或分支版本。以许可证原文为准。1.3.3 及更早的版本仍按 MIT 许可证提供。

YTKTV 是独立的个人项目，与 YouTube 和 Google 没有关联。它不托管、不分发任何音乐或视频，只是在你自己的电脑上通过 yt-dlp 和 mpv 播放 YouTube 视频。这样播放可能不符合 YouTube 的服务条款；歌曲的版权使用取决于你所在的地方和唱歌的场所，由使用者自己负责。详见英文 [README](README.md#disclaimer)。
