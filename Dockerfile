FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HF_HOME=/root/.cache/huggingface
ENV HF_HUB_OFFLINE=1
ENV TRANSFORMERS_OFFLINE=1
ENV HF_HUB_DISABLE_TELEMETRY=1

WORKDIR /app

COPY requirements.txt .
COPY deployment/constraints-py312.txt deployment/constraints-py312.txt

# Keep the working environment's versions; CPU wheels avoid unused CUDA downloads.
RUN pip install --no-cache-dir torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt -c deployment/constraints-py312.txt \
    && pip check

# MySQL 8 caching_sha2_password authentication, without changing PyMySQL's version.
RUN pip install --no-cache-dir "PyMySQL[rsa]==1.2.3" -c deployment/constraints-py312.txt \
    && pip check

COPY . .

EXPOSE 8000

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
