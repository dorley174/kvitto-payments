# API платежей Квитто

Тестовое задание Junior Python Developer: API для оплаты курсов онлайн-школы. Сервис создаёт платежи, применяет промокод, рассчитывает рассрочку и обрабатывает подписанные уведомления банка.

Стек: Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.x, SQLite, PostgreSQL через psycopg, Alembic, pytest, httpx, Ruff и Docker Compose. Версии указаны в `pyproject.toml`; полные списки зависимостей с версиями и хешами находятся в `requirements.txt` и `requirements-dev.txt`.

Все суммы в API, базе и вычислениях — **целые копейки**.

| Тариф | Название | Цена, коп. |
|---|---|---:|
| `basic` | Basic | 990000 |
| `standard` | Standard | 1990000 |
| `premium` | Premium | 2990000 |

Тарифы добавляются при старте приложения. Повторный запуск сохраняет существующие тарифы и платежи.

## Локальный запуск с нуля

Нужны Python 3.11 или новее и `pip`. Для примеров запросов нужен `curl`. Команды ниже выполняются из корня проекта в Bash на Linux/macOS либо WSL.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements-dev.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

Копируйте `.env.example` только при первой настройке: существующий `.env` содержит ваши настройки. В Windows PowerShell виртуальное окружение активируется командой `.venv\Scripts\Activate.ps1`.

Миграции создают базу и таблицы; каталог `data` при необходимости создаётся автоматически. Сервер доступен по адресу [http://127.0.0.1:8000](http://127.0.0.1:8000), интерактивная документация — [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs). Для остановки нажмите `Ctrl+C`.

При следующих запусках активируйте окружение, выполните `alembic upgrade head`, затем запустите `uvicorn`. Автоматическое создание таблиц через `create_all()` не используется.

### Конфигурация

Настройки читаются из `.env` в текущем каталоге и переменных окружения. Переменные окружения имеют приоритет.

| Переменная | Назначение |
|---|---|
| `DATABASE_URL` | По умолчанию `sqlite:///./data/payments.db`; относительный путь отсчитывается от рабочего каталога. |
| `WEBHOOK_SECRET` | Обязательный непустой секрет для HMAC-SHA256. |

Значение секрета в `.env.example` предназначено только для локальной разработки. Новый секрет можно получить командой `python -c "import secrets; print(secrets.token_hex(32))"` и записать в `.env`. Без непустого `WEBHOOK_SECRET` приложение и команды миграций отказываются запускаться. Проверка подписи всегда включена.

Для PostgreSQL укажите URL существующей доступной базы в `.env`, например `postgresql+psycopg://kvitto:local-password@localhost:5432/kvitto`, и повторите `alembic upgrade head`. Драйвер уже включён в зависимости. В контейнере имя сервера PostgreSQL должно быть доступно из Docker; `localhost` означает сам контейнер.

### Чистая база без изменения текущих данных

Чтобы проверить развёртывание заново, выберите новое имя файла и укажите один и тот же URL при миграции и запуске:

```bash
DATABASE_URL=sqlite:///./data/clean-check.db alembic upgrade head
DATABASE_URL=sqlite:///./data/clean-check.db uvicorn app.main:app --port 8001
```

Этот пример создаёт отдельную базу и открывает сервер на порту `8001`.

## Тесты, качество кода и миграции

В активированном окружении:

```bash
pytest
ruff check .
ruff format --check .
alembic current
alembic check
```

Тесты используют отдельные временные SQLite-базы и не изменяют `data/payments.db`. Они проверяют суммы, все сроки рассрочки, валидацию, подписи, фильтры, миграции, повторные и конкурентные запросы, переходы статусов и сохранность данных при ошибках.

Зафиксированная версия Starlette предупреждает, что использование HTTPX в TestClient устарело, и рекомендует HTTPX2. Текущий набор из 197 тестов проходит с HTTPX; предупреждение не подавляется.

GitHub Actions настроен на `push` и `pull_request`: Python 3.11/3.12, установка зависимостей, оба запуска Ruff, миграция чистой базы, `alembic check` и `pytest`. Настройки для CI задаются в workflow; локальный `.env` не требуется.

## Docker Compose

Нужны Docker и плагин Docker Compose v2. Подготовьте `.env` из `.env.example`, если его ещё нет, затем выполните:

```bash
docker compose up --build
```

API доступен на [http://127.0.0.1:8000](http://127.0.0.1:8000). Контейнер устанавливает зависимости с проверкой хешей, выполняет миграции перед запуском Uvicorn и работает от непривилегированного пользователя. Проверка состояния обращается к `/tariffs`.

С настройками по умолчанию SQLite хранится в именованном томе `payments_data`, смонтированном в `/app/data`. Локальная база и база контейнера независимы. Чтобы данные SQLite сохранялись, оставляйте путь базы внутри `/app/data`, например значение из `.env.example`.

```bash
docker compose ps
docker compose logs api
docker compose restart api
docker compose down
```

Перезапуск, пересоздание контейнера и обычный `docker compose down` сохраняют том. Флаг `--volumes` у команды `down` удаляет его вместе с данными.

## Контракт API

| Метод и путь | Результат |
|---|---|
| `GET /tariffs` | `200`, список объектов `id`, `title`, `price`. |
| `POST /payments` | `201`, новый платёж; `200`, существующий платёж при повторе `Idempotency-Key`. |
| `GET /payments/{id}` | `200`, платёж; `404`, если его нет. |
| `GET /payments` | `200`, список платежей; необязательные фильтры `email` и `status` работают отдельно и совместно. |
| `POST /webhooks/bank` | `200 {"result":"ok"}`; `401` при неверной подписи; `404` для отсутствующего платежа; `409 {"error":"invalid_transition"}` при запрещённом переходе. |

Ошибки валидации возвращают стандартный ответ FastAPI с кодом `422`.

### Создание и чтение платежей

Тело `POST /payments`: обязательные `tariff_id`, `email`, `method`; необязательный `promo_code`; для `method="installment"` обязательный `installment_months` — целое число `3`, `6` или `12`. Строка `"3"`, дробное число и логическое значение не подходят. Для `card` и `sbp` срок должен отсутствовать или быть `null`.

При создании нового платежа неизвестный тариф возвращает `404`. Промокод `KVITTO10` даёт скидку 10% без учёта регистра; неизвестный, в том числе пустой, код возвращает `422`. Отсутствующий код или `null` означает полную стоимость. Скидка считается от цены тарифа и возвращается в `discount`; `amount` — сумма после скидки. Лишние поля тела запроса отклоняются с `422`.

Ответ содержит только `id`, `status`, `tariff_id`, `amount`, `discount`, `method`, `installment_months`, `schedule`, `email`, `created_at`. Для `card` и `sbp` значение `schedule` равно `null`. Для рассрочки лишние копейки распределяются по первым платежам; сумма графика точно равна `amount`. `created_at` содержит время в UTC.

`Idempotency-Key` — необязательная непустая строка длиной до 255 символов, состоящая не только из пробелов; регистр значим. Первый запрос с ключом возвращает `201`, повторный — тот же платёж с `200`. Даже при другом **валидном по схеме** теле запроса ключ возвращает первоначальный платёж без пересчёта и изменения параметров. Ответ отражает его текущий статус. Валидация тела выполняется до поиска ключа, поэтому некорректное тело возвращает `422`. Проверка существования нового тарифа выполняется только при создании нового платежа. Без ключа каждый запрос создаёт отдельный платёж.

Список платежей отсортирован по `created_at`, затем `id`, по возрастанию. Фильтр `email` сравнивает точное нормализованное значение: Pydantic проверяет адрес и нормализует домен. Фильтр `status` принимает `pending`, `succeeded`, `failed`, `refunded`. Пагинации нет.

### Уведомления банка

Тело: `payment_id` и `status`. Допустимы только `pending → succeeded`, `pending → failed`, `succeeded → refunded`. Остальные переходы, включая повтор уже выполненного перехода, дают `409`; состояние не меняется.

`X-Signature` содержит 64 шестнадцатеричных символа HMAC-SHA256 от **исходных байтов тела запроса**; регистр hex-символов не важен. Подпись проверяется через `hmac.compare_digest` до разбора JSON. Отсутствующая или неверная подпись даёт `401`. Некорректный JSON с верной подписью даёт `422`; корректно подписанный запрос к отсутствующему платежу — `404`.

## Примеры запросов

Оставьте сервер работающим. Во втором терминале перейдите в корень проекта и активируйте то же окружение. Для примеров используется порт `8000` и каталог `data` для временных JSON-файлов.

### Тарифы и создание рассрочки

```bash
source .venv/bin/activate
mkdir -p data
curl -i http://127.0.0.1:8000/tariffs

cat > data/payment-request.json <<'JSON'
{"tariff_id":"standard","email":"student@example.com","method":"installment","installment_months":3}
JSON

curl --silent --show-error --fail-with-body \
  --output data/payment.json --write-out 'HTTP %{http_code}\n' \
  --request POST http://127.0.0.1:8000/payments \
  --header 'Content-Type: application/json' \
  --header 'Idempotency-Key: example-installment-001' \
  --data-binary @data/payment-request.json
python -m json.tool data/payment.json
```

При первом выполнении получится `HTTP 201` и ответ такого вида; идентификатор и время будут другими:

```json
{
  "id": "e09c941d-a453-4b82-b260-5dc2054b4017",
  "status": "pending",
  "tariff_id": "standard",
  "amount": 1990000,
  "discount": 0,
  "method": "installment",
  "installment_months": 3,
  "schedule": [663334, 663333, 663333],
  "email": "student@example.com",
  "created_at": "2026-10-19T12:00:00Z"
}
```

### Повторный запрос, чтение и фильтры

Повтор возвращает `200` и тот же `id`:

```bash
curl -i --request POST http://127.0.0.1:8000/payments \
  --header 'Content-Type: application/json' \
  --header 'Idempotency-Key: example-installment-001' \
  --data-binary @data/payment-request.json

PAYMENT_ID=$(python -c 'import json; print(json.load(open("data/payment.json"))["id"])')
curl -i "http://127.0.0.1:8000/payments/$PAYMENT_ID"

curl -i --get http://127.0.0.1:8000/payments \
  --data-urlencode 'email=student@example.com' \
  --data-urlencode 'status=pending'
```

Пример оплаты картой с промокодом: ответ содержит `discount=199000`, `amount=1791000`, `schedule=null`.

```bash
curl -i --request POST http://127.0.0.1:8000/payments \
  --header 'Content-Type: application/json' \
  --data '{"tariff_id":"standard","email":"student@example.com","method":"card","promo_code":"kViTtO10"}'
```

### Подпись и отправка webhook

Следующие команды используют переменную `PAYMENT_ID` из предыдущего примера. Сначала запишем тело в файл, затем подпишем его байты и отправим **тот же файл**. Секрет берётся из текущей конфигурации приложения; он должен совпадать с секретом запущенного сервера.

```bash
python - "$PAYMENT_ID" <<'PY'
import json
import sys
from pathlib import Path

payload = {"payment_id": sys.argv[1], "status": "succeeded"}
Path("data/webhook.json").write_text(json.dumps(payload), encoding="utf-8")
PY

SIGNATURE=$(python - <<'PY'
import hashlib
import hmac
from pathlib import Path

from app.config import Settings

secret = Settings().webhook_secret.get_secret_value().encode("utf-8")
payload = Path("data/webhook.json").read_bytes()
print(hmac.new(secret, payload, hashlib.sha256).hexdigest())
PY
)

curl -i --request POST http://127.0.0.1:8000/webhooks/bank \
  --header 'Content-Type: application/json' \
  --header "X-Signature: $SIGNATURE" \
  --data-binary @data/webhook.json
```

Первое уведомление переводит `pending` в `succeeded` и возвращает `200 {"result":"ok"}`. Повторите последнюю команду с тем же телом и подписью: получится `409` с телом:

```json
{"error": "invalid_transition"}
```

Платёж останется `succeeded`. Для возврата измените статус в файле на `refunded`, заново вычислите подпись и отправьте файл. Изменение пробелов или перевода строки в теле тоже требует новой подписи.

## Структура и решения

| Путь | Назначение |
|---|---|
| `app/main.py`, `app/config.py` | Приложение, жизненный цикл и настройки. |
| `app/database.py`, `app/models.py` | Подключение, сессии, таблицы и ограничения. |
| `app/schemas.py`, `app/services.py` | Входные/выходные схемы и бизнес-логика. |
| `app/routers/` | HTTP-маршруты тарифов, платежей и webhook. |
| `app/seed.py` | Идемпотентное создание исходных тарифов. |
| `tests/` | Проверки бизнес-логики, API, миграций и конкуренции. |
| `alembic/`, `alembic.ini` | Управление схемой базы. |
| `pyproject.toml`, `requirements*.txt` | Зависимости и настройки инструментов. |
| `Dockerfile`, `compose.yaml`, `.dockerignore` | Сборка и запуск контейнера. |
| `.github/workflows/ci.yml` | Автоматические проверки. |
| `.env.example`, `.gitignore` | Пример конфигурации и исключение локальных данных. |
| `AI_LOG.md`, `CLAUDE.md` | История использования ИИ и правила проекта. |

Идемпотентность защищена уникальным ограничением базы: при конкурентном конфликте вставки транзакция откатывается и возвращается уже созданный платёж. Статусы изменяются условным атомарным `UPDATE`, поэтому два конкурирующих запроса не могут независимо перезаписать одно исходное состояние. У каждого запроса своя сессия базы.

Рассрочка использует `divmod`: сначала равная целая часть, затем по одной копейке первым платежам. Для текущих тарифов скидка 10% целая. Если появится тариф с ценой, не кратной десяти копейкам, скидка округляется вниз до целой копейки (`price // 10`).

Docker, GitHub Actions и подключение к отдельному серверу PostgreSQL требуют проверки в соответствующем окружении. В среде подготовки проекта Docker был недоступен; фактический запуск контейнера и сохранение данных после его перезапуска здесь не проверялись.
