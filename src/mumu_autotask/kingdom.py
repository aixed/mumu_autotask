from __future__ import annotations

from dataclasses import dataclass
from xml.etree import ElementTree

from .adb import AdbClient
from .config import ALLOWED_KINGDOM, DEFAULT_PACKAGE, DeviceProfile


PLAYERPREFS_KEY = "__KEY_KINGDOM__"
SDK_SERVER_KEY = "CONTEXT_UTILS_RECENTLY_SERVERID"
PLAYERPREFS_PATH = (
    "/data/data/com.gof.global/shared_prefs/com.gof.global.v2.playerprefs.xml"
)
SDK_PREFS_PATH = "/data/data/com.gof.global/shared_prefs/com.cg.sdk.xml"


class KingdomGuardError(RuntimeError):
    """Raised when the active game kingdom cannot be proven safe."""


@dataclass(frozen=True, slots=True)
class KingdomStatus:
    serial: str
    playerprefs_kingdom: int
    sdk_server_id: int
    playerprefs_path: str
    sdk_preferences_path: str

    @property
    def kingdom(self) -> int:
        return self.playerprefs_kingdom


def _parse_unique_integer_preference(
    xml_text: str, *, key: str, source: str
) -> int:
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        raise KingdomGuardError(f"{source} is not valid XML: {exc}") from exc

    matches = [
        element
        for element in root.iter()
        if element.attrib.get("name") == key
    ]
    if len(matches) != 1:
        raise KingdomGuardError(
            f"{source} must contain exactly one {key} entry; "
            f"found {len(matches)}"
        )
    raw_value = matches[0].attrib.get("value", matches[0].text or "").strip()
    try:
        return int(raw_value, 10)
    except ValueError as exc:
        raise KingdomGuardError(
            f"{key} in {source} is not an integer: {raw_value!r}"
        ) from exc


def parse_playerprefs_kingdom(xml_text: str) -> int:
    return _parse_unique_integer_preference(
        xml_text, key=PLAYERPREFS_KEY, source="Unity PlayerPrefs"
    )


def parse_sdk_server_id(xml_text: str) -> int:
    return _parse_unique_integer_preference(
        xml_text, key=SDK_SERVER_KEY, source="CenturyGame SDK preferences"
    )


class KingdomGuard:
    def __init__(self, adb: AdbClient, allowed_kingdom: int = ALLOWED_KINGDOM) -> None:
        if allowed_kingdom != ALLOWED_KINGDOM:
            raise KingdomGuardError(
                f"only kingdom {ALLOWED_KINGDOM} is permitted by this build"
            )
        self.adb = adb
        self.allowed_kingdom = allowed_kingdom

    def read(self, profile: DeviceProfile) -> KingdomStatus:
        if profile.expected_kingdom != self.allowed_kingdom:
            raise KingdomGuardError(
                f"{profile.serial}: configured kingdom {profile.expected_kingdom} is blocked"
            )
        if profile.package_name != DEFAULT_PACKAGE:
            raise KingdomGuardError(
                f"{profile.serial}: only package {DEFAULT_PACKAGE!r} is permitted"
            )
        canonical_path = PLAYERPREFS_PATH
        path = profile.resolved_playerprefs_path
        if path != canonical_path:
            raise KingdomGuardError(
                f"{profile.serial}: refusing non-canonical PlayerPrefs path {path!r}"
            )
        playerprefs_xml = self.adb.shell(
            profile.serial, "su", "0", "cat", PLAYERPREFS_PATH
        )
        sdk_xml = self.adb.shell(
            profile.serial, "su", "0", "cat", SDK_PREFS_PATH
        )
        playerprefs_kingdom = parse_playerprefs_kingdom(playerprefs_xml)
        sdk_server_id = parse_sdk_server_id(sdk_xml)
        return KingdomStatus(
            profile.serial,
            playerprefs_kingdom,
            sdk_server_id,
            PLAYERPREFS_PATH,
            SDK_PREFS_PATH,
        )

    def require(self, profile: DeviceProfile) -> KingdomStatus:
        status = self.read(profile)
        if status.playerprefs_kingdom != status.sdk_server_id:
            raise KingdomGuardError(
                f"{profile.serial}: kingdom sources disagree: PlayerPrefs="
                f"{status.playerprefs_kingdom}, SDK={status.sdk_server_id}"
            )
        if (
            status.playerprefs_kingdom != self.allowed_kingdom
            or status.sdk_server_id != self.allowed_kingdom
        ):
            raise KingdomGuardError(
                f"{profile.serial}: active kingdom is "
                f"{status.playerprefs_kingdom}; "
                f"only {self.allowed_kingdom} is allowed"
            )
        return status
