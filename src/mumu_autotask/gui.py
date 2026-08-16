from __future__ import annotations

import argparse
import logging
import queue
import sys
import threading
from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import tkinter as tk
from tkinter import messagebox, ttk

from .config import ALLOWED_KINGDOM, ConfigError, DeviceProfile, Settings, load_settings
from .gui_backend import (
    DEFAULT_GUI_CATEGORIES,
    DEFAULT_HUNT_CONCURRENCY,
    MAX_HUNT_CONCURRENCY,
    MIN_HUNT_CONCURRENCY,
    CliRunner,
    GuiBackend,
    GuiBackendError,
)


LOGGER = logging.getLogger(__name__)
APP_TITLE = "多开控制器"

QUALITY_META: dict[str, tuple[str, str]] = {
    "green": ("绿色", "#2F855A"),
    "blue": ("蓝色", "#2B6CB0"),
    "purple": ("紫色", "#805AD5"),
    "yellow": ("黄色", "#D69E2E"),
}
CATEGORY_META: dict[str, str] = {
    "monster": "狩猎野兽",
    "hero": "英雄之旅",
    "rescue": "营救幸存者",
}


TaskCallback = Callable[[Any | None, Exception | None], None]


class HuntBatchError(ValueError):
    """Raised when a GUI batch would not target the selected intelligence."""


@dataclass(frozen=True, slots=True)
class HuntBatchTarget:
    runtime_id: int
    quality: str
    expires_at: int
    level: int | None = None
    category: str = "monster"

    @classmethod
    def from_item(cls, item: Mapping[str, Any]) -> "HuntBatchTarget":
        runtime_id = item.get("runtime_id")
        quality = item.get("quality")
        expires_at = item.get("expires_at")
        level = item.get("level")
        if (
            isinstance(runtime_id, bool)
            or not isinstance(runtime_id, int)
            or runtime_id <= 0
        ):
            raise HuntBatchError("情报目标 ID 无效")
        if not isinstance(quality, str) or quality not in QUALITY_META:
            raise HuntBatchError(f"目标 {runtime_id} 的品质无效")
        if (
            isinstance(expires_at, bool)
            or not isinstance(expires_at, int)
            or expires_at <= 0
        ):
            raise HuntBatchError(f"目标 {runtime_id} 的过期时间无效")
        if isinstance(level, bool) or not isinstance(level, int):
            level = None
        category = item.get("category", "monster")
        if not isinstance(category, str) or category not in CATEGORY_META:
            raise HuntBatchError(f"目标 {runtime_id} 的类别无效")
        return cls(runtime_id, quality, expires_at, level, category)

    @property
    def label(self) -> str:
        quality_label = QUALITY_META[self.quality][0]
        level = f" Lv.{self.level}" if self.level is not None else ""
        if self.category == "monster":
            return f"{quality_label}目标 {self.runtime_id}{level}"
        return f"{CATEGORY_META[self.category]} {quality_label}目标 {self.runtime_id}{level}"


@dataclass(frozen=True, slots=True)
class HuntBatchOutcome:
    target: HuntBatchTarget
    status: str
    detail: str


def build_hunt_queue(
    items: Sequence[Mapping[str, Any]],
    selected_qualities: Sequence[str],
) -> tuple[HuntBatchTarget, ...]:
    """Expand selected monster qualities into the exact target queue."""

    if isinstance(selected_qualities, (str, bytes)):
        raise HuntBatchError("所选品质必须是列表")
    selected = set(selected_qualities)
    invalid = sorted(selected.difference(QUALITY_META))
    if invalid:
        raise HuntBatchError(f"包含不支持的品质：{invalid}")
    if not selected:
        raise HuntBatchError("请至少选择一个骷髅品质")
    quality_order = {quality: index for index, quality in enumerate(QUALITY_META)}
    targets = [
        HuntBatchTarget.from_item(item)
        for item in items
        if item.get("category", "monster") == "monster"
        and item.get("quality") in selected
    ]
    targets.sort(
        key=lambda target: (
            quality_order[target.quality],
            target.expires_at,
            target.runtime_id,
        )
    )
    if not targets:
        raise HuntBatchError("所选品质当前没有可用野兽情报")
    runtime_ids = [target.runtime_id for target in targets]
    if len(runtime_ids) != len(set(runtime_ids)):
        raise HuntBatchError("情报列表包含重复的目标 ID")
    return tuple(targets)


def build_category_queue(
    items: Sequence[Mapping[str, Any]],
    category: str,
) -> tuple[HuntBatchTarget, ...]:
    if category not in CATEGORY_META:
        raise HuntBatchError(f"不支持的情报类别：{category}")
    if category == "monster":
        raise HuntBatchError("野兽类别必须按品质筛选")
    targets = [
        HuntBatchTarget.from_item(item)
        for item in items
        if item.get("category") == category
    ]
    targets.sort(
        key=lambda target: (
            target.quality,
            target.expires_at,
            target.runtime_id,
        )
    )
    if not targets:
        raise HuntBatchError(f"当前没有可用的{CATEGORY_META[category]}情报")
    runtime_ids = [target.runtime_id for target in targets]
    if len(runtime_ids) != len(set(runtime_ids)):
        raise HuntBatchError("情报列表包含重复的目标 ID")
    return tuple(targets)


def build_task_queue(
    items: Sequence[Mapping[str, Any]],
    selected_categories: Sequence[str],
    selected_qualities: Sequence[str],
) -> tuple[HuntBatchTarget, ...]:
    """Build the exact mixed intelligence queue selected in the GUI."""

    if isinstance(selected_categories, (str, bytes)):
        raise HuntBatchError("所选类别必须是列表")
    categories = set(selected_categories)
    invalid_categories = sorted(categories.difference(CATEGORY_META))
    if invalid_categories:
        raise HuntBatchError(f"包含不支持的情报类别：{invalid_categories}")
    if not categories:
        raise HuntBatchError("请至少选择一种情报类别")

    targets: list[HuntBatchTarget] = []
    if "monster" in categories:
        if not selected_qualities:
            if categories == {"monster"}:
                raise HuntBatchError("请至少选择一种骷髅品质")
        else:
            try:
                targets.extend(build_hunt_queue(items, selected_qualities))
            except HuntBatchError as exc:
                if categories == {"monster"} or "当前没有可用野兽情报" not in str(exc):
                    raise

    for category in CATEGORY_META:
        if category == "monster" or category not in categories:
            continue
        targets.extend(
            sorted(
                (
                    HuntBatchTarget.from_item(item)
                    for item in items
                    if item.get("category") == category
                ),
                key=lambda target: (
                    target.expires_at,
                    target.runtime_id,
                ),
            )
        )

    if not targets:
        raise HuntBatchError("所选类别当前没有可用情报")
    runtime_ids = [target.runtime_id for target in targets]
    if len(runtime_ids) != len(set(runtime_ids)):
        raise HuntBatchError("情报列表包含重复的目标 ID")
    return tuple(targets)


def build_hunt_waves(
    targets: Sequence[HuntBatchTarget],
    concurrency: int,
) -> tuple[tuple[HuntBatchTarget, ...], ...]:
    """Freeze an exact target queue into dispatch waves.

    Monster hunts consume march teams and are capped by ``concurrency``. Hero
    journey and survivor rescue tasks do not consume those teams, so every
    selected battle-style task is attached to the first wave and submitted at
    once.
    """

    if (
        isinstance(concurrency, bool)
        or not isinstance(concurrency, int)
        or not MIN_HUNT_CONCURRENCY <= concurrency <= MAX_HUNT_CONCURRENCY
    ):
        raise HuntBatchError(
            f"并发出征数必须是 {MIN_HUNT_CONCURRENCY}-{MAX_HUNT_CONCURRENCY} 的整数"
        )
    frozen = tuple(targets)
    monster_targets = tuple(
        target for target in frozen if target.category == "monster"
    )
    battle_targets = tuple(
        target for target in frozen if target.category != "monster"
    )
    monster_waves = [
        monster_targets[index : index + concurrency]
        for index in range(0, len(monster_targets), concurrency)
    ]
    if battle_targets:
        if monster_waves:
            monster_waves[0] = monster_waves[0] + battle_targets
        else:
            monster_waves.append(battle_targets)
    return tuple(monster_waves)


class HuntWaveBatch:
    """Pure state model for concurrent wave dispatch and one final claim."""

    def __init__(
        self,
        targets: Sequence[HuntBatchTarget],
        concurrency: int,
    ) -> None:
        if not targets:
            raise HuntBatchError("批次不能为空")
        runtime_ids = [target.runtime_id for target in targets]
        if len(runtime_ids) != len(set(runtime_ids)):
            raise HuntBatchError("批次目标 ID 不能重复")
        self.targets = tuple(targets)
        self.concurrency = concurrency
        self.waves = build_hunt_waves(self.targets, concurrency)
        self.wave_index = 0
        self.outcomes: list[HuntBatchOutcome] = []
        self._state = {target.runtime_id: "pending" for target in self.targets}
        self._wave_phase = "ready"
        self._dispatch_errors: dict[int, str] = {}
        self._reconciled_dispatch_details: dict[int, str] = {}
        self.claim_attempted = False
        self.claim_verified = False
        self.claim_error: str | None = None
        self.final_reconcile_attempted = False

    @property
    def current_wave(self) -> tuple[HuntBatchTarget, ...]:
        if self.wave_index >= len(self.waves):
            return ()
        return self.waves[self.wave_index]

    @property
    def wave_number(self) -> int:
        return min(self.wave_index + 1, len(self.waves))

    @property
    def all_waves_done(self) -> bool:
        return self.wave_index >= len(self.waves)

    @property
    def wave_phase(self) -> str:
        return self._wave_phase

    @property
    def dispatch_pending_ids(self) -> tuple[int, ...]:
        return tuple(
            target.runtime_id
            for target in self.current_wave
            if self._state[target.runtime_id] in {"dispatch_queued", "dispatching"}
        )

    @property
    def dispatch_queued_ids(self) -> tuple[int, ...]:
        return tuple(
            target.runtime_id
            for target in self.current_wave
            if self._state[target.runtime_id] == "dispatch_queued"
        )

    @property
    def dispatch_active_ids(self) -> tuple[int, ...]:
        return tuple(
            target.runtime_id
            for target in self.current_wave
            if self._state[target.runtime_id] == "dispatching"
        )

    @property
    def dispatch_error_ids(self) -> tuple[int, ...]:
        return tuple(
            target.runtime_id
            for target in self.current_wave
            if self._state[target.runtime_id] == "dispatch_error"
        )

    @property
    def reconciled_dispatch_ids(self) -> tuple[int, ...]:
        return tuple(
            target.runtime_id
            for target in self.current_wave
            if target.runtime_id in self._reconciled_dispatch_details
        )

    @property
    def dispatch_callbacks_done(self) -> bool:
        return self._wave_phase == "dispatching" and not self.dispatch_active_ids

    def prepare_current_wave(
        self,
        available_runtime_ids: set[int] | None = None,
    ) -> tuple[HuntBatchTarget, ...]:
        """Freeze every dispatch in this wave before any worker is submitted."""

        self._require_phase("ready")
        prepared: list[HuntBatchTarget] = []
        self._wave_phase = "dispatching"
        for target in self.current_wave:
            if self._state[target.runtime_id] != "pending":
                raise HuntBatchError(f"目标 {target.runtime_id} 的波次状态无效")
            if (
                available_runtime_ids is not None
                and target.runtime_id not in available_runtime_ids
            ):
                self._record(
                    target,
                    "reconciled",
                    "开始前目标已不再可用，确认已完成",
                )
                continue
            self._state[target.runtime_id] = "dispatch_queued"
            prepared.append(target)
        return tuple(prepared)

    def begin_next_dispatch(self) -> HuntBatchTarget | None:
        self._require_phase("dispatching")
        target = next(
            (
                candidate
                for candidate in self.current_wave
                if self._state[candidate.runtime_id] == "dispatch_queued"
            ),
            None,
        )
        if target is None:
            return None
        self._state[target.runtime_id] = "dispatching"
        return target

    def mark_dispatched(self, runtime_id: int, detail: str) -> None:
        self._require_phase("dispatching")
        target = self._require_current_wave_target(runtime_id, "dispatching")
        self._state[target.runtime_id] = "dispatched"
        self._dispatch_errors.pop(target.runtime_id, None)

    def mark_attempt_error(self, runtime_id: int, detail: str) -> None:
        self._require_phase("dispatching")
        target = self._require_current_wave_target(runtime_id, "dispatching")
        self._state[target.runtime_id] = "dispatch_error"
        self._dispatch_errors[target.runtime_id] = detail or "出征命令失败"

    def finish_dispatches(self) -> None:
        self._require_phase("dispatching")
        if self.dispatch_pending_ids:
            raise HuntBatchError("当前波次仍有出征回执尚未返回")
        if self.dispatch_error_ids:
            raise HuntBatchError("当前波次仍有出征错误尚未核对")
        self._wave_phase = "resolved"

    def begin_dispatch_reconciliation(self) -> tuple[int, ...]:
        self._require_phase("dispatching")
        if self.dispatch_active_ids:
            raise HuntBatchError("当前波次仍有出征回执尚未返回")
        target_ids = self.dispatch_error_ids
        if not target_ids:
            raise HuntBatchError("当前波次没有需要核对的出征错误")
        self._wave_phase = "reconciling"
        return target_ids

    def reconcile_dispatch_errors(
        self,
        available_runtime_ids: set[int],
    ) -> tuple[HuntBatchOutcome, ...]:
        self._require_phase("reconciling")
        outcomes: list[HuntBatchOutcome] = []
        for target in self.current_wave:
            if self._state[target.runtime_id] != "dispatch_error":
                continue
            detail = self._dispatch_errors.pop(
                target.runtime_id,
                "服务器回执未证明出征成功",
            )
            if target.runtime_id not in available_runtime_ids:
                self._state[target.runtime_id] = "dispatched"
                self._reconciled_dispatch_details[target.runtime_id] = (
                    f"{detail}；刷新后目标已不再可发起，按实际已出征纳入本波等待"
                )
            else:
                outcomes.append(self._record(target, "failed", detail))
        self._wave_phase = "dispatching" if self.dispatch_queued_ids else "resolved"
        return tuple(outcomes)

    @property
    def wait_target_ids(self) -> tuple[int, ...]:
        return tuple(
            target.runtime_id
            for target in self.current_wave
            if self._state[target.runtime_id] == "dispatched"
        )

    def complete_current_wave(
        self,
        completed_target_ids: Sequence[int],
        detail: str,
    ) -> tuple[HuntBatchOutcome, ...]:
        self._require_phase("waiting")
        completed = tuple(completed_target_ids)
        expected = self.wait_target_ids
        if completed != expected:
            raise HuntBatchError("等待回执的目标 ID 与当前波次不一致")
        outcomes: list[HuntBatchOutcome] = []
        for target in self.current_wave:
            if self._state[target.runtime_id] != "dispatched":
                continue
            reconciled_detail = self._reconciled_dispatch_details.pop(
                target.runtime_id,
                None,
            )
            if reconciled_detail is None:
                outcomes.append(self._record(target, "success", detail))
            else:
                outcomes.append(
                    self._record(
                        target,
                        "reconciled",
                        f"{reconciled_detail}；{detail}",
                    )
                )
        self._advance_wave()
        return tuple(outcomes)

    def reconcile_wait_failure(
        self,
        available_runtime_ids: set[int],
        detail: str,
    ) -> tuple[HuntBatchOutcome, ...]:
        self._require_phase("waiting")
        outcomes: list[HuntBatchOutcome] = []
        for target in self.current_wave:
            if self._state[target.runtime_id] != "dispatched":
                continue
            reconciled_detail = self._reconciled_dispatch_details.pop(
                target.runtime_id,
                None,
            )
            if target.runtime_id not in available_runtime_ids:
                outcome_detail = f"{detail}；刷新后目标不再可用，确认已处理"
                if reconciled_detail is not None:
                    outcome_detail = f"{reconciled_detail}；{outcome_detail}"
                outcomes.append(
                    self._record(
                        target,
                        "reconciled",
                        outcome_detail,
                    )
                )
            else:
                outcome_detail = detail
                if reconciled_detail is not None:
                    outcome_detail = f"{reconciled_detail}；{detail}"
                outcomes.append(self._record(target, "failed", outcome_detail))
        self._stop_after_wait_failure(detail)
        return tuple(outcomes)

    def fail_wait_reconciliation(
        self,
        detail: str,
    ) -> tuple[HuntBatchOutcome, ...]:
        self._require_phase("waiting")
        outcomes: list[HuntBatchOutcome] = []
        for target in self.current_wave:
            if self._state[target.runtime_id] != "dispatched":
                continue
            reconciled_detail = self._reconciled_dispatch_details.pop(
                target.runtime_id,
                None,
            )
            outcome_detail = detail
            if reconciled_detail is not None:
                outcome_detail = f"{reconciled_detail}；{detail}"
            outcomes.append(self._record(target, "failed", outcome_detail))
        self._stop_after_wait_failure(detail)
        return tuple(outcomes)

    def abort_unresolved_dispatch(
        self,
        detail: str,
    ) -> tuple[HuntBatchOutcome, ...]:
        """Stop after a dispatch result can no longer be reconciled safely."""

        if self.all_waves_done:
            raise HuntBatchError("所有波次已经完成")
        outcomes: list[HuntBatchOutcome] = []
        for target in self.targets:
            state = self._state[target.runtime_id]
            if state == "dispatched":
                reconciled_detail = self._reconciled_dispatch_details.get(
                    target.runtime_id
                )
                outcome_detail = f"批次已停止；已发起目标未获完成证明；{detail}"
                if reconciled_detail is not None:
                    outcome_detail = f"{reconciled_detail}；{outcome_detail}"
                outcomes.append(
                    self._record(
                        target,
                        "failed",
                        outcome_detail,
                    )
                )
            elif state == "dispatching":
                outcomes.append(
                    self._record(
                        target,
                        "failed",
                        f"本次出征回执尚未返回，结果无法核对；{detail}",
                    )
                )
            elif state == "dispatch_queued":
                outcomes.append(
                    self._record(
                        target,
                        "skipped",
                        f"本波尚未提交，批次已停止；{detail}",
                    )
                )
            elif state == "dispatch_error":
                attempt = self._dispatch_errors.get(target.runtime_id, "出征命令失败")
                outcomes.append(
                    self._record(
                        target,
                        "failed",
                        f"{attempt}；本次出征结果无法核对；{detail}",
                    )
                )
            elif state == "pending":
                outcomes.append(
                    self._record(
                        target,
                        "skipped",
                        f"本波出征结果无法核对，批次已停止；{detail}",
                    )
                )
        self._dispatch_errors.clear()
        self._reconciled_dispatch_details.clear()
        self.wave_index = len(self.waves)
        self._wave_phase = "stopped"
        return tuple(outcomes)

    def advance_terminal_wave(self) -> None:
        self._require_phase("resolved")
        if self.wait_target_ids:
            raise HuntBatchError("当前波次仍有目标等待完成")
        self._advance_wave()

    def begin_wait(self) -> tuple[int, ...]:
        self._require_phase("resolved")
        target_ids = self.wait_target_ids
        if not target_ids:
            raise HuntBatchError("当前波次没有需要等待的目标")
        self._wave_phase = "waiting"
        return target_ids

    @property
    def counts(self) -> dict[str, int]:
        result = {"success": 0, "reconciled": 0, "failed": 0, "skipped": 0}
        for outcome in self.outcomes:
            result[outcome.status] += 1
        return result

    @property
    def can_claim(self) -> bool:
        counts = self.counts
        return (
            self.all_waves_done
            and len(self.outcomes) == len(self.targets)
            and counts["failed"] == 0
            and counts["skipped"] == 0
        )

    @property
    def needs_final_reconcile(self) -> bool:
        counts = self.counts
        return (
            self.all_waves_done
            and not self.claim_attempted
            and not self.final_reconcile_attempted
            and (counts["failed"] > 0 or counts["skipped"] > 0)
        )

    def begin_final_reconcile(self) -> tuple[int, ...]:
        if not self.needs_final_reconcile:
            raise HuntBatchError("当前批次不需要最终复核")
        self.final_reconcile_attempted = True
        return tuple(target.runtime_id for target in self.targets)

    def reconcile_terminal_outcomes(
        self,
        terminal_runtime_ids: set[int],
        detail: str,
    ) -> tuple[HuntBatchOutcome, ...]:
        updates: list[HuntBatchOutcome] = []
        rewritten: list[HuntBatchOutcome] = []
        for outcome in self.outcomes:
            if (
                outcome.status in {"failed", "skipped"}
                and outcome.target.runtime_id in terminal_runtime_ids
            ):
                updated = replace(
                    outcome,
                    status="reconciled",
                    detail=f"{outcome.detail}；{detail}",
                )
                self._state[outcome.target.runtime_id] = "reconciled"
                updates.append(updated)
                rewritten.append(updated)
            else:
                rewritten.append(outcome)
        self.outcomes = rewritten
        return tuple(updates)

    def begin_claim(self) -> tuple[int, ...]:
        if self.claim_attempted:
            raise HuntBatchError("本批次已经发起过领取")
        if not self.can_claim:
            raise HuntBatchError("存在未解决失败，禁止领取")
        self.claim_attempted = True
        return tuple(target.runtime_id for target in self.targets)

    def mark_claim_error(self, detail: str) -> None:
        if not self.claim_attempted:
            raise HuntBatchError("领取尚未发起")
        self.claim_error = detail or "领取命令失败"

    def verify_claim_absence(self, available_runtime_ids: set[int]) -> bool:
        if not self.claim_attempted:
            raise HuntBatchError("领取尚未发起")
        remaining = sorted(
            target.runtime_id
            for target in self.targets
            if target.runtime_id in available_runtime_ids
        )
        if remaining:
            self.claim_verified = False
            self.claim_error = f"领取后目标仍存在：{remaining}"
            return False
        self.claim_verified = True
        return True

    def summary(self) -> str:
        counts = self.counts
        summary = (
            f"批次完成：共 {len(self.targets)} 个，成功 {counts['success']} 个，"
            f"刷新确认已处理 {counts['reconciled']} 个，失败 {counts['failed']} 个，"
            f"跳过 {counts['skipped']} 个"
        )
        if self.claim_verified:
            return f"{summary}；奖励领取已核验"
        if not self.can_claim:
            return f"{summary}；存在未解决失败，未领取奖励"
        if self.claim_error:
            return f"{summary}；领取核验失败：{self.claim_error}"
        return f"{summary}；奖励尚未领取"

    def _record(
        self,
        target: HuntBatchTarget,
        status: str,
        detail: str,
    ) -> HuntBatchOutcome:
        current_state = self._state[target.runtime_id]
        if current_state in {"success", "reconciled", "failed", "skipped"}:
            raise HuntBatchError(f"目标 {target.runtime_id} 已经有最终结果")
        outcome = HuntBatchOutcome(target, status, detail)
        self._state[target.runtime_id] = status
        self.outcomes.append(outcome)
        return outcome

    def _require_phase(self, expected: str) -> None:
        if self.all_waves_done:
            raise HuntBatchError("所有波次已经完成")
        if self._wave_phase != expected:
            raise HuntBatchError(
                f"当前波次状态为 {self._wave_phase}，预期为 {expected}"
            )

    def _require_current_wave_target(
        self,
        runtime_id: int,
        expected_state: str,
    ) -> HuntBatchTarget:
        target = next(
            (
                candidate
                for candidate in self.current_wave
                if candidate.runtime_id == runtime_id
            ),
            None,
        )
        if target is None:
            raise HuntBatchError(f"目标 {runtime_id} 不属于当前波次")
        state = self._state[target.runtime_id]
        if state != expected_state:
            raise HuntBatchError(
                f"目标 {runtime_id} 状态为 {state}，预期为 {expected_state}"
            )
        return target

    def _advance_wave(self) -> None:
        unfinished = [
            target.runtime_id
            for target in self.current_wave
            if self._state[target.runtime_id]
            in {
                "pending",
                "dispatch_queued",
                "dispatching",
                "dispatch_error",
                "dispatched",
            }
        ]
        if unfinished:
            raise HuntBatchError(f"当前波次仍有未完成目标：{unfinished}")
        self.wave_index += 1
        self._wave_phase = "ready"

    def _stop_after_wait_failure(self, detail: str) -> None:
        for target in self.targets:
            if self._state[target.runtime_id] == "pending":
                self._record(
                    target,
                    "skipped",
                    f"前一波等待失败，批次已停止；{detail}",
                )
        self.wave_index = len(self.waves)
        self._wave_phase = "stopped"


class HuntBatchQueue:
    """State machine for a resilient, sequential GUI hunt batch."""

    def __init__(self, targets: Sequence[HuntBatchTarget]) -> None:
        if not targets:
            raise HuntBatchError("批次不能为空")
        runtime_ids = [target.runtime_id for target in targets]
        if len(runtime_ids) != len(set(runtime_ids)):
            raise HuntBatchError("批次目标 ID 不能重复")
        self.targets = tuple(targets)
        self.pending: deque[HuntBatchTarget] = deque(targets)
        self.current: HuntBatchTarget | None = None
        self.outcomes: list[HuntBatchOutcome] = []
        self.blocked_qualities: dict[str, str] = {}
        self.attempt_error: str | None = None

    def next_target(
        self,
        available_runtime_ids: set[int] | None = None,
    ) -> HuntBatchTarget | None:
        if self.current is not None:
            raise HuntBatchError("当前批次目标尚未完成核对")
        while self.pending:
            target = self.pending.popleft()
            blocked = self.blocked_qualities.get(target.quality)
            if blocked is not None:
                self.outcomes.append(
                    HuntBatchOutcome(target, "skipped", f"同品质后续目标已阻止：{blocked}")
                )
                continue
            if (
                available_runtime_ids is not None
                and target.runtime_id not in available_runtime_ids
            ):
                self.outcomes.append(
                    HuntBatchOutcome(target, "skipped", "刷新后目标已不再可用")
                )
                continue
            self.current = target
            self.attempt_error = None
            return target
        return None

    def mark_attempt_success(self, runtime_id: int, detail: str) -> HuntBatchOutcome:
        target = self._require_current()
        if runtime_id != target.runtime_id:
            raise HuntBatchError(
                f"服务器回执目标 {runtime_id} 与队列目标 {target.runtime_id} 不一致"
            )
        outcome = HuntBatchOutcome(target, "success", detail)
        self.outcomes.append(outcome)
        self.current = None
        self.attempt_error = None
        return outcome

    def mark_attempt_error(self, detail: str) -> None:
        self._require_current()
        self.attempt_error = detail or "出征命令失败"

    def reconcile_current(
        self,
        available_runtime_ids: set[int],
    ) -> HuntBatchOutcome:
        target = self._require_current()
        detail = self.attempt_error or "服务器回执未证明出征成功"
        if target.runtime_id not in available_runtime_ids:
            outcome = HuntBatchOutcome(
                target,
                "reconciled",
                f"{detail}；刷新后目标不再可用，确认已处理",
            )
        else:
            outcome = HuntBatchOutcome(target, "failed", detail)
            self.blocked_qualities[target.quality] = detail
        self.outcomes.append(outcome)
        self.current = None
        self.attempt_error = None
        return outcome

    def fail_reconciliation(self, detail: str) -> HuntBatchOutcome:
        target = self._require_current()
        attempt = self.attempt_error or "出征命令失败"
        outcome = HuntBatchOutcome(target, "failed", f"{attempt}；{detail}")
        self.outcomes.append(outcome)
        self.blocked_qualities[target.quality] = detail
        self.current = None
        self.attempt_error = None
        return outcome

    @property
    def complete(self) -> bool:
        return self.current is None and not self.pending

    @property
    def counts(self) -> dict[str, int]:
        result = {"success": 0, "reconciled": 0, "failed": 0, "skipped": 0}
        for outcome in self.outcomes:
            result[outcome.status] += 1
        return result

    def summary(self) -> str:
        counts = self.counts
        return (
            f"批次完成：共 {len(self.targets)} 个，成功 {counts['success']} 个，"
            f"刷新确认已处理 {counts['reconciled']} 个，失败 {counts['failed']} 个，"
            f"跳过 {counts['skipped']} 个"
        )

    def _require_current(self) -> HuntBatchTarget:
        if self.current is None:
            raise HuntBatchError("当前没有正在处理的批次目标")
        return self.current


class TaskDispatcher:
    def __init__(self, root: tk.Misc) -> None:
        self.root = root
        self._results: queue.Queue[tuple[TaskCallback, Any | None, Exception | None]] = (
            queue.Queue()
        )
        self._lock = threading.Lock()
        self._active = 0
        self._closed = False
        self.root.after(80, self._drain)

    @property
    def active_count(self) -> int:
        with self._lock:
            return self._active

    def submit(self, action: Callable[[], Any], callback: TaskCallback) -> None:
        with self._lock:
            if self._closed:
                return
            self._active += 1

        def worker() -> None:
            value: Any | None = None
            error: Exception | None = None
            try:
                value = action()
            except Exception as exc:  # surfaced in the UI thread
                error = exc
            finally:
                with self._lock:
                    self._active -= 1
                self._results.put((callback, value, error))

        threading.Thread(target=worker, daemon=True).start()

    def close(self) -> None:
        with self._lock:
            self._closed = True

    def _drain(self) -> None:
        if self._closed:
            return
        while True:
            try:
                callback, value, error = self._results.get_nowait()
            except queue.Empty:
                break
            try:
                callback(value, error)
            except Exception:
                LOGGER.exception("GUI task callback failed")
        self.root.after(80, self._drain)


def _profile_name(profile: DeviceProfile) -> str:
    return profile.instance_name or profile.serial


def _is_online_status(payload: Mapping[str, Any]) -> bool:
    return (
        payload.get("adb") == "device"
        and payload.get("kingdom") == ALLOWED_KINGDOM
        and payload.get("playerprefs_kingdom") == ALLOWED_KINGDOM
        and payload.get("sdk_server_id") == ALLOWED_KINGDOM
        and payload.get("frida_ready") is True
        and payload.get("bridge_initialized") is True
        and isinstance(payload.get("pid"), int)
        and payload.get("process") == "Whiteout Survival"
        and payload.get("game_activity_foreground") is True
    )


def _format_expiry(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return "-"
    try:
        return datetime.fromtimestamp(value).strftime("%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return str(value)


def validate_march_intel_receipt(
    payload: Mapping[str, Any],
    serial: str,
    target_id: int,
    *,
    expected_role: str,
) -> int:
    if payload.get("serial") != serial:
        raise HuntBatchError("出征回执的设备不匹配")
    if payload.get("kingdom") != ALLOWED_KINGDOM:
        raise HuntBatchError("出征回执的区域不是 4549")
    if payload.get("role") != expected_role:
        raise HuntBatchError("出征回执的角色与批次开始角色不匹配")
    if payload.get("request_dispatched") is not True:
        raise HuntBatchError("服务器回执未证明出征成功")
    target = payload.get("target")
    runtime_id = target.get("runtime_id") if isinstance(target, Mapping) else None
    if isinstance(runtime_id, bool) or not isinstance(runtime_id, int):
        raise HuntBatchError("服务器回执缺少目标 ID")
    if runtime_id != target_id:
        raise HuntBatchError(
            f"服务器回执目标 {runtime_id} 与队列目标 {target_id} 不一致"
        )
    return runtime_id


def validate_wait_intel_receipt(
    payload: Mapping[str, Any],
    serial: str,
    target_ids: Sequence[int],
    *,
    require_missing: bool = False,
    expected_role: str | None = None,
) -> tuple[int, ...]:
    expected = tuple(target_ids)
    if payload.get("serial") != serial:
        raise HuntBatchError("等待回执的设备不匹配")
    if payload.get("kingdom") != ALLOWED_KINGDOM:
        raise HuntBatchError("等待回执的区域不是 4549")
    if expected_role is not None and payload.get("role") != expected_role:
        raise HuntBatchError("等待回执的角色与批次开始角色不匹配")
    if payload.get("target_ids") != list(expected):
        raise HuntBatchError("等待回执的目标 ID 与当前波次不一致")
    if payload.get("wait_completed") is not True:
        raise HuntBatchError("等待回执未证明本波已经完成")
    statuses = payload.get("statuses")
    if not isinstance(statuses, list) or len(statuses) != len(expected):
        raise HuntBatchError("等待回执缺少精确目标状态")
    for index, (runtime_id, status) in enumerate(
        zip(expected, statuses, strict=True)
    ):
        if not isinstance(status, Mapping):
            raise HuntBatchError(f"等待回执状态 {index} 无效")
        state = status.get("state")
        if status.get("runtime_id") != runtime_id:
            raise HuntBatchError("等待回执状态顺序与目标 ID 不一致")
        allowed_states = {"MISSING"} if require_missing else {"COMPLETED", "MISSING"}
        if state not in allowed_states:
            if require_missing:
                raise HuntBatchError(f"领取后目标 {runtime_id} 仍未消失")
            raise HuntBatchError(f"目标 {runtime_id} 尚未完成")
    return expected


def terminal_target_ids_from_status_payload(
    payload: Mapping[str, Any],
    serial: str,
    target_ids: Sequence[int],
    *,
    expected_role: str | None = None,
) -> set[int]:
    expected = tuple(target_ids)
    if payload.get("serial") != serial:
        raise HuntBatchError("状态回执的设备不匹配")
    if payload.get("kingdom") != ALLOWED_KINGDOM:
        raise HuntBatchError("状态回执的区域不是 4549")
    if expected_role is not None and payload.get("role") != expected_role:
        raise HuntBatchError("状态回执的角色与批次开始角色不匹配")
    if payload.get("target_ids") != list(expected):
        raise HuntBatchError("状态回执的目标 ID 与批次不一致")
    statuses = payload.get("statuses_after", payload.get("statuses"))
    if not isinstance(statuses, list) or len(statuses) != len(expected):
        raise HuntBatchError("状态回执缺少精确目标状态")
    terminal: set[int] = set()
    for index, (runtime_id, status) in enumerate(
        zip(expected, statuses, strict=True)
    ):
        if not isinstance(status, Mapping):
            raise HuntBatchError(f"状态回执状态 {index} 无效")
        if status.get("runtime_id") != runtime_id:
            raise HuntBatchError("状态回执状态顺序与目标 ID 不一致")
        state = status.get("state")
        if state in {"COMPLETED", "MISSING"}:
            terminal.add(runtime_id)
        elif state != "PENDING":
            raise HuntBatchError(f"目标 {runtime_id} 状态无效：{state!r}")
    return terminal


def validate_claim_intel_receipt(
    payload: Mapping[str, Any],
    serial: str,
    target_ids: Sequence[int],
    *,
    expected_role: str | None = None,
) -> tuple[int, ...]:
    expected = tuple(target_ids)
    if payload.get("serial") != serial:
        raise HuntBatchError("领取回执的设备不匹配")
    if payload.get("kingdom") != ALLOWED_KINGDOM:
        raise HuntBatchError("领取回执的区域不是 4549")
    if expected_role is not None and payload.get("role") != expected_role:
        raise HuntBatchError("领取回执的角色与批次开始角色不匹配")
    if payload.get("target_ids") != list(expected):
        raise HuntBatchError("领取回执的目标 ID 与批次不一致")
    if payload.get("claim_allowed") is not True:
        raise HuntBatchError("领取回执未确认所有目标均已完成")
    dispatched = payload.get("request_dispatched") is True
    idempotent = payload.get("idempotent") is True
    if dispatched == idempotent:
        raise HuntBatchError("领取回执没有唯一的发送或幂等证明")
    if payload.get("verified_missing") is not True:
        raise HuntBatchError("领取回执未证明目标已经消失")
    statuses = payload.get("statuses_after")
    if not isinstance(statuses, list) or len(statuses) != len(expected):
        raise HuntBatchError("领取回执缺少领取后的精确目标状态")
    for runtime_id, status in zip(expected, statuses, strict=True):
        if (
            not isinstance(status, Mapping)
            or status.get("runtime_id") != runtime_id
            or status.get("state") != "MISSING"
        ):
            raise HuntBatchError(f"领取后目标 {runtime_id} 未确认消失")
    return expected


class LauncherApp:
    def __init__(
        self,
        root: tk.Tk,
        settings: Settings,
        backend: GuiBackend,
    ) -> None:
        self.root = root
        self.settings = settings
        self.backend = backend
        self.dispatcher = TaskDispatcher(root)
        self.status_by_serial: dict[str, Mapping[str, Any]] = {}
        self.row_serials: dict[str, str] = {}
        self.managers: dict[str, DeviceManagerWindow] = {}
        self.busy = False

        self.root.title(APP_TITLE)
        self.root.geometry("1020x570")
        self.root.minsize(840, 500)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self._configure_style()
        self._build()
        self.root.bind("<Control-Return>", lambda _event: self.open_selected())
        self._populate_profiles()
        self.root.after(180, self.refresh_devices)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        self.root.configure(background="#F4F6F8")
        base_font = ("Microsoft YaHei UI", 10)
        style.configure("TFrame", background="#F4F6F8")
        style.configure("TLabel", background="#F4F6F8", font=base_font, foreground="#20262E")
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 18, "bold"))
        style.configure("Subtle.TLabel", foreground="#59636E")
        style.configure("Status.TLabel", font=("Microsoft YaHei UI", 9))
        style.configure("TButton", font=base_font, padding=(14, 8))
        style.configure(
            "Primary.TButton",
            font=("Microsoft YaHei UI", 10, "bold"),
            foreground="#FFFFFF",
            background="#1769AA",
            bordercolor="#1769AA",
        )
        style.map(
            "Primary.TButton",
            background=[("active", "#12578E"), ("disabled", "#9AA6B2")],
            foreground=[("disabled", "#EDF0F2")],
        )
        style.configure(
            "Treeview",
            font=base_font,
            rowheight=34,
            background="#FFFFFF",
            fieldbackground="#FFFFFF",
            bordercolor="#CFD6DD",
        )
        style.configure(
            "Treeview.Heading",
            font=("Microsoft YaHei UI", 10, "bold"),
            padding=(8, 8),
            background="#E8EDF1",
        )
        style.map("Treeview", background=[("selected", "#D8EAF8")], foreground=[("selected", "#17212B")])
        style.configure("TLabelframe", background="#F4F6F8", bordercolor="#CFD6DD")
        style.configure(
            "TLabelframe.Label",
            background="#F4F6F8",
            font=("Microsoft YaHei UI", 10, "bold"),
        )

    def _build(self) -> None:
        outer = ttk.Frame(self.root, padding=(24, 20, 24, 18))
        outer.grid(row=0, column=0, sticky="nsew")
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        title_bar = ttk.Frame(outer)
        title_bar.grid(row=0, column=0, sticky="ew")
        title_bar.columnconfigure(0, weight=1)
        ttk.Label(title_bar, text=APP_TITLE, style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.refresh_button = ttk.Button(
            title_bar,
            text="刷新设备",
            command=self.refresh_devices,
        )
        self.refresh_button.grid(row=0, column=1, sticky="e")
        ttk.Label(
            title_bar,
            text="仅显示配置中固定为 4549 的三台实例",
            style="Subtle.TLabel",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))

        ttk.Separator(outer).grid(row=1, column=0, sticky="ew", pady=(16, 14))

        table_frame = ttk.Frame(outer)
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        columns = ("state", "instance", "serial", "roles", "kingdom", "process", "frida")
        self.tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
            height=8,
        )
        headings = {
            "state": "状态",
            "instance": "模拟器实例",
            "serial": "ADB 设备",
            "roles": "允许角色",
            "kingdom": "区域",
            "process": "游戏进程",
            "frida": "Frida",
        }
        widths = {
            "state": 82,
            "instance": 150,
            "serial": 152,
            "roles": 172,
            "kingdom": 70,
            "process": 145,
            "frida": 142,
        }
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(
                column,
                width=widths[column],
                minwidth=60,
                anchor="center" if column in {"state", "kingdom"} else "w",
                stretch=column in {"roles", "process"},
            )
        self.tree.tag_configure("online", foreground="#166534")
        self.tree.tag_configure("checking", foreground="#59636E")
        self.tree.tag_configure("offline", foreground="#B42318")
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<<TreeviewSelect>>", self._selection_changed)
        self.tree.bind("<Double-1>", lambda _event: self.open_selected())
        self.tree.bind("<Return>", lambda _event: self.open_selected())

        footer = ttk.Frame(outer)
        footer.grid(row=3, column=0, sticky="ew", pady=(16, 0))
        footer.columnconfigure(0, weight=1)
        self.selection_text = tk.StringVar(value="请选择一台在线模拟器")
        ttk.Label(footer, textvariable=self.selection_text, style="Subtle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.start_button = ttk.Button(
            footer,
            text="启动管理",
            style="Primary.TButton",
            command=self.open_selected,
            state="disabled",
        )
        self.start_button.grid(row=0, column=1, sticky="e")
        self.summary_text = tk.StringVar(value="正在准备连接检查...")
        ttk.Label(outer, textvariable=self.summary_text, style="Status.TLabel").grid(
            row=4, column=0, sticky="w", pady=(12, 0)
        )

    def _populate_profiles(self) -> None:
        for index, profile in enumerate(self.settings.devices):
            row_id = f"device-{index}"
            self.row_serials[row_id] = profile.serial
            self.tree.insert(
                "",
                "end",
                iid=row_id,
                values=(
                    "未检查",
                    _profile_name(profile),
                    profile.serial,
                    " / ".join(profile.roles),
                    profile.expected_kingdom,
                    "-",
                    profile.frida_host,
                ),
                tags=("checking",),
            )

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.refresh_button.configure(state="disabled" if busy else "normal")
        if busy:
            self.start_button.configure(state="disabled")
        else:
            self._selection_changed()

    def refresh_devices(self) -> None:
        if self.busy:
            return
        self._set_busy(True)
        self.summary_text.set("正在连接 ADB、准备 Frida，并检查三台实例的 4549 和游戏进程...")
        for row_id in self.row_serials:
            values = list(self.tree.item(row_id, "values"))
            values[0] = "检查中"
            self.tree.item(row_id, values=values, tags=("checking",))

        def action() -> tuple[dict[str, Mapping[str, Any]], dict[str, str]]:
            statuses: dict[str, Mapping[str, Any]] = {}
            errors: dict[str, str] = {}
            try:
                self.backend.connect_devices()
            except Exception as exc:
                errors["连接阶段"] = str(exc)
            for profile in self.settings.devices:
                try:
                    statuses[profile.serial] = self.backend.status(profile.serial)
                except Exception as exc:
                    errors[profile.serial] = str(exc)
            return statuses, errors

        self.dispatcher.submit(action, self._devices_refreshed)

    def _devices_refreshed(self, value: Any | None, error: Exception | None) -> None:
        self._set_busy(False)
        if error is not None:
            for row_id in self.row_serials:
                values = list(self.tree.item(row_id, "values"))
                values[0] = "离线"
                values[5] = "-"
                self.tree.item(row_id, values=values, tags=("offline",))
            self.summary_text.set(f"连接检查失败：{error}")
            return

        payload_by_serial: dict[str, Mapping[str, Any]] = {}
        errors_by_serial: dict[str, str] = {}
        if isinstance(value, tuple) and len(value) == 2:
            raw_payloads, raw_errors = value
            if isinstance(raw_payloads, dict):
                payload_by_serial = {
                    str(serial): payload
                    for serial, payload in raw_payloads.items()
                    if isinstance(payload, Mapping)
                }
            if isinstance(raw_errors, dict):
                errors_by_serial = {
                    str(serial): str(message)
                    for serial, message in raw_errors.items()
                }
        self.status_by_serial = payload_by_serial
        online_count = 0
        for row_id, serial in self.row_serials.items():
            profile = self.settings.device(serial)
            payload = payload_by_serial.get(serial, {})
            online = _is_online_status(payload)
            if online:
                online_count += 1
            values = (
                "在线" if online else "不可用",
                _profile_name(profile),
                profile.serial,
                " / ".join(profile.roles),
                payload.get("kingdom", "-"),
                payload.get("process", "-") if online else "-",
                profile.frida_host,
            )
            self.tree.item(
                row_id,
                values=values,
                tags=("online" if online else "offline",),
            )
        summary = f"检查完成：{online_count}/{len(self.settings.devices)} 台在线且位于 4549"
        if errors_by_serial:
            failed = ", ".join(
                f"{serial}：{message}"
                for serial, message in errors_by_serial.items()
            )
            summary += f"；不可用：{failed}"
        self.summary_text.set(summary)
        if not self.tree.selection():
            for row_id, serial in self.row_serials.items():
                if _is_online_status(self.status_by_serial.get(serial, {})):
                    self.tree.selection_set(row_id)
                    self.tree.focus(row_id)
                    self.tree.see(row_id)
                    break
        self._selection_changed()
        if self.tree.selection():
            self.tree.focus_set()

    def _selected_profile(self) -> DeviceProfile | None:
        selection = self.tree.selection()
        if len(selection) != 1:
            return None
        serial = self.row_serials.get(selection[0])
        return self.settings.device(serial) if serial is not None else None

    def _selection_changed(self, _event: object | None = None) -> None:
        profile = self._selected_profile()
        online = (
            profile is not None
            and _is_online_status(self.status_by_serial.get(profile.serial, {}))
        )
        if profile is None:
            self.selection_text.set("请选择一台在线模拟器")
        elif online:
            self.selection_text.set(f"已选择：{_profile_name(profile)}  |  {profile.serial}  |  区域 4549")
        else:
            self.selection_text.set(f"{_profile_name(profile)} 当前不可用，请刷新设备状态")
        self.start_button.configure(
            state="normal" if online and not self.busy else "disabled"
        )

    def open_selected(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        status = self.status_by_serial.get(profile.serial, {})
        if not _is_online_status(status):
            messagebox.showwarning(
                "设备不可用",
                "所选模拟器未通过 ADB、Frida 或 4549 检查，请先刷新设备。",
                parent=self.root,
            )
            return
        existing = self.managers.get(profile.serial)
        if existing is not None and existing.exists:
            existing.focus()
            return
        manager = DeviceManagerWindow(
            self,
            profile,
            status,
        )
        self.managers[profile.serial] = manager

    def manager_closed(self, serial: str) -> None:
        self.managers.pop(serial, None)

    def _close(self) -> None:
        if self.dispatcher.active_count:
            should_close = messagebox.askyesno(
                "任务正在执行",
                "当前仍有后台任务未完成。是否取消后台命令并关闭程序？",
                parent=self.root,
            )
            if not should_close:
                return
        self.dispatcher.close()
        self.backend.runner.cancel_all()
        self.root.destroy()


class DeviceManagerWindow:
    def __init__(
        self,
        launcher: LauncherApp,
        profile: DeviceProfile,
        initial_status: Mapping[str, Any],
    ) -> None:
        self.launcher = launcher
        self.profile = profile
        self.backend = launcher.backend
        self.dispatcher = launcher.dispatcher
        self.status = dict(initial_status)
        self.busy = False
        self._closing = False
        self.current_items: list[dict[str, Any]] = []
        self.current_role: str | None = None
        self.hunt_role: str | None = None
        self.hunt_batch: HuntWaveBatch | None = None

        self.window = tk.Toplevel(launcher.root)
        self.window.title(f"{APP_TITLE} - {_profile_name(profile)}")
        self.window.geometry("900x780")
        self.window.minsize(780, 700)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.configure(background="#F4F6F8")
        preference_errors: list[str] = []
        load_preferences = getattr(self.backend, "get_selected_qualities", None)
        if callable(load_preferences):
            try:
                selected_qualities = set(load_preferences(self.profile.serial))
            except Exception as exc:
                preference_errors.append(f"品质：{exc}")
                selected_qualities = {"purple"}
        else:
            selected_qualities = {"purple"}
        load_categories = getattr(self.backend, "get_selected_categories", None)
        if callable(load_categories):
            try:
                selected_categories = set(load_categories(self.profile.serial))
                if selected_categories.difference(CATEGORY_META):
                    raise ValueError("情报类别无效")
            except Exception as exc:
                preference_errors.append(f"类别：{exc}")
                selected_categories = set(DEFAULT_GUI_CATEGORIES)
        else:
            load_category = getattr(self.backend, "get_category", None)
            if callable(load_category):
                try:
                    selected_category = str(load_category(self.profile.serial))
                    if selected_category not in CATEGORY_META:
                        raise ValueError("情报类别无效")
                    selected_categories = {selected_category}
                except Exception as exc:
                    preference_errors.append(f"类别：{exc}")
                    selected_categories = set(DEFAULT_GUI_CATEGORIES)
            else:
                selected_categories = set(DEFAULT_GUI_CATEGORIES)
        load_concurrency = getattr(self.backend, "get_concurrency", None)
        if callable(load_concurrency):
            try:
                concurrency = int(load_concurrency(self.profile.serial))
                if not MIN_HUNT_CONCURRENCY <= concurrency <= MAX_HUNT_CONCURRENCY:
                    raise ValueError(
                        f"并发出征数超出 {MIN_HUNT_CONCURRENCY}-{MAX_HUNT_CONCURRENCY}"
                    )
            except Exception as exc:
                preference_errors.append(f"并发数：{exc}")
                concurrency = DEFAULT_HUNT_CONCURRENCY
        else:
            concurrency = DEFAULT_HUNT_CONCURRENCY
        self.identity_text = tk.StringVar(value="正在读取当前角色和情报...")
        self.action_text = tk.StringVar(value="等待情报检查")
        self.quality_labels: dict[str, ttk.Label] = {}
        self.category_vars = {
            category: tk.BooleanVar(
                master=self.window,
                value=category in selected_categories,
            )
            for category in CATEGORY_META
        }
        self.category_checks: dict[str, ttk.Checkbutton] = {}
        self.quality_vars = {
            quality: tk.BooleanVar(
                master=self.window,
                value=quality in selected_qualities,
            )
            for quality in QUALITY_META
        }
        self.quality_checks: dict[str, ttk.Checkbutton] = {}
        self.concurrency_var = tk.IntVar(
            master=self.window,
            value=concurrency,
        )
        self.concurrency_text = tk.StringVar(value=f"{concurrency} 队")
        self._build()
        self.window.bind("<Control-Return>", self._start_hunt_from_event)
        if preference_errors:
            detail = "；".join(preference_errors)
            self._log(f"读取界面偏好失败，已使用默认值：{detail}")
            messagebox.showerror(
                "界面偏好读取失败",
                f"无法读取该设备的部分偏好，已使用默认值：\n{detail}",
                parent=self.window,
            )
        self.window.after(120, self.refresh_intel)

    @property
    def exists(self) -> bool:
        try:
            return bool(self.window.winfo_exists())
        except tk.TclError:
            return False

    def focus(self) -> None:
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()

    def _build(self) -> None:
        outer = ttk.Frame(self.window, padding=(22, 18, 22, 18))
        outer.grid(row=0, column=0, sticky="nsew")
        self.window.rowconfigure(0, weight=1)
        self.window.columnconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=1)
        outer.rowconfigure(5, weight=2)

        title = ttk.Frame(outer)
        title.grid(row=0, column=0, sticky="ew")
        title.columnconfigure(0, weight=1)
        ttk.Label(
            title,
            text=_profile_name(self.profile),
            style="Title.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            title,
            text=f"{self.profile.serial}  |  区域 {ALLOWED_KINGDOM}  |  {self.profile.frida_host}",
            style="Subtle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.refresh_intel_button = ttk.Button(
            title,
            text="刷新情报",
            command=self.refresh_intel,
        )
        self.refresh_intel_button.grid(row=0, column=1, rowspan=2, sticky="e")
        ttk.Label(title, textvariable=self.identity_text, style="Status.TLabel").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(10, 0)
        )

        ttk.Separator(outer).grid(row=1, column=0, sticky="ew", pady=(14, 12))

        quality_frame = ttk.LabelFrame(outer, text="情报设置", padding=(14, 10))
        quality_frame.grid(row=2, column=0, sticky="ew")
        for column in range(len(QUALITY_META)):
            quality_frame.columnconfigure(column, weight=1, uniform="quality")
        category_frame = ttk.Frame(quality_frame)
        category_frame.grid(
            row=0,
            column=0,
            columnspan=len(QUALITY_META),
            sticky="ew",
            pady=(0, 8),
        )
        ttk.Label(category_frame, text="类别").grid(row=0, column=0, sticky="w")
        for column, (category, label) in enumerate(CATEGORY_META.items(), start=1):
            check = ttk.Checkbutton(
                category_frame,
                text=label,
                variable=self.category_vars[category],
                command=self._category_changed,
            )
            check.grid(row=0, column=column, sticky="w", padx=(14, 0))
            self.category_checks[category] = check

        ttk.Separator(quality_frame).grid(
            row=1,
            column=0,
            columnspan=len(QUALITY_META),
            sticky="ew",
            pady=(0, 8),
        )
        for column, (quality, (label, color)) in enumerate(QUALITY_META.items()):
            cell = ttk.Frame(quality_frame)
            cell.grid(row=2, column=column, sticky="w", padx=(0, 18))
            swatch = tk.Canvas(
                cell,
                width=16,
                height=16,
                background=color,
                highlightthickness=1,
                highlightbackground="#707982",
            )
            swatch.grid(row=0, column=0, padx=(0, 7))
            check = ttk.Checkbutton(
                cell,
                variable=self.quality_vars[quality],
                command=self._quality_changed,
            )
            check.grid(row=0, column=1)
            text = ttk.Label(cell, text=f"{label} (0)")
            text.grid(row=0, column=2, padx=(3, 0))
            self.quality_checks[quality] = check
            self.quality_labels[quality] = text

        ttk.Separator(quality_frame).grid(
            row=3,
            column=0,
            columnspan=len(QUALITY_META),
            sticky="ew",
            pady=(10, 8),
        )
        concurrency_frame = ttk.Frame(quality_frame)
        concurrency_frame.grid(
            row=4,
            column=0,
            columnspan=len(QUALITY_META),
            sticky="ew",
        )
        concurrency_frame.columnconfigure(1, weight=1)
        ttk.Label(concurrency_frame, text="同时出征").grid(
            row=0, column=0, sticky="w", padx=(0, 12)
        )
        self.concurrency_scale = tk.Scale(
            concurrency_frame,
            from_=MIN_HUNT_CONCURRENCY,
            to=MAX_HUNT_CONCURRENCY,
            resolution=1,
            orient="horizontal",
            showvalue=False,
            variable=self.concurrency_var,
            command=self._concurrency_changed,
            length=240,
            sliderlength=18,
            borderwidth=0,
            highlightthickness=0,
            background="#F4F6F8",
            activebackground="#1769AA",
            troughcolor="#CFD6DD",
        )
        self.concurrency_scale.grid(row=0, column=1, sticky="ew")
        ttk.Label(
            concurrency_frame,
            textvariable=self.concurrency_text,
            width=5,
            anchor="e",
        ).grid(row=0, column=2, sticky="e", padx=(12, 0))

        intel_frame = ttk.LabelFrame(outer, text="当前可用情报", padding=(10, 8))
        intel_frame.grid(row=3, column=0, sticky="nsew", pady=(12, 0))
        intel_frame.rowconfigure(0, weight=1)
        intel_frame.columnconfigure(0, weight=1)
        columns = ("category", "quality", "level", "position", "expires", "runtime")
        self.intel_tree = ttk.Treeview(
            intel_frame,
            columns=columns,
            show="headings",
            height=7,
        )
        headings = {
            "category": "类别",
            "quality": "品质",
            "level": "等级",
            "position": "坐标",
            "expires": "过期时间",
            "runtime": "目标 ID",
        }
        widths = {
            "category": 120,
            "quality": 90,
            "level": 70,
            "position": 130,
            "expires": 150,
            "runtime": 110,
        }
        for column in columns:
            self.intel_tree.heading(column, text=headings[column])
            self.intel_tree.column(column, width=widths[column], anchor="center")
        self.intel_tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(intel_frame, orient="vertical", command=self.intel_tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.intel_tree.configure(yscrollcommand=scroll.set)

        action_bar = ttk.Frame(outer)
        action_bar.grid(row=4, column=0, sticky="ew", pady=(14, 12))
        action_bar.columnconfigure(0, weight=1)
        ttk.Label(action_bar, textvariable=self.action_text, style="Subtle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.hunt_button = ttk.Button(
            action_bar,
            text="情报-自动狩猎野兽",
            style="Primary.TButton",
            command=self._start_hunt_from_event,
            state="disabled",
        )
        self.hunt_button.grid(row=0, column=1, sticky="e")
        self.hunt_button.bind("<Return>", self._start_hunt_from_event)

        log_frame = ttk.LabelFrame(outer, text="运行记录", padding=(8, 8))
        log_frame.grid(row=5, column=0, sticky="nsew")
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self.log_text = tk.Text(
            log_frame,
            height=13,
            wrap="word",
            font=("Consolas", 9),
            background="#FFFFFF",
            foreground="#26313B",
            borderwidth=0,
            padx=8,
            pady=6,
            state="disabled",
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self._log("管理窗口已绑定到所选模拟器。")

    def _log(self, text: str) -> None:
        if not self.exists:
            return
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{stamp}] {text}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_busy(self, busy: bool, message: str) -> None:
        self.busy = busy
        self.action_text.set(message)
        self.refresh_intel_button.configure(state="disabled" if busy else "normal")
        for check in self.category_checks.values():
            check.configure(state="disabled" if busy else "normal")
        for check in self.quality_checks.values():
            check.configure(state="disabled" if busy else "normal")
        self.concurrency_scale.configure(state="disabled" if busy else "normal")
        self._update_hunt_button()

    def _update_hunt_button(self) -> None:
        categories = self._selected_categories()
        selected = self._selected_qualities()
        monster_count = (
            sum(
                item.get("category", "monster") == "monster"
                and item.get("quality") in selected
                for item in self.current_items
            )
            if "monster" in categories and selected
            else 0
        )
        category_counts = {
            category: sum(item.get("category") == category for item in self.current_items)
            for category in categories
            if category != "monster"
        }
        count = monster_count + sum(category_counts.values())
        enabled = not self.busy and count > 0
        self.hunt_button.configure(state="normal" if enabled else "disabled")
        self.hunt_button.configure(text="情报-自动处理所选类别")
        if not self.busy:
            if not categories:
                self.action_text.set("请选择至少一种情报类别")
                return
            parts: list[str] = []
            if "monster" in categories:
                labels = "、".join(QUALITY_META[quality][0] for quality in selected)
                if selected:
                    parts.append(f"狩猎野兽 {monster_count} 个（{labels}）")
                else:
                    parts.append("狩猎野兽未选择骷髅品质")
            for category in categories:
                if category != "monster":
                    parts.append(
                        f"{CATEGORY_META[category]} {category_counts.get(category, 0)} 个"
                    )
            if count:
                self.action_text.set(
                    f"已选择：{'、'.join(parts)}；将处理 {count} 个目标"
                )
            else:
                self.action_text.set(f"所选类别当前没有可用情报：{'、'.join(parts)}")

    def _selected_categories(self) -> tuple[str, ...]:
        return tuple(
            category
            for category in CATEGORY_META
            if self.category_vars[category].get()
        )

    def _selected_qualities(self) -> tuple[str, ...]:
        return tuple(
            quality
            for quality in QUALITY_META
            if self.quality_vars[quality].get()
        )

    def _quality_changed(self) -> None:
        save_preferences = getattr(self.backend, "set_selected_qualities", None)
        if callable(save_preferences):
            try:
                save_preferences(
                    self.profile.serial,
                    self._selected_qualities(),
                )
            except Exception as exc:
                self._log(f"品质偏好保存失败：{exc}")
                messagebox.showerror(
                    "品质偏好保存失败",
                    f"本次复选状态未能保存：\n{exc}",
                    parent=self.window,
                )
        self._update_hunt_button()

    def _category_changed(self) -> None:
        categories = self._selected_categories()
        save_categories = getattr(self.backend, "set_selected_categories", None)
        if callable(save_categories):
            try:
                save_categories(self.profile.serial, categories)
            except Exception as exc:
                self._log(f"类别偏好保存失败：{exc}")
                messagebox.showerror(
                    "类别偏好保存失败",
                    f"本次类别选择未能保存：\n{exc}",
                    parent=self.window,
                )
        else:
            save_category = getattr(self.backend, "set_category", None)
            if callable(save_category) and categories:
                try:
                    save_category(self.profile.serial, categories[0])
                except Exception as exc:
                    self._log(f"类别偏好保存失败：{exc}")
                    messagebox.showerror(
                        "类别偏好保存失败",
                        f"本次类别选择未能保存：\n{exc}",
                        parent=self.window,
                    )
        self._update_hunt_button()

    def _concurrency_changed(self, value: str) -> None:
        concurrency = max(
            MIN_HUNT_CONCURRENCY,
            min(MAX_HUNT_CONCURRENCY, int(round(float(value)))),
        )
        if self.concurrency_var.get() != concurrency:
            self.concurrency_var.set(concurrency)
        self.concurrency_text.set(f"{concurrency} 队")
        save_concurrency = getattr(self.backend, "set_concurrency", None)
        if callable(save_concurrency):
            try:
                save_concurrency(self.profile.serial, concurrency)
            except Exception as exc:
                self._log(f"并发数偏好保存失败：{exc}")
                messagebox.showerror(
                    "并发数保存失败",
                    f"本次并发数未能保存：\n{exc}",
                    parent=self.window,
                )

    def refresh_intel(self) -> None:
        if self.busy:
            return
        self.current_items = []
        self._render_items()
        self._set_busy(True, "正在确保游戏位于野外并读取情报...")
        self._log("开始返回野外检查。")
        self.dispatcher.submit(
            self._ensure_world_then_inspect,
            self._intel_refreshed,
        )

    def _ensure_world_then_inspect(self) -> Mapping[str, Any]:
        ensure_world = getattr(self.backend, "ensure_world", None)
        if callable(ensure_world):
            ensure_world(self.profile.serial)
        inspect_tasks = getattr(self.backend, "inspect_tasks", None)
        if callable(inspect_tasks):
            return inspect_tasks(self.profile.serial)
        return self.backend.inspect_intel(self.profile.serial)

    def _intel_refreshed(self, value: Any | None, error: Exception | None) -> None:
        if not self.exists:
            return
        if error is not None:
            self.current_items = []
            self.identity_text.set("情报检查失败，未允许执行出征")
            self._set_busy(False, f"情报检查失败：{error}")
            self._log(f"情报检查失败：{error}")
            return
        payload = value if isinstance(value, Mapping) else {}
        if (
            payload.get("serial") != self.profile.serial
            or payload.get("kingdom") != ALLOWED_KINGDOM
        ):
            self.current_items = []
            self.identity_text.set("设备或区域回执不匹配，已阻止执行")
            self._set_busy(False, "安全校验失败")
            self._log("安全校验失败：情报回执的设备或区域不匹配。")
            return
        items = payload.get("items", [])
        self.current_items = [dict(item) for item in items if isinstance(item, Mapping)]
        role = str(payload.get("role", "未知"))
        if role not in self.profile.roles:
            self.current_role = None
            self.current_items = []
            self.identity_text.set("当前角色不在此设备白名单，已阻止执行")
            self._render_items()
            self._set_busy(False, "角色安全校验失败")
            self._log(f"角色安全校验失败：回执角色 {role!r} 不在设备白名单。")
            return
        self.current_role = role
        pid = payload.get("pid", "-")
        self.identity_text.set(
            f"当前角色：{role}  |  区域：{ALLOWED_KINGDOM}  |  PID：{pid}  |  可用情报：{len(self.current_items)}"
        )
        self._render_items()
        self._set_busy(False, "情报检查完成")
        self.hunt_button.focus_set()
        self._log(f"情报检查完成：角色 {role}，发现 {len(self.current_items)} 个可用目标。")

    def _render_items(self) -> None:
        for row in self.intel_tree.get_children():
            self.intel_tree.delete(row)
        counts = {quality: 0 for quality in QUALITY_META}
        for item in self.current_items:
            category = str(item.get("category", "monster"))
            quality = str(item.get("quality", ""))
            if category == "monster" and quality in counts:
                counts[quality] += 1
            quality_label = QUALITY_META.get(quality, (quality, ""))[0]
            category_label = CATEGORY_META.get(category, category)
            self.intel_tree.insert(
                "",
                "end",
                values=(
                    category_label,
                    quality_label,
                    f"Lv.{item.get('level', '-')}",
                    f"{item.get('world_x', '-')}, {item.get('world_y', '-')}",
                    _format_expiry(item.get("expires_at")),
                    item.get("runtime_id", "-"),
                ),
            )
        for quality, (label, _color) in QUALITY_META.items():
            self.quality_labels[quality].configure(text=f"{label} ({counts[quality]})")
        self._update_hunt_button()

    def _start_hunt_from_event(self, _event: object | None = None) -> str:
        self.start_hunt()
        return "break"

    def start_hunt(self) -> None:
        if self.busy:
            return
        categories = self._selected_categories()
        selected_qualities = self._selected_qualities()
        concurrency = int(self.concurrency_var.get())
        if self.current_role not in self.profile.roles:
            messagebox.showwarning(
                "无法开始批次",
                "当前角色尚未通过刷新校验，请先刷新情报。",
                parent=self.window,
            )
            return
        try:
            targets = build_task_queue(
                self.current_items,
                categories,
                selected_qualities,
            )
            waves = build_hunt_waves(targets, concurrency)
        except HuntBatchError as exc:
            self._update_hunt_button()
            messagebox.showwarning("无法开始批次", str(exc), parent=self.window)
            return
        role_text = self.current_role
        target_text = self._format_target_counts(targets, selected_qualities)
        self.hunt_batch = HuntWaveBatch(targets, concurrency)
        self.hunt_role = role_text
        self._set_busy(True, f"正在处理 {len(targets)} 个目标，请勿切换角色或关闭窗口...")
        self._log(
            f"批量自动处理开始：{target_text}，共 {len(targets)} 个目标；"
            f"野兽并发上限已冻结为 {concurrency} 队，共 {len(waves)} 波；"
            "英雄之旅/营救幸存者不占用该上限。"
        )
        self._dispatch_next_hunt(self._available_runtime_ids())

    @staticmethod
    def _format_target_counts(
        targets: Sequence[HuntBatchTarget],
        selected_qualities: Sequence[str],
    ) -> str:
        parts: list[str] = []
        monster_targets = [target for target in targets if target.category == "monster"]
        if monster_targets:
            quality_counts = {
                quality: sum(target.quality == quality for target in monster_targets)
                for quality in selected_qualities
            }
            parts.extend(
                f"{QUALITY_META[quality][0]}野兽 {quality_counts[quality]} 个"
                for quality in selected_qualities
                if quality_counts[quality]
            )
        for category in CATEGORY_META:
            if category == "monster":
                continue
            count = sum(target.category == category for target in targets)
            if count:
                parts.append(f"{CATEGORY_META[category]} {count} 个")
        return "、".join(parts) if parts else "0 个目标"

    def _dispatch_next_hunt(
        self,
        available_runtime_ids: set[int] | None,
    ) -> None:
        batch = self.hunt_batch
        if batch is None or not self.exists:
            return
        if batch.all_waves_done:
            if batch.can_claim:
                self._start_claim()
            else:
                self._finish_hunt_batch()
            return
        previous_outcomes = len(batch.outcomes)
        try:
            targets = batch.prepare_current_wave(available_runtime_ids)
        except HuntBatchError as exc:
            self._log(f"波次发起状态错误：{exc}")
            self._march_reconcile_failed(str(exc))
            return
        for outcome in batch.outcomes[previous_outcomes:]:
            self._log_batch_outcome(outcome)
        if not targets:
            self._resolve_wave_dispatches()
            return
        self.action_text.set(
            f"第 {batch.wave_number}/{len(batch.waves)} 波，"
            f"正在同时提交 {len(targets)} 个情报任务..."
        )
        self._log(
            f"第 {batch.wave_number}/{len(batch.waves)} 波，"
            f"同时提交精确目标 {[target.runtime_id for target in targets]}；"
            f"{self._wave_flow_text(targets)}，全部发起后再等待本波完成。"
        )
        self._start_next_hunt_dispatch()

    @staticmethod
    def _dispatch_flow_text(target: HuntBatchTarget) -> str:
        if target.category == "monster":
            return "平均配置 -> 出征 -> 结果验证"
        if target.category == "hero":
            return "战斗开始 -> 战斗结束 -> 结果验证"
        return "营救发起 -> 完成验证"

    @classmethod
    def _wave_flow_text(cls, targets: Sequence[HuntBatchTarget]) -> str:
        monster_count = sum(target.category == "monster" for target in targets)
        hero_count = sum(target.category == "hero" for target in targets)
        rescue_count = sum(target.category == "rescue" for target in targets)
        if len(targets) == 1:
            return cls._dispatch_flow_text(targets[0])
        parts: list[str] = []
        if monster_count:
            parts.append(f"{monster_count} 个野兽执行平均配置 -> 出征 -> 结果验证")
        if hero_count:
            parts.append(
                f"{hero_count} 个英雄之旅执行战斗开始 -> 战斗结束 -> 结果验证"
            )
        if rescue_count:
            parts.append(f"{rescue_count} 个营救幸存者执行营救发起 -> 完成验证")
        return "；".join(parts)

    def _start_next_hunt_dispatch(self) -> None:
        batch = self.hunt_batch
        if batch is None or not self.exists or batch.wave_phase != "dispatching":
            return
        submitted = 0
        targets: list[HuntBatchTarget] = []
        while True:
            try:
                target = batch.begin_next_dispatch()
            except HuntBatchError as exc:
                self._log(f"波内提交状态错误：{exc}")
                self._march_reconcile_failed(str(exc))
                return
            if target is None:
                break
            submitted += 1
            targets.append(target)
            ordinal = next(
                index
                for index, queued in enumerate(batch.targets, start=1)
                if queued.runtime_id == target.runtime_id
            )
            wave_ordinal = next(
                index
                for index, queued in enumerate(batch.current_wave, start=1)
                if queued.runtime_id == target.runtime_id
            )
            self.action_text.set(
                f"第 {batch.wave_number}/{len(batch.waves)} 波，"
                f"正在提交 {wave_ordinal}/{len(batch.current_wave)}：{target.label}"
            )
            self._log(
                f"批量发起 {ordinal}/{len(batch.targets)}：{target.label}。"
            )
        if submitted == 0:
            self._resolve_wave_dispatches()
            return
        frozen_targets = tuple(targets)
        self.dispatcher.submit(
            lambda targets=frozen_targets: self._guarded_task_targets(targets),
            lambda value, error, batch=batch, targets=frozen_targets: (
                self._hunt_batch_dispatch_finished(batch, targets, value, error)
            ),
        )
        self.action_text.set(
            f"第 {batch.wave_number}/{len(batch.waves)} 波，"
            f"已通过单会话提交 {submitted} 个任务，等待出征回执..."
        )

    def _guarded_task_targets(
        self,
        targets: Sequence[HuntBatchTarget],
    ) -> Mapping[str, Any]:
        ensure_world = getattr(self.backend, "ensure_world", None)
        if callable(ensure_world):
            ensure_world(
                self.profile.serial,
                expected_role=self.hunt_role,
            )
        batch_intel = getattr(self.backend, "batch_intel", None)
        if callable(batch_intel):
            payload_targets = [
                {
                    "category": target.category,
                    "runtime_id": target.runtime_id,
                    "quality": target.quality,
                }
                for target in targets
            ]
            return batch_intel(
                self.profile.serial,
                payload_targets,
                expected_role=self.hunt_role,
            )
        results = [self._dispatch_task_target(target) for target in targets]
        return {"results": results}

    def _guarded_task_target(self, target: HuntBatchTarget) -> Mapping[str, Any]:
        ensure_world = getattr(self.backend, "ensure_world", None)
        if callable(ensure_world):
            ensure_world(
                self.profile.serial,
                expected_role=self.hunt_role,
            )
        return self._dispatch_task_target(target)

    def _dispatch_task_target(self, target: HuntBatchTarget) -> Mapping[str, Any]:
        if target.category in {"hero", "rescue"}:
            return self.backend.battle_intel(
                self.profile.serial,
                target.category,
                runtime_id=target.runtime_id,
                expected_role=self.hunt_role,
            )
        return self.backend.march(
            self.profile.serial,
            target.quality,
            runtime_id=target.runtime_id,
            expected_role=self.hunt_role,
        )

    def _hunt_batch_dispatch_finished(
        self,
        expected_batch: HuntWaveBatch,
        targets: Sequence[HuntBatchTarget],
        value: Any | None,
        error: Exception | None,
    ) -> None:
        batch = self.hunt_batch
        if not self.exists or batch is not expected_batch:
            return
        if error is not None:
            for target in targets:
                self._record_target_dispatch_result(batch, target, None, error)
            self._resolve_wave_dispatches()
            return
        payload = value if isinstance(value, Mapping) else {}
        raw_results = payload.get("results")
        results_by_id: dict[int, Mapping[str, Any]] = {}
        if isinstance(raw_results, list):
            for item in raw_results:
                if not isinstance(item, Mapping):
                    continue
                target_payload = item.get("target")
                runtime_id = (
                    target_payload.get("runtime_id")
                    if isinstance(target_payload, Mapping)
                    else None
                )
                if isinstance(runtime_id, int) and not isinstance(runtime_id, bool):
                    results_by_id[runtime_id] = item
        for target in targets:
            result = results_by_id.get(target.runtime_id)
            if result is None:
                self._record_target_dispatch_result(
                    batch,
                    target,
                    None,
                    HuntBatchError("批量回执缺少该目标结果"),
                )
            elif result.get("error"):
                self._record_target_dispatch_result(
                    batch,
                    target,
                    None,
                    HuntBatchError(str(result["error"])),
                )
            else:
                self._record_target_dispatch_result(batch, target, result, None)
        self._resolve_wave_dispatches()

    def _hunt_finished(
        self,
        expected_batch: HuntWaveBatch,
        target: HuntBatchTarget,
        value: Any | None,
        error: Exception | None,
    ) -> None:
        batch = self.hunt_batch
        if not self.exists or batch is not expected_batch:
            return
        self._record_target_dispatch_result(batch, target, value, error)
        self._resolve_wave_dispatches()

    def _record_target_dispatch_result(
        self,
        batch: HuntWaveBatch,
        target: HuntBatchTarget,
        value: Any | None,
        error: Exception | None,
    ) -> None:
        if target.runtime_id not in batch.dispatch_active_ids:
            self._log(f"忽略重复或过期的出征回执：目标 {target.runtime_id}。")
            return
        if error is not None:
            batch.mark_attempt_error(target.runtime_id, str(error))
            self._log(
                f"{target.label} 命令返回错误：{error}；"
                "等待本波其余回执后统一刷新核对。"
            )
            return

        payload = value if isinstance(value, Mapping) else {}
        expected_role = self.hunt_role
        if expected_role is None:
            batch.mark_attempt_error(target.runtime_id, "批次开始角色未冻结")
            self._log("批次开始角色未冻结；等待本波其余回执后统一刷新核对。")
            return
        try:
            runtime_id = validate_march_intel_receipt(
                payload,
                self.profile.serial,
                target.runtime_id,
                expected_role=expected_role,
            )
        except HuntBatchError as exc:
            detail = str(exc)
            batch.mark_attempt_error(target.runtime_id, detail)
            self._log(
                f"{target.label} 回执验证失败：{detail}；"
                "等待本波其余回执后统一刷新核对。"
            )
            return

        status = str(payload.get("quest_status_after", "-"))
        try:
            batch.mark_dispatched(runtime_id, f"任务状态 {status}")
        except HuntBatchError as exc:
            self._log(f"回执目标状态异常：{exc}。")
            self._march_reconcile_failed(str(exc))
            return
        else:
            self._log(
                f"已发起：{target.label}；任务状态 {status}。"
            )

    def _resolve_wave_dispatches(self) -> None:
        batch = self.hunt_batch
        if batch is None or not self.exists or batch.wave_phase != "dispatching":
            return
        active_ids = batch.dispatch_active_ids
        if active_ids:
            self.action_text.set(
                f"第 {batch.wave_number}/{len(batch.waves)} 波正在提交；"
                f"等待目标 {list(active_ids)} 的出征回执..."
            )
            return
        if batch.dispatch_error_ids:
            try:
                error_ids = batch.begin_dispatch_reconciliation()
            except HuntBatchError as exc:
                self._march_reconcile_failed(f"无法开始波内错误核对：{exc}")
                return
            self._log(
                f"当前出征回执已返回；先核对异常目标 {list(error_ids)}。"
            )
            self._request_march_reconcile()
            return
        if batch.dispatch_queued_ids:
            self._start_next_hunt_dispatch()
            return
        try:
            batch.finish_dispatches()
        except HuntBatchError as exc:
            self._march_reconcile_failed(f"无法完成波内回执收敛：{exc}")
            return
        self._continue_after_wave_dispatches()

    def _continue_after_wave_dispatches(self) -> None:
        batch = self.hunt_batch
        if batch is None or not self.exists:
            return
        if batch.wait_target_ids:
            self._wait_current_wave()
            return
        try:
            batch.advance_terminal_wave()
        except HuntBatchError as exc:
            self._log(f"波次状态错误：{exc}")
            self._finish_hunt_batch()
            return
        self._dispatch_next_hunt(None)

    def _request_march_reconcile(self) -> None:
        if self.hunt_batch is None or not self.exists:
            return
        self.action_text.set("正在只读刷新并统一核对本波异常出征结果...")
        self.dispatcher.submit(
            self._inspect_current_tasks,
            self._march_reconciled,
        )

    def _inspect_current_tasks(self) -> Mapping[str, Any]:
        inspect_tasks = getattr(self.backend, "inspect_tasks", None)
        if callable(inspect_tasks):
            return inspect_tasks(self.profile.serial)
        return self.backend.inspect_intel(self.profile.serial)

    def _march_reconciled(
        self,
        value: Any | None,
        error: Exception | None,
    ) -> None:
        batch = self.hunt_batch
        if batch is None or not self.exists:
            return
        if error is not None:
            self._march_reconcile_failed(f"情报刷新失败：{error}")
            return
        payload = value if isinstance(value, Mapping) else {}
        try:
            available_runtime_ids = self._apply_intel_payload(payload)
        except HuntBatchError as exc:
            self._march_reconcile_failed(str(exc))
            return
        try:
            outcomes = batch.reconcile_dispatch_errors(available_runtime_ids)
        except HuntBatchError as exc:
            self._march_reconcile_failed(f"波内错误核对状态异常：{exc}")
            return
        for outcome in outcomes:
            self._log_batch_outcome(outcome)
        for runtime_id in batch.reconciled_dispatch_ids:
            self._log(
                f"刷新确认目标 {runtime_id} 已实际发起；"
                "继续纳入当前波等待，不提前启动下一波。"
            )
        if any(outcome.status == "failed" for outcome in outcomes):
            detail = "本波存在确认失败的出征目标，批次已停止"
            self._log(detail)
            try:
                stopped = batch.abort_unresolved_dispatch(detail)
            except HuntBatchError as exc:
                self._log(f"出征失败停止异常：{exc}")
            else:
                for outcome in stopped:
                    self._log_batch_outcome(outcome)
            self._finish_hunt_batch()
            return
        if batch.wave_phase == "dispatching":
            self._start_next_hunt_dispatch()
            return
        self._continue_after_wave_dispatches()

    def _march_reconcile_failed(self, detail: str) -> None:
        batch = self.hunt_batch
        if batch is None:
            return
        self._log(detail)
        try:
            outcomes = batch.abort_unresolved_dispatch(detail)
        except HuntBatchError as exc:
            self._log(f"出征失败核对异常：{exc}")
        else:
            for outcome in outcomes:
                self._log_batch_outcome(outcome)
        self._finish_hunt_batch()

    def _wait_current_wave(self) -> None:
        batch = self.hunt_batch
        if batch is None or not batch.wait_target_ids or not self.exists:
            return
        try:
            target_ids = batch.begin_wait()
        except HuntBatchError as exc:
            self._log(f"无法开始等待本波：{exc}")
            self._finish_hunt_batch()
            return
        self.action_text.set(
            f"第 {batch.wave_number}/{len(batch.waves)} 波已发起，"
            f"正在等待 {len(target_ids)} 个目标完成..."
        )
        self._log(
            f"第 {batch.wave_number}/{len(batch.waves)} 波发起完毕；"
            f"等待精确目标 {list(target_ids)} 全部完成。"
        )
        self.dispatcher.submit(
            lambda target_ids=target_ids: self.backend.wait_intel(
                self.profile.serial,
                target_ids,
                expected_role=self.hunt_role,
            ),
            self._wave_wait_finished,
        )

    def _wave_wait_finished(
        self,
        value: Any | None,
        error: Exception | None,
    ) -> None:
        batch = self.hunt_batch
        if batch is None or not self.exists:
            return
        target_ids = batch.wait_target_ids
        if error is not None:
            detail = f"本波等待失败：{error}"
            self._log(detail)
            self._request_wave_reconcile(detail)
            return
        payload = value if isinstance(value, Mapping) else {}
        try:
            completed_ids = validate_wait_intel_receipt(
                payload,
                self.profile.serial,
                target_ids,
                expected_role=self.hunt_role,
            )
            outcomes = batch.complete_current_wave(
                completed_ids,
                "只读状态回执已证明本波完成",
            )
        except HuntBatchError as exc:
            detail = f"本波等待回执验证失败：{exc}"
            self._log(detail)
            self._request_wave_reconcile(detail)
            return
        for outcome in outcomes:
            self._log_batch_outcome(outcome)
        self._dispatch_next_hunt(None)

    def _request_wave_reconcile(self, detail: str) -> None:
        self.action_text.set("正在只读刷新；本波未获完成证明时将停止并跳过后续波次...")
        self.dispatcher.submit(
            self._inspect_current_tasks,
            lambda value, error, detail=detail: self._wave_reconciled(
                value,
                error,
                detail,
            ),
        )

    def _wave_reconciled(
        self,
        value: Any | None,
        error: Exception | None,
        detail: str,
    ) -> None:
        batch = self.hunt_batch
        if batch is None or not self.exists:
            return
        if error is None and isinstance(value, Mapping):
            try:
                self._apply_intel_payload(value)
            except HuntBatchError as exc:
                detail = f"{detail}；只读刷新回执无效：{exc}"
            else:
                detail = (
                    f"{detail}；只读刷新完成，但可用情报列表不足以证明"
                    "行军已经结束"
                )
        else:
            detail = f"{detail}；只读刷新失败：{error}"
        try:
            outcomes = batch.fail_wait_reconciliation(detail)
        except HuntBatchError as exc:
            self._log(f"波次失败核对异常：{exc}")
            self._finish_hunt_batch()
            return
        for outcome in outcomes:
            self._log_batch_outcome(outcome)
        self._dispatch_next_hunt(None)

    def _start_claim(self) -> None:
        batch = self.hunt_batch
        if batch is None or not self.exists:
            return
        try:
            target_ids = batch.begin_claim()
        except HuntBatchError as exc:
            self._log(f"已阻止奖励领取：{exc}")
            self._finish_hunt_batch()
            return
        self.action_text.set("全部波次已完成，正在统一领取一次奖励...")
        self._log(f"全部波次已完成，发起一次统一领取：{list(target_ids)}。")
        self.dispatcher.submit(
            lambda target_ids=target_ids: self.backend.claim_intel(
                self.profile.serial,
                target_ids,
                expected_role=self.hunt_role,
            ),
            self._claim_finished,
        )

    def _claim_finished(
        self,
        value: Any | None,
        error: Exception | None,
    ) -> None:
        batch = self.hunt_batch
        if batch is None or not self.exists:
            return
        target_ids = tuple(target.runtime_id for target in batch.targets)
        if error is not None:
            detail = f"统一领取命令失败：{error}"
            batch.mark_claim_error(detail)
            self._log(f"{detail}；仍将执行一次只读消失核对。")
        else:
            payload = value if isinstance(value, Mapping) else {}
            try:
                validate_claim_intel_receipt(
                    payload,
                    self.profile.serial,
                    target_ids,
                    expected_role=self.hunt_role,
                )
            except HuntBatchError as exc:
                detail = f"统一领取回执验证失败：{exc}"
                batch.mark_claim_error(detail)
                self._log(f"{detail}；仍将执行一次只读消失核对。")
            else:
                proof = "幂等确认" if payload.get("idempotent") is True else "请求已发送"
                self._log(f"统一领取回执通过：{proof}；开始独立只读核验。")
        self._request_claim_verification(target_ids)

    def _request_claim_verification(self, target_ids: tuple[int, ...]) -> None:
        self.action_text.set("正在只读核验领取后所有目标 ID 已消失...")
        self.dispatcher.submit(
            lambda target_ids=target_ids: self.backend.wait_intel(
                self.profile.serial,
                target_ids,
                expected_role=self.hunt_role,
            ),
            self._claim_verified,
        )

    def _claim_verified(
        self,
        value: Any | None,
        error: Exception | None,
    ) -> None:
        batch = self.hunt_batch
        if batch is None or not self.exists:
            return
        target_ids = tuple(target.runtime_id for target in batch.targets)
        if error is not None:
            batch.mark_claim_error(f"领取后只读核验失败：{error}")
            self._finish_hunt_batch()
            return
        payload = value if isinstance(value, Mapping) else {}
        try:
            validate_wait_intel_receipt(
                payload,
                self.profile.serial,
                target_ids,
                require_missing=True,
                expected_role=self.hunt_role,
            )
        except HuntBatchError as exc:
            statuses = payload.get("statuses")
            remaining = {
                status.get("runtime_id")
                for status in statuses
                if isinstance(statuses, list)
                and isinstance(status, Mapping)
                and status.get("state") != "MISSING"
                and isinstance(status.get("runtime_id"), int)
            } if isinstance(statuses, list) else set(target_ids)
            batch.verify_claim_absence({int(value) for value in remaining})
            batch.mark_claim_error(f"领取后只读核验失败：{exc}")
        else:
            batch.verify_claim_absence(set())
            claimed = set(target_ids)
            self.current_items = [
                item
                for item in self.current_items
                if item.get("runtime_id") not in claimed
            ]
            self._render_items()
            self._log("独立只读核验通过：本批次所有目标 ID 均已消失。")
        self._finish_hunt_batch()

    def _apply_intel_payload(self, payload: Mapping[str, Any]) -> set[int]:
        if (
            payload.get("serial") != self.profile.serial
            or payload.get("kingdom") != ALLOWED_KINGDOM
        ):
            raise HuntBatchError("情报刷新回执的设备或区域不匹配")
        items = payload.get("items")
        if not isinstance(items, list):
            raise HuntBatchError("情报刷新回执缺少目标列表")
        role = str(payload.get("role", "未知"))
        if role not in self.profile.roles:
            raise HuntBatchError("情报刷新回执角色不在设备白名单")
        if self.hunt_batch is not None and role != self.hunt_role:
            raise HuntBatchError("情报刷新回执角色与批次开始角色不匹配")
        self.current_items = [
            dict(item) for item in items if isinstance(item, Mapping)
        ]
        self.current_role = role
        pid = payload.get("pid", "-")
        self.identity_text.set(
            f"当前角色：{role}  |  区域：{ALLOWED_KINGDOM}  |  "
            f"PID：{pid}  |  可用情报：{len(self.current_items)}"
        )
        self._render_items()
        return self._available_runtime_ids()

    def _available_runtime_ids(self) -> set[int]:
        return {
            int(item["runtime_id"])
            for item in self.current_items
            if isinstance(item.get("runtime_id"), int)
            and not isinstance(item.get("runtime_id"), bool)
        }

    def _log_batch_outcome(self, outcome: HuntBatchOutcome) -> None:
        labels = {
            "success": "成功",
            "reconciled": "刷新确认已处理",
            "failed": "失败",
            "skipped": "跳过",
        }
        self._log(
            f"{labels[outcome.status]}：{outcome.target.label}；{outcome.detail}"
        )

    def _finish_hunt_batch(self) -> None:
        batch = self.hunt_batch
        if batch is None:
            return
        if batch.needs_final_reconcile:
            self._request_final_hunt_reconcile(batch)
            return
        summary = batch.summary()
        self.hunt_batch = None
        self.hunt_role = None
        self._set_busy(False, summary)
        self.action_text.set(summary)
        self._log(summary)

    def _request_final_hunt_reconcile(self, expected_batch: HuntWaveBatch) -> None:
        try:
            target_ids = expected_batch.begin_final_reconcile()
        except HuntBatchError as exc:
            self._log(f"最终状态复核无法启动：{exc}")
            return
        self.action_text.set("正在最终复核失败项是否已完成...")
        self._log(
            "批次存在未解决失败；正在按精确目标 ID 做最终状态复核。"
        )
        self.dispatcher.submit(
            lambda target_ids=target_ids: self.backend.intel_status(
                self.profile.serial,
                target_ids,
                expected_role=self.hunt_role,
            ),
            lambda value, error, batch=expected_batch, target_ids=target_ids: (
                self._final_hunt_reconciled(batch, target_ids, value, error)
            ),
        )

    def _final_hunt_reconciled(
        self,
        expected_batch: HuntWaveBatch,
        target_ids: Sequence[int],
        value: Any | None,
        error: Exception | None,
    ) -> None:
        batch = self.hunt_batch
        if not self.exists or batch is not expected_batch:
            return
        if error is not None:
            self._log(f"最终状态复核失败：{error}")
            self._finish_hunt_batch()
            return
        payload = value if isinstance(value, Mapping) else {}
        try:
            terminal_ids = terminal_target_ids_from_status_payload(
                payload,
                self.profile.serial,
                target_ids,
                expected_role=self.hunt_role,
            )
            updates = batch.reconcile_terminal_outcomes(
                terminal_ids,
                "最终精确状态复核显示目标已完成或已消失",
            )
        except HuntBatchError as exc:
            self._log(f"最终状态复核回执无效：{exc}")
            self._finish_hunt_batch()
            return
        for outcome in updates:
            self._log_batch_outcome(outcome)
        if batch.can_claim:
            self._log("最终状态复核已消除失败项；继续执行一键领取。")
            self._claim_hunt_rewards()
            return
        self._finish_hunt_batch()

    def close(self) -> None:
        if self._closing:
            return
        if self.busy and self.hunt_batch is not None:
            should_close = messagebox.askyesno(
                "任务正在执行",
                "当前正在处理出征或领取流程。是否取消该设备后台命令并关闭管理窗口？",
                parent=self.window,
            )
            if not should_close:
                return
        self._closing = True
        if self.busy:
            cancel_serial = getattr(self.backend.runner, "cancel_serial", None)
            if callable(cancel_serial):
                cancel_serial(self.profile.serial)
            else:
                self.backend.runner.cancel_all()
        self.busy = False
        self.hunt_batch = None
        self.hunt_role = None
        self.launcher.manager_closed(self.profile.serial)
        self.window.destroy()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mumu-autotask-gui")
    parser.add_argument("--config", default="config.json")
    return parser


def _configure_file_logging(config_path: Path) -> None:
    try:
        logging.basicConfig(
            filename=config_path.parent / "mumu_autotask_gui.log",
            level=logging.INFO,
            encoding="utf-8",
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    except OSError:
        logging.basicConfig(level=logging.INFO)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config_path = Path(args.config).resolve()
    _configure_file_logging(config_path)
    try:
        settings = load_settings(config_path)
        if len(settings.devices) != 3:
            raise ConfigError("GUI requires exactly the three configured MuMu devices")
    except ConfigError as exc:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("配置错误", str(exc), parent=root)
        root.destroy()
        return 2

    root = tk.Tk()
    backend = GuiBackend(CliRunner(config_path))
    LauncherApp(root, settings, backend)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        backend.runner.cancel_all()
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "DeviceManagerWindow",
    "HuntBatchError",
    "HuntBatchOutcome",
    "HuntBatchQueue",
    "HuntBatchTarget",
    "HuntWaveBatch",
    "LauncherApp",
    "APP_TITLE",
    "CATEGORY_META",
    "QUALITY_META",
    "TaskDispatcher",
    "build_task_queue",
    "build_hunt_queue",
    "build_category_queue",
    "build_hunt_waves",
    "build_parser",
    "main",
    "terminal_target_ids_from_status_payload",
    "validate_claim_intel_receipt",
    "validate_wait_intel_receipt",
]
