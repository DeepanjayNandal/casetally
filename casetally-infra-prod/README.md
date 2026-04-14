# CaseTally Infra Prod

Production infrastructure for:

- Traefik reverse proxy
- Docker registry
- Docker registry UI on the same public hostname as the registry

Default security model:

- Public over HTTPS: `registry.<domain>`
- Restricted by IP allowlist + auth: `traefik.<domain>`
- Browser visits to `https://registry.<domain>/` load the registry UI
- Docker clients use `https://registry.<domain>/v2/`

## Files

- `docker-compose.prod.yml`: production stack
- `.env.prod.example`: required environment variables
- `traefik/dynamic/middlewares.yml`: shared security headers middleware

## 1) Server prerequisites

1. Linux server with Docker Engine + Docker Compose plugin.
2. Public IP on the server.
3. Firewall/security group allows inbound `80/tcp` and `443/tcp`.
4. Docker network created:

```bash
docker network create casetally-network 2>/dev/null || true
```

## 2) Configure environment

Copy and edit:

```bash
cp .env.prod.example .env.prod
```

Set these values in `.env.prod`:

- `TRAEFIK_DOMAIN`
- `REGISTRY_DOMAIN`
- `LETSENCRYPT_EMAIL`
- `ADMIN_ALLOWLIST_CIDRS`
- `TRAEFIK_BASIC_AUTH`
- `REGISTRY_BASIC_AUTH`
- `REGISTRY_PROXY_BASIC_AUTH_B64`

Generate auth values:

```bash
htpasswd -nbm casetallyadmin "CHANGE_ME_DASHBOARD_PASSWORD"
htpasswd -nbm casetallyregistry "CHANGE_ME_REGISTRY_PASSWORD"
echo -n "casetallyregistry:CHANGE_ME_REGISTRY_PASSWORD" | base64
```

Important: replace each `$` with `$$` in `.env.prod` for `*_BASIC_AUTH`.

## 3) Prepare Let's Encrypt storage

```bash
mkdir -p volumes/traefik/letsencrypt
touch volumes/traefik/letsencrypt/acme.json
chmod 600 volumes/traefik/letsencrypt/acme.json
```

## 4) GoDaddy DNS setup

In GoDaddy DNS for your domain, add `A` records to your server public IP:

- `traefik` -> `<server_public_ip>`
- `registry` -> `<server_public_ip>`

If your domain is `casetally.io`, this becomes:

- `traefik.casetally.io`
- `registry.casetally.io`

Use low TTL (for example 600 seconds) during cutover.

## 5) Deploy

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d
```

Check status:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml ps
docker compose --env-file .env.prod -f docker-compose.prod.yml logs -f traefik
```

## 6) Validate endpoints

Run:

```bash
curl -I https://$REGISTRY_DOMAIN/v2/
curl -I https://$REGISTRY_DOMAIN/
curl -I https://$TRAEFIK_DOMAIN
```

Expected:

- Registry returns `401 Unauthorized` without auth (this is correct).
- Registry root serves the UI after basic auth.
- Traefik dashboard challenges for auth and only allow listed IPs can access.

Test Docker registry:

```bash
docker login $REGISTRY_DOMAIN
docker pull $REGISTRY_DOMAIN/some-image:tag
```

## Why the UI can look empty

The default registry UI is empty when the registry itself has no repositories yet.

Push at least one image first:

```bash
docker login $REGISTRY_DOMAIN
docker tag alpine:latest $REGISTRY_DOMAIN/test/alpine:latest
docker push $REGISTRY_DOMAIN/test/alpine:latest
```

Then refresh `https://$REGISTRY_DOMAIN/` and the UI should list `test/alpine`.

## 7) Operational notes

- Keep `REGISTRY_DELETE_ENABLED=false` unless image deletion is required.
- Rotate both dashboard and registry passwords regularly.
- Back up:
  - registry volume (`casetally_registry_data`)
  - `volumes/traefik/letsencrypt/acme.json`
