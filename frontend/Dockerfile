FROM node:24-alpine AS build
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ /app/frontend/
# Vite resolves bundled application frontends directly from App Center. Copying
# the parent directory keeps optional, uninitialized submodules optional while
# still including every in-repository application frontend.
COPY backend/app_center/ /app/backend/app_center/
WORKDIR /app/frontend
RUN /app/node_modules/.bin/tsc && /app/node_modules/.bin/vite build

FROM nginx:1.29-alpine
COPY --from=build /app/frontend/dist /usr/share/nginx/html
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
