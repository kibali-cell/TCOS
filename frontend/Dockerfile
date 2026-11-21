# Development image: runs the Vite dev server. The production build image
# (static files behind a TLS web server) is added in a later slice.
FROM node:22-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev"]
