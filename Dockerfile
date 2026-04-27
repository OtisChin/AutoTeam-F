FROM python:3.12-slim

# 系统依赖
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    curl \
    nodejs \
    npm \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app

# 复制项目文件
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev

# 安装 Playwright 浏览器
RUN uv run playwright install chromium && uv run playwright install-deps chromium

# 复制源码
COPY src/ src/
COPY web/ web/

# 构建前端静态资源
RUN cd web \
    && npm config set fetch-retries 5 \
    && npm config set fetch-retry-factor 2 \
    && npm config set fetch-retry-mintimeout 20000 \
    && npm config set fetch-retry-maxtimeout 120000 \
    && npm config set fetch-timeout 300000 \
    && npm ci \
    && npm run build

# 数据卷（.env、accounts.json、auths/、state.json、screenshots/）
VOLUME ["/app/data"]

# 启动时将数据目录软链到工作目录
RUN mkdir -p /app/data
ENV DISPLAY=:99

EXPOSE 8787

# 启动脚本
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["api"]
