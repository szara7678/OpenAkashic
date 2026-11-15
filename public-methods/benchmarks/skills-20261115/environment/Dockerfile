FROM python:3.12-alpine
RUN apk add --no-cache nodejs npm chromium poppler-utils font-dejavu && pip install --no-cache-dir reportlab==5.1.0 pypdf==7.1.0 pandas==2.3.3 numpy==2.5.4 && npm install --prefix /opt/eval-browser playwright-core
ENV NODE_PATH=/opt/eval-browser/node_modules CHROMIUM_PATH=/usr/bin/chromium-browser
