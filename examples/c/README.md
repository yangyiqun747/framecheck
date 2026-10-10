# C 解析器接入

示例协议：`AA 55 | payload_len:u8 | seq:u8 | type:u8 | payload:N | crc16:le`。
最大负载 64 字节。CRC 使用 CRC-16/CCITT-FALSE，覆盖长度、序号、消息类型和负载：
多项式 `0x1021`、初始值 `0xffff`、输入/输出不反射、输出异或 `0`。

提供 `fc_reset()` 和 `fc_feed()` 两个导出函数即可接入，签名见 `parser.h`。
`fc_feed()` 应同步调用 `emit` 输出完整消息，返回消息数；负数表示出错。
回调负载内存只需在回调期间有效。每个测试用例前会重置解析器。
串流分块边界没有协议含义；不能假定一次调用包含一个完整帧。

`parser.c` 默认是正确实现。编译参数 `FC_BUG=1..4` 分别演示分包、粘包、
CRC 校验和噪声恢复问题，供验证测试工具能否发现已知缺陷。

适配器仅调用已有编译器，不下载工具链。支持 GCC、Clang 和已配置环境的 MSVC。
若自动检测失败，使用命令中的 `--compiler` 指定编译器完整路径。
Windows 会通过现有 Visual Studio Installer 的 `vswhere` 自动查找 MSVC，
并在子进程加载其编译环境，普通 PowerShell 即可运行。若自动查找失败，
可以先进入其 Developer PowerShell / Command Prompt。DLL 位数必须与 Python 一致。

本示例用全局缓存，不能并行运行同一 DLL 的多个实例；接入多实例时可改为
带上下文指针的 ABI。C 库在当前进程执行，测试应只加载可信源码构建的库。
