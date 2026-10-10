"""A separate newline-delimited protocol; demonstrates arbitrary output schemas."""


class LineParser:
    def reset(self):
        self.buffer = bytearray()

    def feed(self, data):
        self.buffer.extend(data)
        out = []
        while b"\n" in self.buffer:
            index = self.buffer.index(10)
            line = bytes(self.buffer[:index])
            del self.buffer[:index+1]
            out.append({"line": line.decode("ascii")})
        return out


def create_parser():
    return LineParser()
