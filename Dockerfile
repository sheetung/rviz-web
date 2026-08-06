# syntax=docker/dockerfile:1

FROM node:22-alpine AS frontend-build

WORKDIR /build
COPY VERSION ./VERSION
COPY frontend/package*.json ./frontend/
RUN --mount=type=cache,target=/root/.npm \
    cd frontend && npm ci
COPY frontend/ ./frontend/
RUN cd frontend && npm run build


FROM ros:humble-perception-jammy

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        ffmpeg \
        nginx \
        python3-pip \
        python3-venv \
    && python3 -m pip install --no-cache-dir uv==0.11.29 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN python3 -m venv --system-site-packages .venv \
    && VIRTUAL_ENV=/app/backend/.venv uv sync --frozen --no-dev --active

COPY backend/app ./app
COPY VERSION /app/VERSION
COPY rvizweb_configs /app/rvizweb_configs
COPY --from=frontend-build /build/frontend/dist /var/www/html
COPY docker/nginx.conf /etc/nginx/sites-available/default
COPY docker/start-container.sh /app/start-container.sh
RUN chmod 0755 /app/start-container.sh

ENV PYTHONPATH=/app/backend
ENV ROS_DOMAIN_ID=0
ENV BACKEND_HOST=127.0.0.1
ENV RMW_IMPLEMENTATION=rmw_fastrtps_cpp
ENV FASTDDS_BUILTIN_TRANSPORTS=UDPv4
ENV ROS_LOCALHOST_ONLY=0

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl --fail http://127.0.0.1:3000/health || exit 1

CMD ["/app/start-container.sh"]
