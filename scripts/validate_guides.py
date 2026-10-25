"""Validate the public manual dataset without reading or controlling the game."""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

from build_manual_guides import DENIED, ORDINARY_YURI, safe_point, ordered_clicks

ROOT = Path(__file__).resolve().parent.parent


def validate(path=ROOT / "data/characters.json"):
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    checks = 0

    def check(condition, message):
        nonlocal checks
        checks += 1
        if not condition:
            raise AssertionError(message)

    check(data.get("schemaVersion") == 1, "unsupported public schema")
    characters = data["characters"]
    check(len(characters) == 22, "this edition must cover all22 resource identities")
    check(len({c["id"] for c in characters}) == len(characters), "duplicate character selector ID")
    check(len({c["resource"] for c in characters}) == len(characters), "duplicate resource identity")
    check(len({c["name"] for c in characters}) == 21, "two Teresse costumes must not be counted as two people")
    check(not re.search(r"[A-Za-z]:\\|/Users/|/home/|Bearer\s|gh[pousr]_[A-Za-z0-9]{12}|github_pat_|base64|AvatarPng|ScreenX|ScreenY|ProcessId|ProcessStartTicks|BridgeInstance|39/39|1092/1092", text), "private/runtime data in public payload")
    counts = dict(actions=0, combinations=0, phases=0)
    for character in characters:
        check(bool(character["name"] and character["costume"]), "missing player identity")
        check(character["availability"] == "需在游戏中拥有并进入对应服装。", "account-specific ownership exposed")
        check(character["verification"]["level"] in ("historical-live", "current-in-progress", "configuration-only", "current-live"), "verification scope missing")
        phases = character["phases"]
        phase_ids = {p["id"] for p in phases}
        check(len(phase_ids) == len(phases), "duplicate stage selector")
        check(character.get("initialPhaseId") is None or character["initialPhaseId"] in phase_ids, "invalid initialization target")
        actions_count = combos_count = unknown_drag_count = merged_count = 0
        for phase in phases:
            actions = {a["id"]: a for a in phase["actions"]}
            check(len(actions) == len(phase["actions"]), "duplicate action anchor")
            for action in actions.values():
                check(bool(action["location"] and action["instructions"]), "manual action lacks location or operation")
                check(not re.search(r"互动点|对象\s*\d|[0-9]+\s*·", action["name"]), "developer numbering leaked into player label")
                check(not DENIED.search(action["name"]), "sensitive body target included")
                check(action["gesture"] in ("短按", "连续短按", "长按", "拖拽", "自动触发"), "unknown gesture")
                if action["holdSeconds"] is not None:
                    check(math.isfinite(action["holdSeconds"]) and 0 < action["holdSeconds"] <= 30, "invalid hold duration")
                if action["drag"]:
                    check(bool(action["drag"]["direction"] and action["drag"]["destination"]), "drag lacks direction/target scope")
                    if not action["drag"]["verified"]:
                        unknown_drag_count += 1
                        check("待核对" in action["drag"]["direction"] or "待" in action["drag"]["destination"], "unverified drag presented as measured")
                if action.get("variantCount", 1) > 1:
                    merged_count += 1
                    check("差异尚待核对" in action["note"], "merged native labels claim known separate positions")
            for combo in phase["combos"]:
                check(len(combo["steps"]) >= 2, "single gesture presented as combo")
                for step in combo["steps"]:
                    check(step["actionId"] in actions, "combo points to an omitted or foreign action")
                    check(step["gesture"] in ("短按", "连续短按", "长按", "拖拽"), "wait/tool/automatic motion presented as combo interaction")
                    check(bool(step["instruction"]), "combo lacks manual instructions")
            for transition in phase["transitions"]:
                check(transition["to"] in phase_ids and transition["to"] != phase["id"], "unknown or self stage transition")
                check(transition["direction"] in ("one-way", "reversible"), "transition direction missing")
                if "actionId" in transition:
                    check(transition["actionId"] in actions, "stage edge references omitted action")
            actions_count += len(actions)
            combos_count += len(phase["combos"])
        check(character["coverage"]["actions"] == actions_count, "action count differs")
        check(character["coverage"]["combinations"] == combos_count, "combo count differs")
        check(character["coverage"]["unlocatedDrags"] == unknown_drag_count, "unknown drag count differs")
        check(character["coverage"]["unseparatedLocations"] == merged_count, "merged location count differs")
        if character["id"] == "yuri":
            for phase in phases:
                check(not phase["gaugeRules"] and not phase["transitions"] and not phase["combos"], "ordinary-only entry acquired an advanced route")
                for action in phase["actions"]:
                    check(action["gesture"] == "短按" and ORDINARY_YURI.search(action["name"]), "ordinary-only body allowlist was bypassed")
        counts["actions"] += actions_count
        counts["combinations"] += combos_count
        counts["phases"] += len(phases)
    check(all(data["summary"][key] == value for key, value in counts.items()), "summary does not match selector data")
    aquila = next(c for c in characters if c["id"] == "aquila")
    ending = next(p for p in aquila["phases"] if p["id"] == "2")
    check(any(a["gesture"] == "自动触发" and "无需再次" in a["location"] for a in ending["actions"]), "Aquila automatic ending presented as an extra click")
    check(any("重置为 50" in rule["description"] for rule in ending["gaugeRules"]), "Aquila native reset omitted")
    check(any(rule["title"] == "降低进度" and "-5" in rule["description"] for rule in ending["gaugeRules"]), "Aquila manual cooling operation omitted")
    palette = next(c for c in characters if c["id"] == "palette")
    check(any("膝盖 → 脚底" == combo["name"] for phase in palette["phases"] for combo in phase["combos"]), "Palette prerequisite/foot route missing")
    # Regression: a device name containing 手 must not pass a head/hand allowlist.
    check(not safe_point(dict(DisplayName="腿部中央（手机）1", PointId=2), yuri=True), "手机 matched ordinary hand allowlist")
    check(safe_point(dict(DisplayName="额头（扇子）1", PointId=3), yuri=True), "ordinary forehead entry was dropped")
    fixture = dict(SupportsClick=True, SupportsHold=False, SupportsDrag=False, ChangesStageOnEnd=False,
                   SupportsContinuousClick=False, NativeClickMotionsReadable=True, NativeClickMotionsRandom=False,
                   NativeClickMotionNames=["reaction-a", "reaction-b"])
    check(ordered_clicks(fixture), "proven distinct ordered click actions omitted")
    check(not ordered_clicks({**fixture, "NativeClickMotionsRandom": True}), "random variants promoted to fixed combo")
    check(not ordered_clicks({**fixture, "NativeClickMotionNames": ["same", "same"]}), "repeated one-motion gesture promoted to fixed combo")
    check(not ordered_clicks({**fixture, "NativeClickMotionsReadable": False, "ClickMaxCount": 2}), "serialized default maximum promoted to fixed combo")
    return dict(status="passed", checks=checks, summary=data["summary"], sha256=hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == "__main__":
    print(json.dumps(validate(), ensure_ascii=False, indent=2))
