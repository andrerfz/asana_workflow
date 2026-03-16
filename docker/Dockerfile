FROM python:3.12-slim

# Git + Node.js + Docker CLI for agent operations
RUN apt-get update && apt-get install -y --no-install-recommends git curl make openssh-client && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    npm install -g @anthropic-ai/claude-code && \
    # Docker CLI binary (no apt repo — avoids libc6 version mismatch on slim images)
    DOCKER_VERSION=27.5.1 && \
    curl -fsSL "https://download.docker.com/linux/static/stable/x86_64/docker-${DOCKER_VERSION}.tgz" | \
    tar xz --strip-components=1 -C /usr/local/bin docker/docker && \
    # Docker Compose plugin (standalone binary)
    COMPOSE_VERSION=v2.32.4 && \
    mkdir -p /usr/local/lib/docker/cli-plugins && \
    curl -fsSL "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-x86_64" \
    -o /usr/local/lib/docker/cli-plugins/docker-compose && \
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data

# Non-root user — Claude Code CLI refuses --dangerously-skip-permissions as root
# UID 501 matches default macOS user for seamless file permissions on mounted volumes
ARG HOST_UID=501
RUN useradd -m -s /bin/bash -u ${HOST_UID} agent && \
    chown -R agent:agent /app /app/data

USER agent

# Git config for worktree/commit operations
RUN git config --global user.name "Asana Agent" && \
    git config --global user.email "agent@asana-workflow.local" && \
    git config --global safe.directory '*'

EXPOSE 8765

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8765", "--reload", "--reload-dir", "/app"]
