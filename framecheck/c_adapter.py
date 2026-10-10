"""Build and load a parser implementing the small FrameCheck C ABI.

The C parser runs inside this Python process. Only compile sources you trust.
No toolchain is downloaded or installed by this module.
"""

from __future__ import annotations

import ctypes
import locale
import os
from pathlib import Path
import shutil
import subprocess
import sys


class BuildError(RuntimeError):
    """A compiler is missing, or rejected the parser source."""


def _discover_msvc() -> Path | None:
    if os.name != "nt":
        return None
    installer = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    vswhere = installer / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if not vswhere.is_file():
        return None
    try:
        result = subprocess.run(
            [str(vswhere), "-latest", "-products", "*", "-requires",
             "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    installation = Path(result.stdout.strip())
    tools = installation / "VC" / "Tools" / "MSVC"
    arch = "x64" if ctypes.sizeof(ctypes.c_void_p) == 8 else "x86"
    compilers = list(tools.glob(f"*/bin/Hostx64/{arch}/cl.exe"))
    return sorted(compilers, key=lambda p: p.parts[-5], reverse=True)[0] if compilers else None


def _find_compiler(compiler: str | None) -> str:
    if compiler:
        found = shutil.which(compiler)
        if found:
            return found
        candidate = Path(compiler)
        if candidate.is_file():
            return str(candidate.resolve())
        raise BuildError(f"C compiler does not exist: {compiler}")
    for name in ("cc", "gcc", "clang", "cl"):
        found = shutil.which(name)
        if found:
            return found
    msvc = _discover_msvc()
    if msvc:
        return str(msvc)
    raise BuildError(
        "No C compiler found. Install a C toolchain or provide --compiler with "
        "the path to gcc, clang, or cl (cl requires a configured Developer shell)."
    )


def _compiler_environment(executable: str) -> dict[str, str] | None:
    """Read the installed MSVC environment without changing the parent shell."""
    if os.name != "nt" or Path(executable).stem.lower() not in {"cl", "clang-cl"}:
        return None
    if os.environ.get("INCLUDE") and os.environ.get("LIB"):
        return None  # An existing Developer shell already supplies these paths.
    candidates = [parent / "Auxiliary" / "Build" / "vcvars64.bat"
                  for parent in Path(executable).resolve().parents]
    vcvars = next((path for path in candidates if path.is_file()), None)
    if vcvars is None:
        raise BuildError("MSVC environment was not found; use a Visual Studio Developer shell")
    arch = "x64" if ctypes.sizeof(ctypes.c_void_p) == 8 else "x86"
    if arch == "x86":
        vcvars = vcvars.with_name("vcvars32.bat")
    # cmd expands percent signs even inside quotes. Reject ambiguous paths;
    # the compiler invocation itself always uses a shell-free argument list.
    if any(char in str(vcvars) for char in ('"', "%", "\r", "\n")):
        raise BuildError("MSVC environment path cannot safely be passed to cmd")
    comspec = os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe")
    command = subprocess.list2cmdline([comspec]) + f' /d /v:off /s /c ""{vcvars}" >nul && set"'
    try:
        result = subprocess.run(
            command, capture_output=True, text=True,
            encoding=locale.getpreferredencoding(False), errors="replace", timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BuildError(f"MSVC environment could not be loaded: {exc}") from exc
    if result.returncode != 0:
        raise BuildError(f"MSVC environment could not be loaded: {result.stderr.strip()}")
    environment = os.environ.copy()
    for line in result.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator and key and not key.startswith("="):
            environment[key] = value
    if not environment.get("INCLUDE") or not environment.get("LIB"):
        raise BuildError("MSVC environment did not provide INCLUDE/LIB paths")
    return environment


def build_library(
    source: Path,
    build_dir: Path,
    bug: int = 0,
    compiler: str | None = None,
) -> Path:
    """Compile *source* as a shared library and return its absolute path.

    FC_BUG is a compile-time switch used by the bundled teaching example;
    production parsers can ignore it. Compiler arguments are passed directly,
    without a shell. Compilation is bounded to 60 seconds.
    """
    source = Path(source).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if isinstance(bug, bool) or not isinstance(bug, int) or not 0 <= bug <= 4:
        raise ValueError("bug must be an integer from 0 to 4")
    executable = _find_compiler(compiler)
    environment = _compiler_environment(executable)
    build_dir = Path(build_dir).resolve()
    build_dir.mkdir(parents=True, exist_ok=True)
    suffix = ".dll" if os.name == "nt" else ".dylib" if sys.platform == "darwin" else ".so"
    library = build_dir / f"{source.stem}_bug{bug}{suffix}"
    name = Path(executable).stem.lower()
    if name in {"cl", "clang-cl"}:
        command = [
            executable, "/nologo", "/LD", "/O2", "/W4",
            f"/DFC_BUG={bug}", f"/Fo{build_dir / (source.stem + '_bug' + str(bug) + '.obj')}",
            str(source), "/link", f"/OUT:{library}",
            f"/IMPLIB:{library.with_suffix('.lib')}",
        ]
    else:
        command = [executable, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror"]
        command += ["-dynamiclib"] if sys.platform == "darwin" else ["-shared"]
        if os.name != "nt":
            command += ["-fPIC"]
        command += [f"-DFC_BUG={bug}", str(source), "-o", str(library)]
    try:
        result = subprocess.run(
            command, cwd=build_dir, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60, check=False, env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BuildError(f"C compilation could not complete: {exc}") from exc
    if result.returncode != 0 or not library.is_file():
        details = (result.stdout + result.stderr).strip()
        raise BuildError(f"C compilation failed (exit {result.returncode}):\n{details}")
    return library


_EmitCallback = ctypes.CFUNCTYPE(
    None,
    ctypes.c_uint8,
    ctypes.c_uint8,
    ctypes.POINTER(ctypes.c_uint8),
    ctypes.c_size_t,
    ctypes.c_void_p,
)


class CParser:
    """Synchronous wrapper around fc_reset/fc_feed.

    The example ABI has global state: instances loading the same library must
    not be interleaved or used concurrently. Reset before each test case.
    Callback payload memory is copied before fc_feed returns.
    """

    def __init__(self, library: Path) -> None:
        self._library = ctypes.CDLL(str(Path(library).resolve()))
        try:
            self._reset = self._library.fc_reset
            self._feed = self._library.fc_feed
        except AttributeError as exc:
            raise ValueError("C parser must export fc_reset and fc_feed") from exc
        self._reset.argtypes = []
        self._reset.restype = None
        self._feed.argtypes = [
            ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t,
            _EmitCallback, ctypes.c_void_p,
        ]
        self._feed.restype = ctypes.c_int
        self.reset()

    def reset(self) -> None:
        self._reset()

    def feed(self, data: bytes) -> list[dict]:
        if not isinstance(data, bytes):
            raise TypeError("feed expects bytes")
        messages: list[dict] = []

        def receive(seq: int, msg_type: int, payload: object, size: int, _user: object) -> None:
            messages.append({
                "seq": int(seq), "type": int(msg_type),
                "payload_hex": ctypes.string_at(payload, size).hex(),
            })

        callback = _EmitCallback(receive)
        buffer = (ctypes.c_uint8 * len(data)).from_buffer_copy(data)
        emitted = self._feed(buffer, len(data), callback, None)
        if emitted < 0:
            raise RuntimeError(f"C parser returned an error: {emitted}")
        if emitted != len(messages):
            raise RuntimeError(
                f"C parser return count {emitted} differs from {len(messages)} callbacks"
            )
        return messages


def load_c_parser(library: Path) -> CParser:
    """Load a trusted shared library exposing the FrameCheck C ABI."""
    return CParser(library)
