FROM python:3.13.5-slim

RUN pip install --no-cache-dir websockets==17.0.1
WORKDIR /app
COPY players /app/players

ENV PYTHONHASHSEED=0
CMD ["python", "-m", "players.baseline.player"]
