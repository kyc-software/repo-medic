FROM oven/bun:1.3.14 AS build

WORKDIR /workspace
COPY package.json bun.lock ./
COPY apps/web/package.json ./apps/web/package.json
RUN bun install --frozen-lockfile

COPY apps/web ./apps/web
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
RUN bun --cwd apps/web build

FROM oven/bun:1.3.14-slim
WORKDIR /workspace
ENV NODE_ENV=production
COPY --from=build /workspace/package.json /workspace/bun.lock ./
COPY --from=build /workspace/apps/web ./apps/web
COPY --from=build /workspace/node_modules ./node_modules
EXPOSE 3000
CMD ["bun", "--cwd", "apps/web", "start"]
