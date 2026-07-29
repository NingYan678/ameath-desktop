# 爱弥斯 Hermes 桌面终端

爱弥斯是 Windows 上的 PySide6 桌宠，也是 Hermes 的原生桌面终端。桌宠负责显示和输入；人格、记忆、技能、工具、任务与操作确认由 Hermes Gateway 处理。

## 日常使用

安装后首次启动会打开设置向导，可选择 DeepSeek、OpenAI、OpenAI 兼容接口或本机 Ollama。模型密钥使用当前 Windows 用户加密保存，不会写入桌宠界面或普通日志。

- 桌面和开始菜单提供启动入口，桌宠也可以隐藏到系统托盘。
- 连接现有 Gateway 时，爱弥斯只使用桌宠专属平台插件，不修改 Hermes 的全局模型、人格或工具设置。
- Hermes 官方 `main` 每天最多检查一次；安装更新前会要求确认。共享 Hermes 使用官方更新器，内置 Hermes 使用独立版本槽并可回滚。
- 爱弥斯应用本身不自动升级，正式版通过受信任的安装包手动升级。
- 卸载时可以选择保留个人设置、记忆、凭据和 Hermes 更新槽。

## 开发运行

```powershell
cd 'E:\digital pet'
.\run.bat
```

开发模式使用显式配置的 Hermes 环境；正式安装包使用独立运行时和当前用户数据目录，不会读取或停止电脑上的其他 Hermes Gateway。

## 构建 1.1.0 离线安装包

需要 Windows、[uv](https://docs.astral.sh/uv/) 和 Inno Setup 6。必须使用干净的 Hermes Git 检出，并且提交必须等于 `packaging/build_release.py` 中声明的基线。

```powershell
python .\packaging\build_release.py --hermes-source 'C:\path\to\clean\hermes-agent'
```

构建脚本会在临时目录准备 PyInstaller 前端、便携 Python、Hermes 源码和白名单素材；成功或失败后都会清理 staging。最终文件位于 `dist/Ameath-1.1.0-offline-setup.exe`。

安装包未进行 Windows 代码签名。发布页会同时提供 SHA-256 校验文件，首次运行时 Windows 可能显示“未知发布者”。

## 项目边界与许可

Hermes 的技能、记忆、工具和操作确认仍由 Hermes Gateway 管理，桌宠不另建任务或权限系统。项目代码使用 MIT 许可证，详见 [LICENSE](LICENSE)。角色名称、角色图像、音频和 `assets/recovered/` 中的衍生素材不包含在代码许可证内，详见 [NOTICE.md](NOTICE.md)。

版本变更记录见 [CHANGELOG.md](CHANGELOG.md)，发布验收步骤见 [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md)。
面向普通用户的完整安装、日常操作、Hermes 更新、隐私与故障排查说明见 [docs/USER_GUIDE.md](docs/USER_GUIDE.md)。

## 1.1.0 说明

- 爱弥斯主动提问可通过气泡中的“回应”进入聊天；回答会以一次性的 `proactive_reply` 上下文发送给 Hermes。
- 记忆提示默认关闭。明确授权后，Hermes 只能返回短暂的兴趣、目标或话题提示；桌宠只保存哈希和过期时间，不读取屏幕、窗口标题、文件、日历或原始记忆。
- 锁屏、休眠和低功耗时会暂停主动互动与非必要动画；“减少动画”会保留静态待机、拖动反馈、聊天和错误状态。
- 爱弥斯应用更新只跟踪 `NingYan678/ameath-desktop` 的正式 Release，下载前确认，安装包必须通过 SHA-256 校验。Hermes 更新仍是独立流程。
- 当前版本没有可用代码签名证书时会发布未签名安装包，Windows 可能显示“未知发布者”；请使用随包 `.sha256` 文件核对下载结果。
