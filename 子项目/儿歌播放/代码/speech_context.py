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

_ROBOT_EXTRA_ALIASES = {
    "直立": (
        "立起来", "站起来", "竖起来", "竖直起来", "直起来", "直立起来",
        "机械臂直立", "机械臂站起来", "机械臂竖起来", "手臂直立", "手臂站起来",
        "之力起来", "实力起来", "只立起来", "治理起来", "纸立", "支棱起来",
        "站起", "站直", "竖直一点", "立正一点", "直立一点", "直力起来",
        "支力起来", "治立起来", "纸里起来", "机械臂立起来",
    ),
    "放平": (
        "放平一点", "放下来", "放低一点", "往下放", "向下放", "平下来",
        "机械臂放平", "手臂放平", "机械臂放下来", "手臂放下来", "躺下来",
        "放瓶", "放评", "访平", "方评", "防评", "防屏", "放品",
        "放平一下", "放低下来", "往前放", "向前放", "平放一下", "趴下来",
        "平躺", "放倒一点", "房平", "方屏", "放凭", "防凭",
    ),
    "抓取": (
        "抓一下", "抓一个", "抓物块", "抓住物块", "抓起物块", "抓这个",
        "夹一下", "夹一个", "夹物块", "夹住物块", "夹起物块", "拿一下",
        "拿住", "拿起来", "爪举", "抓举", "抓去", "夹去", "夹举", "早取",
        "抓取一下", "抓紧物块", "夹取物块", "拿起物块", "拿这个", "取一下",
        "抓住这个", "夹住这个", "加取", "家取", "爪取一下", "找取一下",
    ),
    "搬运": (
        "搬运一下", "搬一下", "搬一搬", "帮我搬运", "开始搬运", "执行搬运",
        "搬运物块", "搬一下物块", "搬这个物块", "把物块搬走", "把物块搬过去",
        "移动物块", "移动一下物块", "转移物块", "转运物块", "运送物块",
        "搬云一下", "搬晕一下", "搬用一下", "搬孕一下", "半运一下", "班运一下",
        "帮运一下", "般运一下", "办运一下", "板运一下", "搬过来", "搬过去",
        "机器臂搬运", "机械手搬运", "机械臂帮运", "机械臂班运",
        "帮我搬一下", "帮我搬一搬", "搬运一下物块", "搬运这个", "搬运这块",
        "把它搬走", "把它搬过去", "把这个搬走", "把这个搬过去", "帮我转移",
        "开始转移", "执行转移", "搬一", "搬运一", "搬运一块", "班用一下",
        "半用一下", "帮用一下", "搬嗯一下", "机器搬运", "机器臂班运",
    ),
    "停止": (
        "停一下", "先停", "暂停一下", "不要动", "别动了", "停止动作",
        "停止运行", "停住", "停下来", "停一停", "先别动",
        "停住别动", "马上停", "立即停", "别运行", "先暂停", "停掉",
    ),
    "张开": (
        "张开一点", "打开一点", "打开夹爪", "张开夹爪", "松开夹爪",
        "松爪", "开爪子", "打开爪子", "夹爪松开", "爪子张开",
        "张卡", "张凯", "章凯", "展开夹爪", "展开爪子",
        "张开一下", "打开一下", "松一点", "松开一点", "张爪", "打开爪",
        "开一下夹爪", "张凯一下", "章开一下", "展开一下",
    ),
    "闭合": (
        "闭合一点", "合起来", "合上一点", "关闭夹爪", "夹爪闭合",
        "夹爪合上", "夹爪夹紧", "爪子合上", "爪子夹紧", "夹紧一点",
        "闭盒", "闭和", "并合", "闭夹", "合夹",
        "闭合一下", "合上夹爪", "合一下", "夹一下", "夹住一点", "关上夹爪",
        "关闭爪子", "合住", "闭上一点", "并拢",
    ),
    "复位": (
        "回到原点", "回原位", "回到原位", "恢复原位", "恢复一下",
        "回中间", "回正一下", "复原一下", "重新复位", "重置一下",
        "归位一下", "归中一下", "付位一下", "腹位一下",
        "回初始", "回到初始", "恢复初始", "回默认", "回到默认", "回正位",
    ),
}

for _command, _aliases in _ROBOT_EXTRA_ALIASES.items():
    HOTWORDS["robot"][_command] = tuple(dict.fromkeys(HOTWORDS["robot"].get(_command, ()) + _aliases))


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
