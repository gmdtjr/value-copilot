FROM node:20-alpine

WORKDIR /app

RUN npm install -g pnpm

COPY package.json ./
RUN pnpm install

COPY . .

CMD ["pnpm", "dev", "--host", "0.0.0.0"]
