from __future__ import annotations

import re


class LuaSafetyError(ValueError):
    """Raised when arbitrary Lua was not explicitly authorized."""


_SAFE_READ_ONLY_PROBES = {
    "return _VERSION",
    "return tostring(_VERSION)",
    "return type(package.loaded)",
}


def normalize_lua(code: str) -> str:
    return re.sub(r"\s+", " ", code.strip().removesuffix(";").strip())


def require_safe_lua(code: str, *, allow_unsafe: bool = False) -> None:
    if not code or not code.strip():
        raise LuaSafetyError("Lua code cannot be empty")
    if allow_unsafe:
        return
    if normalize_lua(code) not in _SAFE_READ_ONLY_PROBES:
        raise LuaSafetyError(
            "exec-lua only allows built-in read-only probes by default; pass "
            "--allow-unsafe-lua to explicitly authorize arbitrary in-process code"
        )
