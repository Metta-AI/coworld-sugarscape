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

FROM ubuntu:22.04 AS thaler
ENV DEBIAN_FRONTEND=noninteractive STACK_ROOT=/opt/thaler-stack
RUN apt-get update && apt-get install -y --no-install-recommends haskell-stack git curl ca-certificates gcc libc6-dev make libgmp-dev libtinfo5 freeglut3-dev python3 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY tools/setup_thaler_research.py /app/tools/setup_thaler_research.py
COPY --from=sources /app/src/coworld/research_sources/thaler_2019 /app/src/coworld/research_sources/thaler_2019
RUN --mount=type=cache,id=sugarscape-thaler-ghc843,target=/opt/thaler-stack python3 tools/setup_thaler_research.py /opt/thaler
FROM julia:1.11.3-bookworm AS quera
ENV JULIA_DEPOT_PATH=/opt/julia-depot JULIA_NUM_THREADS=1 JULIA_NUM_PRECOMPILE_TASKS=1 JULIA_PKG_PRECOMPILE_AUTO=0 JULIA_CPU_TARGET=generic OPENBLAS_NUM_THREADS=1
WORKDIR /app
COPY --from=sources /app/src/coworld/research_sources/quera_2025 /app/src/coworld/research_sources/quera_2025
RUN julia --startup-file=no --project=/app/src/coworld/research_sources/quera_2025 -e 'using SHA; p="/app/src/coworld/research_sources/quera_2025/Manifest.toml"; h=bytes2hex(sha256(read(p))); @assert h=="3b1cdef37a183be5822a4e3032fa3125ad3dee70ec231c387791c036bdbd2f81"; using Pkg; Pkg.instantiate(); using DiffABM, Images; @assert bytes2hex(sha256(read(p)))==h'

FROM mysql:5.7@sha256:4bc6bc963e6d8443453676cae56536f4b8156d78bae03c0145cbe47c2aad73bb AS lima_database
USER root
RUN mkdir -p /opt/lima/mysql/bin /opt/lima/mysql/lib \
    && cp /usr/sbin/mysqld /opt/lima/mysql/bin/ \
    && ldd /usr/sbin/mysqld | awk '{for(i=1;i<=NF;i++) if ($i ~ /^\//) print $i}' | xargs -I '{}' cp -L '{}' /opt/lima/mysql/lib/ \
    && cp -a /usr/share/mysql /opt/lima/mysql/share

FROM gradle:7.4.2-jdk18@sha256:d0d756611201a1c54c0c31b28e28f6d083bdfacd656f9d1fe418264a0d258383 AS lima_jacamo
USER root
RUN curl -fL 'https://github.com/AdoptOpenJDK/openjdk15-binaries/releases/download/jdk-15.0.2%2B7/OpenJDK15U-jdk_x64_linux_hotspot_15.0.2_7.tar.gz' -o /tmp/java15.tgz \
    && echo '94f20ca8ea97773571492e622563883b8869438a015d02df6028180dd9acc24d  /tmp/java15.tgz' | sha256sum -c - \
    && mkdir /opt/java15 && tar xzf /tmp/java15.tgz --strip-components=1 -C /opt/java15
ENV JAVA_HOME=/opt/java15
COPY --from=sources /app/src/coworld/research_sources/lima_2024/original/shared_volume/jacamo/jacamo_model /opt/lima/jacamo_model
COPY tools/setup_lima_jacamo.gradle /tmp/setup.gradle
WORKDIR /opt/lima/jacamo_model
RUN --mount=type=cache,id=sugarscape-lima-gradle742,target=/home/gradle/.gradle \
    gradle --no-daemon --no-watch-fs --console=plain -I /tmp/setup.gradle dependencies --configuration compileClasspath \
    && \
    gradle --no-daemon --no-watch-fs --console=plain -I /tmp/setup.gradle \
    -Dorg.gradle.java.installations.paths=/opt/java15 -Dorg.gradle.java.installations.auto-download=false \
    classes coworldRuntime

FROM eclipse-temurin:8-jdk-jammy@sha256:44ab6db1a674bf1a4af11dd208c92130d61b78d34b3efffc566926c808c3c1d3 AS lima_netlogo
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && curl -fL -A coworld-sugarscape/1.0 https://downloads.netlogo.org/6.0.4/NetLogo-6.0.4-64.tgz -o /tmp/netlogo.tgz \
    && echo '0dcd9df4dfb218826a74f9df42163fa588908a1dfe58864106936f8dfb76acec  /tmp/netlogo.tgz' | sha256sum -c - \
    && mkdir -p /opt/lima/netlogo && tar xzf /tmp/netlogo.tgz --strip-components=1 -C /opt/lima/netlogo

FROM python:3.11.14-slim-bookworm AS lima
RUN pip install --no-cache-dir pydantic==2.12.3 flask==3.1.2 mysql-connector-python==9.5.0 requests==2.32.5
COPY --from=lima_database /opt/lima/mysql /opt/lima/mysql
COPY --from=lima_jacamo /opt/java15 /opt/lima/java15
COPY --from=lima_jacamo /opt/lima/jacamo_model/coworld-runtime /opt/lima/jacamo
COPY --from=lima_netlogo /opt/java/openjdk /opt/lima/java8
COPY --from=lima_netlogo /opt/lima/netlogo /opt/lima/netlogo
COPY --from=sources /app/src/coworld/research_sources/lima_2024 /opt/lima/source
COPY src/coworld/lima_runner.py src/coworld/lima_api.py /opt/lima/
COPY tools/qualify_lima_runtime.py /tmp/qualify_lima_runtime.py
RUN python /tmp/qualify_lima_runtime.py
ENV COWORLD_LIMA=/opt/lima PYTHONUNBUFFERED=1

FROM python:3.13.5-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends libfreetype6 fontconfig \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir websockets==17.0.1 pydantic==2.12.3 jsonschema==4.25.1
COPY --from=research /usr/local /opt/research-python
COPY --from=dogan /usr/local /opt/dogan-python
COPY --from=java /opt/java/openjdk /opt/java/openjdk
COPY --from=netlogo /app/build/research-runtimes /opt/research-runtimes
COPY --from=thaler /opt/thaler/bin /opt/thaler/bin
COPY --from=thaler /opt/thaler/lib /opt/thaler/lib
COPY --from=thaler /opt/thaler/licenses /opt/thaler/licenses
COPY --from=thaler /opt/thaler/qualification.json /opt/thaler/qualification.json
COPY --from=quera /usr/local/julia /usr/local/julia
COPY --from=quera /opt/julia-depot /opt/julia-depot
COPY --from=lima /opt/lima /opt/lima
COPY --from=lima /usr/local /opt/lima-python
WORKDIR /app
COPY src /app/src
COPY --from=sources /app/src/coworld/research_sources /app/src/coworld/research_sources
COPY targets /app/targets
COPY replay-viewer/index.html /app/replay-viewer/index.html
COPY players/baseline /app/players/baseline
COPY tools/research_experiments.py /app/tools/research_experiments.py
COPY coworld_manifest.json /app/coworld_manifest.json

ENV COWORLD_LIMA=/opt/lima
ENV COWORLD_LIMA_PYTHON_PREFIX=/opt/lima-python
ENV COWORLD_THALER=/opt/thaler
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
