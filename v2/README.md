# Adrobot — конструктор и редактор кампаний Keitaro

Веб-приложение для работы с рекламным трекером Keitaro через Admin API v1:

1. **Создание кампании** — по названию, гео-коду страны, ID оффера и
   справочникам домена/группы/источника создаёт в трекере кампанию с двумя
   потоками: первый принимает трафик только из указанной страны и
   редиректит на Google, второй отправляет остальных на выбранный оффер.
2. **Редактор кампании** — загружает потоки кампании из Keitaro и позволяет
   локально добавлять/удалять/возвращать офферы, закреплять доли и
   задавать проценты; изменения уходят в трекер кнопкой **Push**.

Репозиторий: https://github.com/fxzznv/tz_etolegko (проект в каталоге `v2/`).

**Стек:** FastAPI + SQLAlchemy (SQLite по умолчанию) + Alembic, фронт —
ванильный JS, отдаётся самим бэкендом.

## Требования

- Python 3.9+
- ключ Keitaro Admin API v1 (в админке: Maintenance → Users → Key for
  Admin API, либо Account → API keys)
- для демо-режима без трекера — ничего, ключ не нужен

## Запуск

```bash
cd v2
cp .env.example .env          # заполните KEITARO_URL и KEITARO_API_KEY
# или для демо без трекера: KEITARO_MOCK=1

cd backend
python3 -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# миграции БД (создают таблицы campaigns и streams)
alembic upgrade head

uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Откройте http://127.0.0.1:8000

При первом запуске таблицы также создаются автоматически
(`Base.metadata.create_all`), но для продакшена используйте Alembic.

## Конфигурация (.env в корне v2)

| Переменная | Описание |
|---|---|
| `KEITARO_URL` | адрес трекера без `/admin` и `/admin_api/v1` |
| `KEITARO_API_KEY` | ключ Admin API |
| `KEITARO_MOCK` | `1` — встроенный демо-трекер вместо реального API |
| `DATABASE_URL` | по умолчанию `sqlite:///./adrobot.db` (файл в `backend/`) |

## Как это работает

### Создание кампании

`POST /api/campaigns` создаёт в Keitaro кампанию (state=disabled), затем два
потока и включает кампанию:

- поток `regular` с фильтром `country = <код>` → `action_payload:
  https://www.google.com/`, position 1;
- поток `default` со `schema=landings` и одним оффером share=100,
  position 2.

Если Keitaro не подтвердил шаг, API возвращает ошибку с alias кампании —
по нему можно найти кампанию в трекере и проверить вручную.

### Редактор

- `POST /api/campaigns/{id}/fetch` — читает кампанию и её потоки из
  Keitaro, сохраняет в SQLite. Офферы, пропавшие из трекера, попадают в
  локальный архив (`state="removed"`). Отказывается работать при наличии
  неопубликованного черновика.
- `POST /api/streams/{id}/offers/{add|remove|restore|pin|unpin}` — правит
  черновик (`draft`) и пересчитывает доли.
- `POST /api/streams/{id}/push` — сравнивает черновик с текущим состоянием
  в Keitaro; если поток меняли снаружи — 409, иначе `PUT /streams/{id}`
  с новым списком offers.
- `POST /api/streams/{id}/cancel` — откатывает черновик к published.

Локальные поля `pin` и `share` не уходят в Keitaro — в API передаются
только `{offer_id, share, state}`.

### Алгоритм долей

После каждого изменения черновика `redistribute()` в `app/shares.py`
приводит активные офферы к сумме ровно 100%:

- офферы с `pin=True` сохраняют свою долю;
- остаток `100 − Σ(pin)` делится поровну между активными офферами без
  `pin`; остаток от деления раздаётся по одному проценту первым по `id`
  (например, 3 оффера → 33/33/34);
- `removed`-офферы в расчёте не участвуют;
- ошибки: сумма pin-долей > 100%, все активные офферы закреплены и их
  сумма ≠ 100%, активных офферов нет — возвращается 422.

Удаление последнего активного оффера блокируется той же проверкой
«нет активных офферов».

Покрыто unit-тестами (`backend/tests/test_shares.py`, pytest):
1 оффер, 3 оффера с остатком, pin + остаток, сумма pin > 100%,
все офферы закреплены, удалённые офферы, формат payload для API.

### Откат при сбое создания кампании

Если создание потоков или включение кампании падает, бэкенд вызывает
`DELETE /admin_api/v1/campaigns/{id}`. В Keitaro это **архивация**
(soft delete), а не физическое удаление: кампания пропадает из основного
списка и не может получать трафик, но остаётся в архиве
(`GET /campaigns/deleted`) и при необходимости восстанавливается через
`POST /campaigns/{id}/restore`.

Если архивация не удалась (старая версия Keitaro, таймаут) — в ответе
возвращается alias кампании для ручной проверки в трекере.

Alias кампании генерируется заново при каждой попытке (`uuid4`), поэтому
повторное создание после архивации не конфликтует со старой кампанией —
в трекере просто появится ещё одна запись с новым alias.

Форматы запросов и ответов Admin API v1 сверены с публичной реализацией
аналогичного инструмента: https://github.com/rs-an/offer-flow-manager;
код приложения написан самостоятельно.

## Структура

```
v2/
├── .env.example
└── backend/
    ├── alembic.ini
    ├── alembic/            # миграции (env.py, versions/0001_initial.py)
    ├── app/
    │   ├── main.py         # FastAPI: API + раздача фронта
    │   ├── keitaro.py      # клиент Admin API + MockKeitaro
    │   ├── models.py       # Campaign, Stream (SQLAlchemy)
    │   ├── shares.py       # доли офферов: pin/redistribute/payload
    │   ├── db.py           # engine/session
    │   └── static/         # index.html, app.js, style.css
    └── requirements.txt
```

## API (кратко)

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/api/meta` | режим работы (demo или реальный трекер) |
| GET | `/api/options` | домены, группы, источники из Keitaro |
| GET | `/api/offers?q=` | поиск офферов |
| GET | `/api/campaigns` | локальные кампании |
| GET | `/api/campaigns/{id}` | кампания с потоками |
| POST | `/api/campaigns` | создать кампанию в Keitaro |
| POST | `/api/campaigns/{id}/fetch` | загрузить потоки из Keitaro |
| POST | `/api/streams/{id}/offers/{action}` | правка черновика |
| POST | `/api/streams/{id}/push` | опубликовать черновик |
| POST | `/api/streams/{id}/cancel` | откатить черновик |

## Что проверено, а что нет

**Проверено на `KEITARO_MOCK=1`:** весь цикл — создание кампании с двумя
потоками, загрузка потоков, add/remove/restore/pin офферов, пересчёт долей,
Push/Cancel, откат при сбое (mock поддерживает DELETE кампаний).
Unit-тесты `pytest backend/tests` покрывают алгоритм долей.

**Не проверено на живом Keitaro:** ключ Admin API в тестовом задании не
был предоставлен, поэтому реальные вызовы API не выполнялись. Форматы
запросов и ответов (`POST /campaigns`, `POST /streams`, `PUT /streams/{id}`,
списки `domains`/`groups`/`traffic_sources`/`offers`, `POST
/campaigns/{id}/enable`, `DELETE /campaigns/{id}`) реализованы по
документации Admin API v1. При первом запуске с реальным ключом
рекомендуется проверить создание тестовой кампании и push одного оффера.
