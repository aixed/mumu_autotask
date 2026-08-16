from __future__ import annotations

import unittest

from mumu_autotask.lua_safety import LuaSafetyError, require_safe_lua


class LuaSafetyTests(unittest.TestCase):
    def test_allows_version_probe_by_default(self) -> None:
        require_safe_lua("  return   tostring(_VERSION); ")

    def test_rejects_arbitrary_code_by_default(self) -> None:
        with self.assertRaisesRegex(LuaSafetyError, "allow-unsafe-lua"):
            require_safe_lua("GoOnMarch()")

    def test_explicit_switch_allows_arbitrary_code(self) -> None:
        require_safe_lua("GoOnMarch()", allow_unsafe=True)


if __name__ == "__main__":
    unittest.main()

