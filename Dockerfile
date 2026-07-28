FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Install Node.js for the WhatsApp bridge
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates gnupg git bubblewrap openssh-client libmagic1 tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng && \
    mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_24.x nodistro main" > /etc/apt/sources.list.d/nodesource.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends nodejs && \
    apt-get purge -y gnupg && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (cached layer). Hatch reads the custom build
# hook from hatch_build.py even for this metadata-only install.
COPY pyproject.toml README.md LICENSE THIRD_PARTY_NOTICES.md hatch_build.py ./
RUN mkdir -p nanobot bridge && touch nanobot/__init__.py && \
    uv pip install --system --no-cache . && \
    rm -rf nanobot bridge

# Copy the full source and install
COPY nanobot/ nanobot/
COPY bridge/ bridge/
COPY webui/ webui/
COPY scripts/install_channel_dependencies.py scripts/install_channel_dependencies.py
RUN NANOBOT_FORCE_WEBUI_BUILD=1 uv pip install --system --no-cache .
# WhatsApp is available in the default image. Reuse the channel manifest so
# the image stays aligned when its optional dependency constraints change.
RUN python -m scripts.install_channel_dependencies whatsapp

# Preload tiktoken's encoder into the image so the first live chat turn does
# not block on encoder download/cache creation.
ENV TIKTOKEN_CACHE_DIR=/tmp/data-gym-cache
RUN mkdir -p "$TIKTOKEN_CACHE_DIR" && \
    python -c "import tiktoken; tiktoken.get_encoding('cl100k_base').encode('nanobot warmup')" && \
    chmod -R 1777 "$TIKTOKEN_CACHE_DIR"

# Build the WhatsApp bridge
WORKDIR /app/bridge
RUN git config --global --add url."https://github.com/".insteadOf ssh://git@github.com/ && \
    git config --global --add url."https://github.com/".insteadOf git@github.com: && \
    npm install && npm run build
WORKDIR /app

# Create non-root user and config directory
RUN useradd -m -u 1000 -s /bin/bash nanobot && \
    mkdir -p /home/nanobot/.nanobot && \
    chown -R nanobot:nanobot /home/nanobot /app

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint.sh && chmod +x /usr/local/bin/entrypoint.sh

USER nanobot
ENV HOME=/home/nanobot

# Gateway health endpoint and optional WebUI/WebSocket channel ports
EXPOSE 18790 8765

ENTRYPOINT ["entrypoint.sh"]
CMD ["status"]
