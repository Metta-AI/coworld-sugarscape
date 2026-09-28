FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive STACK_ROOT=/opt/thaler-stack
RUN apt-get update && apt-get install -y --no-install-recommends haskell-stack git curl ca-certificates gcc libc6-dev make libgmp-dev libtinfo5 freeglut3-dev python3 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY tools/setup_thaler_research.py /app/tools/setup_thaler_research.py
COPY src/coworld/research_sources/thaler_2019 /app/src/coworld/research_sources/thaler_2019
RUN --mount=type=cache,id=sugarscape-thaler-ghc843,target=/opt/thaler-stack python3 tools/setup_thaler_research.py /opt/thaler
