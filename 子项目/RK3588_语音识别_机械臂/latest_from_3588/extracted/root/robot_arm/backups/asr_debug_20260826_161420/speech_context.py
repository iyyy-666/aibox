"""Scene-aware speech correction for local RK3588 voice apps."""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass


def normalize_text(text: str) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]+", "", text or "").lower()


@dataclass(frozen=True)
class Correction:
    text: str
    matched: str
    score: float


HOTWORDS: dict[str, dict[str, tuple[str, ...]]] = {
    "assistant": {
        "你好": ("你好", "您好", "哈喽", "hello", "hi", "喂", "泥好", "你号", "你你好", "你好呀"),
        "小帅": ("小帅", "小衰", "小率", "小水", "小睡", "小谁", "肖帅", "晓帅"),
        "小星星": ("小星星", "小心星", "小猩猩", "小新星", "星星"),
        "两只老虎": ("两只老虎", "两支老虎", "两个老虎", "杨知老虎", "杨知老", "老虎"),
        "机械臂": ("机械臂", "机器人手臂", "机器臂", "机械手"),
        "语音儿歌播放": ("语音儿歌播放", "儿歌播放", "播放儿歌"),
    },
    "nursery": {
        "小星星": ("小星星", "小星", "星星", "小心星", "小猩猩", "小新星", "小行星", "小欣欣", "小星心", "小猩星", "小新新", "小心心", "播放小星星", "我要听小星星", "一闪一闪", "亮晶晶", "满天都是小星星"),
        "两只老虎": ("两只老虎", "两支老虎", "两个老虎", "两只老", "两只虎", "两老虎", "二只老虎", "俩只老虎", "梁志老虎", "良知老虎", "杨知老", "杨知老虎", "两只脑虎", "两只老古", "两只老五", "两只老胡", "两只劳虎", "播放两只老虎", "我要听两只老虎", "老虎", "脑虎", "劳虎", "老胡", "老古", "老五", "跑得快", "真奇怪"),
    },
    "robot": {
        "直立": ("直立", "直", "立", "竖", "站", "起", "起来", "直起", "立起", "站立", "竖立", "竖直", "立正", "抬起", "升起", "立起来", "竖起来", "竖直起来", "之力", "直力", "支立", "之立", "只立", "智力", "治理", "实力", "纸币", "指令"),
        "放平": ("放平", "放", "平", "平放", "放下", "放低", "下放", "躺平", "摆平", "铺平", "摊平", "展开", "前倾", "放倒", "倒下", "手臂放平", "机械臂放平", "方平", "防平", "放屏", "放瓶", "放坪", "访评"),
        "抓取": ("抓取", "抓", "取", "抓起", "抓紧", "抓住", "抓起来", "拿取", "拿起", "拿起来", "夹取", "夹住", "夹紧", "夹起来", "取物", "抓物", "抓东西", "拿东西", "抓去", "爪取", "早取", "找取", "他取", "它取", "夹去", "抓举", "格局", "各取", "搁取"),
        "搬运": ("搬运", "移", "移动", "搬", "搬过去", "移过去", "挪动", "挪过去", "拿过去", "放过去", "转过去", "迁移", "转一", "转椅", "转移"),
        "停止": ("停止", "停", "停下", "停住", "别动", "不要动", "暂停", "急停", "停止动作", "停下来", "停一停", "别转", "别抓", "别动了"),
        "张开": ("张开", "开", "打开", "松开", "放开", "打开夹子", "松开夹子", "开夹", "开爪", "夹爪打开", "张开夹爪", "张凯", "章开", "张卡", "张夹", "张爪", "张家"),
        "闭合": ("闭合", "合", "合上", "闭上", "关", "关闭", "夹紧", "夹住", "关夹", "合爪", "闭爪", "夹爪闭合", "夹爪合上", "并合", "闭盒"),
        "复位": ("复位", "回", "回位", "归位", "回中", "回正", "回原点", "回到原点", "恢复", "重置", "复原", "归中", "回到中间", "付位", "腹位"),
    },
}


HOTWORDS["robot"].update({
    "\u53f3\u8f6c\u79fb": (
        "\u53f3\u8f6c\u79fb", "\u5411\u53f3\u8f6c\u79fb", "\u5411\u53f3\u8f6c",
        "\u53f3\u8f6c", "\u53f3\u8fb9\u8f6c\u79fb", "\u642c\u5230\u53f3\u8fb9",
    ),
    "\u5de6\u8f6c\u79fb": (
        "\u5de6\u8f6c\u79fb", "\u5411\u5de6\u8f6c\u79fb", "\u5411\u5de6\u8f6c",
        "\u5de6\u8f6c", "\u5de6\u8fb9\u8f6c\u79fb", "\u642c\u5230\u5de6\u8fb9",
    ),
})

_BANYUN_ALIASES = (
    "\u642c\u8fd0", "\u822c\u8fd0", "\u534a\u8fd0", "\u73ed\u8fd0", "\u5e2e\u8fd0",
    "\u642c\u4e91", "\u642c\u6655", "\u642c\u97f5", "\u642c\u7528", "\u642c\u5b55",
    "\u642c", "\u8fd0", "\u8fd0\u8f93", "\u8fd0\u9001", "\u8f6c\u8fd0",
    "\u642c\u4e00\u4e0b", "\u642c\u4e00\u642c", "\u5f00\u59cb\u642c",
    "\u5f00\u59cb\u642c\u8fd0", "\u6267\u884c\u642c\u8fd0", "\u642c\u8fc7\u53bb",
    "\u642c\u5230", "\u642c\u8d70", "\u642c\u8d27", "\u642c\u7269",
    "\u79fb\u8fc7\u53bb", "\u79fb\u52a8", "\u632a\u52a8", "\u62ff\u8fc7\u53bb",
    "\u653e\u8fc7\u53bb", "\u8f6c\u79fb", "\u8f6c\u8fc7\u53bb",
)
HOTWORDS["robot"]["\u642c\u8fd0"] = tuple(dict.fromkeys(HOTWORDS["robot"].get("\u642c\u8fd0", ()) + _BANYUN_ALIASES))


COMMON_FIXES = {
    "泥好": "你好",
    "你号": "你好",
    "你你好": "你好",
    "小衰": "小帅",
    "小率": "小帅",
    "小水": "小帅",
    "小睡": "小帅",
    "小谁": "小帅",
    "肖帅": "小帅",
    "晓帅": "小帅",
    "小心星": "小星星",
    "小猩猩": "小星星",
    "小新星": "小星星",
    "两支老虎": "两只老虎",
    "两个老虎": "两只老虎",
    "杨知老虎": "两只老虎",
    "杨知老": "两只老虎",
    "梁只老虎": "两只老虎",
}


def _best_hotword(compact: str, scene: str) -> Correction | None:
    hotwords = HOTWORDS.get(scene, {})
    best: Correction | None = None
    for canonical, aliases in hotwords.items():
        for alias in aliases + (canonical,):
            alias_norm = normalize_text(alias)
            if not alias_norm:
                continue
            if len(alias_norm) == 1 and compact != alias_norm:
                score = 0.0
            elif alias_norm in compact:
                score = 1.0 if alias_norm == compact else min(0.98, 0.72 + len(alias_norm) / max(len(compact), 1) * 0.25)
            else:
                score = difflib.SequenceMatcher(None, compact, alias_norm).ratio()
            if best is None or score > best.score:
                best = Correction(canonical, alias_norm, score)
    return best


def correct_text(text: str, scene: str = "assistant", *, strict: bool = False) -> str:
    original = (text or "").strip()
    compact = normalize_text(original)
    if not compact:
        return ""

    for wrong, right in COMMON_FIXES.items():
        wrong_norm = normalize_text(wrong)
        if wrong_norm and wrong_norm in compact:
            if strict or len(compact) <= len(wrong_norm) + 4:
                return right
            return original.replace(wrong, right)

    best = _best_hotword(compact, scene)
    if not best:
        return original

    threshold = 0.78 if scene in {"nursery", "robot"} else 0.86
    if best.score >= threshold:
        if strict or len(compact) <= len(best.matched) + 4:
            return best.text
        return original
    return original


def match_command(text: str, commands: list[str] | tuple[str, ...]) -> str | None:
    compact = normalize_text(text)
    if not compact:
        return None

    corrected = correct_text(text, "robot", strict=False)
    if corrected in commands:
        return corrected

    best_command: str | None = None
    best_score = 0.0
    for command in commands:
        aliases = HOTWORDS["robot"].get(command, (command,))
        for alias in aliases + (command,):
            alias_norm = normalize_text(alias)
            if not alias_norm:
                continue
            if len(alias_norm) == 1 and compact != alias_norm:
                continue
            if alias_norm in compact or compact in alias_norm:
                score = 1.0 if alias_norm == compact else 0.92
            else:
                score = difflib.SequenceMatcher(None, compact, alias_norm).ratio()
            if score > best_score:
                best_command = command
                best_score = score

    if best_score >= 0.68:
        return best_command
    return None


def match_song(text: str) -> str | None:
    corrected = correct_text(text, "nursery", strict=True)
    return corrected if corrected in HOTWORDS["nursery"] else None
