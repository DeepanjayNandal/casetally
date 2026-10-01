# ---- Builder ----
FROM node:20-alpine AS builder

WORKDIR /app

# Copy only lockfile and package manifest for dependency install caching
COPY package.json package-lock.json* ./

# Install deps (dev deps needed for build)
RUN npm ci --silent

# Copy source and build
COPY . .

# NEXT_PUBLIC_* variables are inlined into the client bundle at BUILD time, not
# read at runtime, so this has to be a build arg. It must match the origin the
# browser actually uses: the page and its API calls have to be same-origin, or
# the browser blocks them. Changing the ingress host means rebuilding this image.
ARG NEXT_PUBLIC_BACKEND_URL
ENV NEXT_PUBLIC_BACKEND_URL=$NEXT_PUBLIC_BACKEND_URL
RUN npm run build

# ---- Runner ----
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000
# Next's standalone server binds localhost by default, which inside a pod means
# nothing outside the container can reach it, including the kubelet's probes.
ENV HOSTNAME=0.0.0.0

RUN addgroup -g 1001 -S nodejs && adduser -S nextjs -u 1001

# Standalone output carries its own trimmed node_modules and server.js, so the
# runtime stage installs nothing. public/ and .next/static are not included in
# the bundle and have to be copied separately.
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

CMD ["node", "server.js"]
