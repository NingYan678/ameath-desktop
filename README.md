# 爱弥斯 Hermes 桌面终端

爱弥斯是一个 Windows 本地运行的 PySide6 桌宠，也是 Hermes 的原生桌面终端。桌宠只负责显示和输入；人格、记忆、技能、工具、任务与操作确认全部由同一个 Hermes Gateway 处理。

## 日常使用

个人安装包安装后会自动打开首次设置：选择 DeepSeek、OpenAI、OpenAI 兼容接口或本机 Ollama，填写必要信息并测试连接。完成后爱弥斯会启动自己的 Hermes 内核，不会读取、修改或停止电脑上已有的 `D:\hermes`。

- 桌面与开始菜单都有“启动爱弥斯”入口。
- 模型密钥使用 Windows 当前账户加密保存，不会显示在桌宠设置或日志中。
- 在设置页可重新打开“配置模型服务”。
- 卸载时可选择保留个人设置、记忆与任务，方便日后恢复。
- 当前版本不提供自动更新；请从受信任的个人安装包手动升级。

本项目中的游戏提取素材仅用于个人本地安装包；请勿公开发布或重新分发 `assets/recovered/` 与 `_reference/`。

## 开发运行

```powershell
cd 'E:\digital pet'
.\run.bat
```

开发模式会继续使用你显式配置的 Hermes 环境；正式安装包使用完全独立的运行时与当前用户数据目录。

## 构建个人安装包

需要 Windows、[uv](https://docs.astral.sh/uv/) 与 Inno Setup 6。离线包会从指定 Hermes 源码构建一个裁剪后的独立运行时；联网包要求填写该运行时压缩包的受信 URL 和 SHA-256。

```powershell
python .\packaging\build_release.py --mode offline
python .\packaging\build_release.py --mode online --runtime-url 'https://your-private-host/Ameath-Hermes-runtime.zip' --runtime-sha256 '<sha256>'
```

生成的安装程序位于 `dist/`。联网版安装时会校验运行时 SHA-256 后才解压；离线版无需网络。Hermes 按 MIT 许可证随个人安装包附带。
