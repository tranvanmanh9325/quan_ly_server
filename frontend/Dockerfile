# syntax=docker/dockerfile:1

# ==============================================================================
# STAGE 1: Source Builder (For Local Dev & Fallback)
# ==============================================================================
FROM node:20-alpine AS builder

WORKDIR /app

# Configure resilient npm network settings to prevent timeout on international routing
ENV NPM_CONFIG_FETCH_RETRIES=5 \
    NPM_CONFIG_FETCH_RETRY_MINTIMEOUT=20000 \
    NPM_CONFIG_FETCH_RETRY_MAXTIMEOUT=120000 \
    NPM_CONFIG_FETCH_TIMEOUT=300000 \
    NPM_CONFIG_AUDIT=false \
    NPM_CONFIG_FUND=false

# Copy package manifests first to leverage Docker layer cache
COPY package*.json ./

# Use BuildKit Cache Mount + npm ci with --legacy-peer-deps for deterministic, conflict-free installs
RUN --mount=type=cache,target=/root/.npm \
    npm ci --legacy-peer-deps

COPY . .
RUN npm run build

# ==============================================================================
# STAGE 2: Base Nginx Runtime
# ==============================================================================
FROM nginx:alpine AS nginx-base

# Replace default config with SPA Cyberpunk routing configuration
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]

# ==============================================================================
# TARGET: ci (For GitHub Actions / CI-CD Deployment)
# BuildKit automatically prunes Stage 1: zero Node.js pull, zero npm install.
# Copies pre-built dist artifact in ~1 second.
# ==============================================================================
FROM nginx-base AS ci
COPY dist /usr/share/nginx/html

# ==============================================================================
# TARGET: local (Default for Local Development / Direct Docker build)
# Builds from source using Stage 1
# ==============================================================================
FROM nginx-base AS local
COPY --from=builder /app/dist /usr/share/nginx/html
