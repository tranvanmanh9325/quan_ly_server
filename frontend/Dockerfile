FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine
# Copy react build output to nginx html directory
COPY --from=builder /app/dist /usr/share/nginx/html
# Xoá config mặc định của nginx và thay bằng cấu hình hỗ trợ React
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
