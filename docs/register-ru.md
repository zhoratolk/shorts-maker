# Register check (RU) — how a real person sounds vs. AI-written

Second half of [metadata-writing-ru.md](metadata-writing-ru.md)'s anti-AI-tone
guard. Adapted from [jointime1/reels-skill](https://github.com/jointime1/reels-skill)'s
`register-ru.md` (MIT) — that skill writes build-in-public voiceover from git
commits, ours writes youtube description / tiktok / instagram captions for a
clip. The rules and structure carried over; the git-flavored examples (`Prisma
5.0 → 5.7`, `nginx.conf`, `payments-worker`) were swapped for stream/clip ones.

## Base principle

**Write it to be read like a chat message, not a corporate blog post.**

If you can picture this line as a Telegram message to a friend — keep it. If
it reads like a press release — rewrite it.

## Rules (most common mistakes first)

### 1. Short sentences

Max 12 words per sentence, 6–8 is better. Longer than that — split with a
period instead of a comma.

```
❌ Стример весь стрим пытался пройти этот момент, используя разные
   тактики, и в итоге прошёл его случайно, отвлёкшись на чат.

✅ Полчаса пытался пройти этот момент. Прошёл, когда отвлёкся на чат.
```

### 2. Active voice

```
❌ Момент был замечен чатом сразу.
✅ Чат заметил момент сразу.

❌ Комбо было выполнено с первой попытки.
✅ Выполнил комбо с первой попытки.
```

### 3. Verbs, not action-nouns

```
❌ Использование этой тактики дало преимущество.
✅ С этой тактикой стало проще.

❌ Прохождение уровня заняло сорок минут.
✅ Уровень шёл сорок минут.
```

### 4. "Я"/direct address up front is fine

Written-register rules say avoid "I" — spoken/caption register wants the
opposite.

```
❌ Была допущена ошибка в тайминге прыжка.
✅ Я промахнулся с таймингом прыжка.
```

### 5. Numbers, literally

"Много", "несколько", "довольно" — noise. Use the real number.

```
❌ Понадобилось много попыток.
✅ Понадобилось сорок попыток.

❌ Чат отреагировал бурно.
✅ За минуту в чате 300 сообщений.
```

### 6. Jargon needs a one-second gloss, not a lecture

```
❌ Это была ошибка хитбокса — несовпадение зоны коллизии с моделью.
✅ Хитбокс — зона, где реально бьёт. Тут он не совпал с моделью.
```

### 7. Concrete names over categories

```
❌ Один из боссов оказался сложнее остальных.
✅ Финальный босс третьей главы оказался сложнее остальных.

❌ Игра выдала странную ошибку.
✅ Игра выдала ошибку `0x8007045D`.
```

### 8. Cut long participles

`-щий`, `-ющий`, `-вший`, `-вшись` — almost always stiff. Replace with a
clause.

```
❌ Момент, вызвавший больше всего реакций в чате.
✅ Момент, на который чат отреагировал больше всего.
```

### 9. "Это" without a connector is fine

```
❌ Оказалось, что баг был в самой игре, что и объясняло краш.
✅ Баг был в игре. Это и было причиной краша.
```

### 10. Show emotion through action, not adjectives

```
❌ Стример был в шоке.
✅ Стример замолчал на пять секунд. Потом заорал.
```

## Test before shipping the caption

1. **Speak-test.** Read each line mentally at talking pace. Stumbled? Too
   long? Feels AI-written? Rewrite.
2. **Telegram-test.** Could this be a message to a friend in chat? If not,
   rewrite.
3. **Random-test.** Swap every noun for "штука" — does the sentence
   structure still sound like normal spoken Russian? It should.

## What NOT to rewrite

If a line already sounds like speech, leave it — don't "improve" it into
something more literary. "Стрим лёг" beats "трансляция оказалась
недоступна." Rough-but-alive beats polished-but-dead. Don't censor
profanity the streamer/chat itself didn't censor, when `config.content.allow_mature` allows it.
