# Writing clip metadata (RU) — hooks and anti-AI-tone filter

Guidance for SKILL.md step 5 ("Per-platform metadata"). Adapted from
[jointime1/reels-skill](https://github.com/jointime1/reels-skill)'s
`ban-list-ru.md` / `hook-bank-ru.md` (MIT) — that skill writes reel scripts
from git commits, ours writes title/description/captions for a clip already
cut from a stream. The anti-AI-tone filter and hook formulas below are
generic to short-form Russian copy either way; the git-specific material
(commit arcs, scoring, story atoms) is not — it isn't included here.

Apply this after drafting `youtube.title`/`description` and
`tiktok`/`instagram` captions in SKILL.md step 5, before writing the
metadata JSON. See also [register-ru.md](register-ru.md) for sentence-level
rules (short sentences, active voice, concrete numbers/names) and its own
speak-test/Telegram-test/random-test.

## Hook (first line of the caption / the title itself)

A hook is ≤7 words, readable in ≤3 seconds. Pick the formula that fits what
actually happened in the clip — don't force one that doesn't match.

| Formula | Fits when the clip has... | Example |
| --- | --- | --- |
| **Confession** | The streamer admitting a mistake/reaction on themselves | «Я час не мог найти босса, который стоял рядом» |
| **Number shock** | A concrete surprising number | «Три попытки. Ноль урона» |
| **Inversion** | The opposite of what you'd expect | «Самый лёгкий босс оказался самым долгим» |
| **Stakes-first** | Something on the line right away | «Ещё одна смерть — и стрим закрыт» |
| **In medias res** | A sudden peak moment, no setup | «Пол-секунды до вайпа» |
| **Question** | A surprising answer to a simple question | «Сколько попыток на этот прыжок? Сорок» |
| **Receipt** (visual) | A literal screen/chat/counter moment | «Вот что было в чате в этот момент» |
| **Quote** | A literal line said in chat/voice | «Чат написал: 'ты издеваешься'. Я тоже так подумал» |
| **POV** | A relatable native-format framing | «POV: ты понял прикол на пять секунд позже всех» |
| **Hot take** | An unpopular opinion the streamer states | «Этот босс — не сложный, а сломанный» |
| **The smallest thing** | A tiny detail causing a big outcome | «Один пиксель. Весь забег заново» |

Not a hook: "сегодня покажу как...", "в этом видео...", any sentence over
7 words / 3 seconds of speech. Read it aloud at talking speed — if it drags,
cut it.

### Приёмы из разбора топовых RU-геймлинг-шортсов (2026-07)

Из сравнения выборки ~65 топовых нарезок ниши против слабых
(work/refs/_analysis/, гитигнор):

- **Один КАПС-акцент в названии** — вопрос или утверждение-интрига с одним
  словом капсом: «Игра ПЕРЕОЦЕНЕНА?», «Первая встреча с НИМ», «Силксонг
  СЛОЖНЕЕ оригинала?». Ровно одно слово, то, на котором интрига; капсить
  два+ слова = кричащий спам. Совместимо с формулами выше (Question,
  Inversion, Hot take) — это оформление, не отдельная формула.
- **Хештеги: максимум 2 в названии** (игра + один нишевый), остальное — в
  описание. 4-5 хештегов в тайтле у слабых клипов выборки коррелируют с
  околонулевыми просмотрами; у топов в тайтле 0–2.
- **Бренд-названия из одного мем-слова не копировать** («ЖКХ», «КРУЖОУ» у
  крупных нарезчиков) — они работают только на устоявшейся фанбазе; для
  малого канала название обязано продавать момент само.
- **Никогда не спойлерить панчлайн** — хук (и тайтл, и плашка Phase 8,
  которая из него берётся) продаёт сетап, ставку или вопрос, но не
  развязку. Тест: если после прочтения хука досматривать незачем — хук
  раскрыл панч, переписать. «КОМНАТА НА 5 500 000 РУБ» (ставка, исход
  неизвестен) — правильно; «Я СЛУЧАЙНО УДАЛИЛ СЕЙВ» на клипе, где панч и
  есть удаление сейва — спойлер. Особенно критично для шутко-клипов и
  standalone-мемов: там панч = весь клип; хук для них — контекст или
  первая половина сетапа, никогда цитата панча. Формулы выше это уже
  соблюдают (Question/Stakes-first/Inversion создают долг любопытства) —
  правило нужно при соблазне вынести самую смешную фразу клипа в тайтл.
  Приём, как это писать: **хук формулируется из точки во времени ДО
  панча, глазами стримера в моменте**, а не как описание клипа снаружи.
  Клип «промазал всё, оказалось наушники не той стороной»: хук «Где
  враг?» (вопрос, который стример реально задавал себе в моменте — зритель
  проживает путаницу и получает развязку вместе с ним) правильный; хук
  «Наушники не той стороной?» — уже взгляд из после, ответ зашит в вопрос.
  Практически: возьми фразу/вопрос/эмоцию из ПЕРВОЙ половины клипа, не из
  последней.

### Приёмы загрузки Shorts (разбор Мартина Радина, 2026-07)

Из разбора «Как правильно загружать YouTube Shorts в 2025»
(youtube.com/watch?v=iolgNqXF7Fc) — то, что ложится на наш пайплайн
метадаты и автопаблиша:

- **Первые два слова тайтла = самые сильные ключевые слова момента.**
  В ленте Shorts зритель замечает только начало названия — релевантные
  первые два слова решают, продолжит ли он смотреть. Совместимо с
  хук-формулами выше: подбирай формулу так, чтобы ключевики оказались в
  начале («Силксонг СЛОЖНЕЕ оригинала?», не «А правда ли, что Силксонг…»).
- **Описание никогда не пустое.** Зритель его не читает — алгоритм читает:
  Shorts с проработанным описанием выигрывают поисковую выдачу. Структура:
  1. одно короткое предложение о содержании клипа (по register-ru.md);
  2. 4-5 ключевых слов, вплетённых в связный текст (не списком через
     запятую — YouTube трактует голый список как спам);
  3. 4-5 хештегов в конце (в дополнение к 0-2 из тайтла);
  4. **блок ссылок последней строкой — всегда, на всех платформах**:
     `Телеграм: t.me/zhorekp · Твич: twitch.tv/ZhorikP`. Ссылки кликабельны,
     связывают аудиторию между площадками и уводят на основной канал/стрим.
     Ставится в каждое описание (YouTube/TikTok/Instagram) — не опускать.
  Ключевые слова брать из поисковых подсказок YouTube по теме клипа
  (что показывает автодополнение при вводе темы) — это готовые реальные
  запросы.
- **Теги (поле tags, не хештеги): тема клипа + общие по нише + название
  канала.** Тег с именем канала связывает шортсы между собой в
  рекомендациях. Лимит суммарной длины 500 символов проверяет
  `publish_queue.py`.
- Категория Gaming проставляется автоматически при аплоаде
  (`publish_queue.py`, categoryId 20) — в метадате её указывать не нужно.

## Few-shot по стилю канала

Когда доступен `work/_profile/style_profile.json` с непустым `naming_examples`
(реальные прошлые названия канала, ранжированные по перформансу) — опирайся
на них при черновике: подражай их регистру, длине и словам, а не выдумывай
общее, обезличенное название с нуля. Это лишь линза, применяемая когда профиль есть, а
не обязательное требование (fail-open: нет профиля/пустой список —
пиши ровно как раньше, без ошибки и без упоминания пользователю).

Пример (только вымышленные названия для иллюстрации):
```
1. "Boss Rage Quit Moment" (signal: 62.0)
2. "Clutch 1v5 Ace" (signal: 30.0)
```
Новый черновик должен звучать в этом же духе (короткие, конкретные,
геймплейные), но не быть одним из этих названий.

Не копировать пример название дословно, и не пересказывать примеры прозой
вида «стиль канала — короткий и дерзкий» — оба варианта убивают смысл
конкретных few-shot примеров (подражание тону, а не пересказ или переиспользование).

## Без мата в тексте метадаты

`youtube.title`, `youtube.description`, `tiktok`/`instagram` caption — никогда
не содержат мат/нецензурную лексику в самом тексте, даже когда клип целиком
про матерный панчлайн и даже когда `config.content.allow_mature` включён и
клип помечен `⚠️ 18+`. Это применяется к драфту метадаты отдельно от аудио
клипа — сам ролик по-прежнему может звучать матом (`config.profanity.enabled`
глушит его отдельно), 18+-варнинг в описании по-прежнему ставится когда
применимо (см. SKILL.md step 5). Просто заголовок/описание/капшн не
пересказывают и не цитируют мат текстом — перефразируй вокруг него, не режь
панч в ноль: «Два члена экипажа» вместо «Два члена экипажа, блять»,
«Своих же убил» вместо «Своих же убил, нахуй». Канал: 2026-07-17.

## Anti-AI-tone filter

Run the drafted title/description/caption through this before writing the
metadata JSON. Each match gets cut or replaced — never left in.

**Cut outright (AI markers):** «давайте разберёмся», «итак» (opening a
sentence), «погружаемся в…», «представьте», «в этом видео я расскажу/покажу»,
«сегодня поговорим о…», «хочу поделиться», «и знаете что?», «а теперь самое
интересное», «на самом деле» (as a filler opener), «по сути».

**Cut/replace (канцелярит — office-memo Russian, not spoken Russian):**
«является» → a real verb or drop it; «представляет собой» → «это»;
«осуществляет»/«производит» → «делает»/«считает»/«отправляет»; «данный» →
«этот»; «в рамках» → «когда»/«для»; «в связи с» → «из-за».

**Cut/replace (English calques):** «это о том, как…» → «X сломался»/«я
сделал X»; «имеет смысл» (standalone) → drop or «понятно почему»; «в конце
дня» → «в итоге»/drop; «таким образом» (as a linker) → a period and a new
sentence.

**Cut/replace (marketing tone — understatement beats hype):** «крутой»,
«топовый», «потрясающе», «невероятно», «киллер-фича», «лайфхак» (without
irony), «инсайт» (without irony), «огонь»/«бомба» (without self-irony),
«фишка», «вот это поворот» (outside irony). Replace with the specific thing
that makes it impressive — a number, a name, a comparison — not an adjective.

**Generic metaphors — banned unless it's literally in the source** (a
name the streamer/chat actually used): «иголка в стоге сена», «слон в
посудной лавке», «снежный ком», «эффект бабочки», «верхушка айсберга».

**Hedging/filler — cut:** «вроде бы», «в принципе», «достаточно»/«весьма»/
«довольно» (without a number after), «по факту» (as hedging), «в общем-то».

**Speak test:** read the first sentence of the caption aloud. Does it sound
like a message to a friend in chat, or a corporate blog post? If it's the
latter, rewrite from a different hook.
