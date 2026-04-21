FROM python:3.11-slim

WORKDIR /app

RUN sed -i "s/deb.debian.org/mirrors.aliyun.com/g" /etc/apt/sources.list.d/debian.sources && apt-get update && apt-get install -y --no-install-recommends curl git tmux gcc python3-dev tzdata ca-certificates gnupg lsb-release && mkdir -p /etc/apt/keyrings && curl -fsSL https://mirrors.aliyun.com/docker-ce/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://mirrors.aliyun.com/docker-ce/linux/debian $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null && apt-get update && apt-get install -y docker-ce-cli && rm -rf /var/lib/apt/lists/*

ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ && pip install --no-cache-dir numpy pandas tiktoken lxml html5lib jinja2

COPY . .
RUN pip install --no-cache-dir .
RUN pip uninstall -y nanobot-ai

ENV PYTHONUNBUFFERED=1
ENV ARK_SLOT_WORKSPACE=/root/.nanobot/workspace
ENV PYTHONPATH=/app

CMD ["python", "-m", "nanobot", "gateway", "--port", "8080"]
