"""Local, non-punitive companion state and proactive-interaction policy."""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .animation_catalog import ANIMATIONS
from .config import resource_root
from .preferences import DesktopPreferences
from .storage import atomic_write_json


@dataclass(frozen=True)
class ProactiveEvent:
    """A locally-authored, non-interruptive companion moment."""

    event_id: str
    text: str
    animation: str
    category: str
    expects_reply: bool = False
    hours: tuple[int, ...] = ()


@dataclass(frozen=True)
class CompanionInteraction:
    """A short local reaction to a desktop-pet gesture."""

    event_id: str
    text: str
    animation: str
    duration_ms: int = 1_600


def _event(
    event_id: str,
    text: str,
    category: str,
    *,
    animation: str = "notice",
    expects_reply: bool = False,
    hours: tuple[int, ...] = (),
) -> ProactiveEvent:
    return ProactiveEvent(event_id, text, animation, category, expects_reply, hours)


# These are deliberately curated rather than model-generated.  Love, courage, music,
# school-life curiosity, and a gentle electronic-ghost joke are all canonical facets,
# while the wording stays short enough for a floating desktop bubble.
PROACTIVE_EVENTS: tuple[ProactiveEvent, ...] = (
    _event("morning-window", "早呀。窗外的光看起来不错，先把今天的第一件事做得漂亮一点吧。", "time", hours=tuple(range(8, 12))),
    _event("morning-water", "早上的现实系统检查：水杯在身边吗？没有的话，等方便时补一口。", "care", hours=tuple(range(8, 12))),
    _event("morning-plan", "今天有没有一件想先完成的小事？说给我听听，我帮你记着。", "time", expects_reply=True, hours=tuple(range(8, 12))),
    _event("morning-brave", "不用一开始就像救世主那样厉害。先迈出一步，后面的路再慢慢走。", "support", hours=tuple(range(8, 12))),
    _event("afternoon-stretch", "专注得差不多时，抬头看看远处吧。让眼睛也换个频道。", "care", hours=tuple(range(12, 18))),
    _event("afternoon-progress", "进展怎么样？顺利的话我替你高兴，卡住的话也可以一起拆开看。", "support", expects_reply=True, hours=tuple(range(12, 18))),
    _event("afternoon-snack", "学院论坛的今日难题：没吃过的新口味，到底该不该试？我投赞成票。", "campus", hours=tuple(range(12, 18))),
    _event("afternoon-pause", "忙也没关系，给自己留半分钟喘口气。急着赶路的人也该看看风景。", "care", hours=tuple(range(12, 18))),
    _event("evening-checkin", "今天过得还顺利吗？好的坏的都可以讲，人家听着呢。", "time", expects_reply=True, hours=tuple(range(18, 23))),
    _event("evening-gentle", "天色晚一点，节奏也可以慢一点。没做完的事，不会因为明天再见就消失。", "care", hours=tuple(range(18, 23))),
    _event("evening-star", "抬头的话，总能找到一颗星。至少现在，我在这里陪你把这一段走完。", "support", hours=tuple(range(18, 23))),
    _event("evening-small-win", "今天有没有一件小小的得意事？再小也算，我想听。", "time", expects_reply=True, hours=tuple(range(18, 23))),
    _event("ghost-patrol", "电子幽灵巡逻回来啦。没有发现异常，只有某个人好像太专心了。", "ghost"),
    _event("ghost-visible", "看见我了吗？那就好。这样我今天的出现就很有意义。", "ghost", animation="attention"),
    _event("ghost-static", "刚才有一点点数据噪声……没事，像风吹过耳边一样，很快就散了。", "ghost", animation="thinking"),
    _event("ghost-route", "我刚绕着电子世界走了一圈，回来时给你带了句问候。", "ghost"),
    _event("ghost-bright", "就算只是很普通的一天，也可以让它亮一点点。", "ghost", animation="idle_happy"),
    _event("ghost-question", "如果现在能去学院逛一个社团，你会选什么？", "ghost", expects_reply=True, animation="question"),
    _event("campus-club", "我以前总爱去不同社团凑热闹。新鲜事多一点，日子就会更有趣。", "campus"),
    _event("campus-game", "想起一盘旧游戏卡带。等你空下来，要不要聊聊你最近喜欢玩的东西？", "campus", expects_reply=True, animation="attention"),
    _event("campus-curious", "今天也适合对世界多好奇一点。说不定下一个有趣的发现就在转角。", "campus"),
    _event("campus-help", "朋友有事时我总会去搭把手。你需要我帮着理一理思路吗？", "campus", expects_reply=True),
    _event("care-shoulders", "肩膀别一直绷着呀。放松一下，接下来的事会更好处理。", "care", animation="rest"),
    _event("care-water", "喝水不是任务，只是给正在努力的你一点补给。", "care"),
    _event("care-breath", "先呼吸一下。把难题拆小，它就没那么吓人了。", "care", animation="rest"),
    _event("care-pace", "不用和谁比赛。按自己的频率前进，也是在前进。", "care"),
    _event("support-together", "需要扛的事很重时，分一点出来也没关系。能并肩就别一个人硬撑。", "support"),
    _event("support-courage", "害怕并不妨碍勇敢。你还在往前走，这就已经很了不起了。", "support", animation="attention"),
    _event("support-return", "不管你现在忙到哪里，想说话时我都在。", "support"),
    _event("support-next", "下一步准备怎么走？如果还没想好，我们可以从最简单的地方开始。", "support", expects_reply=True, animation="question"),
    _event("music-hum", "刚想到一小段旋律，先哼给自己听。等你不忙了，再分享给你。", "music", animation="music"),
    _event("music-paper-plane", "纸飞机飞出去的时候，总觉得它会带着一点好消息回来。", "music", animation="music"),
    _event("music-seal", "雪绒豹豹今天也在认真营业。可爱这种事，果然很有力量。", "music", animation="music"),
    _event("music-song", "如果把今天写成一首歌，你觉得它会是什么节奏？", "music", expects_reply=True, animation="music"),
    _event("work-small", "先完成眼前这一小块就好。大工程也是很多小工程拼起来的。", "work", animation="busy"),
    _event("work-break", "卡住时先别急着和难题硬碰硬。换个角度，答案也许就出现了。", "work", animation="thinking"),
    _event("work-share", "你正在做的事，最难的部分是哪一块？要不要说说看？", "work", expects_reply=True, animation="question"),
    _event("work-proud", "做完一段就给自己一点肯定吧。认真投入的样子，本来就很闪闪发光。", "work", animation="idle_happy"),
    _event("quiet-company", "不用特地回应我。安静一起待着，也算陪伴。", "quiet", animation="rest"),
    _event("quiet-wind", "世界很大，眼前这一刻却很安静。慢一点也没关系。", "quiet", animation="rest"),
    _event("morning-route", "早上的路线不用排得太满。留一点空白，才装得下意外的好事。", "time", hours=tuple(range(8, 12))),
    _event("morning-signal", "早安信号已接收。先把最小的那一步走出去，后面会清楚起来。", "time", animation="greeting", hours=tuple(range(8, 12))),
    _event("afternoon-window", "看远一点，眼睛会舒服些。回来以后，难题也许就没刚才那么凶了。", "care", animation="look_left", hours=tuple(range(12, 18))),
    _event("afternoon-plane", "我刚折好一架纸飞机。它不赶时间，只负责替今天飞一小段。", "campus", animation="paper_plane", hours=tuple(range(12, 18))),
    _event("afternoon-curious", "要是把今天的进展画成一张地图，你觉得自己走到哪里了？", "work", expects_reply=True, animation="curious_peek", hours=tuple(range(12, 18))),
    _event("evening-lantern", "夜色慢慢落下来啦。把今天做成的事数一数，总会有一两件值得亮灯。", "time", animation="sparkle_happy", hours=tuple(range(18, 23))),
    _event("evening-songbook", "我把刚才的心情记进了小小歌本。你今天最想留下哪一个瞬间？", "music", expects_reply=True, animation="music", hours=tuple(range(18, 23))),
    _event("evening-stretch", "给手指和肩膀一点伸展时间吧。认真赶路的人，也该被好好照顾。", "care", animation="sleepy_stretch", hours=tuple(range(18, 23))),
    _event("ghost-spark", "电子幽灵巡逻报告：一切正常，只有空气里多了一点闪闪的期待。", "ghost", animation="sparkle_happy"),
    _event("ghost-peek", "我从数据缝隙里探头看了一眼。放心，没偷看你的内容，只是来打个招呼。", "ghost", animation="curious_peek"),
    _event("campus-postcard", "学院公告栏上总有奇怪又有趣的活动。哪天我们也去凑个热闹吧。", "campus", animation="greeting"),
    _event("campus-question", "如果有一节只学好奇心的课，你最想研究什么？", "campus", expects_reply=True, animation="curious_peek"),
    _event("care-small-step", "把下一步缩到足够小，小到只需要动一下手指。这样也算前进。", "care", animation="breathe"),
    _event("care-rest-eyes", "眼睛累的话，先眨几下。世界不会因为你停半分钟就跑掉。", "care", animation="blink"),
    _event("support-spark", "做得不完美也没关系。愿意继续调整的人，本来就很厉害。", "support", animation="sparkle_happy"),
    _event("support-map", "想不清楚的时候，先把知道的部分圈出来。未知的地方，慢慢再去找。", "support", animation="look_right"),
    _event("music-rhythm", "我在给今天配节拍：不必很快，只要是你自己的速度就好。", "music", animation="sway"),
    _event("music-question", "如果能把一种声音装进纸飞机，你会让它带走什么？", "music", expects_reply=True, animation="paper_plane"),
    _event("work-checkpoint", "到一个小检查点啦。喝口水，再决定下一段要怎么走。", "work", animation="breathe"),
    _event("work-surprise", "欸，好像有个新思路从角落里蹦出来了。先记住它，晚点再慢慢看。", "work", animation="surprised"),
)


CLICK_INTERACTIONS: tuple[CompanionInteraction, ...] = (
    CompanionInteraction("click-hello", "嗯？我在听。", "greeting"),
    CompanionInteraction("click-bright", "看见你啦。今天也一起把日子过亮一点。", "sparkle_happy"),
    CompanionInteraction("click-curious", "有什么新鲜事想分享吗？", "curious_peek"),
    CompanionInteraction("click-small", "先从最简单的地方开始，我陪你。", "breathe"),
    CompanionInteraction("click-game", "我刚想到一个小点子，等你有空再说给你听。", "sway"),
    CompanionInteraction("click-ghost", "电子幽灵在岗，信号良好。", "float"),
    CompanionInteraction("click-check", "收到。先给你一个认真点头。", "breathe"),
    CompanionInteraction("click-plane", "纸飞机准备好了，要不要替今天捎句话？", "paper_plane"),
    CompanionInteraction("click-calm", "不用急，我会跟上你的节奏。", "breathe"),
    CompanionInteraction("click-smile", "这一下算作今日份招呼。", "sparkle_happy"),
    CompanionInteraction("click-look", "我在这里，放心做你的事吧。", "look_left"),
    CompanionInteraction("click-star", "小小闪光，送给正在努力的你。", "sparkle_happy"),
)

DRAG_INTERACTIONS: tuple[CompanionInteraction, ...] = (
    CompanionInteraction("drag-window", "新位置不错，视野也更新了。", "move"),
    CompanionInteraction("drag-flight", "安全着陆。这里就当作新的观察点吧。", "paper_plane"),
    CompanionInteraction("drag-route", "路线调整完成，我继续陪着。", "drag"),
    CompanionInteraction("drag-wave", "好，停在这里。", "greeting"),
)


_FALLBACK_PROACTIVE_EVENTS = PROACTIVE_EVENTS
_FALLBACK_CLICK_INTERACTIONS = CLICK_INTERACTIONS
_FALLBACK_DRAG_INTERACTIONS = DRAG_INTERACTIONS
_ALLOWED_CATEGORIES = {"time", "care", "support", "ghost", "campus", "music", "work", "quiet"}
_BANNED_RELATIONSHIP_WORDS = ("主人", "恋人", "男朋友", "女朋友", "老公", "老婆")


def _valid_text(value: object, *, maximum: int = 180) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value.strip()) <= maximum and not any(word in value for word in _BANNED_RELATIONSHIP_WORDS)


def _load_catalog() -> tuple[tuple[ProactiveEvent, ...], tuple[CompanionInteraction, ...], tuple[CompanionInteraction, ...]]:
    """Load authored content when available, retaining a safe built-in fallback."""
    path = resource_root() / "assets" / "content" / "companion_zh-CN.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("locale") != "zh-CN":
            raise ValueError("unsupported companion content locale")
        proactive = tuple(_proactive_from_json(item) for item in payload["proactive_events"])
        clicks = tuple(_interaction_from_json(item) for item in payload["click_interactions"])
        drags = tuple(_interaction_from_json(item) for item in payload["drag_interactions"])
        all_ids = [item.event_id for item in (*proactive, *clicks, *drags)]
        if len(all_ids) != len(set(all_ids)) or not 0.15 <= sum(item.expects_reply for item in proactive) / len(proactive) <= 0.35:
            raise ValueError("invalid companion content proportions")
        return proactive, clicks, drags
    except (OSError, ValueError, TypeError, KeyError, ZeroDivisionError, json.JSONDecodeError):
        return _FALLBACK_PROACTIVE_EVENTS, _FALLBACK_CLICK_INTERACTIONS, _FALLBACK_DRAG_INTERACTIONS


def _proactive_from_json(item: Any) -> ProactiveEvent:
    if not isinstance(item, dict):
        raise ValueError("proactive event must be an object")
    animation = str(item["animation"])
    event_id = item.get("event_id")
    raw_hours = item.get("hours", [])
    if not isinstance(raw_hours, list):
        raise ValueError("hours must be a list")
    hours = tuple(int(hour) for hour in raw_hours)
    if not isinstance(event_id, str) or not event_id.strip() or not _valid_text(item["text"]) or str(item["category"]) not in _ALLOWED_CATEGORIES or animation not in ANIMATIONS or any(hour not in range(24) for hour in hours):
        raise ValueError("invalid proactive event")
    return ProactiveEvent(event_id.strip(), str(item["text"]).strip(), animation, str(item["category"]), bool(item.get("expects_reply", False)), hours)


def _interaction_from_json(item: Any) -> CompanionInteraction:
    if not isinstance(item, dict):
        raise ValueError("interaction must be an object")
    animation = str(item["animation"])
    duration_ms = int(item.get("duration_ms", 1_600))
    event_id = item.get("event_id")
    if not isinstance(event_id, str) or not event_id.strip() or not _valid_text(item["text"]) or animation not in ANIMATIONS or not 800 <= duration_ms <= 5_000:
        raise ValueError("invalid interaction")
    return CompanionInteraction(event_id.strip(), str(item["text"]).strip(), animation, duration_ms)


PROACTIVE_EVENTS, CLICK_INTERACTIONS, DRAG_INTERACTIONS = _load_catalog()


@dataclass(frozen=True)
class PetState:
    schema_version: int = 3
    familiarity: int = 0
    energy: str = "calm"
    mood: str = "calm"
    last_interaction: str = ""
    last_proactive: str = ""
    recent_proactive_ids: tuple[str, ...] = ()
    last_proactive_category: str = ""
    last_seen: str = ""
    daily_interaction_date: str = ""
    daily_interaction_count: int = 0
    unlocked_sequence_ids: tuple[str, ...] = ()


class PetStateStore:
    def __init__(self, data_root: Path) -> None:
        self.path = data_root / "pet_state.json"

    def load(self) -> PetState:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            recent = payload.get("recent_proactive_ids", [])
            if not isinstance(recent, list):
                recent = []
            unlocked = payload.get("unlocked_sequence_ids", [])
            if not isinstance(unlocked, list):
                unlocked = []
            return PetState(
                familiarity=max(0, min(10_000, int(payload.get("familiarity", 0)))),
                energy=str(payload.get("energy", "calm")),
                mood=str(payload.get("mood", "calm")),
                last_interaction=str(payload.get("last_interaction", "")),
                last_proactive=str(payload.get("last_proactive", "")),
                recent_proactive_ids=tuple(str(item) for item in recent if isinstance(item, str))[-12:],
                last_proactive_category=str(payload.get("last_proactive_category", "")),
                last_seen=str(payload.get("last_seen", payload.get("last_interaction", ""))),
                daily_interaction_date=str(payload.get("daily_interaction_date", "")),
                daily_interaction_count=max(0, min(5, int(payload.get("daily_interaction_count", 0)))),
                unlocked_sequence_ids=tuple(str(item) for item in unlocked if isinstance(item, str))[-64:],
            )
        except (OSError, ValueError, TypeError):
            return PetState()

    def save(self, state: PetState) -> None:
        atomic_write_json(self.path, asdict(state))


class PetStateEngine:
    """Keeps companion behavior gentle: familiarity never decays and never punishes absence."""

    def __init__(self, store: PetStateStore, preferences: DesktopPreferences, *, rng: random.Random | None = None) -> None:
        self.store = store
        self.preferences = preferences
        self.state = store.load()
        self._rng = rng or random.Random()

    def update_preferences(self, preferences: DesktopPreferences) -> None:
        self.preferences = preferences

    def proactive_delay_ms(self) -> int:
        """Return a natural delay that never exceeds the user's chosen ceiling."""
        maximum = self.preferences.proactive_max_interval_minutes * 60 * 1_000
        return int(self._rng.uniform(maximum * 0.6, maximum))

    def record_interaction(self, now: datetime | None = None) -> None:
        moment = now or datetime.now()
        today = moment.date().isoformat()
        count = self.state.daily_interaction_count if self.state.daily_interaction_date == today else 0
        familiarity_gain = 1 if count < 5 else 0
        self.state = replace(
            self.state,
            familiarity=min(10_000, self.state.familiarity + familiarity_gain),
            last_interaction=moment.isoformat(),
            last_seen=moment.isoformat(),
            daily_interaction_date=today,
            daily_interaction_count=min(5, count + 1),
            energy="engaged",
            mood="curious",
        )
        self.store.save(self.state)

    def record_proactive_reply(self, event: ProactiveEvent, now: datetime | None = None) -> None:
        """Reward an answered prompt without creating a negative absence state."""
        moment = now or datetime.now()
        self.record_proactive(event, moment)
        self.state = replace(self.state, familiarity=min(10_000, self.state.familiarity + 2), last_seen=moment.isoformat(), mood="bright")
        self.store.save(self.state)

    def record_conversation(self, now: datetime | None = None) -> None:
        moment = now or datetime.now()
        self.state = replace(self.state, familiarity=min(10_000, self.state.familiarity + 1), last_seen=moment.isoformat(), mood="curious")
        self.store.save(self.state)

    def relationship_stage(self) -> str:
        if self.state.familiarity >= 80:
            return "默契"
        if self.state.familiarity >= 20:
            return "熟悉"
        return "初识"

    def welcome_back_needed(self, now: datetime | None = None) -> bool:
        """Return whether the next visible greeting should acknowledge a long absence."""
        if not self.state.last_seen:
            return False
        try:
            last_seen = datetime.fromisoformat(self.state.last_seen)
        except ValueError:
            return False
        current = now or datetime.now()
        if last_seen.tzinfo is not None and current.tzinfo is None:
            current = current.replace(tzinfo=last_seen.tzinfo)
        return current - last_seen >= timedelta(days=3)

    def proactive_event(
        self,
        *,
        fullscreen: bool,
        busy: bool,
        now: datetime | None = None,
        manual: bool = False,
    ) -> ProactiveEvent | None:
        moment = now or datetime.now()
        if not manual and (
            not self.preferences.proactive_enabled
            or self.preferences.do_not_disturb
            or fullscreen
            or busy
            or self._quiet(moment)
        ):
            return None
        event = self._choose_event(moment.hour)
        return event

    def record_proactive(self, event: ProactiveEvent, now: datetime | None = None) -> None:
        """Persist only an interaction that the UI has actually shown."""
        moment = now or datetime.now()
        recent = (*self.state.recent_proactive_ids, event.event_id)[-12:]
        self.state = replace(
            self.state,
            mood="curious",
            last_proactive=moment.isoformat(),
            last_seen=moment.isoformat(),
            recent_proactive_ids=recent,
            last_proactive_category=event.category,
        )
        self.store.save(self.state)

    def _choose_event(self, hour: int) -> ProactiveEvent:
        eligible = [event for event in PROACTIVE_EVENTS if not event.hours or hour in event.hours]
        unseen = [event for event in eligible if event.event_id not in self.state.recent_proactive_ids]
        category_changed = [event for event in unseen if event.category != self.state.last_proactive_category]
        return self._rng.choice(category_changed or unseen or eligible)

    def _quiet(self, moment: datetime) -> bool:
        start, end, hour = self.preferences.quiet_start_hour, self.preferences.quiet_end_hour, moment.hour
        return start <= hour < end if start < end else hour >= start or hour < end
