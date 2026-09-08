"""The fixed vocabulary a clip's `moment_tag` has to come from, and the table
that maps every tag ever written by hand onto it.

`moment_tag` exists to answer one question with numbers: which *kind* of moment
holds viewers. It was free-form, so it never could. Across 234 published clips
it grew 168 distinct values, 152 of them used exactly once - not a distribution,
a list. Two things went wrong and both are visible in that list:

  - it was being written as the *name* of a moment rather than its class
    ("ящик Шрёдингера на дне", "травма от пчелы", "ползуны"), so no two clips
    ever shared one;
  - the same class was written in two languages, splitting its own evidence:
    self-deprecating (7) + self-deprecation + самоирония (2) + самоирония по
    статистике = 11 clips, the largest group on the channel, recorded as four
    unrelated tags of which none looked significant.

So the class goes in a closed list, and the name of the moment goes somewhere
else - that is what a free-form index line is for, and it is a different field
with a different consumer (search), not this one (statistics).

ALIASES carries every historical value onto the new list. Without it the
vocabulary produces no statistics until a few months of clips accumulate; with
it the 234 clips already published become usable the moment it lands.

    python scripts/moment_tags.py --list
    python scripts/moment_tags.py --check "самоирония"
"""

from __future__ import annotations

import argparse
import sys

# tag -> what belongs in it, in the words step 5 needs to make the call.
MOMENT_TAGS: dict[str, str] = {
    "self-deprecation": "смеётся над собой: над своей игрой, статистикой, рангом, руками",
    "meme-chant": "речёвка, песня, скандирование, мем хором",
    "wordplay": "игра слов, оговорка, комичная путаница, неудачная формулировка",
    "absurd-claim": "абсурдное утверждение или байка, поданная всерьёз",
    "aphorism": "внезапно ёмкая формулировка, которая стоит сама по себе",
    "dark-humor": "чёрный юмор, деадпан про плохое, врачебная жуть",
    "sex-joke": "телесное и сексуальное",
    "rage-rant": "возмущение игрой, балансом, интерфейсом, техникой",
    "trash-talk": "наезд на людей: тиммейтов, чужих в войсе, пискунов",
    "game-fail": "провал в игре: физика, техника, промах, неудачный ультимейт",
    "teamkill": "по своим: тимкилл, мародёрство, размен товарищем",
    "death-beat": "смерть, вайп, мгновенная карма, накаркал",
    "loot-find": "находка, лут, пропажа вещей",
    "game-bug": "баг, тупой бот, сломанный ИИ, застрявшая модель",
    "lore-explainer": "объяснение или спор о правилах мира и игры",
    "irl-story": "история из жизни: работа, семья, быт, еда",
    "meta": "про сам стрим, клипы, ритуалы, конец эфира",
}

# Every value written by hand before the vocabulary existed, mapped onto it.
# Kept in the repo deliberately: this is a synonym table, not channel
# statistics - no titles, no view counts, no video ids.
ALIASES: dict[str, str] = {
    # --- self-deprecation ---
    "self-deprecating": "self-deprecation",
    "самоирония": "self-deprecation",
    "самоирония по статистике": "self-deprecation",
    "cope-logic": "self-deprecation",
    "confession": "self-deprecation",
    "setup-confession": "self-deprecation",
    "best-squad-denial": "self-deprecation",
    "незаслуженный топ": "self-deprecation",
    "приговор наигранным часам": "self-deprecation",
    "хвастливый панчлайн": "self-deprecation",
    "тревога за ранг": "self-deprecation",
    "losing-streak-base": "self-deprecation",
    "самоирония по статистике ": "self-deprecation",
    # --- meme-chant ---
    "song-parody": "meme-chant",
    "поют невпопад": "meme-chant",
    "wordplay-rhyme": "meme-chant",
    "мем-реакция": "meme-chant",
    "meme-observation": "meme-chant",
    "мем про рост": "meme-chant",
    "хайп-момент": "meme-chant",
    "покемон-отсылка": "meme-chant",
    # --- wordplay ---
    "calendar-joke": "wordplay",
    "поиск эвфемизма": "wordplay",
    "комичная путаница": "wordplay",
    "кривой пересказ": "wordplay",
    "misunderstanding": "wordplay",
    "комедийная растерянность": "wordplay",
    "joke": "wordplay",
    "список не туда": "wordplay",
    # --- absurd-claim ---
    "absurd": "absurd-claim",
    "absurd-observation": "absurd-claim",
    "absurd-story": "absurd-claim",
    "абсурдная байка": "absurd-claim",
    "absurd-cat-story": "absurd-claim",
    "absurd-roommate-story": "absurd-claim",
    "absurd-crew-bit": "absurd-claim",
    "news-absurd": "absurd-claim",
    "gross-out-news-bit": "absurd-claim",
    "абсурдный рекорд": "absurd-claim",
    "абсурдный рекорд + панчлайн": "absurd-claim",
    "number-shock-rant": "absurd-claim",
    "лестница рангов": "absurd-claim",
    "сверка рангов": "absurd-claim",
    "ранг младшего брата выше всех": "absurd-claim",
    "token-math": "absurd-claim",
    "chaos": "absurd-claim",
    # --- aphorism ---
    "внезапный афоризм": "aphorism",
    "оптимизм после взрыва": "aphorism",
    "dark-philosophy": "aphorism",
    "новое знание": "aphorism",
    # --- dark-humor ---
    "деадпан про травму": "dark-humor",
    "деадпан в четыре реплики": "dark-humor",
    "gross-out-taunt": "dark-humor",
    "диагноз игроку": "dark-humor",
    "травма от пчелы": "dark-humor",
    "медицина на борту": "dark-humor",
    "биология баротравмы": "dark-humor",
    # --- rage-rant ---
    "rage": "rage-rant",
    "rage-quit-beat": "rage-rant",
    "rage-suggestion": "rage-rant",
    "рейдж-рант": "rage-rant",
    "rant": "rage-rant",
    "ui-rant": "rage-rant",
    "br-complaint": "rage-rant",
    "претензия к игре": "rage-rant",
    "подъёб про баланс": "rage-rant",
    "teammate-rant": "rage-rant",
    "vehicle-design-rant": "rage-rant",
    "dramatic-exit": "rage-rant",
    "wt-suffering-classic": "rage-rant",
    "delivery-grief": "rage-rant",
    "разнос грязной клавиатуры": "rage-rant",
    # --- trash-talk ---
    "сленг-оскорбления": "trash-talk",
    "разбор тиммейта": "trash-talk",
    "kid-squeaker": "trash-talk",
    "mic-bleed-argument": "trash-talk",
    "ответ незнакомцу в войсе": "trash-talk",
    "tier-list": "trash-talk",
    "спор про кубик": "trash-talk",
    # --- game-fail ---
    "physics-fail": "game-fail",
    "vehicle-fail": "game-fail",
    "фейл на посадке": "game-fail",
    "посадка с прокруткой": "game-fail",
    "летит без крыльев": "game-fail",
    "неуправляемая техника": "game-fail",
    "провальный ультимейт": "game-fail",
    "промах в упор": "game-fail",
    "event-fail": "game-fail",
    "event-choice": "game-fail",
    "drowning-fiasco": "game-fail",
    "абсурдный самострел": "game-fail",
    "flip-over-bit": "game-fail",
    "rickochet-gag": "game-fail",
    "vehicle-duel": "game-fail",
    "burning-tank-standoff": "game-fail",
    "tiger-standoff": "game-fail",
    "прятки в матче": "game-fail",
    "отказ стрелять": "game-fail",
    "приоритеты без рук": "game-fail",
    "ПДД в танках": "game-fail",
    "докатился до ремзоны": "game-fail",
    "поломка лодки": "game-fail",
    "ремонт корпуса": "game-fail",
    "пробоина в пещере": "game-fail",
    "война с реагентом": "game-fail",
    "explosion": "game-fail",
    "monster": "game-fail",
    "ползуны": "game-fail",
    "пропажа брони": "game-fail",
    # --- teamkill ---
    "friendly-fire": "teamkill",
    "teammate-griefing": "teamkill",
    "мародёрство своих": "teamkill",
    "размен собой": "teamkill",
    "бросили умирать": "teamkill",
    "revenge-kill-take": "teamkill",
    "рекурсивная кража ульты": "teamkill",
    # --- death-beat ---
    "смерть напарника": "death-beat",
    "потеря экипажа": "death-beat",
    "мгновенная карма": "death-beat",
    "jinx": "death-beat",
    "ирония судьбы": "death-beat",
    "irony": "death-beat",
    "wipe": "death-beat",
    "бомбёжка мимо": "death-beat",
    "cure": "death-beat",
    # --- loot-find ---
    "loot": "loot-find",
    "loot-joke": "loot-find",
    "находка в руинах": "loot-find",
    "встреча в руинах": "loot-find",
    "ящик Шрёдингера на дне": "loot-find",
    "empty-map-realization": "loot-find",
    # --- game-bug ---
    "npc-ai": "game-bug",
    "боты не работают": "game-bug",
    "баг у неигрового персонажа": "game-bug",
    "фейковая интеграция": "game-bug",
    "ник решил судьбу": "game-bug",
    # --- lore-explainer ---
    "wh40k-lore": "lore-explainer",
    "прогресс в науке": "lore-explainer",
    "спор про физику": "lore-explainer",
    "эксперименты на борту": "lore-explainer",
    "дружба в баротравме": "lore-explainer",
    "stalinium-bit": "lore-explainer",
    # --- irl-story ---
    "bet-story": "irl-story",
    "war-story": "irl-story",
    "жиза-история": "irl-story",
    "work-joke": "irl-story",
    "story-app-bit": "irl-story",
    "младший вырос": "irl-story",
    "bread-and-cheese": "irl-story",
    "recipe-trial-error": "irl-story",
    "перекур на глубине": "irl-story",
    # --- meta ---
    "claude-meta-joke": "meta",
    "meta-bit": "meta",
    "meta-joke": "meta",
    "meta-clip-joke": "meta",
    "конец стрима": "meta",
    "ритуал вечера": "meta",
    "ритуал на поиск катки": "meta",
    "ритуал сработал": "meta",
    "recurring-bit": "meta",
    "running-gag": "meta",
    # --- values that were only ever in the publish queue, never in the
    # retention summary: the queue holds clips the analytics pass has not
    # caught up with yet, including the two most recent batches. ---
    "абсурдный вордплей": "wordplay",
    "мемная отсылка": "meme-chant",
    "ностальгия-мем": "meme-chant",
    "tension-chant-payoff": "meme-chant",
    "угадай мелодию": "meme-chant",
    "non-sequitur": "absurd-claim",
    "non-sequitur-joke": "absurd-claim",
    "absurd-monster-naming": "absurd-claim",
    "absurd-friendship-reveal": "absurd-claim",
    "равноправие на глубине": "absurd-claim",
    "отыгрыш роли": "absurd-claim",
    "дресс-код на борту": "absurd-claim",
    "навигация": "absurd-claim",
    "живучесть": "absurd-claim",
    "dark-humor-confession": "dark-humor",
    "идеальное преступление": "dark-humor",
    "самолечение": "dark-humor",
    "планы на похороны": "dark-humor",
    "meta-copyright-joke": "meta",
    "session-summary-line": "meta",
    "сводка о положении дел": "meta",
    "итог капитана": "meta",
    "итоги рейса": "meta",
    "конец сессии": "meta",
    "gameplay-blame-reenactment": "trash-talk",
    "сравнение статов": "self-deprecation",
    "признание про аим": "self-deprecation",
    "проводы напарника": "death-beat",
    "странные смерти": "death-beat",
    "абордаж": "death-beat",
    "книга варпа": "lore-explainer",
    "молитвы": "lore-explainer",
    "истории про обмороки": "irl-story",
    "работа и созвоны": "irl-story",
    "быт": "irl-story",
    "обыск пленных": "loot-find",
    "претензия к оптимизации": "rage-rant",
    "состояние корабля": "rage-rant",
    "отношения с хасками": "sex-joke",
    "дисциплина на борту": "teamkill",
    "загадочный взрыв": "game-fail",
    "паника": "game-fail",
    "аварии": "game-fail",
    "баги анимации": "game-bug",
}


def canonical_tag(raw: str | None) -> str | None:
    """The vocabulary entry this value belongs to, or None if it is unknown.

    Case and surrounding whitespace are ignored - a tag that differs only in
    capitalisation is the same tag, and treating it otherwise is how a closed
    list quietly grows an eighteenth member.
    """
    if not raw:
        return None
    value = " ".join(raw.split()).lower()
    for tag in MOMENT_TAGS:
        if value == tag:
            return tag
    for alias, tag in ALIASES.items():
        if value == " ".join(alias.split()).lower():
            return tag
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="печатает словарь")
    parser.add_argument("--check", metavar="TAG", help="во что превращается это значение")
    args = parser.parse_args(argv)

    if args.check is not None:
        tag = canonical_tag(args.check)
        if tag is None:
            print(f"{args.check!r} — не из словаря", file=sys.stderr)
            return 1
        print(tag)
        return 0

    for tag, description in MOMENT_TAGS.items():
        print(f"{tag:18} {description}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
