# Discord MCP

Standalone MCP server for Discord administration and automation tools.

## Features

- MCP tool endpoints for channels, messages, roles, threads, invites, and moderation
- Streamable HTTP MCP transport (`/mcp`) for client integrations
- JDA-backed Discord API operations

## Requirements

- Java 17+
- Maven 3.9+
- Discord bot token (`DISCORD_TOKEN`)

## Environment

Create `.env` from `.env.example`:

```bash
cp .env.example .env
```

Required variables:

- `DISCORD_TOKEN`
- `DISCORD_GUILD_ID` (optional default guild)

## Run locally

```bash
mvn clean package
SPRING_PROFILES_ACTIVE=http java -jar target/discord-mcp-1.0.0.jar
```

Health check:

- `http://localhost:8085/actuator/health`

MCP endpoint:

- `http://localhost:8085/mcp`

## Run with Docker

```bash
docker compose up -d --build
```

## Repository scope

This repository contains only the MCP server app.
Primo slash commands are now maintained in a separate `primo-bot` repository.
