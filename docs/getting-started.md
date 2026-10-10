# 新手接入指南

你不必先整理一份完整协议。FrameCheck 的 Codex 技能可以先读取你允许访问的项目，找到相关函数，再逐步确认缺少的信息。它也可以只接收你粘贴的最小代码片段。

开始前按 [安装说明](install.md) 加载插件。在源码根目录直接运行 CLI 不需要安装 Codex 插件。

## 情况一：项目已经在 Codex 中打开

直接说：

> 帮我检查当前项目的串口解析器。先找解析入口、帧格式和 CRC 函数，再引导我补充缺少的信息。

引导流程会先确认可读取的项目范围，再寻找接收回调、字节缓存、解析状态机、帧结构、发送编码和校验函数。结果会附带文件路径、函数或行号与候选依据；你可以纠正“这个是旧版本，实际使用的是另一个文件”。

找到多个协议时，先确定一个入口。找到代码后，不会再让你把相同内容手动粘贴一次。

## 情况二：项目在另一个目录

给出路径和范围即可：

> 用 FrameCheck 检查 `D:\projects\my-robot`。只读取这个项目，重点看 `firmware/protocol` 里的串口接收解析。

插件会在指定范围内查找，不自动扩大到其他项目或整个磁盘。默认跳过构建产物、依赖目录、版本管理数据、环境配置、密钥和二进制等无关文件。目录排除只是减少无关读取，不能保证自动识别所有机密；需要时可以把范围进一步缩小到协议目录。

## 情况三：只能粘贴片段

先发送“接收字节并解析出消息”的函数，说明它所在文件即可。比如：

> 我现在只能粘贴代码。这是 `uart_protocol.c` 的解析函数，请先看它，再告诉我还需要哪一段。

插件会按当前缺项继续引导，一次只收集推进下一步所需的内容：

- 缺帧定义：给出对应结构体、帧头和长度常量，通常在关联头文件中。
- 缺校验规则：给出 CRC／校验函数，以及调用它的那一段。
- 缺正确输出依据：提供一条已确认正确的完整报文，并说明它代表什么消息。

已知文件位置时，提示会指出具体文件、函数或行号，并说明为什么需要它。没有位置依据时会说明要寻找的内容，不编造行号。不要发送无关账户配置、密钥或整个工程压缩包。

只有协议文档或十六进制报文也能开始整理用例；但没有实际解析代码或可调用实现时，无法完成对真实解析器的验证。

## 插件会怎样推进

### 先确认协议规则

插件会根据代码和你提供的资料列出已知规则，并为结论保留依据。遇到影响预期的歧义时，会提出小范围问题，例如：

> 长度字段看起来用于载荷长度，但代码没有说明是否包含 CRC。协议规定是哪一种？如果有一条已确认的完整报文，也可以用它确认。

不需要重新回答代码已经明确显示的文件位置或函数名。协议预期与实现行为会分别记录：待测代码产生的输出不能直接当作正确答案。不确定的字段和行为会保留为待确认项；缺少关键依据时，不会把推测包装成测试通过。

### 再生成接入文件和测试

规则足够明确后，插件会创建薄适配器，将现有解析函数接入测试；默认使用单独目录保存接入文件、用例和报告，保留原解析代码。你不必先手写 JSON 用例。

Python 解析器可以通过适配器调用。C/C++ 解析器需要在电脑上编译成动态库；如果依赖 STM32 HAL、RTOS 或其他板卡接口，可能需要包装接收入口、替换无关硬件调用，或由你确认哪些部分能用于宿主测试。包装和替身不能代替真实板卡验证。具体接口见 [适配器接入](adapter.md)。

测试会根据已确认的协议规则选择完整帧、不同位置分包、逐字节输入、连续帧、边界长度、校验损坏和噪声恢复等用例；不适用于协议的规则不会机械套用。涉及时间间隔、掉线、重传或状态机的行为需要额外明确约定。

### 最后看报告并重跑

报告展示输入分块、预期消息、实际消息和第一处消息差异。失败输入会保存到 `repros/`，供同样条件再次测试。修复后可以说：

> 重放刚才的失败用例，检查修改后的解析器，并保留修复前后的结果。

报告中的失败表示与已确认预期不一致；异常、超时或进程退出记为运行错误。宿主测试通过不代表串口电气、DMA、中断或 MCU 时序已经通过。

## 命令行方式

以下命令在 FrameCheck 源码根目录运行，需要 Python 3.10 或更高版本。运行时仅使用标准库；C/C++ 测试另需宿主编译器。

### 先整理代码候选

```console
python -m framecheck inspect --project D:\projects\my-robot --out ./intake
```

已知协议目录时可以缩小检索范围：

```console
python -m framecheck inspect --project D:\projects\my-robot --focus firmware/protocol --out ./intake
```

该命令只读取项目并生成 `intake.md` 和 `intake.json`，帮助列出可能相关的代码。它不导入或执行项目代码，不联网，也不负责理解完整协议、自动产生正确预期或判定解析器通过。Codex 可以依据这份清单继续查看相关代码，也可以直接检索已授权项目。

### 运行附带示例

```console
python -m framecheck demo --out ./demo-output
python -m framecheck run --python examples/python/parser.py --out ./test-output
```

打开 `demo-output/index.html` 或 `test-output/report.html`。内置演示中的故障版本出现失败属于预期；演示命令返回 `0` 表示预设检查符合预期。

仓库还附带 [逐行协议示例](../examples/custom/suite.json)，使用 `line` 字段演示不同协议与消息结构：

```console
python -m framecheck run --python examples/custom/parser.py --suite examples/custom/suite.json --out ./custom-output
```

### 运行自己的协议

Codex 可以生成以下命令所需的适配器和用例；手动使用时需要自行准备它们：

```console
python -m framecheck run --python my_parser_adapter.py --suite my_suite.json --out ./my-results
```

省略 `--suite` 时使用 FrameCheck 示例协议的用例，不会自动识别你的协议。`expected` 支持任意 JSON 对象列表，按消息顺序和全部字段比较。预期消息应来自协议、人工确认样例或独立实现，不能直接复制待测解析器的输出。

接入 C 示例：

```console
python -m framecheck run --c-source examples/c/parser.c --out ./c-results
python -m framecheck demo --native --out ./native-demo
```

指定编译器或使用已有动态库：

```console
python -m framecheck run --c-source examples/c/parser.c --compiler PATH --out ./c-results
python -m framecheck run --library path/to/parser.dll --suite my_suite.json --out ./c-results
```

Linux 使用 `.so`，macOS 使用 `.dylib`。动态库架构必须与 Python 一致，并导出约定接口。参见 [适配器接入](adapter.md) 和 [协议与用例说明](protocol.md)。

### 保存失败，验证修复

内置演示会保存已知故障的失败输入，可以交给正确解析器再次运行：

```console
python -m framecheck replay ./demo-output/fragment/repros/bytewise.json --python examples/python/parser.py --out ./replay-output
```

测试自己的解析器时，用报告中实际生成的失败文件替换上述路径。正确解析器通过的用例不会产生失败文件。`replay` 同样支持 `--c-source` 或 `--library`，不会沿用失败文件中的代码路径执行程序。

导出固定种子的示例用例，可编辑后纳入版本管理：

```console
python -m framecheck export-suite --out ./suite.json --seed 20261008
```

普通 `run` 和 `replay` 的退出码：`0` 全部通过，`1` 存在不一致或运行错误，`2` 命令或配置无效。报告中的 `fail` 表示输出与预期不一致；`error` 表示异常、超时、进程退出等未正常完成的情况。

## 读取范围与数据

项目检索脚本在本地运行，只读取指定项目范围；测试工具也不主动访问网络。但当 Codex 查看源代码、用例或报告时，这些内容可能进入模型上下文，受你所用服务的数据处理规则约束。本地测试不等于整个对话离线。如果代码不能用于该服务，请只使用本地 CLI，或提供你允许分享的最小示例。

运行解析器会执行适配器或动态库，使用当前进程权限。子进程超时机制用于回收卡住的用例，不是安全沙箱；只运行可信代码。
