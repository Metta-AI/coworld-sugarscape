FROM python:3.13.5-slim

RUN pip install --no-cache-dir websockets==17.0.1
WORKDIR /app
COPY src /app/src
COPY targets /app/targets

ENV PYTHONHASHSEED=0
ENV PYTHONPATH=/app/src
CMD ["python", "-m", "coworld.server"]
