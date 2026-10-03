# Транскрибатор голосовых заметок

Веб-сервис для VPS: загружаете файлы диктофона iPhone (`.m4a`, также wav/mp4/ogg и др.), сервер
конвертирует их в лёгкий mono-mp3 (ffmpeg), отправляет в [AssemblyAI](https://www.assemblyai.com/docs/pre-recorded-audio/getting-started/transcribe-an-audio-file)
и хранит результат. Определение языка и разделение по спикерам включены.

- Очередь: можно кидать несколько файлов сразу, статус каждого виден в списке
- История: оригинал `.m4a`, `.mp3`, текст — всё на сервере (`./data`), скачивание `.txt`, `.srt`, `mp3`, оригинала
- Текст прямо в интерфейсе + кнопка «Копировать», удаление записей вместе с файлами
- Вход по одному паролю; ключ AssemblyAI живёт только в `.env` на сервере
- Адаптивный UI и PWA: на iPhone — Safari → «Поделиться» → «На экран Домой»

## Запуск на VPS

```bash
cp .env.example .env
# заполните ASSEMBLYAI_API_KEY, APP_PASSWORD, SECRET_KEY
docker compose up -d --build
```

Сервис слушает порт `8000`. Для HTTPS (нужен домен, указывающий на VPS):

```bash
# в .env: DOMAIN=stt.example.com, BIND=127.0.0.1:8000, COOKIE_SECURE=true
docker compose --profile https up -d --build
```

Без HTTPS пароль и записи идут по сети открытым текстом — для интернета HTTPS обязателен.

## Настройки (`.env`)

| Переменная | Назначение |
|---|---|
| `ASSEMBLYAI_API_KEY` | ключ AssemblyAI |
| `APP_PASSWORD` | пароль входа |
| `SECRET_KEY` | подпись cookie (при смене все выходят из сессии) |
| `MAX_UPLOAD_MB` | лимит размера файла (по умолчанию 500) |
| `WORKERS` | сколько файлов обрабатывать параллельно (по умолчанию 2) |
| `SPEECH_MODELS` | модели распознавания через запятую, см. актуальную доку AssemblyAI |
| `COOKIE_SECURE` | `true` за HTTPS |

После перезапуска контейнера неоконченные записи автоматически возвращаются в очередь.

## Разработка

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt      # нужен ffmpeg в PATH
pytest
ASSEMBLYAI_API_KEY=... APP_PASSWORD=pw uvicorn app.main:app_factory --factory --reload
```
