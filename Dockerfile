FROM python:3.13.5-slim-bookworm AS sources
WORKDIR /app
COPY tools/fetch_research_sources.py /app/tools/fetch_research_sources.py
COPY src/coworld/research_sources /app/src/coworld/research_sources
RUN python tools/fetch_research_sources.py

FROM python:3.11.14-slim-bookworm AS research
RUN pip install --no-cache-dir pydantic==2.12.3 jsonschema==4.25.1

FROM python:3.12.4-slim-bookworm AS dogan
RUN pip install --no-cache-dir pydantic==2.12.3 jsonschema==4.25.1 mesa==3.5.1 numpy==2.4.2 pandas==2.3.3 networkx==3.7

FROM eclipse-temurin:11-jdk-jammy AS java

FROM python:3.13.5-slim-bookworm AS netlogo
COPY --from=java /opt/java/openjdk /opt/java/openjdk
WORKDIR /app
COPY tools/setup_netlogo_research.py /app/tools/setup_netlogo_research.py
COPY --from=sources /app/src/coworld/research_sources /app/src/coworld/research_sources
RUN python tools/setup_netlogo_research.py --javac /opt/java/openjdk/bin/javac \
    && rm build/research-runtimes/*.tgz

FROM python:3.13.5-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends libfreetype6 fontconfig \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir websockets==17.0.1 pydantic==2.12.3 jsonschema==4.25.1
COPY --from=research /usr/local /opt/research-python
COPY --from=dogan /usr/local /opt/dogan-python
COPY --from=java /opt/java/openjdk /opt/java/openjdk
COPY --from=netlogo /app/build/research-runtimes /opt/research-runtimes
WORKDIR /app
COPY src /app/src
COPY --from=sources /app/src/coworld/research_sources /app/src/coworld/research_sources
COPY targets /app/targets
COPY replay-viewer/index.html /app/replay-viewer/index.html
COPY players/baseline /app/players/baseline
COPY tools/research_experiments.py /app/tools/research_experiments.py
COPY coworld_manifest.json /app/coworld_manifest.json

ENV COWORLD_JAVA=/opt/java/openjdk/bin/java
ENV COWORLD_NETLOGO_5=/opt/research-runtimes/netlogo-5.3.1
ENV COWORLD_NETLOGO_6=/opt/research-runtimes/netlogo-6.1.1
ENV COWORLD_RESEARCH_PYTHON_DOGAN=/opt/dogan-python/bin/python3.12
ENV COWORLD_RESEARCH_PREFIX_DOGAN=/opt/dogan-python
ENV COWORLD_RESEARCH_PYTHON=/opt/research-python/bin/python3.11
ENV COWORLD_RESEARCH_PREFIX=/opt/research-python
ENV PYTHONHASHSEED=0
ENV PYTHONPATH=/app/src
CMD ["python", "-m", "coworld.server"]
