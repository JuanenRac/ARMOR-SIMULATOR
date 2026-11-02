# ARMOR-SIMULATOR - image of the virtual bench (several simulated nodes delivering to a server). Built by the compose file of ARMOR-DEVOPS (profile "bench").
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /opt/armor-simulator
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --no-compile . && useradd --system --no-create-home --uid 10001 armor
COPY docker/bench.sh /usr/local/bin/armor-bench
RUN chmod 0555 /usr/local/bin/armor-bench
USER armor
ENTRYPOINT ["/usr/local/bin/armor-bench"]
