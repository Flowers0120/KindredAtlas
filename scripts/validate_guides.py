"""Validate the public manual dataset without reading or controlling the game."""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

from build_manual_guides import DENIED, ORDINARY_YURI, safe_point, ordered_clicks, make_gauge_routes

ROOT = Path(__file__).resolve().parent.parent


def combo_action(character, current_phase, step):
    """Resolve explicit stage references without borrowing a same-ID local card."""
    phase_id = str(step.get("phaseId", current_phase["id"]))
    phase = next((p for p in character["phases"] if p["id"] == phase_id), None)
    return next((a for a in phase["actions"] if a["id"] == step["actionId"]), None) if phase else None


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
    combination_types = {}
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
                kind = combo.get("kind")
                if kind is not None:
                    combination_types[kind] = combination_types.get(kind, 0) + 1
                    check(kind in ("hidden-route", "ordered-clicks", "gauge-route", "stage-route", "wiki-route"), "unknown combination dependency")
                    check(bool(combo.get("evidence")), "new combination lacks source scope")
                if kind == "gauge-route":
                    check(len({(str(s.get('phaseId', phase['id'])), s['actionId']) for s in combo['steps']}) >= 2,
                          "same interaction repetitions presented as a temperature dependency")
                    check(bool(combo.get("conditions")), "temperature route lacks starting conditions")
                for step in combo["steps"]:
                    check(combo_action(character, phase, step) is not None, "combo points to an omitted or unknown stage action")
                    check(step["gesture"] in ("短按", "连续短按", "长按", "拖拽"), "wait/tool/automatic motion presented as combo interaction")
                    check(bool(step["instruction"] and step.get("location")), "combo lacks manual instructions or location")
                    if "repeatUntil" in step:
                        check(isinstance(step["repeatUntil"], str) and bool(step["repeatUntil"]), "repeat control lacks a visible target")
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
    if "combinationTypes" in data["summary"]:
        check(data["summary"]["combinationTypes"] == combination_types, "combination type counts differ")
    manual_source = ROOT / "data/manual-combos.json"
    if manual_source.exists():
        manual = json.loads(manual_source.read_text(encoding="utf-8"))
        published = {combo["id"]: combo for character in characters for phase in character["phases"] for combo in phase["combos"]}
        for route in manual["routes"]:
            check(route["id"] in published and published[route["id"]]["steps"] == route["steps"], "reviewed Wiki route was lost or rewritten during extraction")
        expected_additions = {(a["characterId"], a["phaseId"], a["id"]) for a in manual.get("actions", [])}
        published_additions = {(c["id"], p["id"], a["id"]) for c in characters for p in c["phases"] for a in p["actions"] if a.get("source") == "wiki-text"}
        check(expected_additions == published_additions, "supplemental Wiki location cards differ")
    skin_names = {"justia": ("仲夏之梦", "泳池派对"), "teresse-beach": ("奶牛比基尼", "海滨天使"),
                  "zenith": ("神秘面纱兔女郎", "罗宾汉"), "levia": ("享乐主义者", "温泉管理员"),
                  "scheherazade": ("从容的王牌", "泳池派对")}
    for selector, (skin, base) in skin_names.items():
        item = next(c for c in characters if c["id"] == selector)
        check(item["costume"] == skin and base in item.get("aliases", []), "historical base name replaced a native prestige skin")
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
    first = dict(id="1", actions=[dict(id="same", name="first")])
    second = dict(id="2", actions=[dict(id="same", name="second")])
    sample = dict(phases=[first, second])
    check(combo_action(sample, first, dict(actionId="same", phaseId="2"))["name"] == "second", "cross-stage link resolved to local duplicate")
    check(combo_action(sample, first, dict(actionId="same"))["name"] == "first", "legacy current-stage step changed")
    check(combo_action(sample, first, dict(actionId="same", phaseId="missing")) is None, "unknown stage borrowed another action")
    # Replay a concrete progress dependency: two effective head taps unlock the hand.
    pump_key, goal_key = (1, 0, 1), (1, 0, 2)
    pump = dict(PointGroupId=1, ToolId=0, PointId=1, DisplayName="头部", SupportsClick=True,
                GaugeIsOn=True, GaugeScores=[10, 0], GaugeInteractableMin=0, GaugeInteractableMax=100,
                ContinuousClickResetSeconds=2)
    goal = dict(PointGroupId=1, ToolId=0, PointId=2, DisplayName="手部", SupportsClick=True,
                GaugeIsOn=True, GaugeInteractableMin=20, GaugeInteractableMax=30)
    public_cards = {key: dict(id=str(key[-1]), location=point["DisplayName"], gesture="短按",
                             conditions=[], instructions=["短按一次。"])
                    for key, point in ((pump_key, pump), (goal_key, goal))}
    gauge = dict(IsOn=True, StartScore=0, MinMaxScore=dict(x=0, y=100), AutoDecreaseScorePerSecond=0)

    def routes(pump_value=pump, goal_value=goal, gauge_value=gauge, automatic=()):
        return make_gauge_routes(1, {pump_key: pump_value, goal_key: goal_value}, public_cards,
                                 [dict(tool=0, gauge=gauge_value)], set(automatic), "合成回归")

    route = routes()[0]
    check([s["actionId"] for s in route["steps"]] == ["1", "1", "2"], "progress route skipped an effective input")
    check("2" in route["steps"][1]["instruction"] and "复位" in route["steps"][1]["instruction"], "repeated progress input omitted native reset wait")
    check(not routes({**pump, "ChangesStageOnEnd": True}), "stage-changing preparation used as a stable progress control")
    check(not routes({**pump, "NativeClickMotionsRandom": True}), "random preparation promoted to deterministic progress route")
    check(not routes(gauge_value={**gauge, "MotionNameByScoreList": [dict(Score=20, IsCanPlayWhenIncreaseScore=True)]}), "progress route crossed automatic ending")
    check(not routes(goal_value={**goal, "NativeMotionNames": ["automatic"]}, automatic=["automatic"]), "automatic ending acquired a manual final step")
    dynamic = routes(gauge_value={**gauge, "AutoDecreaseScorePerSecond": -1})[0]
    check(len(dynamic["steps"]) == 2 and isinstance(dynamic["steps"][0].get("repeatUntil"), str), "decaying progress promised a fixed tap count")
    check("次数不固定" in dynamic["note"], "decaying progress omitted live observation scope")
    return dict(status="passed", checks=checks, summary=data["summary"], sha256=hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == "__main__":
    print(json.dumps(validate(), ensure_ascii=False, indent=2))
