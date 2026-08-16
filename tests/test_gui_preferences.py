from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mumu_autotask.gui_backend import (
    DEFAULT_HUNT_CONCURRENCY,
    GUI_PREFERENCES_FILENAME,
    GuiBackendError,
    GuiPreferences,
)


class GuiPreferencesTests(unittest.TestCase):
    def test_first_use_defaults_to_purple_without_creating_a_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.json"
            preferences = GuiPreferences.for_config(config)

            self.assertEqual(
                preferences.get_selected_qualities("127.0.0.1:16384"),
                ("purple",),
            )
            self.assertEqual(
                preferences.path,
                (Path(directory) / GUI_PREFERENCES_FILENAME).resolve(),
            )
            self.assertFalse(preferences.path.exists())
            self.assertEqual(
                preferences.get_concurrency("127.0.0.1:16384"),
                DEFAULT_HUNT_CONCURRENCY,
            )

    def test_device_sections_are_saved_immediately_and_independently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / GUI_PREFERENCES_FILENAME
            preferences = GuiPreferences(path)

            preferences.set_selected_qualities(
                "127.0.0.1:16384",
                ("green", "blue"),
            )
            first_write = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                first_write["devices"]["127.0.0.1:16384"]["qualities"],
                {
                    "green": True,
                    "blue": True,
                    "purple": False,
                    "yellow": False,
                },
            )

            preferences.set_selected_qualities(
                "127.0.0.1:16480",
                ("purple", "yellow"),
            )
            reloaded = GuiPreferences(path)
            self.assertEqual(
                reloaded.get_selected_qualities("127.0.0.1:16384"),
                ("green", "blue"),
            )
            self.assertEqual(
                reloaded.get_selected_qualities("127.0.0.1:16480"),
                ("purple", "yellow"),
            )

    def test_explicitly_clearing_all_qualities_does_not_restore_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / GUI_PREFERENCES_FILENAME
            preferences = GuiPreferences(path)

            preferences.set_selected_qualities("127.0.0.1:16416", ())

            self.assertEqual(
                GuiPreferences(path).get_selected_qualities("127.0.0.1:16416"),
                (),
            )
            self.assertEqual(
                GuiPreferences(path).get_selected_qualities("unseen-device"),
                ("purple",),
            )

    def test_concurrency_is_saved_per_device_and_validated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / GUI_PREFERENCES_FILENAME
            preferences = GuiPreferences(path)

            preferences.set_concurrency("127.0.0.1:16384", 1)
            preferences.set_concurrency("127.0.0.1:16416", 2)

            reloaded = GuiPreferences(path)
            self.assertEqual(reloaded.get_concurrency("127.0.0.1:16384"), 1)
            self.assertEqual(reloaded.get_concurrency("127.0.0.1:16416"), 2)
            self.assertEqual(reloaded.get_concurrency("127.0.0.1:16480"), 3)
            for invalid in (0, 4, True, 1.5):
                with self.subTest(invalid=invalid):
                    with self.assertRaisesRegex(GuiBackendError, "1-3"):
                        preferences.set_concurrency(  # type: ignore[arg-type]
                            "127.0.0.1:16384", invalid
                        )

    def test_quality_and_concurrency_updates_preserve_each_other(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / GUI_PREFERENCES_FILENAME
            preferences = GuiPreferences(path)

            preferences.set_concurrency("127.0.0.1:16384", 1)
            preferences.set_selected_qualities(
                "127.0.0.1:16384", ("green", "yellow")
            )
            self.assertEqual(preferences.get_concurrency("127.0.0.1:16384"), 1)

            preferences.set_concurrency("127.0.0.1:16384", 2)
            self.assertEqual(
                preferences.get_selected_qualities("127.0.0.1:16384"),
                ("green", "yellow"),
            )
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                saved["devices"]["127.0.0.1:16384"]["concurrency"], 2
            )

    def test_legacy_quality_only_section_uses_default_concurrency(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / GUI_PREFERENCES_FILENAME
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "devices": {
                            "127.0.0.1:16384": {
                                "qualities": {
                                    "green": False,
                                    "blue": True,
                                    "purple": False,
                                    "yellow": False,
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            preferences = GuiPreferences(path)

            self.assertEqual(preferences.get_concurrency("127.0.0.1:16384"), 3)
            self.assertEqual(
                preferences.get_selected_qualities("127.0.0.1:16384"),
                ("blue",),
            )


if __name__ == "__main__":
    unittest.main()
