# Umbrel Docker Stack

Este repositório registra a estrutura Docker do Umbrel em `C:\Umbrel`.
O container externo inicia o gerenciador do Umbrel, que restaura e administra os apps registrados:

- Hermes Agent
- Jellyfin
- Obsidian
- Ollama

Todos os containers usam a rede `umbrel_main_network` e recebem `C:\Umbrel` em `/shared`.

## Inicialização

A rede precisa existir antes do primeiro `docker compose up`:

```powershell
docker network create --driver bridge --subnet 10.21.0.0/16 --gateway 10.21.0.1 umbrel_main_network
docker compose up -d
```

Se a rede já existir, ignore o erro de nome duplicado e execute apenas o segundo comando.

O painel fica disponível em `http://localhost:8080` e o Jellyfin em `http://localhost:8096`.

## Estrutura

- `docker-compose.yml`: container externo do Umbrel.
- `umbrel-core/docker-compose.yml`: serviços internos de autenticação e Tor com `/shared`.
- `apps/*/docker-compose.yml`: cópias versionadas dos Compose dos apps customizados.

Os dados persistentes permanecem em `C:\Umbrel` e não são versionados neste repositório.
