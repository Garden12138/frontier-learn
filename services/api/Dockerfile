FROM python:3.12-slim
WORKDIR /srv
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv==0.9.5 && uv sync --frozen --no-dev --no-install-project
COPY app ./app
COPY alembic.ini ./
RUN groupadd --system frontier && useradd --system --gid frontier frontier
USER frontier
EXPOSE 8000
CMD [".venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
