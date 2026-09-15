FROM node:24-alpine AS build
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ /app/frontend/
COPY backend/app_center/creation_master/react/src/ /app/backend/app_center/creation_master/react/src/
COPY backend/app_center/WeMD/apps/web/ /app/backend/app_center/WeMD/apps/web/
COPY backend/app_center/WeMD/packages/core/ /app/backend/app_center/WeMD/packages/core/
WORKDIR /app/frontend
RUN /app/node_modules/.bin/tsc && /app/node_modules/.bin/vite build

FROM nginx:1.27-alpine
COPY --from=build /app/frontend/dist /usr/share/nginx/html
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
