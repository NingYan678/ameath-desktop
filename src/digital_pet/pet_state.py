"""Local, non-punitive companion state and proactive-interaction policy."""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path

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
)


@dataclass(frozen=True)
class PetState:
    schema_version: int = 2
    familiarity: int = 0
    energy: str = "calm"
    mood: str = "calm"
    last_interaction: str = ""
    last_proactive: str = ""
    recent_proactive_ids: tuple[str, ...] = ()
    last_proactive_category: str = ""


class PetStateStore:
    def __init__(self, data_root: Path) -> None:
        self.path = data_root / "pet_state.json"

    def load(self) -> PetState:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            recent = payload.get("recent_proactive_ids", [])
            if not isinstance(recent, list):
                recent = []
            return PetState(
                familiarity=max(0, min(10_000, int(payload.get("familiarity", 0)))),
                energy=str(payload.get("energy", "calm")),
                mood=str(payload.get("mood", "calm")),
                last_interaction=str(payload.get("last_interaction", "")),
                last_proactive=str(payload.get("last_proactive", "")),
                recent_proactive_ids=tuple(str(item) for item in recent if isinstance(item, str))[-12:],
                last_proactive_category=str(payload.get("last_proactive_category", "")),
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
        self.state = replace(
            self.state,
            familiarity=min(10_000, self.state.familiarity + 1),
            last_interaction=moment.isoformat(),
            energy="engaged",
            mood="curious",
        )
        self.store.save(self.state)

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
        recent = (*self.state.recent_proactive_ids, event.event_id)[-12:]
        self.state = replace(
            self.state,
            mood="curious",
            last_proactive=moment.isoformat(),
            recent_proactive_ids=recent,
            last_proactive_category=event.category,
        )
        self.store.save(self.state)
        return event

    def _choose_event(self, hour: int) -> ProactiveEvent:
        eligible = [event for event in PROACTIVE_EVENTS if not event.hours or hour in event.hours]
        unseen = [event for event in eligible if event.event_id not in self.state.recent_proactive_ids]
        category_changed = [event for event in unseen if event.category != self.state.last_proactive_category]
        return self._rng.choice(category_changed or unseen or eligible)

    def _quiet(self, moment: datetime) -> bool:
        start, end, hour = self.preferences.quiet_start_hour, self.preferences.quiet_end_hour, moment.hour
        return start <= hour < end if start < end else hour >= start or hour < end
