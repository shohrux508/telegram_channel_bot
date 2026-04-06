# ── Base Image ───────────────────────────────────────────────────────────
FROM python:3.12-slim as builder

# ── Environment ──────────────────────────────────────────────────────────
# Отключаем создание .pyc и включаем немедленный вывод логов (stdout/stderr)
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# ── Dependencies ─────────────────────────────────────────────────────────
WORKDIR /app

# Установка системных зависимостей для сборки некоторых пакетов (если нужно)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Копируем requirements.txt и устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Application ──────────────────────────────────────────────────────────
# Копируем весь проект в контейнер
COPY . .

# Проверяем наличие всех модулей (опциональный этап)
RUN python -c "import app; print('App modules loaded!')"

# ── Runtime ──────────────────────────────────────────────────────────────
# Railway использует переменную PORT, бот её подхватит (мы настроили config.py)
EXPOSE 8000

# Главная точка входа — запуск обоих компонентов (Bot + API) через main.py
CMD ["python", "main.py"]
