# 本地使用与 Codex 插件加载

解压后先在包含 `plugin.json` 的 FrameCheck 目录运行：

```text
python scripts/framecheck_cli.py demo --out ../framecheck-demo
```

无需安装 Python 依赖或配置 API 密钥。这条命令可独立使用，不要求 Codex 安装插件。

0.2.0 新增引导接入。日常使用时可以直接说“帮我检查当前项目的串口解析器”，无需先准备 JSON 用例或适配器。Codex 会根据指定项目查找相关代码，只追问影响测试结果的缺失规则，再准备测试。只有项目不在当前工作区或尚不明确时，才需要先提供项目路径。详见 [引导式开始](getting-started.md)。

## 可选板卡工具环境

`board-info` 需要可选 `board` 依赖；推荐复用独立工具环境或创建虚拟环境，详见 [接板信息入口](board-intake.md)。不影响现有标准库解析器测试，也不会自动安装或更新当前 Codex 插件。可先查看 [验证记录](validation.md)，再按下面的方式加载插件。

真实 `serial-run` 使用独立的可选 `serial` 依赖，或复用已有 `board` 环境；其 `--dry-run` 无需依赖。详见 [串口验收入口](serial-exchanges.md)。

## 在 Codex 中试用

本目录已经附带 `plugin.json`、`skills/framecheck/SKILL.md`、本地市场文件 `.agents/plugins/marketplace.json` 和项目启用配置 `.codex/config.toml`。本地市场指向当前目录 `./`，所有代码与技能会一起分发。

在支持本地插件市场的 Codex 客户端中，把这个目录作为受信任的项目打开，然后按客户端要求重新加载或重启，查看插件列表中的“FrameCheck 解析器验收”。安装/启用后，可输入“用 FrameCheck 演示解析器回归测试”。如果当前客户端没有加载本地市场，可直接让 Codex 阅读本目录的 `skills/framecheck/SKILL.md` 并执行演示；CLI 功能相同。

如果放入已有代码仓库，建议复制到 `plugins/framecheck/`，然后将仓库根目录 `.agents/plugins/marketplace.json` 的对应条目设置为：

```json
{
  "name": "framecheck-local",
  "plugins": [{
    "name": "framecheck",
    "source": {"source": "local", "path": "./plugins/framecheck"},
    "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
    "category": "Productivity"
  }]
}
```

已有市场文件应合并条目，不要覆盖其他插件。项目 `.codex/config.toml` 可添加：

```toml
[plugins."framecheck@framecheck-local"]
enabled = true
```

路径相对于仓库/市场根目录，配置在受信任项目中生效。加载方式参考 [OpenAI 官方插件打包文档](https://developers.openai.com/plugins/build/plugins)。是否已经安装、启用，以当前客户端的插件列表为准；解压测试包本身不会自动安装插件。当前尚未上架官方插件目录。

## 源码与验证

源码仓库：[yangyiqun747/framecheck](https://github.com/yangyiqun747/framecheck)。项目使用 MIT 许可证，当前为开发预览版，尚未发布到 PyPI 或官方插件目录。仓库不包含板端固件、本机编译产物或个人日志。

建议先用自己的协议完成失败输入 → 修复 → 重放 → 全套回归。已有验证的范围与限制见 [验证记录](validation.md)。演示报告中的错误解析器是刻意构造的教学实现。
