from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from mumu_autotask.gui import (
    DeviceManagerWindow,
    HuntBatchError,
    HuntBatchQueue,
    HuntWaveBatch,
    build_hunt_queue,
    build_hunt_waves,
    terminal_target_ids_from_status_payload,
    validate_claim_intel_receipt,
    validate_march_intel_receipt,
    validate_wait_intel_receipt,
    _is_online_status,
)


def intel_item(
    runtime_id: int,
    quality: str,
    *,
    expires_at: int,
) -> dict[str, object]:
    return {
        "runtime_id": runtime_id,
        "quality": quality,
        "expires_at": expires_at,
        "level": 13,
    }


class HuntBatchQueueTests(unittest.TestCase):
    def test_online_status_requires_foreground_game_activity(self) -> None:
        payload = {
            "adb": "device",
            "kingdom": 4549,
            "playerprefs_kingdom": 4549,
            "sdk_server_id": 4549,
            "pid": 7359,
            "process": "Whiteout Survival",
            "game_activity_foreground": True,
        }

        self.assertTrue(_is_online_status(payload))
        self.assertFalse(
            _is_online_status({**payload, "game_activity_foreground": False})
        )
        without_activity = {
            key: value
            for key, value in payload.items()
            if key != "game_activity_foreground"
        }
        self.assertFalse(_is_online_status(without_activity))

    def test_selected_qualities_expand_by_fixed_quality_order_and_current_count(
        self,
    ) -> None:
        items = [
            intel_item(42, "yellow", expires_at=900),
            intel_item(31, "purple", expires_at=500),
            intel_item(20, "blue", expires_at=300),
            intel_item(11, "green", expires_at=200),
            intel_item(41, "yellow", expires_at=800),
            intel_item(32, "purple", expires_at=600),
        ]

        queue = build_hunt_queue(
            items,
            ("yellow", "purple", "green", "blue"),
        )

        self.assertEqual(
            [(target.quality, target.runtime_id) for target in queue],
            [
                ("green", 11),
                ("blue", 20),
                ("purple", 31),
                ("purple", 32),
                ("yellow", 41),
                ("yellow", 42),
            ],
        )

    def test_error_reconciled_as_processed_continues_with_same_quality_target(
        self,
    ) -> None:
        targets = build_hunt_queue(
            [
                intel_item(436, "purple", expires_at=100),
                intel_item(437, "purple", expires_at=200),
            ],
            ("purple",),
        )
        batch = HuntBatchQueue(targets)

        first = batch.next_target()
        self.assertEqual(first.runtime_id, 436)  # type: ignore[union-attr]
        batch.mark_attempt_error(
            "go action was invoked but the intelligence status did not change"
        )
        outcome = batch.reconcile_current({437})

        self.assertEqual(outcome.status, "reconciled")
        second = batch.next_target({437})
        self.assertEqual(second.runtime_id, 437)  # type: ignore[union-attr]
        batch.mark_attempt_success(437, "verified")
        self.assertTrue(batch.complete)
        self.assertEqual(
            batch.counts,
            {"success": 1, "reconciled": 1, "failed": 0, "skipped": 0},
        )

    def test_failed_target_does_not_stop_later_selected_quality(self) -> None:
        targets = build_hunt_queue(
            [
                intel_item(101, "green", expires_at=100),
                intel_item(202, "purple", expires_at=200),
            ],
            ("green", "purple"),
        )
        batch = HuntBatchQueue(targets)

        first = batch.next_target()
        self.assertEqual(first.runtime_id, 101)  # type: ignore[union-attr]
        batch.mark_attempt_error("first dispatch failed")
        outcome = batch.reconcile_current({101, 202})
        self.assertEqual(outcome.status, "failed")

        second = batch.next_target({101, 202})
        self.assertEqual(second.runtime_id, 202)  # type: ignore[union-attr]
        batch.mark_attempt_success(202, "verified")

        self.assertTrue(batch.complete)
        self.assertEqual(
            batch.counts,
            {"success": 1, "reconciled": 0, "failed": 1, "skipped": 0},
        )
        self.assertIn("成功 1 个", batch.summary())
        self.assertIn("失败 1 个", batch.summary())


class HuntWaveBatchTests(unittest.TestCase):
    def targets(self, count: int = 7):
        return build_hunt_queue(
            [
                intel_item(100 + index, "purple", expires_at=1000 + index)
                for index in range(count)
            ],
            ("purple",),
        )

    def begin_dispatch(self, batch: HuntWaveBatch, runtime_id: int) -> None:
        target = batch.begin_next_dispatch()
        self.assertIsNotNone(target)
        self.assertEqual(target.runtime_id, runtime_id)  # type: ignore[union-attr]

    def test_waves_are_partitioned_in_order_and_concurrency_is_frozen(self) -> None:
        targets = self.targets()

        waves = build_hunt_waves(targets, 3)
        batch = HuntWaveBatch(targets, 3)

        self.assertEqual(
            [[target.runtime_id for target in wave] for wave in waves],
            [[100, 101, 102], [103, 104, 105], [106]],
        )
        self.assertEqual(batch.concurrency, 3)
        self.assertEqual(batch.waves, waves)
        self.assertEqual(
            [[target.runtime_id for target in wave] for wave in build_hunt_waves(targets, 4)],
            [[100, 101, 102, 103], [104, 105, 106]],
        )
        for invalid in (0, 5, True, 1.5):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(HuntBatchError, "1-4"):
                    build_hunt_waves(targets, invalid)  # type: ignore[arg-type]

    def test_each_wave_prepares_all_dispatches_then_waits_before_next(self) -> None:
        batch = HuntWaveBatch(self.targets(3), 2)

        prepared = batch.prepare_current_wave()
        self.assertEqual([target.runtime_id for target in prepared], [100, 101])
        self.assertEqual(batch.dispatch_pending_ids, (100, 101))
        self.assertEqual(batch.dispatch_queued_ids, (100, 101))
        self.begin_dispatch(batch, 100)
        batch.mark_dispatched(100, "server proof")
        self.assertEqual(batch.dispatch_pending_ids, (101,))
        self.begin_dispatch(batch, 101)
        batch.mark_dispatched(101, "server proof")
        self.assertTrue(batch.dispatch_callbacks_done)
        batch.finish_dispatches()
        self.assertEqual(batch.wait_target_ids, (100, 101))
        self.assertEqual(batch.wave_number, 1)
        self.assertEqual(batch.begin_wait(), (100, 101))

        outcomes = batch.complete_current_wave((100, 101), "completion proof")
        self.assertEqual([outcome.status for outcome in outcomes], ["success", "success"])
        self.assertEqual(batch.wave_number, 2)
        self.assertEqual(
            [target.runtime_id for target in batch.prepare_current_wave()],
            [102],
        )

    def test_dispatch_errors_are_reconciled_before_remaining_wave_targets(self) -> None:
        batch = HuntWaveBatch(self.targets(4), 3)

        batch.prepare_current_wave()
        self.begin_dispatch(batch, 100)
        batch.mark_attempt_error(100, "first callback failed")

        self.assertTrue(batch.dispatch_callbacks_done)
        self.assertEqual(batch.dispatch_error_ids, (100,))
        self.assertEqual(batch.begin_dispatch_reconciliation(), (100,))
        outcomes = batch.reconcile_dispatch_errors({100, 101, 102, 103})

        self.assertEqual(
            [(outcome.target.runtime_id, outcome.status) for outcome in outcomes],
            [(100, "failed")],
        )
        self.assertEqual(batch.wave_phase, "dispatching")
        self.begin_dispatch(batch, 101)
        batch.mark_dispatched(101, "second callback succeeded")
        self.begin_dispatch(batch, 102)
        batch.mark_attempt_error(102, "third callback failed")
        self.assertEqual(batch.begin_dispatch_reconciliation(), (102,))
        outcomes = batch.reconcile_dispatch_errors({100, 101, 103})
        self.assertEqual(outcomes, ())
        self.assertEqual(batch.reconciled_dispatch_ids, (102,))
        self.assertEqual(batch.wait_target_ids, (101, 102))
        self.assertEqual(batch.wave_phase, "resolved")
        self.assertEqual(batch.begin_wait(), (101, 102))
        completed = batch.complete_current_wave((101, 102), "completion proof")
        self.assertEqual(
            [(outcome.target.runtime_id, outcome.status) for outcome in completed],
            [(101, "success"), (102, "reconciled")],
        )
        self.assertEqual(batch.wave_number, 2)

    def test_duplicate_or_wrong_wave_callback_cannot_mutate_target_state(self) -> None:
        batch = HuntWaveBatch(self.targets(3), 2)
        batch.prepare_current_wave()
        self.begin_dispatch(batch, 100)
        batch.mark_dispatched(100, "server proof")

        with self.assertRaisesRegex(HuntBatchError, "状态"):
            batch.mark_attempt_error(100, "duplicate callback")
        with self.assertRaisesRegex(HuntBatchError, "不属于当前波次"):
            batch.mark_dispatched(102, "wrong wave")

        self.assertEqual(batch.wait_target_ids, (100,))
        self.assertEqual(batch.dispatch_pending_ids, (101,))

    def test_wait_failure_reconciles_then_stops_and_skips_later_waves(self) -> None:
        batch = HuntWaveBatch(self.targets(3), 2)
        batch.prepare_current_wave()
        for runtime_id in (100, 101):
            self.begin_dispatch(batch, runtime_id)
            batch.mark_dispatched(runtime_id, "server proof")
        batch.finish_dispatches()
        batch.begin_wait()

        outcomes = batch.reconcile_wait_failure(
            {101, 102},
            "等待完成超时",
        )
        self.assertEqual(
            [(outcome.target.runtime_id, outcome.status) for outcome in outcomes],
            [(100, "reconciled"), (101, "failed")],
        )

        self.assertTrue(batch.all_waves_done)
        self.assertEqual(
            [(outcome.target.runtime_id, outcome.status) for outcome in batch.outcomes],
            [(100, "reconciled"), (101, "failed"), (102, "skipped")],
        )
        self.assertFalse(batch.can_claim)
        with self.assertRaisesRegex(HuntBatchError, "禁止领取"):
            batch.begin_claim()

    def test_failed_wait_reconciliation_skips_every_unstarted_wave(self) -> None:
        batch = HuntWaveBatch(self.targets(5), 2)
        batch.prepare_current_wave()
        for runtime_id in (100, 101):
            self.begin_dispatch(batch, runtime_id)
            batch.mark_dispatched(runtime_id, "server proof")
        batch.finish_dispatches()
        batch.begin_wait()

        outcomes = batch.fail_wait_reconciliation("只读刷新失败")

        self.assertEqual(
            [(outcome.target.runtime_id, outcome.status) for outcome in outcomes],
            [(100, "failed"), (101, "failed")],
        )
        self.assertEqual(
            [(outcome.target.runtime_id, outcome.status) for outcome in batch.outcomes],
            [
                (100, "failed"),
                (101, "failed"),
                (102, "skipped"),
                (103, "skipped"),
                (104, "skipped"),
            ],
        )
        self.assertTrue(batch.all_waves_done)

    def test_unresolved_dispatch_reconciliation_stops_the_entire_batch(self) -> None:
        batch = HuntWaveBatch(self.targets(4), 3)
        batch.prepare_current_wave()
        self.begin_dispatch(batch, 100)
        batch.mark_dispatched(100, "server proof")
        self.begin_dispatch(batch, 101)
        batch.mark_attempt_error(101, "dispatch result was ambiguous")

        outcomes = batch.abort_unresolved_dispatch("active role changed")

        self.assertEqual(
            [(outcome.target.runtime_id, outcome.status) for outcome in outcomes],
            [
                (100, "failed"),
                (101, "failed"),
                (102, "skipped"),
                (103, "skipped"),
            ],
        )
        self.assertTrue(batch.all_waves_done)
        self.assertFalse(batch.can_claim)

    def test_claim_can_start_exactly_once_and_requires_disappearance(self) -> None:
        batch = HuntWaveBatch(self.targets(2), 2)
        batch.prepare_current_wave()
        for runtime_id in (100, 101):
            self.begin_dispatch(batch, runtime_id)
            batch.mark_dispatched(runtime_id, "server proof")
        batch.finish_dispatches()
        batch.begin_wait()
        batch.complete_current_wave((100, 101), "completion proof")

        self.assertEqual(batch.begin_claim(), (100, 101))
        with self.assertRaisesRegex(HuntBatchError, "已经发起"):
            batch.begin_claim()
        self.assertFalse(batch.verify_claim_absence({101}))
        self.assertIn("101", batch.summary())
        self.assertTrue(batch.verify_claim_absence(set()))
        self.assertTrue(batch.claim_verified)
        self.assertIn("奖励领取已核验", batch.summary())

    def test_target_missing_before_dispatch_is_already_completed(self) -> None:
        batch = HuntWaveBatch(self.targets(2), 2)

        prepared = batch.prepare_current_wave({101})
        self.assertEqual([target.runtime_id for target in prepared], [101])
        self.begin_dispatch(batch, 101)
        batch.mark_dispatched(101, "server proof")
        self.assertEqual(batch.outcomes[0].status, "reconciled")
        batch.finish_dispatches()
        batch.begin_wait()
        batch.complete_current_wave((101,), "completion proof")

        self.assertTrue(batch.can_claim)

    def test_wait_receipt_requires_exact_order_and_terminal_proof(self) -> None:
        payload = {
            "serial": "device-1",
            "kingdom": 4549,
            "role": "打工人",
            "target_ids": [100, 101],
            "wait_completed": True,
            "statuses": [
                {"runtime_id": 100, "state": "COMPLETED", "quest_status": 2},
                {"runtime_id": 101, "state": "MISSING", "quest_status": None},
            ],
        }
        self.assertEqual(
            validate_wait_intel_receipt(
                payload,
                "device-1",
                (100, 101),
                expected_role="打工人",
            ),
            (100, 101),
        )
        with self.assertRaisesRegex(HuntBatchError, "仍未消失"):
            validate_wait_intel_receipt(
                payload,
                "device-1",
                (100, 101),
                require_missing=True,
                expected_role="打工人",
            )
        tampered = dict(payload, target_ids=[101, 100])
        with self.assertRaisesRegex(HuntBatchError, "目标 ID"):
            validate_wait_intel_receipt(
                tampered,
                "device-1",
                (100, 101),
                expected_role="打工人",
            )
        with self.assertRaisesRegex(HuntBatchError, "角色"):
            validate_wait_intel_receipt(
                dict(payload, role="打工魂"),
                "device-1",
                (100, 101),
                expected_role="打工人",
            )

    def test_march_receipt_is_bound_to_frozen_role_and_exact_target(self) -> None:
        payload = {
            "serial": "device-1",
            "kingdom": 4549,
            "role": "打工人",
            "request_dispatched": True,
            "target": {"runtime_id": 100},
        }
        self.assertEqual(
            validate_march_intel_receipt(
                payload,
                "device-1",
                100,
                expected_role="打工人",
            ),
            100,
        )
        for mutation in (
            {"serial": "device-2"},
            {"kingdom": 4583},
            {"role": "打工魂"},
            {"request_dispatched": False},
            {"target": {"runtime_id": 101}},
        ):
            with self.subTest(mutation=mutation):
                with self.assertRaises(HuntBatchError):
                    validate_march_intel_receipt(
                        dict(payload, **mutation),
                        "device-1",
                        100,
                        expected_role="打工人",
                    )

    def test_reconcile_refresh_rejects_role_drift_before_mutating_items(self) -> None:
        manager = object.__new__(DeviceManagerWindow)
        manager.profile = SimpleNamespace(
            serial="device-1",
            roles=("打工人", "打工魂"),
        )
        manager.hunt_batch = object()
        manager.hunt_role = "打工人"
        manager.current_items = [{"runtime_id": 999}]

        with self.assertRaisesRegex(HuntBatchError, "批次开始角色"):
            manager._apply_intel_payload(
                {
                    "serial": "device-1",
                    "kingdom": 4549,
                    "role": "打工魂",
                    "items": [{"runtime_id": 100}],
                }
            )

        self.assertEqual(manager.current_items, [{"runtime_id": 999}])

    def test_start_hunt_immediately_freezes_role_and_default_concurrency(self) -> None:
        manager = object.__new__(DeviceManagerWindow)
        manager.busy = False
        manager.profile = SimpleNamespace(
            serial="device-1",
            roles=("打工人", "打工魂"),
        )
        manager.current_role = "打工人"
        manager.current_items = [
            intel_item(100 + index, "purple", expires_at=1000 + index)
            for index in range(4)
        ]
        manager.concurrency_var = SimpleNamespace(get=lambda: 3)
        manager._selected_qualities = lambda: ("purple",)
        manager._available_runtime_ids = lambda: {100, 101, 102, 103}
        events: list[tuple[object, ...]] = []

        def set_busy(busy: bool, message: str) -> None:
            manager.busy = busy
            events.append(("busy", busy, message))

        manager._set_busy = set_busy
        manager._log = lambda message: events.append(("log", message))
        manager._dispatch_next_hunt = (
            lambda available: events.append(("dispatch", available))
        )

        class DialogTrap:
            def __getattr__(self, name: str) -> object:
                raise AssertionError(f"direct start must not open messagebox.{name}")

        with patch("mumu_autotask.gui.messagebox", DialogTrap()):
            manager.start_hunt()

        self.assertTrue(manager.busy)
        self.assertEqual(manager.hunt_role, "打工人")
        self.assertEqual(manager.hunt_batch.concurrency, 3)
        self.assertEqual([len(wave) for wave in manager.hunt_batch.waves], [3, 1])
        self.assertEqual(events[-1], ("dispatch", {100, 101, 102, 103}))

    def test_click_and_keyboard_handler_directly_start_without_second_event(self) -> None:
        manager = object.__new__(DeviceManagerWindow)
        starts: list[str] = []
        manager.start_hunt = lambda: starts.append("started")

        result = manager._start_hunt_from_event(object())

        self.assertEqual(starts, ["started"])
        self.assertEqual(result, "break")

    def test_gui_serializes_wave_dispatches_then_waits_for_entire_wave(self) -> None:
        manager = object.__new__(DeviceManagerWindow)
        targets = build_hunt_queue(
            [
                intel_item(100 + index, "purple", expires_at=1000 + index)
                for index in range(3)
            ],
            ("purple",),
        )
        manager.window = SimpleNamespace(winfo_exists=lambda: 1)
        manager.profile = SimpleNamespace(serial="device-1")
        manager.hunt_batch = HuntWaveBatch(targets, 3)
        manager.hunt_role = "打工人"
        events: list[tuple[object, ...]] = []
        manager.action_text = SimpleNamespace(
            set=lambda value: events.append(("status", value))
        )
        manager._log = lambda message: events.append(("log", message))
        manager._log_batch_outcome = lambda outcome: events.append(("outcome", outcome))
        manager._wait_current_wave = lambda: events.append(
            ("wait", manager.hunt_batch.wait_target_ids)
        )
        march_calls: list[int] = []
        call_order: list[tuple[str, object]] = []

        def ensure_world(
            serial: str,
            *,
            expected_role: str,
        ) -> None:
            self.assertEqual((serial, expected_role), ("device-1", "打工人"))
            call_order.append(("ensure-world", expected_role))

        def march(
            serial: str,
            quality: str,
            *,
            runtime_id: int,
            expected_role: str,
        ) -> dict[str, object]:
            self.assertEqual((serial, quality, expected_role), ("device-1", "purple", "打工人"))
            march_calls.append(runtime_id)
            call_order.append(("march", runtime_id))
            return {
                "serial": serial,
                "kingdom": 4549,
                "role": expected_role,
                "request_dispatched": True,
                "target": {"runtime_id": runtime_id},
                "quest_status_after": 1,
            }

        manager.backend = SimpleNamespace(
            ensure_world=ensure_world,
            march=march,
        )

        class CapturingDispatcher:
            def __init__(self) -> None:
                self.submissions: list[tuple[object, object]] = []

            def submit(self, action: object, callback: object) -> None:
                self.submissions.append((action, callback))

        dispatcher = CapturingDispatcher()
        manager.dispatcher = dispatcher

        manager._dispatch_next_hunt({100, 101, 102})

        self.assertEqual(len(dispatcher.submissions), 1)
        self.assertEqual(manager.hunt_batch.dispatch_active_ids, (100,))
        self.assertEqual(manager.hunt_batch.dispatch_queued_ids, (101, 102))
        self.assertFalse(any(event[0] == "wait" for event in events))

        for index, runtime_id in enumerate((100, 101, 102)):
            action, callback = dispatcher.submissions[index]
            result = action()  # type: ignore[operator]
            self.assertEqual(march_calls[-1], runtime_id)
            callback(result, None)  # type: ignore[operator]
            if index < 2:
                self.assertEqual(len(dispatcher.submissions), index + 2)
                self.assertEqual(
                    manager.hunt_batch.dispatch_active_ids,
                    (runtime_id + 1,),
                )
                self.assertNotIn(("wait", (100, 101, 102)), events)

        self.assertEqual(march_calls, [100, 101, 102])
        self.assertEqual(
            call_order,
            [
                ("ensure-world", "打工人"),
                ("march", 100),
                ("ensure-world", "打工人"),
                ("march", 101),
                ("ensure-world", "打工人"),
                ("march", 102),
            ],
        )
        self.assertEqual(len(dispatcher.submissions), 3)
        self.assertEqual(manager.hunt_batch.dispatch_pending_ids, ())
        self.assertEqual(manager.hunt_batch.wait_target_ids, (100, 101, 102))
        self.assertEqual(manager.hunt_batch.wave_phase, "resolved")
        self.assertEqual(
            [event for event in events if event[0] == "wait"],
            [("wait", (100, 101, 102))],
        )

    def test_gui_reconciles_dispatch_error_before_next_serial_dispatch(self) -> None:
        manager = object.__new__(DeviceManagerWindow)
        targets = build_hunt_queue(
            [
                intel_item(100 + index, "purple", expires_at=1000 + index)
                for index in range(2)
            ],
            ("purple",),
        )
        manager.window = SimpleNamespace(winfo_exists=lambda: 1)
        manager.profile = SimpleNamespace(serial="device-1", roles=("打工人",))
        manager.hunt_batch = HuntWaveBatch(targets, 2)
        manager.hunt_role = "打工人"
        manager.current_items = [
            intel_item(100, "purple", expires_at=1000),
            intel_item(101, "purple", expires_at=1001),
        ]
        events: list[tuple[object, ...]] = []
        manager.identity_text = SimpleNamespace(set=lambda value: events.append(("identity", value)))
        manager.action_text = SimpleNamespace(
            set=lambda value: events.append(("status", value))
        )
        manager._render_items = lambda: events.append(("render",))
        manager._log = lambda message: events.append(("log", message))
        manager._log_batch_outcome = lambda outcome: events.append(("outcome", outcome))
        manager._wait_current_wave = lambda: events.append(
            ("wait", manager.hunt_batch.wait_target_ids)
        )

        class CapturingDispatcher:
            def __init__(self) -> None:
                self.submissions: list[tuple[object, object]] = []

            def submit(self, action: object, callback: object) -> None:
                self.submissions.append((action, callback))

        dispatcher = CapturingDispatcher()
        manager.dispatcher = dispatcher
        manager.backend = SimpleNamespace(
            march=lambda *args, **kwargs: {},
            inspect_intel=lambda serial: {
                "serial": serial,
                "kingdom": 4549,
                "role": "打工人",
                "pid": 7,
                "items": [intel_item(101, "purple", expires_at=1001)],
            },
        )

        manager._dispatch_next_hunt({100, 101})
        self.assertEqual(len(dispatcher.submissions), 1)

        first_callback = dispatcher.submissions[0][1]
        first_callback(None, RuntimeError("ambiguous"))  # type: ignore[operator]
        self.assertEqual(len(dispatcher.submissions), 2)
        refresh_action, refresh_callback = dispatcher.submissions[1]
        refresh_callback(refresh_action(), None)  # type: ignore[operator]

        self.assertEqual(len(dispatcher.submissions), 3)
        self.assertEqual(manager.hunt_batch.dispatch_active_ids, (101,))
        self.assertFalse(any(event[0] == "wait" for event in events))
        second_action, second_callback = dispatcher.submissions[2]
        second_callback(
            {
                "serial": "device-1",
                "kingdom": 4549,
                "role": "打工人",
                "request_dispatched": True,
                "target": {"runtime_id": 101},
                "quest_status_after": 1,
            },
            None,
        )  # type: ignore[operator]

        self.assertEqual(manager.hunt_batch.reconciled_dispatch_ids, (100,))
        self.assertEqual(manager.hunt_batch.wait_target_ids, (100, 101))
        self.assertEqual(
            [event for event in events if event[0] == "wait"],
            [("wait", (100, 101))],
        )

    def test_gui_stops_batch_when_dispatch_error_is_confirmed_failed(self) -> None:
        manager = object.__new__(DeviceManagerWindow)
        targets = build_hunt_queue(
            [
                intel_item(100, "purple", expires_at=1000),
                intel_item(101, "purple", expires_at=1001),
            ],
            ("purple",),
        )
        manager.window = SimpleNamespace(winfo_exists=lambda: 1)
        manager.profile = SimpleNamespace(serial="device-1", roles=("打工人",))
        batch = HuntWaveBatch(targets, 2)
        manager.hunt_batch = batch
        manager.hunt_role = "打工人"
        manager.current_items = [
            intel_item(100, "purple", expires_at=1000),
            intel_item(101, "purple", expires_at=1001),
        ]
        events: list[tuple[object, ...]] = []
        manager.identity_text = SimpleNamespace(set=lambda value: events.append(("identity", value)))
        manager.action_text = SimpleNamespace(
            set=lambda value: events.append(("status", value))
        )
        manager._render_items = lambda: events.append(("render",))
        manager._log = lambda message: events.append(("log", message))
        manager._log_batch_outcome = lambda outcome: events.append(("outcome", outcome))
        manager._set_busy = lambda busy, message: events.append(
            ("busy", busy, message)
        )
        manager._wait_current_wave = lambda: events.append(
            ("wait", manager.hunt_batch.wait_target_ids)
        )

        class CapturingDispatcher:
            def __init__(self) -> None:
                self.submissions: list[tuple[object, object]] = []

            def submit(self, action: object, callback: object) -> None:
                self.submissions.append((action, callback))

        dispatcher = CapturingDispatcher()
        manager.dispatcher = dispatcher
        manager.backend = SimpleNamespace(
            march=lambda *args, **kwargs: {},
            inspect_intel=lambda serial: {
                "serial": serial,
                "kingdom": 4549,
                "role": "打工人",
                "pid": 7,
                "items": [
                    intel_item(100, "purple", expires_at=1000),
                    intel_item(101, "purple", expires_at=1001),
                ],
            },
            intel_status=lambda *args, **kwargs: {
                "serial": "device-1",
                "kingdom": 4549,
                "role": "打工人",
                "target_ids": [100, 101],
                "statuses_after": [
                    {"runtime_id": 100, "state": "PENDING"},
                    {"runtime_id": 101, "state": "PENDING"},
                ],
            },
        )

        manager._dispatch_next_hunt({100, 101})
        first_callback = dispatcher.submissions[0][1]
        first_callback(None, RuntimeError("direct failure"))  # type: ignore[operator]
        refresh_action, refresh_callback = dispatcher.submissions[1]
        refresh_callback(refresh_action(), None)  # type: ignore[operator]
        final_action, final_callback = dispatcher.submissions[2]
        final_callback(final_action(), None)  # type: ignore[operator]

        self.assertEqual(len(dispatcher.submissions), 3)
        self.assertIsNone(manager.hunt_batch)
        self.assertTrue(batch.all_waves_done)
        self.assertEqual(
            [(outcome.target.runtime_id, outcome.status) for outcome in batch.outcomes],
            [(100, "failed"), (101, "skipped")],
        )
        self.assertFalse(any(event[0] == "wait" for event in events))
        self.assertTrue(any(event[0] == "busy" and event[1] is False for event in events))

    def test_final_reconcile_converts_terminal_failures_and_claims(self) -> None:
        manager = object.__new__(DeviceManagerWindow)
        targets = build_hunt_queue(
            [
                intel_item(100, "purple", expires_at=1000),
                intel_item(101, "purple", expires_at=1001),
            ],
            ("purple",),
        )
        batch = HuntWaveBatch(targets, 2)
        manager.hunt_batch = batch
        manager.hunt_role = "打工人"
        manager.profile = SimpleNamespace(serial="device-1")
        manager.window = SimpleNamespace(winfo_exists=lambda: 1)
        events: list[tuple[object, ...]] = []
        manager.action_text = SimpleNamespace(
            set=lambda value: events.append(("status", value))
        )
        manager._log = lambda message: events.append(("log", message))
        manager._log_batch_outcome = lambda outcome: events.append(("outcome", outcome))
        manager._set_busy = lambda busy, message: events.append(("busy", busy, message))
        manager._claim_hunt_rewards = lambda: events.append(("claim",))

        batch.prepare_current_wave()
        self.begin_dispatch(batch, 100)
        batch.mark_attempt_error(100, "出征回执没有证明")
        batch.begin_dispatch_reconciliation()
        batch.reconcile_dispatch_errors({100, 101})
        batch.abort_unresolved_dispatch("停止")

        class CapturingDispatcher:
            def __init__(self) -> None:
                self.submissions: list[tuple[object, object]] = []

            def submit(self, action: object, callback: object) -> None:
                self.submissions.append((action, callback))

        dispatcher = CapturingDispatcher()
        manager.dispatcher = dispatcher
        manager.backend = SimpleNamespace(
            intel_status=lambda serial, target_ids, *, expected_role: {
                "serial": serial,
                "kingdom": 4549,
                "role": expected_role,
                "target_ids": list(target_ids),
                "statuses_after": [
                    {"runtime_id": 100, "state": "COMPLETED"},
                    {"runtime_id": 101, "state": "MISSING"},
                ],
            }
        )

        manager._finish_hunt_batch()
        self.assertEqual(len(dispatcher.submissions), 1)
        action, callback = dispatcher.submissions[0]
        callback(action(), None)  # type: ignore[operator]

        self.assertEqual(
            [(outcome.target.runtime_id, outcome.status) for outcome in batch.outcomes],
            [(100, "reconciled"), (101, "reconciled")],
        )
        self.assertIn(("claim",), events)

    def test_terminal_status_payload_reports_completed_and_missing_ids(self) -> None:
        payload = {
            "serial": "device-1",
            "kingdom": 4549,
            "role": "打工人",
            "target_ids": [100, 101, 102],
            "statuses_after": [
                {"runtime_id": 100, "state": "COMPLETED"},
                {"runtime_id": 101, "state": "MISSING"},
                {"runtime_id": 102, "state": "PENDING"},
            ],
        }
        self.assertEqual(
            terminal_target_ids_from_status_payload(
                payload,
                "device-1",
                (100, 101, 102),
                expected_role="打工人",
            ),
            {100, 101},
        )

    def test_finish_hunt_batch_uses_status_and_log_without_dialog(self) -> None:
        manager = object.__new__(DeviceManagerWindow)
        manager.hunt_batch = HuntWaveBatch(
            build_hunt_queue(
                [intel_item(100, "purple", expires_at=1000)],
                ("purple",),
            ),
            1,
        )
        manager.hunt_role = "打工人"
        events: list[tuple[object, ...]] = []
        manager._set_busy = lambda busy, message: events.append(
            ("busy", busy, message)
        )
        manager.action_text = SimpleNamespace(
            set=lambda message: events.append(("status", message))
        )
        manager._log = lambda message: events.append(("log", message))

        class DialogTrap:
            def __getattr__(self, name: str) -> object:
                raise AssertionError(f"batch finish must not open messagebox.{name}")

        with patch("mumu_autotask.gui.messagebox", DialogTrap()):
            manager._finish_hunt_batch()

        self.assertIsNone(manager.hunt_batch)
        self.assertIsNone(manager.hunt_role)
        self.assertEqual([event[0] for event in events], ["busy", "status", "log"])

    def test_claim_receipt_requires_one_proof_and_all_ids_missing(self) -> None:
        payload = {
            "serial": "device-1",
            "kingdom": 4549,
            "role": "打工人",
            "target_ids": [100, 101],
            "claim_allowed": True,
            "request_dispatched": True,
            "idempotent": False,
            "verified_missing": True,
            "statuses_after": [
                {"runtime_id": 100, "state": "MISSING", "quest_status": None},
                {"runtime_id": 101, "state": "MISSING", "quest_status": None},
            ],
        }
        self.assertEqual(
            validate_claim_intel_receipt(
                payload,
                "device-1",
                (100, 101),
                expected_role="打工人",
            ),
            (100, 101),
        )
        for mutation in (
            {"idempotent": True},
            {"verified_missing": False},
            {"kingdom": 4583},
            {"role": "打工魂"},
        ):
            with self.subTest(mutation=mutation):
                with self.assertRaises(HuntBatchError):
                    validate_claim_intel_receipt(
                        dict(payload, **mutation),
                        "device-1",
                        (100, 101),
                        expected_role="打工人",
                    )


if __name__ == "__main__":
    unittest.main()
