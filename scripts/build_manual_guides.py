"""Build non-graphic, player-readable guides from reviewed local evidence.

Raw client data, paths, identities and captures never enter the public payload.
Run with --kt-root ../KindredTouch. No game connection or network is used.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import html
import json
import math
import re
from pathlib import Path

DENIED = re.compile(r"胸|乳|臀|屁股|下体|私处|阴|胯|裆|内衣|内裤|胸衣|魔法棒")
CLOTHING_TRANSITION = re.compile(r"上衣|衣带|裙|泳衣|泳装|裤|拉链|外套|衣服")
ORDINARY_YURI = re.compile(r"^(?:额头|头部|头发|面部|脸颊|脸|耳朵|耳部|手部|手腕|手掌|手背|手指)(?:$|[（(])")
EVENT_LABEL = re.compile(r"过场动画|节奏游戏通关|高潮|通关|失败|成功")
SLUGS = ["nebris", "morphea", "loen", "teresse-health", "elise", "wilhelmina", "justia", "sylvia", "teresse-beach", "angelica", "eclipse", "zenith", "tyr", "levia", "bantana", "olivier", "palette", "scheherazade", "glancithe", "dafi", "yuri", "aquila"]


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def clean_name(text):
    text = re.sub(r"\d+$", "", str(text or "")).strip()
    return "" if re.search(r"互动点|对象|未绑定", text) else text


def signature(point):
    return (int(point.get("PointGroupId", 0)), int(point.get("ToolId", 0)), int(point.get("PointId", 0)))


def short_id(text):
    return hashlib.sha256(text.encode()).hexdigest()[:8]


def fnum(value):
    value = float(value)
    return str(int(value)) if value.is_integer() else f"{value:.1f}"


def valid_snapshot(value, resource):
    return isinstance(value, dict) and value.get("Available") and value.get("CatalogComplete") and isinstance(value.get("Points"), list) and value.get("Context", {}).get("ResourceKey") == resource


def identity_tables(base):
    names = {x["id"]: x for x in read(base / "static-identity-names/NameTextTable.json")}
    costumes = {x["id"]: x for x in read(base / "static-identity-tables/CostumeTable.json")}
    chars = read(base / "static-identity-names/CharTable.json")
    prestige = {x["id"]: x for x in read(base / "static-identity-prestige/PrestigeSkinTable.json")}
    result = {}
    for lobby in read(base / "static-identity-tables/LobbySettingItemTable.json"):
        resource = lobby.get("interactionResourceName", "")
        if not resource.startswith("Illust_dating") or not lobby.get("interactionId"):
            continue
        skin = prestige.get(lobby.get("prestigeSkinId"), {})
        costume = costumes.get(skin.get("costumeId", lobby["costumeId"]), {})
        char = next((x for x in chars if x.get("uniqueCharId") == costume.get("useUniqueCharId")), {})
        name = names.get(char.get("charNameTextId"), {}).get("textCn")
        outfit = names.get(skin.get("skinNameTextId", costume.get("costumeNameTextId")), {}).get("textCn")
        if name and outfit:
            result[resource] = dict(name=name, costume=outfit, interaction=lobby["interactionId"])
    point_texts = {x["id"]: x.get("textCn", "") for x in read(base / "static-point-names/SpineInteractionTextTable.json")}
    point_names = {(x["interactionGroupId"], x["groupId"], x["id"]): point_texts.get(x.get("pointNameId"), "") for x in read(base / "static-identity-tables/SpineInteractionPointTable.json")}
    return result, point_names


def static_point(point, interaction, names):
    gauge = point.get("gauge", {})
    bounds = gauge.get("InteractableMinMaxRange", {})
    return dict(PointGroupId=point["stage"], ToolId=point["tool"], PointId=point["pointId"],
                DisplayName=names.get((interaction, point["stage"], point["pointId"]), ""),
                SupportsClick=point.get("nativeActionType") == 0 and not point.get("longPressMode"),
                SupportsHold=point.get("longPressMode") in (1, 2), SupportsDrag=point.get("nativeActionType") in (1, 2),
                NativeActionType=point.get("nativeActionType"), LongPressMode=point.get("longPressMode"),
                HoldThresholdSeconds=point.get("thresholdSeconds", 0), ClickMaxCount=point.get("clickMaxCount", 0),
                SupportsContinuousClick=point.get("continuousClickConfigured", False),
                ContinuousClickResetSeconds=point.get("clickResetSeconds", 0), GaugeReadable=True,
                GaugeIsOn=bool(gauge.get("IsOn")), GaugeInteractableMin=bounds.get("x", 0), GaugeInteractableMax=bounds.get("y", 100),
                GaugeScores=gauge.get("Scores", []), GaugeLongPressSuccessScore=gauge.get("LongPressSuccessScore", 0),
                NativeMotionNames=point.get("animationNames", []), NativeHiddenChildPointIds=[], NativeActivatedPointIds=[],
                HiddenRootPointId=-1, HiddenDurationSeconds=point.get("hiddenDurationSeconds", 0),
                ChangesStageOnEnd=point.get("isNextStateWhenActionEnd", False), DragDestinations=[],
                _staticDestinationCount=len(point.get("destinations", [])))


def direction_for(point, pose, destination):
    if not pose or not all(k in point for k in ("ScreenX", "ScreenY")):
        return None
    width, height = pose.get("ScreenWidth", 0), pose.get("ScreenHeight", 0)
    if width <= 0 or height <= 0:
        return None
    if not (0 <= point["ScreenX"] <= width and 0 <= point["ScreenY"] <= height and 0 <= destination["X"] <= 1 and 0 <= destination["Y"] <= 1):
        return None
    dx = destination["X"] - point["ScreenX"] / width
    dy = destination["Y"] - point["ScreenY"] / height
    if max(abs(dx), abs(dy)) < .015:
        return "原位附近"
    horizontal = "右" if dx > 0 else "左"
    vertical = "上" if dy > 0 else "下"
    if abs(dx) < abs(dy) * .35:
        return "向" + vertical
    if abs(dy) < abs(dx) * .35:
        return "向" + horizontal
    return "向" + horizontal + vertical


def safe_point(point, yuri=False):
    name = clean_name(point.get("DisplayName"))
    if not name or point.get("PointId", 0) <= 0 or DENIED.search(name) or EVENT_LABEL.search(name):
        return False
    if (point.get("ChangesStageOnEnd") or point.get("SupportsDrag")) and CLOTHING_TRANSITION.search(name):
        return False
    if yuri and (not ORDINARY_YURI.search(name) or point.get("ChangesStageOnEnd") or point.get("SupportsDrag") or point.get("SupportsHold")):
        return False
    return True


def ordered_clicks(point):
    motions = point.get("NativeClickMotionNames", [])
    return bool(point.get("SupportsClick") and not point.get("SupportsHold") and not point.get("SupportsDrag") and
                (not point.get("ChangesStageOnEnd") or point.get("SupportsContinuousClick")) and
                (not point.get("SupportsContinuousClick") or 2 <= point.get("ClickMaxCount", 0) <= 128) and
                point.get("NativeClickMotionsReadable") and not point.get("NativeClickMotionsRandom") and
                2 <= len(motions) <= 128 and all(motions) and len(set(motions)) > 1)


def make_action(point, pose, stage_gauge, auto_motion_names, child_names):
    name = clean_name(point["DisplayName"])
    stage, tool, pid = signature(point)
    aid = "touch-" + short_id(f"{stage}:{tool}:{pid}:{name}")
    conditions, instructions, notes = [], [], []
    location = "角色以外的空白背景区域。" if name == "外面" else f"当前姿态中的{name}。左右以画面方向为准。"
    if tool:
        conditions.append("先切换至对应互动方式；该工具的显示名称尚待逐项核对。")
    if point.get("GaugeIsOn"):
        lo, hi = point.get("GaugeInteractableMin", 0), point.get("GaugeInteractableMax", 100)
        if lo != 0 or hi != 100:
            conditions.append(f"进度条为 {fnum(lo)} 时可用。" if lo == hi else f"进度条在 {fnum(lo)}–{fnum(hi)} 范围内可用。")
    threshold = float(point.get("HoldThresholdSeconds", 0) or 0)
    drag, hold = None, None
    if set(point.get("NativeMotionNames", [])) & auto_motion_names:
        gesture = "自动触发"
        instructions = ["按进度条说明达到对应阈值，由游戏自动播放该动作。", "等待收尾动画结束；不要为重复同一动画额外连点。"]
        location = "进度条触发；无需再次寻找手动点击位置。"
    elif point.get("SupportsDrag"):
        gesture = "拖拽"
        destinations = point.get("DragDestinations", [])
        if destinations:
            directions = [direction_for(point, pose, d) for d in destinations]
            known = [d for d in directions if d]
            direction = "／".join(dict.fromkeys(known)) if known and len(known) == len(destinations) else "方向待核对"
            drag = dict(from_=name, direction=direction, destination="拖至游戏允许的终点区域后松开。", verified=bool(known) and len(known) == len(destinations))
            drag["from"] = drag.pop("from_")
            instructions.append(f"在{name}按住鼠标左键，{direction}拖动，再松开。" if drag["verified"] else f"在{name}按住后拖向游戏提示的目标；本指南尚未核对终点与方向。")
            if len(destinations) > 1:
                notes.append(f"配置包含 {len(destinations)} 条不同拖动终点，需要分别尝试；此处不把它们合成一次滑动。")
        elif point.get("_staticDestinationCount", 0):
            drag = dict(direction="方向待核对", destination="终点位置尚未实机核对。", verified=False)
            instructions.append(f"按住{name}进行拖动；方向与终点尚待核对，不提供猜测路线。")
        else:
            drag = dict(direction="自由方向", destination="未配置固定终点；在起始部位附近小幅拖动后松开。", verified=True)
            instructions.append(f"按住{name}，在附近小幅拖动后松开；未配置固定方向与终点。")
        if threshold > 0:
            hold = math.ceil((threshold + .1 - 1e-6) * 10) / 10
            instructions.append(f"到位后保持至少 {fnum(hold)} 秒，再松开。")
    elif point.get("SupportsHold"):
        gesture = "长按"
        hold = math.ceil((threshold + .1 - 1e-6) * 10) / 10 if threshold > 0 else None
        instructions.append(f"在{name}持续按住至少 {fnum(hold)} 秒。" if hold else f"在{name}持续按住；具体阈值尚待核对。")
        instructions.append("达到阈值后松开，等待动作完整结束。" if point.get("LongPressMode") == 2 else "看到成功动作后松开，等待动作完整结束。")
    else:
        count = int(point.get("ClickMaxCount", 0) or 0) if point.get("SupportsContinuousClick") else len(point.get("NativeClickMotionNames", [])) if ordered_clicks(point) else 0
        if count >= 2:
            gesture = "连续短按"
            instructions.append(f"在{name}按顺序短按 {count} 次，每次允许继续触控时再点；最后一次后等待完整动画。")
            if ordered_clicks(point):
                conditions.append("次数以本阶段初始化状态为起点；已经做到中途时，从当前动作继续，不重播开头。")
            reset = float(point.get("ContinuousClickResetSeconds", 0) or 0)
            if reset > 0:
                notes.append(f"两次触控的间隔不要超过约 {fnum(reset)} 秒，否则连续计数会复位。")
        else:
            gesture = "短按"
            instructions.append(f"在{name}单击一次鼠标左键。")
        instructions.append("若要触发隐藏后续，请按组合卡片连续操作；其他单项等本次动画结束后再继续。" if child_names else "等待本次动画结束，再开始下一项。")
    scores = point.get("GaugeScores", [])
    if point.get("GaugeIsOn") and scores and scores[0]:
        notes.append(f"新一轮有效触发的进度变化为 {float(scores[0]):+g}，以游戏实际显示为准。")
        if len(scores) > 1 and scores[1] == 0 and not point.get("SupportsContinuousClick"):
            reset = float(point.get("ContinuousClickResetSeconds", 0) or 0)
            if reset > 0:
                notes.append(f"重复用于调节进度时，先等约 {fnum(reset)} 秒让连续判定复位；快速连点可能不再改变进度。")
    if point.get("GaugeIsOn") and point.get("SupportsHold") and point.get("GaugeLongPressSuccessScore"):
        notes.append(f"长按成功的进度变化为 {float(point['GaugeLongPressSuccessScore']):+g}。")
    return dict(id=aid, name="进度条 · 自动收尾" if gesture == "自动触发" else f"{name} · {gesture}", location=location, gesture=gesture, holdSeconds=hold,
                drag=drag, conditions=conditions, instructions=instructions, note=" ".join(notes), verified=False)


def merge_ordinary_duplicates(actions, combos):
    """Merge indistinguishable wording without inventing anatomical left/right.

    Several native records at one named region are not proof of several screen
    positions. Keep this uncertainty visible instead of numbering user buttons.
    """
    buckets, aliases = {}, {}
    for action in actions:
        signature = json.dumps({k: v for k, v in action.items() if k not in ("id", "verified")}, ensure_ascii=False, sort_keys=True)
        if signature in buckets:
            target = buckets[signature]
            target["variantCount"] += 1
            aliases[action["id"]] = target["id"]
        else:
            action["variantCount"] = 1
            buckets[signature] = action
            aliases[action["id"]] = action["id"]
    for action in buckets.values():
        if action["variantCount"] > 1:
            action["note"] = (action["note"] + " " if action["note"] else "") + "同一部位有不同后续反应；具体触控区差异尚待核对，请开启游戏提示，不按名称后的旧编号猜左右位置。"
    merged_combos = {}
    for combo in combos:
        for step in combo["steps"]:
            step["actionId"] = aliases[step["actionId"]]
        signature = json.dumps([step["actionId"] for step in combo["steps"]]) + json.dumps(combo.get("conditions", []), ensure_ascii=False)
        if signature not in merged_combos:
            merged_combos[signature] = combo
        else:
            if "同名后续记录合并展示" not in merged_combos[signature]["note"]:
                merged_combos[signature]["note"] += " 同名后续记录合并展示，触控区差异仍待核对。"
    return list(buckets.values()), list(merged_combos.values())


def supplemental_poses(kt):
    roots = [kt / ".cache/all-character-live", kt / ".cache/live-1.0-20261017",
             kt / ".cache/interaction-polish-20261017/live-7993-207-stage2",
             kt / ".cache/interaction-polish-20261017/live-7993-207-stage3"]
    paths = list(kt.glob(".cache/*.json")) + [path for root in roots for path in root.rglob("*.json")]
    poses, ranks = {}, {}
    for path in paths:
        if path.stat().st_size > 3_000_000:
            continue
        try:
            snapshot = read(path)
        except (ValueError, OSError):
            continue
        if isinstance(snapshot, dict) and "Snapshot" in snapshot:
            snapshot = snapshot["Snapshot"]
        if not isinstance(snapshot, dict):
            continue
        context = snapshot.get("Context", {})
        resource = context.get("ResourceKey", "")
        if resource not in ("Illust_dating6", "Illust_dating11", "Illust_dating18") or not valid_snapshot(snapshot, resource):
            continue
        for point in snapshot["Points"]:
            key = signature(point)
            if key[:2] != (context.get("PointGroupId"), context.get("ToolId")):
                continue
            identity = (resource, *key)
            rank = (not snapshot.get("AnimationBusy", True), snapshot.get("UtcTicks", 0))
            if rank > ranks.get(identity, (-1, -1)):
                poses[identity], ranks[identity] = (point, snapshot), rank
    return poses


def build(kt: Path, output: Path):
    base = kt / ".cache/new-guests-20261022"
    identities, native_names = identity_tables(base)
    acceptance = read(kt / ".cache/interaction-polish-20261017/live-owned-acceptance-v9/summary-owned-20261017T101008029504Z.json")
    baseline = {x["resourceKey"]: x for x in acceptance["roles"]}
    extra_poses = supplemental_poses(kt)
    characters, audit = [], []
    for resource_index in range(1, 23):
        resource = f"Illust_dating{resource_index}"
        flow = read(base / f"prefab-flows-v2/{resource}.prefab-flow.json")
        identity = identities[resource]
        if resource in baseline:
            identity.update(name=baseline[resource]["characterName"], costume=baseline[resource]["costumeName"])
        snapshots = []
        if resource in baseline:
            # Local paths appear only in the private input and audit, never payload.
            original = str(baseline[resource]["directory"])
            marker = original.lower().index(".cache")
            directory = (kt / original[marker:]).resolve()
            if not directory.is_relative_to((kt / ".cache").resolve()):
                raise ValueError("Historical evidence path escaped the supplied KT cache.")
            for path in sorted(directory.rglob("*.json")):
                if path.stat().st_size > 4_000_000:
                    continue
                try:
                    data = read(path)
                except (ValueError, OSError):
                    continue
                if valid_snapshot(data, resource):
                    snapshots.append((path, data))
        if resource_index == 22:
            for relative in [".cache/aqila-live-20261024/catalog-before-v1.json", ".cache/iteration-20261025/showcase-v4/before.json", ".cache/iteration-20261025/showcase-v4/cancel-after.json"]:
                path = kt / relative
                if path.exists():
                    data = read(path)
                    if "Snapshot" in data:
                        data = data["Snapshot"]
                    if valid_snapshot(data, resource):
                        snapshots.append((path, data))
        points, poses = {}, {}
        for path, snapshot in sorted(snapshots, key=lambda pair: pair[1].get("UtcTicks", 0)):
            for point in snapshot["Points"]:
                points[signature(point)] = dict(point)
                if point["PointGroupId"] == snapshot["Context"]["PointGroupId"] and point["ToolId"] == snapshot["Context"]["ToolId"]:
                    poses[signature(point)] = (point, snapshot)
        for point in flow["points"]:
            key = (point["stage"], point["tool"], point["pointId"])
            if key not in points and not point.get("ambiguous"):
                points[key] = static_point(point, identity["interaction"], native_names)
        for identity_key, pose in extra_poses.items():
            if identity_key[0] == resource:
                poses.setdefault(identity_key[1:], pose)
        # Static PPtr relationships complement runtime metadata; no design-table
        # child aliases are promoted to real hidden dependencies.
        for edge in flow["edges"]:
            if edge["kind"] not in ("hidden_config", "activation_config"):
                continue
            parse = lambda text: tuple(map(int, re.findall(r"(?:stage|tool|point):(\d+)", text)))
            parent, child = parse(edge["from"]), parse(edge["to"])
            if len(parent) == 3 and len(child) == 3 and parent in points and child in points:
                field = "NativeHiddenChildPointIds" if edge["kind"] == "hidden_config" else "NativeActivatedPointIds"
                points[parent].setdefault(field, [])
                if child[2] not in points[parent][field]:
                    points[parent][field].append(child[2])
        yuri = resource_index == 21
        all_body = {k: p for k, p in points.items() if k[2] > 0}
        safe = {k: p for k, p in all_body.items() if safe_point(p, yuri)}
        stages = sorted({state["stage"] for state in flow["stageStates"]} | {k[0] for k in points})
        phases = []
        excluded = len(all_body) - len(safe)
        for stage in stages:
            phase_points = {k: p for k, p in safe.items() if k[0] == stage}
            stage_configs = [s for s in flow["stageStates"] if s["stage"] == stage]
            auto_names = {m["MixAnimationName"] for s in stage_configs for m in s.get("gauge", {}).get("MotionNameByScoreList", [])}
            actions, by_key, conditions_by_key = [], {}, {}
            for key, point in sorted(phase_points.items()):
                children = [clean_name(safe.get((stage, key[1], child), {}).get("DisplayName")) for child in point.get("NativeHiddenChildPointIds", [])]
                pose_point, pose = poses.get(key, (point, None))
                action = make_action({**point, **{k: v for k, v in pose_point.items() if k in ("ScreenX", "ScreenY", "DragDestinations")}}, pose, stage_configs, auto_names if not yuri else set(), children)
                actions.append(action)
                by_key[key] = action
            combos, seen_routes = [], set()
            for key, parent in phase_points.items():
                children = list(dict.fromkeys(parent.get("NativeHiddenChildPointIds", []) + parent.get("NativeActivatedPointIds", [])))
                for child in children:
                    child_key = (stage, key[1], child)
                    if child_key not in by_key or child_key == key:
                        continue
                    route = (by_key[key]["id"], by_key[child_key]["id"])
                    if route in seen_routes:
                        continue
                    seen_routes.add(route)
                    start, end = by_key[key], by_key[child_key]
                    window = float(parent.get("HiddenDurationSeconds", 0) or 0)
                    combo_note = "动作出现后立即接下一步，不在中间插入其他互动。"
                    if window > 0 and child in parent.get("NativeHiddenChildPointIds", []):
                        combo_note += f" 配置窗口约 {fnum(window)} 秒，动画结束也可能提前关闭入口。"
                    combos.append(dict(id="route-" + short_id("/".join(route)), name=f"{clean_name(parent['DisplayName'])} → {clean_name(phase_points[child_key]['DisplayName'])}",
                                       steps=[dict(actionId=start["id"], location=start["location"], gesture=start["gesture"], instruction=start["instructions"][0]), dict(actionId=end["id"], location=end["location"], gesture=end["gesture"], instruction="后续部位出现后，" + end["instructions"][0])],
                                       conditions=start["conditions"], note=combo_note))
            for key, point in phase_points.items():
                if yuri or not ordered_clicks(point) or point.get("NativeHiddenChildPointIds") or point.get("NativeActivatedPointIds") or point.get("HiddenRootPointId", -1) >= 0:
                    continue
                action = by_key[key]
                total = point["ClickMaxCount"] if point.get("SupportsContinuousClick") else len(point["NativeClickMotionNames"])
                steps = []
                for click in range(total):
                    last = click == total - 1
                    label = "首次轻触" if click == 0 else "最后一步" if last else "接续轻触"
                    steps.append(dict(actionId=action["id"], label=label, location=action["location"], gesture="短按",
                                      instruction=f"在{clean_name(point['DisplayName'])}短按一次；" + ("等待本条顺序互动完整结束。" if last else "等游戏允许接续时，再在同一部位进行下一步。")))
                combos.append(dict(id="ordered-" + short_id(str(key)), name=f"{clean_name(point['DisplayName'])} · 同部位顺序互动", steps=steps,
                                   conditions=action["conditions"], note=f"完整顺序共 {total} 次短按，会按固定顺序出现不同反应。不能跳过中间步骤；已经做到中途时，从当前反应继续。"))
            gauge_rules = []
            if not yuri:
                gauge_controls = {}
                for key, point in phase_points.items():
                    if not point.get("GaugeIsOn"):
                        continue
                    scores = point.get("GaugeScores", [])
                    delta = scores[0] if scores else point.get("GaugeLongPressSuccessScore", 0)
                    if not delta:
                        continue
                    action = by_key[key]
                    text = action["instructions"][0] + f"有效触发的进度变化为 {float(delta):+g}。"
                    if action["conditions"]:
                        text += " " + " ".join(action["conditions"])
                    reset = float(point.get("ContinuousClickResetSeconds", 0) or 0)
                    if len(scores) > 1 and scores[1] == 0 and reset > 0 and not point.get("SupportsContinuousClick"):
                        text += f" 重复前等约 {fnum(reset)} 秒复位，快速连点可能不改变进度。"
                    gauge_controls[text] = dict(title="提高进度" if delta > 0 else "降低进度", description=text)
                gauge_rules.extend(gauge_controls.values())
                unique_gauges = {}
                for state in stage_configs:
                    gauge = state.get("gauge", {})
                    if not gauge.get("IsOn"):
                        continue
                    unique_gauges[json.dumps(gauge, sort_keys=True, ensure_ascii=False)] = gauge
                for gauge in unique_gauges.values():
                    lo, hi = gauge.get("MinMaxScore", {}).get("x", 0), gauge.get("MinMaxScore", {}).get("y", 100)
                    gauge_rules.append(dict(title="进度条", description=f"范围 {fnum(lo)}–{fnum(hi)}，本阶段起始值 {fnum(gauge.get('StartScore', 0))}。先完成当前分数区间的普通动作，再推进阶段。"))
                    decrease = float(gauge.get("AutoDecreaseScorePerSecond", 0) or 0)
                    if decrease < 0:
                        limits = gauge.get("AutoDecreaseScoreMinMaxLimit", {})
                        gauge_rules.append(dict(title="自然变化", description=f"进度在 {fnum(limits.get('x', 0))}–{fnum(limits.get('y', 100))} 的开区间内自然下降，每秒约 {fnum(abs(decrease))}；到边界后停止。"))
                    for motion in gauge.get("MotionNameByScoreList", []):
                        direction = "上升" if motion.get("IsCanPlayWhenIncreaseScore") else "下降"
                        score = motion.get("Score", 0)
                        text = f"进度条{direction}跨过 {fnum(score)} 时，由游戏自动播放收尾。等待动画完整结束，不再补同一动作的手动点击。"
                        if resource_index == 22 and stage == 2 and score == 0:
                            text += "本阶段到达 0 后会立即把进度重置为 50，属于正常自动收尾，不要反复降温等待稳定在 0。"
                        gauge_rules.append(dict(title="自动收尾", description=text, trigger=f"{direction}跨过 {fnum(score)}", automatic=True))
            transitions, seen_edges = [], set()
            for key, point in phase_points.items():
                target = point.get("NextPointGroupId", -1)
                if point.get("ChangesStageOnEnd") and target > 0 and target != stage:
                    edge_key = (target, by_key[key]["id"])
                    if edge_key not in seen_edges:
                        seen_edges.add(edge_key)
                        reverse = any(p.get("ChangesStageOnEnd") and p.get("NextPointGroupId") == stage for k, p in safe.items() if k[0] == target)
                        transitions.append(dict(to=str(target), direction="reversible" if reverse else "one-way", label=f"{by_key[key]['name']} → 阶段 {target}", actionId=by_key[key]["id"], condition=" ".join(by_key[key]["conditions"]) or "在当前阶段执行完整动作并等待结束。"))
            actions, combos = merge_ordinary_duplicates(actions, combos)
            # A transition label can point to one of the merged user cards.
            action_ids = {a["id"] for a in actions}
            for transition in transitions:
                if transition["actionId"] not in action_ids:
                    transition.pop("actionId")
            observed_stage = any(snapshot["Context"]["PointGroupId"] == stage for _, snapshot in snapshots) or any(k[0] == stage for k in poses)
            phase_summary = "先选择并列单项；有后继的按组合顺序接续。阶段切换前先补齐想看的当前动作。"
            if not observed_stage:
                phase_summary += " 此姿态来自配置目录，尚未单独核对手动落点。"
            phases.append(dict(id=str(stage), name=f"阶段 {stage}", summary=phase_summary, actions=actions, combos=combos, gaugeRules=gauge_rules, transitions=transitions))
        has_live = resource in baseline
        level = "historical-live" if has_live else "current-in-progress" if resource_index == 22 else "configuration-only"
        label = "含旧版现场资料" if has_live else "新版流程实测中" if resource_index == 22 else "资料流程，尚待实测"
        note = "2026-10-17客户端的流程记录；不代表最新客户端逐项重测。" if has_live else "本页依据配置与现场目录整理，最终动作覆盖仍在核对。" if resource_index == 22 else "这里只整理普通触控信息，不提供未核对的进阶路线。"
        initial_phase = next((str(s.get("InitializationPointGroupId")) for _, s in reversed(snapshots) if s.get("SupportsInitialization") and s.get("InitializationPointGroupId", -1) > 0), None)
        for phase in phases:
            if phase["id"] == initial_phase:
                phase["name"] = f"初始姿态 · 阶段 {phase['id']}"
        character = dict(id=SLUGS[resource_index - 1], name=identity["name"], costume=identity["costume"], resource=resource, initialPhaseId=initial_phase,
                         verification=dict(level=level, label=label, note=note), availability="需在游戏中拥有并进入对应服装。", phases=phases,
                         notes=["左右以当前画面为准。触控点跟随姿态变化，网页不提供固定像素坐标。", "本页只收录普通、中性的操作说明；部分互动未提供，不等同于全部内容。"],
                         limitations=["未核对的拖动终点与工具名会单独注明。", "游戏更新可能改变可用条件；以当前游戏提示为准。"],
                         coverage=dict(phases=len(phases), actions=sum(len(p["actions"]) for p in phases), combinations=sum(len(p["combos"]) for p in phases), omittedItems=excluded,
                                       unlocatedDrags=sum(1 for p in phases for a in p["actions"] if a["drag"] and not a["drag"].get("verified")),
                                       unseparatedLocations=sum(1 for p in phases for a in p["actions"] if a.get("variantCount", 1) > 1)))
        characters.append(character)
        audit.append(dict(resource=resource, identity=identity, inputSnapshots=[str(p.relative_to(kt)) for p, _ in snapshots], sourceSemanticPoints=len(all_body), ordinaryPoints=len(safe), excludedPoints=excluded, coveredKeys=[list(k) for k in safe], coverage=character["coverage"]))
    data = dict(schemaVersion=1, generatedAt="2026-10-25", summary=dict(characters=len(characters), distinctCharacters=len({c['name'] for c in characters}), phases=sum(len(c['phases']) for c in characters), actions=sum(c['coverage']['actions'] for c in characters), combinations=sum(c['coverage']['combinations'] for c in characters), scope="普通、中性手动操作说明；包含待核对项，不是全部互动的公开清单。"), characters=characters)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    private = output.parent.parent / ".cache"
    private.mkdir(exist_ok=True)
    (private / "guide-source-audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    make_coverage(output.parent.parent / "coverage.html", data)
    return data


def make_coverage(path, data):
    rows = []
    for char in data['characters']:
        c = char['coverage']
        rows.append('<tr><td><a href="./#character=' + html.escape(char['id']) + '">' + html.escape(char['name']) + '</a><br><small>' + html.escape(char['costume']) + '</small></td><td>✓ ' + str(c['phases']) + '</td><td>✓ ' + str(c['actions']) + '</td><td>✓ ' + str(c['combinations']) + '</td><td>' + str(c['unlocatedDrags']) + '</td><td>' + str(c['omittedItems']) + '</td><td>' + html.escape(char['verification']['label']) + '</td></tr>')
    path.write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>BD2有缘之客互动图鉴 · 收录记录</title><style>body{font:16px/1.7 system-ui,sans-serif;margin:3rem auto;max-width:1100px;padding:0 1rem;color:#342a30;background:#fcf7f9}a{color:#a53c69}table{border-collapse:collapse;width:100%;background:white}th,td{padding:.8rem;text-align:left;border-bottom:1px solid #eedce4}small{color:#76646c}h1{font-size:2rem}.wrap{overflow:auto}</style><h1>BD2有缘之客互动图鉴 · 收录记录</h1><p>✓ 表示本页数据已经整理并通过结构检查，不表示对应动作已在最新游戏逐项实测。收录普通、中性的操作；未收录内容和未核对的拖动方向分别计数。</p><p><a href="./">回到角色图鉴</a> · 作者 Flowers0120 · 2026-10-25</p><div class="wrap"><table><thead><tr><th>角色／服装</th><th>阶段</th><th>操作条目</th><th>连续组合</th><th>待核对拖动</th><th>未收录项</th><th>证据范围</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div></html>\n', encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kt-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('data/characters.json'))
    arguments = parser.parse_args()
    result = build(arguments.kt_root.resolve(), arguments.output.resolve())
    print(json.dumps(result['summary'], ensure_ascii=False))
