FROM node:22-slim AS frontend

WORKDIR /frontend

COPY frontend-react/package*.json ./
RUN npm ci

COPY frontend-react ./
RUN npm run build


FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src
ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ENV PIP_TRUSTED_HOST=mirrors.aliyun.com
ENV PIP_DEFAULT_TIMEOUT=120

COPY pyproject.toml README.md /app/
COPY src /app/src
COPY configs /app/configs
COPY frontend /app/frontend
COPY --from=frontend /frontend/dist /app/frontend-react/dist

RUN pip install --no-cache-dir -e .

EXPOSE 8000

CMD ["uvicorn", "esg_selective_mineru.api:app", "--host", "0.0.0.0", "--port", "8000"]
