# ARCHIVED: Sugarscape v1 is archival-only; do not extend or release this code.
FROM debian:bookworm-slim AS build

RUN apt-get update && \
  apt-get install -y --no-install-recommends \
    build-essential ca-certificates curl git && \
  rm -rf /var/lib/apt/lists/*

RUN if [ "$(dpkg --print-architecture)" = "amd64" ]; then \
    curl -fsSL -o /usr/local/bin/nimby \
      https://github.com/treeform/nimby/releases/download/0.1.26/nimby-Linux-X64; \
  elif [ "$(dpkg --print-architecture)" = "arm64" ]; then \
    curl -fsSL -o /usr/local/bin/nimby \
      https://github.com/treeform/nimby/releases/download/0.1.26/nimby-Linux-ARM64; \
  else \
    echo "unsupported architecture" && exit 1; \
  fi && \
  chmod +x /usr/local/bin/nimby && \
  nimby use 2.2.6

ENV PATH="/root/.nimby/nim/bin:$PATH"
WORKDIR /workspace/sugarscape
COPY nimby.lock .
RUN nimby --global sync nimby.lock

COPY . .
RUN nim c -d:release --opt:speed --stackTrace:on \
  --nimcache:/tmp/sugarscape-nimcache \
  --out:/bin/sugarscape_coworld src/sugarscape_coworld.nim

FROM debian:bookworm-slim
RUN apt-get update && \
  apt-get install -y --no-install-recommends ca-certificates libcurl4 && \
  rm -rf /var/lib/apt/lists/*
COPY --from=build /bin/sugarscape_coworld /bin/sugarscape_coworld
CMD ["/bin/sugarscape_coworld"]
