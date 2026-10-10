# Guided intake when project access is incomplete

Choose the smallest next request from what is already available. Do not present every question below as a form. The first objective is one concrete parser entry point and one independently supported packet, not a complete project upload.

## Project is available

Start from likely application protocol sources, then follow their local dependencies. Distinguish a UART/DMA interrupt handler that delivers bytes from the function that recognizes complete messages. Useful clues include parse/feed/unpack/decode/state-machine functions, received-byte queues, frame structures/constants, CRC/checksum helpers, pack/encode/send counterparts and known-good test vectors. A generated HAL CRC driver is not automatically the protocol checksum implementation.

An inspection candidate is only a pointer. Read its relevant function, definitions and callers before stating what it does. When the scanner misses custom names, search call sites from the receive callback or byte queue. If there are multiple buses or message protocols, ask which concrete connection matters, with filenames as options.

Keep sources connected to claims. For example:

| Rule | Evidence | Status / next action |
| --- | --- | --- |
| Frame begins AA 55 | protocol.md line 12 | specified |
| Parser adds 7 to the length | parser.c line 84 | implementation_only; compare sender/spec |
| CRC covers the length field | no independent source | ask a focused question |

Existing passing test outputs or round trips through the same pack/parse logic can be useful characterization but are not automatically independent protocol proof. Do not silently turn any candidate into an accepted fixture.

## Only snippets can be provided

Start with: “先发接收字节后判断完整报文的那个函数，连同它用到的帧结构或长度常量就可以；不知道是哪段的话，先发串口接收回调，我帮你顺着找。”

After reading it, name the exact missing symbol or segment and why it matters. Examples:

- “这里调用了 `crc16_check()`，请再发这个函数和它的初值定义，我需要确认坏报文是否会被拒收。”
- “`data_len` 的含义在这段代码里不清楚。它只表示载荷字节数，还是还包括命令字和校验？发送端的打包函数也能帮助确认。”
- “请给一条你已经确认能正常通讯的十六进制报文，并说明它应该解出什么。没有的话，可以先用协议说明构造一条，生成后给你确认。”

Request related constants/types only as needed, not an arbitrary fixed line count or the whole firmware. Screenshots are a fallback; copyable source is easier to execute and review. Do not ask for secret keys, unrelated logs or complete private configuration.

## Only a protocol document or packet exists

Derive a proposed frame layout and a small packet checklist from the document. Mark ambiguities and ask the focused questions that affect expectations. Fixtures or an independent reference encoder can be prepared from confirmed rules, but without the user's parser no claim about their existing implementation is possible. Explain which receive/parse function would be needed next.

## Before running acceptance

Summarize only supported rules and remaining gaps. Independent evidence may be a normative protocol document, a manually checked vendor vector, a user-confirmed real packet plus its meaning, or a separately justified reference implementation. The code being tested is not the expected-result generator. For only partially specified protocols, execute the supported subset and label the remaining recovery/checksum rules as unverified.

Local inspection does not require uploading the entire project archive. Portions read by Codex may enter its conversation context; do not describe this workflow as offline model analysis or as protection against content already sent to a model.
