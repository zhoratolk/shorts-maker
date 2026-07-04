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
