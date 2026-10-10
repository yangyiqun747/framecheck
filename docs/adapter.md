# 解析器接入

适配器负责把 FrameCheck 的字节输入交给现有解析器，再把消息转成 JSON 对象列表。协议逻辑应留在你的解析器中，预期消息应独立写在 suite 中。

## Python

提供一个本地 `.py` 文件，导出 `create_parser()`。返回的对象有两个方法：

```python
def reset(self) -> None:
    ...

def feed(self, data: bytes) -> list[dict]:
    ...
```

`reset()` 清除当前用例的解析状态。`feed()` 处理这次输入，返回新发出的消息；没有完整消息时返回空列表。请返回可以通过标准 JSON 编码的对象，不返回原始 `bytes`、自定义实例、NaN 或无穷值。输出字段可以自定义，只需与 suite 中的 `expected` 对应。

下面的独立示例解析以 LF 结束的 ASCII 行，可用于 `protocol.md` 的行协议用例：

```python
class LineParser:
    def __init__(self):
        self.reset()

    def reset(self):
        self.buffer = bytearray()

    def feed(self, data):
        self.buffer.extend(data)
        messages = []
        while b"\n" in self.buffer:
            cut = self.buffer.index(b"\n")
            line = bytes(self.buffer[:cut]).decode("ascii")
            del self.buffer[:cut + 1]
            messages.append({"line": line})
        return messages


def create_parser():
    return LineParser()
```

把适配器和自定义 suite 放在项目中后运行：

```console
python -m framecheck run --python line_adapter.py --suite line_suite.json --out ./line-results
```

如果协议库依赖额外的本地模块，请保证运行测试的 Python 环境能够导入这些模块。FrameCheck 不会自动安装待测项目的依赖。

## C/C++

首版 C 接口适合输出序号、消息类型和原始负载的流式解析器。使用 `examples/c/parser.h` 中的声明：

```c
typedef void (*fc_emit_fn)(uint8_t seq, uint8_t type,
    const uint8_t *payload, size_t length, void *user);

void fc_reset(void);
int fc_feed(const uint8_t *data, size_t length,
    fc_emit_fn emit, void *user);
```

- `fc_reset()` 清空缓存和状态。
- `fc_feed()` 接受本次输入；可以同步调用 `emit()` 零次、一次或多次。
- `emit()` 的 `payload` 在回调期间必须可读；适配器会复制负载。
- 传入回调时，应原样传回 `user`。不要保存回调供函数返回后异步调用。
- 成功返回本次调用发出的消息数量，必须与 `emit()` 回调次数一致；没有完整消息时返回 `0`。错误返回负值。负返回值或数量不一致会记为运行错误。
- C++ 应使用头文件提供的 `extern "C"` 声明；Windows DLL 需导出符号。

C 适配器将每次回调归一化为：

```json
{"seq": 1, "type": 2, "payload_hex": "00ab"}
```

它不会自动解释负载中的结构体、符号、浮点数、单位或其他业务字段。如果你的验收需要不同的消息结构，可以通过 Python 适配器调用自己的本地库，并返回相应 JSON 对象。

现有 MCU 工程通常需要一层宿主封装：去掉硬件接收入口，将收到的字节传入原来的解析函数，并在原回调处转发 `emit()`。宿主封装应尽量保留解析器原逻辑；对于多源文件、项目专有宏和复杂依赖，建议使用原有构建系统生成动态库，再通过 `--library` 接入。

简单单源文件可以交给工具编译：

```console
python -m framecheck run --c-source examples/c/parser.c --out ./c-results
python -m framecheck run --c-source examples/c/parser.c --compiler /path/to/cc --out ./c-results
```

预先构建的动态库：

```console
python -m framecheck run --library ./parser.dll --suite ./suite.json --out ./c-results
```

需要编译器能够构建当前系统的共享库。Python 和动态库的系统、位数、ABI 必须兼容；其他动态依赖也必须能被系统找到。宿主构建与 MCU 构建的差异仍需在真实平台复测。

## 接入后的验收顺序

1. 一条完整正确报文，检查字段与字节顺序。
2. 同一报文逐字节输入、逐个切点拆成两块，检查完整输出。
3. 多条报文一次输入，检查数量与顺序。
4. 按协议约定加入坏 CRC、异常长度和噪声，检查拒收与恢复。
5. 将真实故障输入保存为固定用例，修复后重放。

内置 `--bug 1..4` 为演示故障开关，仅应配合附带示例源码使用。它不适合作为真实解析器的通用故障注入接口。

## 执行方式与限制

每个用例由独立子进程加载解析器，调用 `reset()`，再依次调用 `feed()`。运行器对该进程设定超时，并将异常、崩溃或超时记为 `error`。单个解析器卡住不应被误记为通过。

子进程仍具有当前用户权限，不是安全沙箱。它不能消除恶意适配器执行其他程序、读写文件或访问网络的能力。仅测试你信任的本地代码。

默认每个用例的超时为 3 秒，包含解释器启动和加载解析器的时间。若本机启动较慢或适配器初始化较重，可通过 `--timeout 10` 调整；它与通信协议的接收超时不同。

薄适配器可能导入其他生产源码。为了让报告对应真实代码版本，Codex 会在 `run` 或 `replay` 时添加 `--record-source <解析源码> <相关头文件或模块> ...`，记录这些文件的 SHA-256。默认适配器指纹不能代表其所有导入依赖；显式记录也只覆盖列出的文件。用例的协议和预期契约会自动记录摘要。

每次测试的消息比较发生在用例结束时；框架不模拟中断并发、DMA、硬件时钟或串口速率，不证明实际设备的实时行为。
