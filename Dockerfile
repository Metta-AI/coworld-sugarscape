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

FROM julia:1.11.3-bookworm AS quera
ENV JULIA_DEPOT_PATH=/opt/julia-depot JULIA_NUM_THREADS=1 JULIA_NUM_PRECOMPILE_TASKS=1 JULIA_PKG_PRECOMPILE_AUTO=0 JULIA_CPU_TARGET=generic OPENBLAS_NUM_THREADS=1
WORKDIR /app
COPY --from=sources /app/src/coworld/research_sources/quera_2025 /app/src/coworld/research_sources/quera_2025
RUN julia --startup-file=no --project=/app/src/coworld/research_sources/quera_2025 -e 'using SHA; p="/app/src/coworld/research_sources/quera_2025/Manifest.toml"; h=bytes2hex(sha256(read(p))); @assert h=="3b1cdef37a183be5822a4e3032fa3125ad3dee70ec231c387791c036bdbd2f81"; using Pkg; Pkg.instantiate(); using DiffABM, Images; @assert bytes2hex(sha256(read(p)))==h'

FROM python:3.13.5-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends libfreetype6 fontconfig \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir websockets==17.0.1 pydantic==2.12.3 jsonschema==4.25.1
COPY --from=research /usr/local /opt/research-python
COPY --from=dogan /usr/local /opt/dogan-python
COPY --from=java /opt/java/openjdk /opt/java/openjdk
COPY --from=netlogo /app/build/research-runtimes /opt/research-runtimes
COPY --from=quera /usr/local/julia /usr/local/julia
COPY --from=quera /opt/julia-depot /opt/julia-depot
WORKDIR /app
COPY src /app/src
COPY --from=sources /app/src/coworld/research_sources /app/src/coworld/research_sources
COPY targets /app/targets
COPY replay-viewer/index.html /app/replay-viewer/index.html
COPY players/baseline /app/players/baseline
COPY tools/research_experiments.py /app/tools/research_experiments.py
COPY coworld_manifest.json /app/coworld_manifest.json

ENV COWORLD_JULIA=/usr/local/julia/bin/julia
ENV COWORLD_JULIA_DEPOT=/opt/julia-depot
ENV JULIA_CPU_TARGET=generic
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
