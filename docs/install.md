# 安装与首次验收

第一次使用先跑通本地演示，再加载 Codex 插件；不需要板卡、传感器或 API 密钥。宿主 Python 演示只需要 Python 3.10+，不需要安装第三方包。当前源码为开发预览版，尚未上架官方插件目录或 PyPI。

## 1. 下载到一个固定目录

打开 [FrameCheck 仓库](https://github.com/yangyiqun747/framecheck)，选择 **Code → Download ZIP**，解压到准备长期保留的位置。也可以克隆：

```console
git clone https://github.com/yangyiqun747/framecheck.git
cd framecheck
```

ZIP 用户进入解压后的源码根目录。应能看到 `plugin.json`、`framecheck/`、`scripts/`、`skills/` 和 `.agents/`；不要只下载单个技能文件。下面的命令都在这个根目录运行。路径包含空格时，在命令里用引号包住完整路径。

## 2. 先确认本地工具能工作

```console
python --version
python scripts/framecheck_cli.py --version
python scripts/framecheck_cli.py demo --out ../framecheck-first-demo
```

Windows 如果 `python` 不存在，可先试 `py -3 --version`，再将命令中的 `python` 换成 `py -3`；使用已有的 Python 3.10+ 即可。输出目录放在源码外，不要将自己工程的目录作为演示输出目录。

**成功判据：**命令最后显示“演示自检: 通过”，并生成 `../framecheck-first-demo/index.html`。打开它：正确解析器应全部通过，四个刻意构造的故障版本应分别暴露对应问题。故障版本的失败是演示预期，不能当作你的设备测试结果。

这一步不证明插件已加载；下面再检查 Codex 安装。

## 3. 将插件加入 Codex

官方支持通过本地市场分发插件；市场登记、安装与项目启用各有作用，客户端支持情况可能不同。参见 [OpenAI 官方插件打包文档](https://developers.openai.com/plugins/build/plugins)。

在源码根目录运行：

```console
codex plugin marketplace add .
```

然后按客户端要求重新加载或重启桌面应用。在插件目录中选择 **FrameCheck 本地开发** 来源，找到 **FrameCheck 解析器验收**，安装并启用。市场名称来自本仓库配置，并不表示它已经上架官方目录。

如果你的 CLI 支持 `codex plugin add --help`，也可以用以下命令安装并检查：

```console
codex plugin add framecheck@framecheck-local
codex plugin list --marketplace framecheck-local --json
```

**成功判据：**列表中的插件为 `framecheck@framecheck-local`，已安装、已启用，版本与本目录 `plugin.json` 一致。字段名可能因客户端版本不同而变化；本次验证的 CLI 使用 `installed`、`enabled` 和 `version`。若你的客户端没有这些命令或市场入口，先使用第 2 步的独立 CLI，不将“源码已下载”当作安装完成。

本目录附带 `.agents/plugins/marketplace.json`，其 `source.path` 为 `./`；`.codex/config.toml` 为受信任的 FrameCheck 项目启用插件。插件安装后还需要在实际工作项目中保持启用。不要把 FrameCheck 源码目录误当成自己的固件工程。

## 4. 在新对话中确认技能入口

在实际项目中打开新对话，选择已启用的 FrameCheck，然后说：

> 用 FrameCheck 先跑附带演示，把报告保存到工作区的单独目录，并告诉我正确版本和故障版本各自的结果。

应得到实际运行后的报告和结果。仅收到一般性建议，或没有找到技能入口，都不能证明插件工作流已经加载。不同客户端的技能选择入口可能不同；可明确让 Codex 阅读已安装目录中的 `skills/framecheck/SKILL.md`，但这种手动阅读应与自动加载区分。

随后接入自己的项目：

> 用 FrameCheck 检查当前固件项目的串口解析器。先定位相关代码，只问缺少的协议规则；保留生产源码，暂时不要操作板卡。

接下来应先得到文件位置、候选入口和缺失规则。你不需要先编写 JSON 或完整协议文档。具体流程见 [新手接入指南](getting-started.md)。

## 可选功能按需准备

- C/C++ 宿主测试需要本机编译器；Python 演示不需要。见 [适配器接入](adapter.md)。
- 真实 `serial-run` 需要独立工具环境中的 `serial` 可选依赖；`--dry-run` 不需要，也不连接板卡。见 [串口验收入口](serial-exchanges.md)。
- `board-info` 使用独立工具环境中的 `board` 可选依赖。设备信息不能证明协议规则。见 [接板信息入口](board-intake.md)。

先复用已有工具环境或创建虚拟环境，避免为试用修改全局 Python。源代码可直接运行上述 CLI；本地 `pip install` 不是加载 Codex 插件的替代方式。

## 常见卡点

| 现象 | 下一步 |
| --- | --- |
| 提示找不到 `framecheck` 或 `scripts/framecheck_cli.py` | 确认当前目录包含 `plugin.json`，ZIP 是否还套着一层目录；也可给脚本使用绝对路径。 |
| `python` 或 `codex` 未被识别 | 核对已安装运行时或客户端命令位置；先使用可用的本地 CLI，不能只靠修改项目配置解决缺失的程序。 |
| 演示中的故障版本出现红色结果 | 查看最后的“演示自检”；正确版本全过、故障按预期被检出才是演示成功。 |
| 市场已存在但版本仍旧 | 先用 `codex plugin marketplace list` 确认 `framecheck-local` 指向哪个来源，再更新那个来源；仅更新另一个下载目录不会更新缓存。 |
| 插件已列出，但新项目没有技能入口 | 检查插件在该项目是否启用、项目是否受信任，并按客户端要求重新加载后用新对话验证。 |
| 没有板卡或 C 编译器 | 继续 Python 演示与源码检索；不要将未运行的 C 或板端检查记为通过。 |

## 更新与回退

记录当前版本和原来源目录后，再用新源码更新对应市场。Git 来源可使用 `codex plugin marketplace upgrade framecheck-local`；本地目录来源先更新该目录文件。更新后重新加载客户端，核对安装版本，再重跑演示。

同名市场已经指向旧目录、又需要更换目录时，可先记录 `codex plugin marketplace list` 中的旧路径，再只移除 `framecheck-local` 市场并登记新目录：

```console
codex plugin marketplace remove framecheck-local
codex plugin marketplace add .
codex plugin add framecheck@framecheck-local
```

这些命令在新源码目录运行，需要当前 CLI 支持安装命令；桌面安装也可按第 3 步完成。保留旧源码目录，回退时登记旧目录并重新安装原版本。不要覆盖或删除其他市场配置。版本记录只能证明安装内容；自然语言技能加载仍需第 4 步单独验证。

项目采用 [MIT 许可证](../LICENSE)。已有验证范围与未覆盖事项见 [验证记录](validation.md)。
