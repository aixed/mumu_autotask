from __future__ import annotations

import unittest

from mumu_autotask.business import (
    BattleIntelItem,
    BusinessError,
    INTEL_COMPLETED,
    INTEL_MISSING,
    INTEL_PENDING,
    IntelItem,
    IntelSnapshot,
    build_claim_intel_lua,
    build_close_expedition_lua,
    build_commit_prepared_march_lua,
    build_commit_march_lua,
    build_start_battle_intel_lua,
    build_inspect_formation_lua,
    build_inspect_intel_lua,
    build_intel_status_lua,
    build_march_ready_lua,
    build_open_march_lua,
    build_prepare_direct_march_lua,
    build_scene_status_lua,
    build_verify_march_lua,
    build_world_monster_commit_lua,
    build_world_monster_search_lua,
    build_world_monster_search_result_lua,
    build_world_monster_status_lua,
    build_world_monster_verify_lua,
    normalize_quality,
    normalize_target_ids,
    normalize_world_monster_level,
    normalize_world_monster_count,
    parse_claim_intel_output,
    parse_battle_commit_output,
    parse_commit_output,
    parse_intel_output,
    parse_intel_status_output,
    parse_march_output,
    parse_open_output,
    parse_prepare_output,
    parse_ready_output,
    build_start_rescue_intel_lua,
    parse_rescue_commit_output,
    parse_scene_status_output,
    parse_verify_output,
    parse_world_monster_commit_output,
    parse_world_monster_search_output,
    parse_world_monster_status_output,
    parse_world_monster_verify_output,
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


def scene_output(
    *,
    scene_type: str = "3",
    class_name: str = "WorldScene",
    map_type: str = "1",
    world: str = "1",
    city: str = "0",
    loading: str = "false",
    transition: str = "false",
) -> str:
    return "\n".join(
        (
            "MUMU_AUTOTASK\t1\tSCENE",
            f"ROLE\t{ROLE_HEX}",
            "KINGDOM\t4549",
            f"SCENE\t{scene_type}\tCLASS\t{class_name}",
            f"MAP\t{map_type}",
            f"WORLD\t{world}\tCITY\t{city}",
            f"BUSY\tLOADING\t{loading}\tTRANSITION\t{transition}",
            "END\t1",
        )
    )


PURPLE_ITEM = (
    "ITEM\t71\t1701\t0\t759\t774\t1900000000"
    "\tpurple\t4\t813\t13\t10\t48200"
)
GREEN_ITEM = (
    "ITEM\t70\t1700\t0\t700\t701\t1800000000"
    "\tgreen\t2\t808\t8\t10\t10000"
)


def battle_target(category: str = "rescue") -> BattleIntelItem:
    quest_type = 2 if category == "rescue" else 3
    return BattleIntelItem(
        runtime_id=438,
        quest_id=2438,
        status=1,
        world_x=789,
        world_y=728,
        expires_at=1900000000,
        category=category,
        quest_type=quest_type,
        quality="blue",
        quality_id=3,
        condition=1,
        level=1,
        stamina_cost=0,
        power_level=0,
    )


def battle_commit_output(target: BattleIntelItem, *, end_request: bool) -> str:
    return "\n".join(
        (
            "MUMU_AUTOTASK\t1\tBATTLE_COMMIT",
            f"ROLE\t{ROLE_HEX}",
            "KINGDOM\t4549",
            f"TARGET\t{target.runtime_id}",
            "START\t1",
            f"END_REQUEST\t{int(end_request)}",
            "HERO\t1\t50006",
            "HERO\t2\t50012",
            "HERO\t3\t50004",
            "END\t1",
        )
    )


def rescue_commit_output(target: BattleIntelItem) -> str:
    return "\n".join(
        (
            "MUMU_AUTOTASK\t1\tRESCUE_COMMIT",
            f"ROLE\t{ROLE_HEX}",
            "KINGDOM\t4549",
            f"TARGET\t{target.runtime_id}",
            "WORLD_MARCH\t1",
            "TYPE\t301",
            "MARCH_MAP_TYPE\t1",
            "END\t1",
        )
    )


def stamina_stage_output(
    kind: str,
    target_id: int,
    *,
    action: str,
    succeeded: bool = True,
    current: int = 49,
    required: int = 8,
    base: int = 10,
) -> str:
    return "\n".join(
        (
            f"MUMU_AUTOTASK\t1\t{kind}",
            f"ROLE\t{ROLE_HEX}",
            "KINGDOM\t4549",
            f"TARGET\t{target_id}",
            "AVERAGE\t1",
            f"STAMINA\t{current}\t{required}\t{base}",
            f"{action}\t{int(succeeded)}",
            f"REASON\t{'NONE' if succeeded else 'INSUFFICIENT_STAMINA'}",
            "END\t1",
        )
    )


class BusinessTests(unittest.TestCase):
    def test_quality_alias_and_invalid_values(self) -> None:
        self.assertEqual(normalize_quality(" ORANGE "), "yellow")
        self.assertEqual(normalize_quality("Purple"), "purple")
        self.assertEqual(normalize_quality("蓝色"), "blue")
        self.assertEqual(normalize_quality("黄色"), "yellow")
        with self.assertRaisesRegex(BusinessError, "quality must be one of"):
            normalize_quality("red")

    def test_role_whitelist_allows_empty_and_rejects_duplicate_or_control_text(self) -> None:
        self.assertEqual(validate_role_whitelist(()), ())
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
        self.assertNotIn("EXPECTED_KINGDOM", code)
        self.assertIn("GetPlayerKid", code)
        self.assertIn("GetPlayerServerId", code)
        self.assertIn("GetQuestType", code)
        self.assertIn("IsShowInWorld", code)
        self.assertIn("GetValidTime", code)
        self.assertIn("stamtina_expend", code)
        self.assertIn("world_map_monster", code)
        self.assertIn("recommendPower", code)
        self.assertIn("GetLeftCount", code)
        self.assertIn("COMMANDER_STAMINA", code)
        self.assertIn('"STAMINA\\t" .. tostring(current_stamina)', code)
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
        self.assertIn("status == 2 or completed == true", status_code)
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
        formation_code = build_inspect_formation_lua((ROLE,), target)
        prepare_direct_code = build_prepare_direct_march_lua((ROLE,), target)
        commit_direct_code = build_commit_prepared_march_lua((ROLE,), target)
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
        self.assertIn("GetRecommendedHeroList", formation_code)
        self.assertIn("GetAverageSoldierList", formation_code)
        self.assertIn("DealWithExpeditionInfo", formation_code)
        self.assertIn("MUMU_AUTOTASK\\t1\\tFORMATION", formation_code)
        self.assertNotIn("RequestMarchStartOff", formation_code)
        self.assertNotIn("OpenView", formation_code)
        self.assertNotIn("SendMsg", formation_code)
        self.assertIn("GetRecommendedHeroList", prepare_direct_code)
        self.assertIn("GetAverageSoldierList", prepare_direct_code)
        self.assertIn("GetCostStaminaEduce(hero_list)", prepare_direct_code)
        self.assertIn("math.ceil(TARGET_STAMINA_COST * (1 - stamina_reduction))", prepare_direct_code)
        self.assertIn("_G.__MUMU_AUTOTASK_DIRECT_MARCH = {", prepare_direct_code)
        self.assertNotIn("RequestMarchStartOff", prepare_direct_code)
        self.assertIn("prepared march payload is unavailable", commit_direct_code)
        self.assertIn("GetLeftCount(ResDefine.COMMANDER_STAMINA)", commit_direct_code)
        self.assertIn("RequestMarchStartOff", commit_direct_code)
        self.assertIn("_G.__MUMU_AUTOTASK_DIRECT_MARCH = nil", commit_direct_code)
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

    def test_rescue_start_script_uses_world_march_payload(self) -> None:
        rescue_code = build_start_rescue_intel_lua((ROLE,), battle_target("rescue"))
        hero_code = build_start_battle_intel_lua((ROLE,), battle_target("hero"))

        self.assertNotIn("RequestStartBattle", rescue_code)
        self.assertNotIn("RequestEndBattle", rescue_code)
        self.assertIn('"req_world_march"', rescue_code)
        self.assertIn("type = 301", rescue_code)
        self.assertIn("endpoint = {", rescue_code)
        self.assertIn("x = TARGET_WORLD_X", rescue_code)
        self.assertIn("y = TARGET_WORLD_Y", rescue_code)
        self.assertIn("event_id = TARGET_RUNTIME_ID", rescue_code)
        self.assertIn("MarchMapType = 1", rescue_code)
        self.assertIn("RESCUE_COMMIT", rescue_code)
        self.assertIn("RequestStartBattle", hero_code)
        self.assertIn("RequestEndBattle", hero_code)

    def test_battle_commit_parser_rejects_rescue_category(self) -> None:
        rescue = battle_target("rescue")
        hero = battle_target("hero")

        with self.assertRaisesRegex(BusinessError, "target category"):
            parse_battle_commit_output(
                battle_commit_output(rescue, end_request=False),
                (ROLE,),
                rescue,
            )
        parse_battle_commit_output(
            battle_commit_output(hero, end_request=True),
            (ROLE,),
            hero,
        )
        with self.assertRaisesRegex(BusinessError, "target category"):
            parse_battle_commit_output(
                battle_commit_output(rescue, end_request=True),
                (ROLE,),
                rescue,
            )
        with self.assertRaisesRegex(BusinessError, "does not match hero"):
            parse_battle_commit_output(
                battle_commit_output(hero, end_request=False),
                (ROLE,),
                hero,
            )

    def test_rescue_commit_parser_accepts_hook_captured_world_march_shape(self) -> None:
        rescue = battle_target("rescue")

        parse_rescue_commit_output(rescue_commit_output(rescue), (ROLE,), rescue)
        with self.assertRaisesRegex(BusinessError, "target category"):
            parse_rescue_commit_output(
                rescue_commit_output(battle_target("hero")),
                (ROLE,),
                battle_target("hero"),
            )
        with self.assertRaisesRegex(BusinessError, "invalid march type"):
            parse_rescue_commit_output(
                rescue_commit_output(rescue).replace("TYPE\t301", "TYPE\t300"),
                (ROLE,),
                rescue,
            )

    def test_scene_status_script_and_parser_report_world_readiness_inputs(self) -> None:
        code = build_scene_status_lua((ROLE,))
        self.assertIn('GModule.SceneModule', code)
        self.assertIn('IsLoading', code)
        self.assertIn('IsInTransition', code)

        status = parse_scene_status_output(scene_output(), (ROLE,))

        self.assertEqual(status.role, ROLE)
        self.assertEqual(status.kingdom, 4549)
        self.assertEqual(status.scene_type, 3)
        self.assertEqual(status.map_type, 1)
        self.assertEqual(status.class_name, "WorldScene")
        self.assertTrue(status.is_world)
        self.assertFalse(status.is_city)
        self.assertFalse(status.loading)
        self.assertFalse(status.transition)

    def test_scene_status_parser_accepts_missing_busy_values(self) -> None:
        status = parse_scene_status_output(
            scene_output(
                scene_type="missing",
                map_type="missing",
                class_name="unknown",
                world="0",
                city="0",
                loading="missing",
                transition="missing",
            ),
            (ROLE,),
        )

        self.assertIsNone(status.scene_type)
        self.assertIsNone(status.map_type)
        self.assertEqual(status.class_name, "unknown")
        self.assertIsNone(status.loading)
        self.assertIsNone(status.transition)

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
            build_prepare_direct_march_lua((ROLE,), target),
            build_commit_prepared_march_lua((ROLE,), target),
            build_verify_march_lua((ROLE,), target),
            build_start_rescue_intel_lua((ROLE,), battle_target("rescue")),
            build_close_expedition_lua((ROLE,)),
            build_scene_status_lua((ROLE,)),
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
        cases = (
            output.replace("TARGET\t72", "TARGET\t99", 1),
            output.replace("MISSING\tmissing", "MISSING\t2", 1),
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
        prepare = stamina_stage_output(
            "PREPARE", 71, action="READY"
        )
        prepare_receipt = parse_prepare_output(prepare, (ROLE,), target)
        self.assertTrue(prepare_receipt.ready_to_commit)
        self.assertEqual(prepare_receipt.required_stamina, 8)
        commit = stamina_stage_output("COMMIT", 71, action="GO")
        commit_receipt = parse_commit_output(commit, (ROLE,), target)
        self.assertTrue(commit_receipt.request_dispatched)
        blocked_prepare = parse_prepare_output(
            stamina_stage_output(
                "PREPARE",
                71,
                action="READY",
                succeeded=False,
                current=7,
                required=8,
            ),
            (ROLE,),
            target,
        )
        self.assertFalse(blocked_prepare.ready_to_commit)
        self.assertEqual(blocked_prepare.blocked_reason, "insufficient_stamina")
        blocked_commit = parse_commit_output(
            stamina_stage_output(
                "COMMIT",
                71,
                action="GO",
                succeeded=False,
                current=7,
                required=8,
            ),
            (ROLE,),
            target,
        )
        self.assertFalse(blocked_commit.request_dispatched)
        self.assertEqual(blocked_commit.current_stamina, 7)
        with self.assertRaisesRegex(BusinessError, "role"):
            parse_open_output(
                stage("OPEN", "OPENED\t1").replace(ROLE_HEX, "626164"),
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
        self.assertEqual(snapshot.items[1].recommended_power, 48200)
        self.assertIsNone(snapshot.current_stamina)

        with_stamina = intel_output(GREEN_ITEM, PURPLE_ITEM).replace(
            "KINGDOM\t4549\n",
            "KINGDOM\t4549\nSTAMINA\t49\n",
            1,
        )
        self.assertEqual(
            parse_intel_output(with_stamina, (ROLE,)).current_stamina,
            49,
        )

    def test_parse_intel_output_accepts_an_empty_snapshot(self) -> None:
        snapshot = parse_intel_output(intel_output(), (ROLE,))
        self.assertEqual(snapshot.items, ())

    def test_parse_intel_output_rejects_identity_and_count_tampering(self) -> None:
        cases = (
            intel_output(PURPLE_ITEM, role_hex="626164"),
            intel_output(PURPLE_ITEM).replace("END\t1", "END\t0"),
        )
        for output in cases:
            with self.subTest(output=output):
                with self.assertRaises(BusinessError):
                    parse_intel_output(output, (ROLE,))
        self.assertEqual(
            parse_intel_output(intel_output(PURPLE_ITEM, kingdom="4550"), (ROLE,)).kingdom,
            4550,
        )

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
        fields = PURPLE_ITEM.split("\t")
        fields[11] = "0"
        invalid = "\t".join(fields)
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

    def test_world_monster_level_and_native_call_chain(self) -> None:
        self.assertEqual(normalize_world_monster_level(16), 16)
        self.assertEqual(normalize_world_monster_count(4), 4)
        for value in (0, 21, True, "16"):
            with self.subTest(value=value), self.assertRaises(BusinessError):
                normalize_world_monster_level(value)  # type: ignore[arg-type]
        for value in (0, 5, True, "4"):
            with self.subTest(count=value), self.assertRaises(BusinessError):
                normalize_world_monster_count(value)  # type: ignore[arg-type]
        search = build_world_monster_search_lua(16)
        search_result = build_world_monster_search_result_lua(16)
        commit = build_world_monster_commit_lua(16)
        verify = build_world_monster_verify_lua(16)
        self.assertIn("local view_id = 207", search)
        self.assertIn("ReqWorldMapSearch", search)
        self.assertIn("GameMsg.AddMessage", search)
        self.assertIn("false", search)
        self.assertNotIn("OnBtnSearchClick", search)
        self.assertNotIn("OpenView", search)
        self.assertIn("resource_id = 0", search)
        self.assertIn("SearchToMapObj", search)
        self.assertIn("ReqWorldMapObjByPos", search)  # legacy-client fallback
        self.assertNotIn("SearchToMapObj", search_result)
        self.assertIn("GetMapDataDic", search_result)
        self.assertNotIn("ReqWorldMapObjByPos", search_result)
        self.assertIn("candidate.GetPos", search_result)
        self.assertIn("GetId", search_result)
        self.assertIn("GetLevel", search_result)
        self.assertNotIn("IsNormalMonster", search_result)
        self.assertNotIn("fallback_id", search_result)
        self.assertIn("march_type.atk_monster", commit)
        self.assertIn("if map_object == nil or (", commit)
        self.assertIn("extra = { monsterid = state.monster_id }", commit)
        self.assertIn("GetRecommendedHeroList", commit)
        self.assertIn("GetAverageSoldierList", commit)
        self.assertIn("GetLeftCount", commit)
        self.assertIn("RequestMarchStartOff", commit)
        self.assertNotIn("transaction_slg", commit)
        self.assertNotIn("event_id", commit)
        self.assertIn("found_id", verify)
        self.assertNotIn("input tap", search + commit + verify)

    def test_world_monster_protocols_block_stamina_and_require_real_march(self) -> None:
        search_output = "\n".join((
            "MUMU_AUTOTASK\t1\tWORLD_MONSTER_SEARCH",
            f"ROLE\t{ROLE_HEX}", "KINGDOM\t4549", "LEVEL\t16",
            "READY\t1", "POINT\t833\t749", "MONSTER\t7100016\t177168",
            "STAMINA\t7", "END\t1",
        ))
        search = parse_world_monster_search_output(search_output, 16)
        blocked_output = "\n".join((
            "MUMU_AUTOTASK\t1\tWORLD_MONSTER_COMMIT",
            f"ROLE\t{ROLE_HEX}", "KINGDOM\t4549", "LEVEL\t16",
            "MONSTER\t7100016", "POINT\t833\t749", "AVERAGE\t1",
            "STAMINA\t7\t8\t10", "QUEUE\t1\t4", "SENT\t0",
            "REASON\tINSUFFICIENT_STAMINA", "END\t1",
        ))
        blocked = parse_world_monster_commit_output(blocked_output, search)
        self.assertFalse(blocked.request_dispatched)
        self.assertEqual(blocked.blocked_reason, "insufficient_stamina")
        self.assertIn("GetSelfMarchCount", build_world_monster_commit_lua(16))
        self.assertIn(
            "GetCurrentMaxMarchCount", build_world_monster_commit_lua(16)
        )
        self.assertIn(
            'return result("0", "NO_IDLE_MARCH_QUEUE")',
            build_world_monster_commit_lua(16),
        )
        commit_code = build_world_monster_commit_lua(16)
        self.assertIn("CheckHasIdleMarch(", commit_code)
        self.assertIn("nil, false)", commit_code)
        verify_missing = "\n".join((
            "MUMU_AUTOTASK\t1\tWORLD_MONSTER_VERIFY",
            f"ROLE\t{ROLE_HEX}", "KINGDOM\t4549", "LEVEL\t16",
            "MONSTER\t7100016", "POINT\t833\t749", "MARCH\tmissing",
            "STAMINA\t7", "END\t1",
        ))
        self.assertIsNone(
            parse_world_monster_verify_output(verify_missing, search).march_id
        )

    def test_world_monster_status_rejects_unknown_ids(self) -> None:
        code = build_world_monster_status_lua((901, 902))
        self.assertIn("ACTIVE", code)
        self.assertIn("RETURNED", code)
        output = "\n".join((
            "MUMU_AUTOTASK\t1\tWORLD_MONSTER_STATUS",
            f"ROLE\t{ROLE_HEX}", "KINGDOM\t4549", "QUEUE\t1\t4", "STAMINA\t32",
            "MARCH\t901\tACTIVE", "MARCH\t902\tRETURNED", "END\t2",
        ))
        snapshot = parse_world_monster_status_output(output, (901, 902))
        self.assertEqual([item.state for item in snapshot.statuses], ["ACTIVE", "RETURNED"])
        with self.assertRaisesRegex(BusinessError, "never observed"):
            parse_world_monster_status_output(
                output.replace("MARCH\t901\tACTIVE", "MARCH\t901\tUNKNOWN"),
                (901, 902),
            )


if __name__ == "__main__":
    unittest.main()
