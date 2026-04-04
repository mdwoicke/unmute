FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# IVA source will be volume-mounted at /app/iva-source
ENV IVA_SOURCE_PATH=/app/iva-source
ENV PYTHONPATH=/app/iva-source:$PYTHONPATH

CMD ["python", "agent.py", "start"]
