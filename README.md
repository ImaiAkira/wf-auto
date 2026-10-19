<!-- markdownlint-disable MD033 MD041 -->
<div align="center">

# 弹射世界国服自动化（WF-Auto）

《弹射世界》国服（雷霆）的日常自动化 —— 主线、外传、副本、领主战、五重决战、扭蛋，一键托管。

[![Release](https://img.shields.io/github/v/release/ImaiAkira/wf-auto?include_prereleases&style=flat-square)](https://github.com/ImaiAkira/wf-auto/releases)
[![License](https://img.shields.io/github/license/ImaiAkira/wf-auto?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-0078d4?style=flat-square)](#系统要求)
[![Powered by](https://img.shields.io/badge/powered%20by-MaaFramework-important?style=flat-square)](https://github.com/MaaXYZ/MaaFramework)

</div>

---

## 三步上手

**不需要安装 Python，不需要装 git，不需要编译。**

1. **下载** —— 到 [Releases](https://github.com/ImaiAkira/wf-auto/releases) 页面下载最新的
   `wf-auto-win-x86_64-<版本>.zip`
2. **解压** —— 解压到任意目录（**路径不要带中文和空格**，例如 `D:\wf-auto`）
3. **双击** —— 双击目录里的 `双击启动.bat`（或直接双击 `MFAAvalonia.exe`）

第一次启动后，在界面里把**设备地址**填上（模拟器默认 `127.0.0.1:16384`），选一个任务，开始。

> **首次运行可能会先要装一个运行时。** 图形界面基于 .NET 10（和 MAA 一样）。
> `双击启动.bat` 会先检测；没有就自动调用包内的 `DependencySetup_依赖库安装_win.bat` 装好
> （需要联网，用 winget）。装完再双击一次即可。

> 想升级？下载新版 zip，解压后覆盖到**同一个目录**即可 —— `config/` 里的设置会保留。

## 系统要求

| 项 | 要求 |
|---|---|
| 系统 | Windows 10 / 11（64 位） |
| 运行时 | **.NET 10 桌面运行时** + VC++ 运行库 —— 包内 `DependencySetup_依赖库安装_win.bat` 一键安装 |
| 游戏 | 《弹射世界》国服（雷霆），安卓端或模拟器 |
| 设备 | MuMu 模拟器 / 雷电 / 夜神，或一台开了 USB 调试的安卓机 |
| 分辨率 | 识别工作在 **720 短边**空间；1080p 手机/模拟器**不需要改**分辨率 |
| 设备型号 | **不做匹配** —— 任何型号都能跑（型号只写进日志方便排查） |

## 能干什么

| 任务 | 说明 |
|---|---|
| 五重决战 | 自动打五重决战，支持自动/手操、单人/多人、续关次数、目标次数 |
| 自动刷副本 | 按副本 + 难度刷，支持单人/多人、招募要求、打满或指定次数 |
| 自动刷深渊EX | 深渊EX 的连续战斗 |
| 自动刷深渊 | 普通深渊，与深渊EX 同一套引擎、只差导航 |
| 自动过主线 | 一路推主线，卡关有界停止 |
| 自动过外传 | 清外传故事列表里的未通关关卡 |
| 切编队 | 按 SET / 队伍横向滑动切换，三重校验 |
| 扭蛋箱抽取 | 扭蛋箱抽空 |
| 扭蛋（抽卡） | 按配置抽卡 |
| 唤醒 / 恢复游戏 | 卡死、掉线、回登录页时重启并归位 |

共用的护栏：体力不足自动用星岛石恢复；战斗失败走 GAME OVER 恢复；页面识别不到时有界停止而不是无限空转；
每个任务结束都会**归位回主城**。

## 常见问题

**连不上设备？**
先确认模拟器已经开了 ADB 调试，`adb devices` 能看到设备；再确认地址填的是 `127.0.0.1:端口`
（MuMu 默认 `16384`，多开时逐个递增）。端口会在模拟器重启后漂移，工具会自动按账号身份重新发现。

**游戏更新后识别不到页面？**
游戏 UI 变了就需要更新资源，等新版 Release。若连续多个页面识别失败，工具会**有界停止**而不是乱点。

**杀毒软件报毒？**
MaaFramework 与 GUI 外壳是常见的误报对象（无签名 + 模拟输入）。加白名单，或从官方 Release 重新下载核对。

**日志在哪？**
`debug/` 目录下；GUI 里也能直接看。

## 免责声明

本项目仅用于**个人学习与自动化操作**，与游戏官方无任何关联。使用本工具可能违反游戏的用户协议，
**由此产生的任何后果（包括但不限于封号）由使用者自行承担**。请自行评估风险。

## 鸣谢

- [MaaFramework](https://github.com/MaaXYZ/MaaFramework) —— 识别与调度引擎
- [MFAAvalonia](https://github.com/SweetSmellFox/MFAAvalonia) —— 通用 GUI 外壳
- [MaaPracticeBoilerplate](https://github.com/MaaXYZ/MaaPracticeBoilerplate) —— 项目骨架

## 参与开发

- [`AGENTS.md`](AGENTS.md) —— 本仓的 agent 协作约定
- [`GLOSSARY.md`](GLOSSARY.md) —— 领域词汇表（页面 / 场景 / 任务 / 入口 / 归位 / 事件）
- [`docs/adr/`](docs/adr) —— 架构决策记录
- [`docs/guide/`](docs/guide) —— 架构与 pipeline 指南

<a href="https://github.com/ImaiAkira/wf-auto/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=ImaiAkira/wf-auto&max=1000" />
</a>
