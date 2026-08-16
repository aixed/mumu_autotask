from __future__ import annotations

import unittest

from mumu_autotask.business import (
    BusinessError,
    INTEL_COMPLETED,
    INTEL_MISSING,
    INTEL_PENDING,
    IntelItem,
    IntelSnapshot,
    build_claim_intel_lua,
    build_close_expedition_lua,
    build_commit_march_lua,
    build_inspect_intel_lua,
    build_intel_status_lua,
    build_march_ready_lua,
    build_open_march_lua,
    build_verify_march_lua,
    normalize_quality,
    normalize_target_ids,
    parse_claim_intel_output,
    parse_commit_output,
    parse_intel_output,
    parse_intel_status_output,
    parse_march_output,
    parse_open_output,
    parse_ready_output,
    parse_verify_output,
    select_march_target,
    script_sha256,
    validate_role_whitelist,
)


ROLE = "worker-one"
ROLE_HEX = ROLE.encode("utf-8").hex()


def intel_output(*items: str, role_hex: str = ROLE_HEX, kingdom: str = "4549") -> str:
    return "\n".join(
        (
            "MUMU_AUTOTASK\t1\tINTEL",
            f"ROLE\t{role_hex}",
            f"KINGDOM\t{kingdom}",
            *items,
            f"END\t{len(items)}",
        )
    )


def intel_status_output(
    *targets: str,
    role_hex: str = ROLE_HEX,
    kingdom: str = "4549",
) -> str:
    return "\n".join(
        (
            "MUMU_AUTOTASK\t1\tINTEL_STATUS",
            f"ROLE\t{role_hex}",
            f"KINGDOM\t{kingdom}",
            *targets,
            f"END\t{len(targets)}",
        )
    )


PURPLE_ITEM = "ITEM\t71\t1701\t0\t759\t774\t1900000000\tpurple\t4\t813\t13\t10"
GREEN_ITEM = "ITEM\t70\t1700\t0\t700\t701\t1800000000\tgreen\t2\t808\t8\t10"


class BusinessTests(unittest.TestCase):
    def test_quality_alias_and_invalid_values(self) -> None:
        self.assertEqual(normalize_quality(" ORANGE "), "yellow")
        self.assertEqual(normalize_quality("Purple"), "purple")
        self.assertEqual(normalize_quality("蓝色"), "blue")
        self.assertEqual(normalize_quality("黄色"), "yellow")
        with self.assertRaisesRegex(BusinessError, "quality must be one of"):
            normalize_quality("red")

    def test_role_whitelist_rejects_empty_duplicate_and_control_text(self) -> None:
        with self.assertRaisesRegex(BusinessError, "no configured role"):
            validate_role_whitelist(())
        with self.assertRaisesRegex(BusinessError, "duplicated"):
            validate_role_whitelist((ROLE, ROLE))
        with self.assertRaisesRegex(BusinessError, "control"):
            validate_role_whitelist(("bad\nrole",))

    def test_target_ids_require_unique_positive_integers(self) -> None:
        self.assertEqual(normalize_target_ids((71, 72)), (71, 72))
        for values in ((), (0,), (True,), (71, 71)):
            with self.subTest(values=values):
                with self.assertRaises(BusinessError):
                    normalize_target_ids(values)

    def test_inspect_script_only_embeds_role_as_hex_and_is_read_only(self) -> None:
        code = build_inspect_intel_lua((ROLE,))
        self.assertNotIn(ROLE, code)
        self.assertIn(ROLE_HEX, code)
        self.assertIn("EXPECTED_KINGDOM = 4549", code)
        self.assertIn("GetPlayerKid", code)
        self.assertIn("GetPlayerServerId", code)
        self.assertIn("GetQuestType", code)
        self.assertIn("IsShowInWorld", code)
        self.assertIn("GetValidTime", code)
        self.assertIn("stamtina_expend", code)
        self.assertNotIn("TimeUtil.GetServerTime", code)
        self.assertNotIn("SendMsg", code)
        self.assertNotIn("RequestMarch", code)
        self.assertEqual(script_sha256(code), script_sha256(code))

    def test_status_and_claim_scripts_bind_ids_and_native_one_key_method(self) -> None:
        status_code = build_intel_status_lua((ROLE,), (71, 99))
        claim_code = build_claim_intel_lua((ROLE,), (71, 99))
        self.assertIn("TARGET_RUNTIME_IDS = { 71, 99 }", status_code)
        self.assertIn("checked_identity()", status_code)
        self.assertIn("exact_intel_statuses(TARGET_RUNTIME_IDS)", status_code)
        self.assertIn('call(quest, "IsCompleted", "quest completion")', status_code)
        self.assertNotIn("RequestReceiveAllQuestReward", status_code)
        self.assertNotIn("SendMsg", status_code)
        self.assertEqual(claim_code.count("RequestReceiveAllQuestReward"), 1)
        self.assertIn("cannot claim while requested intelligence is pending", claim_code)
        self.assertNotIn('req_intelligence_receive_onekey', claim_code)

    def test_march_scripts_bind_exact_target_and_preserve_button_chain(self) -> None:
        target = IntelItem(
            71, 1701, 1, 759, 774, 1900000000, "purple", 4, 813, 13, 10
        )
        open_code = build_open_march_lua((ROLE,), target)
        commit_code = build_commit_march_lua((ROLE,), target)
        self.assertIn("TARGET_RUNTIME_ID = 71", open_code)
        self.assertIn("TARGET_WORLD_X = 759", open_code)
        self.assertIn("TARGET_MONSTER_ID = 813", open_code)
        self.assertIn("TARGET_LEVEL = 13", open_code)
        self.assertIn("TARGET_STAMINA_COST = 10", open_code)
        self.assertIn("selected intelligence monster id changed", open_code)
        self.assertIn("transaction_slg", open_code)
        self.assertIn("stamtina_expend", open_code)
        self.assertIn("OnBtnAverageClick", commit_code)
        self.assertIn("OnBtnGoOnClick", commit_code)
        self.assertNotIn("view.GoOnMarchEx", commit_code)
        self.assertNotIn("CheckSpecialWar", open_code)
        self.assertIn("GetSelfMarchMap", commit_code)
        self.assertIn("capture_self_march_ids(kingdom)", commit_code)
        verify_code = build_verify_march_lua((ROLE,), target)
        self.assertIn(
            'type(data) == "table" and data.transaction_slg or nil',
            verify_code,
        )
        self.assertIn(
            'target_monster = transaction.monster_id',
            verify_code,
        )
        self.assertIn(
            'local end_x, end_y = march_method(march, "GetEndPos")',
            verify_code,
        )
        self.assertIn(
            '_G.__MUMU_AUTOTASK_SELF_MARCH_IDS[id] == true',
            verify_code,
        )
        self.assertNotIn('march_method(march, "GetMarchMapType")', verify_code)
        self.assertNotIn('march_method(march, "GetTargetType")', verify_code)
        self.assertNotIn('march_method(march, "GetServerId")', verify_code)
        self.assertIn("event_id ~= nil and event_id ~= runtime_id", verify_code)
        self.assertNotIn('march_method(march, "GetLevel")', verify_code)
        self.assertIn('proof = march_event_id ~= nil and "MARCH_EVENT" or "MARCH_FIELDS"', verify_code)
        self.assertIn('"PROOF\\t" .. proof', build_verify_march_lua((ROLE,), target))

    def test_all_guarded_stage_scripts_fit_native_bridge_source_buffer(self) -> None:
        target = IntelItem(
            71, 1701, 1, 759, 774, 1900000000, "purple", 4, 813, 13, 10
        )
        scripts = (
            build_inspect_intel_lua((ROLE,)),
            build_intel_status_lua((ROLE,), (71, 72)),
            build_claim_intel_lua((ROLE,), (71, 72)),
            build_open_march_lua((ROLE,), target),
            build_march_ready_lua((ROLE,), target),
            build_commit_march_lua((ROLE,), target),
            build_verify_march_lua((ROLE,), target),
            build_close_expedition_lua((ROLE,)),
        )
        for code in scripts:
            with self.subTest(size=len(code.encode("utf-8"))):
                self.assertLess(len(code.encode("utf-8")), 16384)
                self.assertTrue(code.endswith("\n"))
                self.assertNotIn("\n\n", code)

    def test_select_target_is_quality_exact_and_earliest_expiry(self) -> None:
        later = IntelItem(
            72, 1702, 1, 760, 775, 1900000100, "purple", 4, 814, 14, 10
        )
        earlier = IntelItem(
            71, 1701, 1, 759, 774, 1900000000, "purple", 4, 813, 13, 10
        )
        snapshot = IntelSnapshot(ROLE, 4549, (earlier, later))
        self.assertEqual(select_march_target(snapshot, "purple"), earlier)
        self.assertEqual(select_march_target(snapshot, "purple", 72), later)
        with self.assertRaisesRegex(BusinessError, "is purple, not blue"):
            select_march_target(snapshot, "blue", 72)
        with self.assertRaisesRegex(BusinessError, "no longer available"):
            select_march_target(snapshot, "purple", 999)
        with self.assertRaisesRegex(BusinessError, "no available blue"):
            select_march_target(snapshot, "blue")

    def test_parse_exact_target_statuses_and_rejects_tampering(self) -> None:
        output = intel_status_output(
            "TARGET\t71\tPENDING\t1",
            "TARGET\t72\tPENDING\t3",
            "TARGET\t73\tCOMPLETED\t2",
            "TARGET\t74\tMISSING\tmissing",
        )
        snapshot = parse_intel_status_output(output, (ROLE,), (71, 72, 73, 74))
        self.assertEqual(
            [target.state for target in snapshot.targets],
            [INTEL_PENDING, INTEL_PENDING, INTEL_COMPLETED, INTEL_MISSING],
        )
        self.assertIsNone(snapshot.targets[-1].quest_status)
        diagnostic_only = output.replace("PENDING\t1", "PENDING\t2").replace(
            "COMPLETED\t2", "COMPLETED\t9"
        )
        diagnostic_snapshot = parse_intel_status_output(
            diagnostic_only,
            (ROLE,),
            (71, 72, 73, 74),
        )
        self.assertEqual(diagnostic_snapshot.targets[0].quest_status, 2)
        self.assertEqual(diagnostic_snapshot.targets[2].quest_status, 9)
        cases = (
            output.replace("TARGET\t72", "TARGET\t99", 1),
            output.replace("MISSING\tmissing", "MISSING\t2", 1),
            output.replace("KINGDOM\t4549", "KINGDOM\t4583", 1),
        )
        for invalid in cases:
            with self.subTest(invalid=invalid):
                with self.assertRaises(BusinessError):
                    parse_intel_status_output(
                        invalid,
                        (ROLE,),
                        (71, 72, 73, 74),
                    )

    def test_parse_claim_requires_exact_ids_and_consistent_outcome(self) -> None:
        output = "\n".join(
            (
                "MUMU_AUTOTASK\t1\tCLAIM_INTEL",
                f"ROLE\t{ROLE_HEX}",
                "KINGDOM\t4549",
                "TARGETS\t2\t71\t72",
                "SENT\t1",
                "IDEMPOTENT\t0",
                "END\t1",
            )
        )
        receipt = parse_claim_intel_output(output, (ROLE,), (71, 72))
        self.assertTrue(receipt.request_dispatched)
        self.assertFalse(receipt.idempotent)
        idempotent = parse_claim_intel_output(
            output.replace("SENT\t1", "SENT\t0").replace(
                "IDEMPOTENT\t0", "IDEMPOTENT\t1"
            ),
            (ROLE,),
            (71, 72),
        )
        self.assertTrue(idempotent.idempotent)
        with self.assertRaisesRegex(BusinessError, "targets do not match"):
            parse_claim_intel_output(output, (ROLE,), (72, 71))
        with self.assertRaisesRegex(BusinessError, "inconsistent"):
            parse_claim_intel_output(
                output.replace("IDEMPOTENT\t0", "IDEMPOTENT\t1"),
                (ROLE,),
                (71, 72),
            )

    def test_stage_parsers_require_target_role_and_kingdom_echo(self) -> None:
        target = IntelItem(
            71, 1701, 1, 759, 774, 1900000000, "purple", 4, 813, 13, 10
        )

        def stage(kind: str, state: str) -> str:
            lines = [
                f"MUMU_AUTOTASK\t1\t{kind}",
                f"ROLE\t{ROLE_HEX}",
                "KINGDOM\t4549",
                "TARGET\t71",
                state,
            ]
            if kind == "VERIFY":
                lines.append("MARCH\t1\tEVENT\t71")
                lines.append("PROOF\tMARCH_EVENT")
            lines.append("END\t1")
            return "\n".join(lines)

        parse_open_output(stage("OPEN", "OPENED\t1"), (ROLE,), target)
        self.assertTrue(parse_ready_output(stage("READY", "READY\t1"), (ROLE,), target))
        self.assertEqual(
            parse_verify_output(
                stage("VERIFY", "ACCEPTED\t1\tSTATUS\t2"),
                (ROLE,),
                target,
            ),
            (True, "2"),
        )
        commit = stage("COMMIT", "AVERAGE\t1").replace(
            "AVERAGE\t1\nEND", "AVERAGE\t1\nGO\t1\nEND"
        )
        parse_commit_output(commit, (ROLE,), target)
        with self.assertRaisesRegex(BusinessError, "kingdom"):
            parse_open_output(
                stage("OPEN", "OPENED\t1").replace("4549", "4583"),
                (ROLE,),
                target,
            )
        with self.assertRaisesRegex(BusinessError, "unexpected quest status"):
            parse_verify_output(
                stage("VERIFY", "ACCEPTED\t1\tSTATUS\t0"),
                (ROLE,),
                target,
            )

        with self.assertRaisesRegex(BusinessError, "self-march proof"):
            parse_verify_output(
                stage("VERIFY", "ACCEPTED\t1\tSTATUS\t2")
                .replace("MARCH\t1\tEVENT\t71", "MARCH\t0\tEVENT\t0")
                .replace("PROOF\tMARCH_EVENT", "PROOF\tNONE"),
                (ROLE,),
                target,
            )

        fields_proof = "\n".join(
            (
                "MUMU_AUTOTASK\t1\tVERIFY",
                f"ROLE\t{ROLE_HEX}",
                "KINGDOM\t4549",
                "TARGET\t71",
                "ACCEPTED\t1\tSTATUS\t1",
                "MARCH\t1\tEVENT\tmissing",
                "PROOF\tMARCH_FIELDS",
                "END\t1",
            )
        )
        self.assertEqual(
            parse_verify_output(fields_proof, (ROLE,), target),
            (True, "1"),
        )
        with self.assertRaisesRegex(BusinessError, "proof type is inconsistent"):
            parse_verify_output(
                fields_proof.replace("MARCH_FIELDS", "MARCH_EVENT"),
                (ROLE,),
                target,
            )

        status_proof = "\n".join(
            (
                "MUMU_AUTOTASK\t1\tVERIFY",
                f"ROLE\t{ROLE_HEX}",
                "KINGDOM\t4549",
                "TARGET\t71",
                "ACCEPTED\t1\tSTATUS\t2",
                "MARCH\t0\tEVENT\t0",
                "PROOF\tQUEST_STATUS",
                "END\t1",
            )
        )
        self.assertEqual(
            parse_verify_output(status_proof, (ROLE,), target),
            (True, "2"),
        )
        with self.assertRaisesRegex(BusinessError, "self-march proof"):
            parse_verify_output(
                status_proof.replace("PROOF\tQUEST_STATUS", "PROOF\tNONE"),
                (ROLE,),
                target,
            )

    def test_parse_intel_output_accepts_canonical_sorted_items(self) -> None:
        snapshot = parse_intel_output(
            intel_output(GREEN_ITEM, PURPLE_ITEM),
            (ROLE,),
        )
        self.assertEqual(snapshot.role, ROLE)
        self.assertEqual(snapshot.kingdom, 4549)
        self.assertEqual([item.quality for item in snapshot.items], ["green", "purple"])
        self.assertEqual(snapshot.items[1].world_x, 759)

    def test_parse_intel_output_accepts_an_empty_snapshot(self) -> None:
        snapshot = parse_intel_output(intel_output(), (ROLE,))
        self.assertEqual(snapshot.items, ())

    def test_parse_intel_output_rejects_identity_and_count_tampering(self) -> None:
        cases = (
            intel_output(PURPLE_ITEM, role_hex="626164"),
            intel_output(PURPLE_ITEM, kingdom="4550"),
            intel_output(PURPLE_ITEM).replace("END\t1", "END\t0"),
        )
        for output in cases:
            with self.subTest(output=output):
                with self.assertRaises(BusinessError):
                    parse_intel_output(output, (ROLE,))

    def test_parse_intel_output_rejects_duplicates_and_noncanonical_order(self) -> None:
        with self.assertRaisesRegex(BusinessError, "duplicate runtime ids"):
            parse_intel_output(intel_output(PURPLE_ITEM, PURPLE_ITEM), (ROLE,))
        with self.assertRaisesRegex(BusinessError, "canonical order"):
            parse_intel_output(intel_output(PURPLE_ITEM, GREEN_ITEM), (ROLE,))

    def test_parse_intel_output_rejects_quality_id_disagreement(self) -> None:
        invalid = PURPLE_ITEM.replace("\tpurple\t4\t", "\tpurple\t3\t")
        with self.assertRaisesRegex(BusinessError, "quality name/id disagree"):
            parse_intel_output(intel_output(invalid), (ROLE,))

    def test_parse_intel_output_rejects_noncanonical_integer(self) -> None:
        invalid = PURPLE_ITEM.replace("ITEM\t71", "ITEM\t071")
        with self.assertRaisesRegex(BusinessError, "canonical"):
            parse_intel_output(intel_output(invalid), (ROLE,))

    def test_parse_intel_output_requires_positive_stamina_cost(self) -> None:
        invalid = PURPLE_ITEM.rsplit("\t", 1)[0] + "\t0"
        with self.assertRaisesRegex(BusinessError, "stamina cost must be positive"):
            parse_intel_output(intel_output(invalid), (ROLE,))

    def test_parse_march_output_requires_exact_request_echo(self) -> None:
        target = PURPLE_ITEM.replace("ITEM\t", "TARGET\t", 1)
        output = "\n".join(
            (
                "MUMU_AUTOTASK\t1\tMARCH",
                f"ROLE\t{ROLE_HEX}",
                "KINGDOM\t4549",
                "QUALITY\tpurple\t4",
                target,
                "AVERAGE\t1",
                "SENT\t1",
                "END\t1",
            )
        )
        receipt = parse_march_output(output, (ROLE,), "purple")
        self.assertTrue(receipt.request_dispatched)
        self.assertEqual(receipt.target.runtime_id, 71)
        with self.assertRaisesRegex(BusinessError, "quality does not match"):
            parse_march_output(output, (ROLE,), "blue")

    def test_protocol_rejects_trailing_newline(self) -> None:
        with self.assertRaisesRegex(BusinessError, "line endings"):
            parse_intel_output(intel_output() + "\n", (ROLE,))


if __name__ == "__main__":
    unittest.main()
