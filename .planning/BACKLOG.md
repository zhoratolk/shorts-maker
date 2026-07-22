# Backlog

## n8n оркестрация пайплайна

Обвязать n8n вокруг существующего инлайн-пайплайна (Phase 1-9):
- cron-нода для TikTok очереди (2 клипа/день), Telegram-алерт при провале загрузки
- расписанный fetch YouTube retention analytics (сейчас live token.json ре-консент) → автозапись в `work/_analytics/retention_insights.json`
- webhook/cron триггер вместо ручного запуска скриптов
- retry/backoff нода для publish_queue при 403/квоте YouTube API (сейчас publish_queue сам не ретраит)
- параллельная публикация в TikTok/Instagram API из уже сгенерённых `metadata_data/*.json`, не только YouTube-часть
- алерт-нода: мониторить candidates.json на пустой visual-происхождение (визуал-кандидаты реально не ищутся сейчас — см. инцидент 2026-07-22) и слать алерт вместо надежды что Claude сам заметит
- еженедельная нода: тянуть retention_insights.json и автоматически подкручивать clip.min_seconds/hype_phrases вместо ручной правки конфига
- дедуп/сейфти-гейт нода перед авто-паблишем: проверка что video_id ещё не в queue.json, до отправки в API (защита от дублей при ретраях воркфлоу)

Не блокирующее, добавить когда TikTok-регистрация и OAuth-рутина устоятся.
