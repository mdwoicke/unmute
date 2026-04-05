FROM node:18-alpine

RUN apk add --no-cache libc6-compat curl
RUN corepack enable pnpm

WORKDIR /app

COPY package.json ./
RUN pnpm i

COPY . .

EXPOSE 3000

ENV NODE_ENV=development
ENV HOSTNAME=0.0.0.0
ENV PORT=3000

HEALTHCHECK --start-period=30s \
    CMD curl --fail http://localhost:3000/ || exit 1

CMD ["pnpm", "dev"]
