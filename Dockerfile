FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 GOLD_HOST=0.0.0.0
WORKDIR /app
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt
RUN groupadd --gid 10001 gold && useradd --uid 10001 --gid gold --no-create-home gold && install -d -m 700 -o gold -g gold /app/data
COPY gold gold
COPY fixtures fixtures
COPY scripts scripts
COPY tests tests
USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "gold", "serve"]
