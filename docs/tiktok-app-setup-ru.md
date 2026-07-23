# Настройка TikTok-приложения — гайд

Разовая настройка, чтобы `scripts/tiktok_publish.py` мог сам заливать клипы в TikTok. Делается один раз на developers.tiktok.com под твоим TikTok-аккаунтом — за тебя этот шаг никто не сделает.

## 1. Создать приложение

1. Зайди на [developers.tiktok.com](https://developers.tiktok.com/), создай приложение (My apps → Create app).
2. На вкладке **App details** заполни обязательные поля: иконка (любая квадратная картинка), Category (например Entertainment), Description (пара слов, что делает).
3. **Terms of Service URL** / **Privacy Policy URL** / **Web/Desktop URL** — впиши:
   - `https://zhoratolk.github.io/shorts-maker/tiktok-app/terms-of-service.html`
   - `https://zhoratolk.github.io/shorts-maker/tiktok-app/privacy-policy.html`
   - `https://zhoratolk.github.io/shorts-maker/tiktok-app/`

   (уже сделаны и захостены, ничего создавать не надо). Platforms → **Web**.
4. Под каждым URL нажми **Verify URL properties** → тип **URL prefix** (не Domain — доменом github.io мы не владеем, DNS туда не добавить) → впиши `https://zhoratolk.github.io/shorts-maker/tiktok-app/` → **Verify**. Он даст файл-подпись на скачивание — скинь мне его содержимое, я положу его в репозиторий и запушу, дальше жми Verify в портале.
5. Save.

## 2. Продукты

В левом меню → **Products**:

1. **Login Kit** → Add. Открой его настройки → **Redirect URI** → вкладка **Web** → впиши:
   ```
   https://zhoratolk.github.io/shorts-maker/tiktok-app/oauth-callback.html
   ```
   (тоже уже сделана и захостена). **Важно**: TikTok не принимает `127.0.0.1`/localhost вообще, только реальный подтверждённый домен — это не баг, так у них устроено.
2. **Content Posting API** → теперь должна разблокироваться → Add.
   - **Direct Post** — оставь включённым (по умолчанию так и есть).
   - **Verify domains / pull_by_url** — пропускай, это для другого способа заливки (TikTok сам скачивает видео по ссылке), мы грузим байты напрямую (`push_by_file`), это уже работает без доп. настройки.
3. Done.

## 3. Scopes

Левое меню → **Scopes** → включить ровно два: `video.publish` и `video.upload`. `user.info.basic` появится сам из-за Login Kit — это нормально, не относится к заливке видео, трогать не надо.

## 4. Ключи

Вкладка **App details** → **Credentials** → глазик у **Client key** и **Client secret** → скопируй оба → пришли сюда в чат. Я:
- запишу их в `tiktok_client_key.json` (в репозитории, но в гитигноре — наружу не уйдёт),
- прогоню одноразовый вход (откроется браузер под твоим TikTok-аккаунтом → залогинишься → тебя перекинет на страницу `oauth-callback.html`, она покажет код авторизации → скопируешь его → вставишь в терминал, когда попрошу),
- включу `tiktok_enabled` в конфиге,
- заведу автозапуск (как для YouTube) и пришлю тестовую заливку.

## 5. Пока без публичного ревью

**App review** (с демо-видео и текстом на 1000 символов) — не обязателен для старта. Пока его не пройдёшь, видео будут заливаться, но приватно (`SELF_ONLY`) — API вернёт успех, но наружу ничего не уйдёт. Это нормально для проверки, что всё технически работает. Ревью подаём отдельно, когда решишь, что пора идти в паблик — понадобится записать демо-видео реального рабочего флоу.

---

Где мы сейчас: жду от тебя файл-подпись для домена (шаг 1.4) и/или ключи (шаг 4) — что готово, то и присылай.
