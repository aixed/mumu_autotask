from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from mumu_autotask.config import ConfigError, Settings, load_settings


class ConfigTests(unittest.TestCase):
    def test_example_records_three_instance_role_mappings(self) -> None:
        settings = load_settings(
            Path(__file__).resolve().parents[1] / "config.example.json"
        )
        mappings = {
            profile.serial: (profile.instance_name, profile.roles)
            for profile in settings.devices
        }
        self.assertEqual(
            mappings,
            {
                "127.0.0.1:16384": (
                    "MuMuPlayer-12.0-0",
                    ("打工人", "打工魂"),
                ),
                "127.0.0.1:16416": (
                    "MuMuPlayer-12.0-1",
                    ("打工的",),
                ),
                "127.0.0.1:16448": (
                    "MuMuPlayer-12.0-2",
                    (),
                ),
                "127.0.0.1:16480": (
                    "MuMuPlayer-12.0-3",
                    ("打工客", "打工仔"),
                ),
            },
        )

    def test_frida_device_profile_defaults_to_kingdom_4549(self) -> None:
        settings = Settings.from_dict(
            {
                "devices": [
                    {
                        "serial": "127.0.0.1:16384",
                        "frida_host": "127.0.0.1:27042",
                        "bridge_remote_path": "/data/local/tmp/libmumu_bridge.so",
                        "expected_kingdom": 4549,
                    }
                ]
            }
        )
        profile = settings.devices[0]
        self.assertEqual(profile.frida_host, "127.0.0.1:27042")
        self.assertEqual(profile.frida_local_port, 27042)
        self.assertEqual(profile.frida_remote_port, 27042)
        self.assertEqual(profile.expected_kingdom, 4549)
        self.assertEqual(
            profile.resolved_playerprefs_path,
            "/data/data/com.gof.global/shared_prefs/com.gof.global.v2.playerprefs.xml",
        )

    def test_frida_remote_port_can_be_configured_for_nondefault_server(self) -> None:
        settings = Settings.from_dict(
            {
                "devices": [
                    {
                        "serial": "127.0.0.1:16416",
                        "frida_host": "127.0.0.1:27052",
                        "frida_remote_port": 38417,
                    }
                ]
            }
        )
        profile = settings.devices[0]
        self.assertEqual(profile.frida_local_port, 27052)
        self.assertEqual(profile.frida_remote_port, 38417)

    def test_other_kingdom_can_be_configured(self) -> None:
        settings = Settings.from_dict(
            {
                "devices": [
                    {
                        "serial": "device-1",
                        "frida_host": "127.0.0.1:27042",
                        "expected_kingdom": 4583,
                    }
                ]
            }
        )
        self.assertEqual(settings.devices[0].expected_kingdom, 4583)

    def test_invalid_frida_host_is_rejected(self) -> None:
        with self.assertRaisesRegex(ConfigError, "HOST:PORT"):
            Settings.from_dict(
                {"devices": [{"serial": "device-1", "frida_host": "localhost"}]}
            )

    def test_frida_hosts_are_unique_across_devices(self) -> None:
        with self.assertRaisesRegex(ConfigError, "Frida hosts"):
            Settings.from_dict(
                {
                    "devices": [
                        {
                            "serial": "device-1",
                            "frida_host": "127.0.0.1:27042",
                            "roles": ["role-a"],
                        },
                        {
                            "serial": "device-2",
                            "frida_host": "127.0.0.1:27042",
                            "roles": ["role-b"],
                        },
                    ]
                }
            )

    def test_roles_can_repeat_across_devices(self) -> None:
        settings = Settings.from_dict(
            {
                "devices": [
                    {
                        "serial": "device-1",
                        "frida_host": "127.0.0.1:27042",
                        "roles": ["role-a"],
                    },
                    {
                        "serial": "device-2",
                        "frida_host": "127.0.0.1:27052",
                        "roles": ["role-a"],
                    },
                ]
            }
        )
        self.assertEqual(settings.devices[1].roles, ("role-a",))

    def test_bridge_output_capacity_cannot_exceed_native_buffer(self) -> None:
        with self.assertRaisesRegex(ConfigError, "between 2 and 16384"):
            Settings.from_dict({"frida": {"output_capacity": 16385}})

    def test_noncanonical_playerprefs_path_is_rejected(self) -> None:
        with self.assertRaisesRegex(ConfigError, "canonical Unity PlayerPrefs"):
            Settings.from_dict(
                {
                    "devices": [
                        {
                            "serial": "device-1",
                            "playerprefs_path": "/data/local/tmp/fake.xml",
                        }
                    ]
                }
            )

    def test_valid_config_and_environment_expansion_boundary(self) -> None:
        raw = {
            "devices": [
                {
                    "serial": "device-1",
                    "base_url": "https://example.test",
                    "headers": {"Authorization": "token"},
                }
            ],
            "endpoints": {
                "lookup": {"method": "POST", "path": "/lookup", "json": {}},
            },
            "workflows": {"run": {"steps": [{"action": "lookup"}]}},
        }
        settings = Settings.from_dict(raw)
        self.assertEqual(settings.device("device-1").base_url, "https://example.test")
        self.assertEqual(settings.endpoints["lookup"].method, "POST")

    def test_workflow_cannot_reference_unknown_endpoint(self) -> None:
        with self.assertRaisesRegex(ConfigError, "unknown endpoint"):
            Settings.from_dict(
                {"workflows": {"bad": {"steps": [{"action": "invented"}]}}}
            )

    def test_absolute_endpoint_url_is_rejected(self) -> None:
        with self.assertRaisesRegex(ConfigError, "relative"):
            Settings.from_dict(
                {
                    "endpoints": {
                        "bad": {"method": "POST", "path": "https://other.test/x"}
                    }
                }
            )


if __name__ == "__main__":
    unittest.main()
