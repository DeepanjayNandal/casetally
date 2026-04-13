# ---- Builder ----
FROM node:20-alpine AS builder

WORKDIR /app

# Copy only lockfile and package manifest for dependency install caching
COPY package.json package-lock.json* ./

# Install deps (dev deps needed for build)
RUN npm ci --silent

# Copy source and build
COPY . .
ARG NEXT_PUBLIC_BACKEND_URL
ENV NEXT_PUBLIC_BACKEND_URL=$NEXT_PUBLIC_BACKEND_URL
RUN npm run build

# ---- Runner ----
FROM node:20-alpine AS runner
WORKDIR /app

# Copy package manifest and install production deps only
COPY package.json package-lock.json* ./
RUN npm ci --omit=dev --silent

# Copy build output and public assets
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/next.config.mjs ./next.config.mjs

EXPOSE 3000
ENV NODE_ENV=production
ENV PORT=3000

CMD ["npm", "start"]
