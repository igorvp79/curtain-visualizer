FROM node:22-bookworm-slim AS frontend
WORKDIR /build
RUN npm install --global pnpm@9.15.9
COPY app/frontend/package.json app/frontend/pnpm-lock.yaml app/frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY app/frontend/ ./
RUN pnpm build

FROM python:3.13-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DJANGO_SETTINGS_MODULE=config.demo_settings CRM_DEMO_MODE=true
WORKDIR /srv/app/backend
COPY app/backend/requirements.txt /tmp/requirements.txt
COPY deploy/render/requirements.txt /tmp/render-requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt -r /tmp/render-requirements.txt
COPY app/backend/ ./
COPY --from=frontend /build/dist /srv/app/frontend/dist
COPY deploy/render/start.sh /srv/start-demo.sh
RUN useradd --create-home crm && chmod 755 /srv/start-demo.sh && chown -R crm:crm /srv/app
USER crm
EXPOSE 10000
CMD ["sh", "/srv/start-demo.sh"]
