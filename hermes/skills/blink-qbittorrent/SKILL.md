---
name: blink-qbittorrent
description: Use when Blink must search for, add, inspect, pause, or resume authorized torrent downloads through TorrentClaw and the qBittorrent MCP bridge.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [blink, qbittorrent, torrents, media, downloads, umbrel]
    related_skills: [note-taking, obsidian]
---

# Blink qBittorrent workflow

## Overview

TorrentClaw is the discovery layer; the `qbittorrent` MCP server is the execution and status layer. Keep those responsibilities separate. TorrentClaw returns metadata, magnets, or torrent URLs. The qBittorrent bridge receives only the selected, authorized source.

The bridge exposes only an allow-list of safe operations and intentionally has no delete or remove tool.

## When to use

Use this skill when the user asks to:

- find and download a movie, series, season, episode, or anime;
- add a magnet or `.torrent` URL to qBittorrent;
- check download progress or completion;
- pause or resume downloads;
- route media into the configured household folders.

Do not use it to delete torrents or files, change global qBittorrent settings, expose credentials, or download content the user is not legally authorized to obtain.

## Tool contract

- `qbt_get_status`: verify reachability and qBittorrent state.
- `qbt_get_categories`: confirm configured routing.
- `qbt_list_torrents`: check duplicates and inspect progress.
- `qbt_get_torrent_status`: inspect one torrent by hash.
- `qbt_add_torrent`: add an authorized magnet or HTTP(S) `.torrent` URL.
- `qbt_pause_torrents`: pause by explicit hash.
- `qbt_resume_torrents`: resume by explicit hash.

Never call an undocumented raw endpoint and never ask for qBittorrent credentials in chat.

## One-request workflow

For a request such as “baixe a última temporada de uma série dublada em PT-BR”:

1. Parse title, media type, season or episode, language, dubbing, and quality preferences.
2. Resolve “última temporada” from current, reliable metadata. Ask one concise clarification only if the title or season is ambiguous.
3. Search with TorrentClaw. Prefer exact title and season matches, Brazilian Portuguese audio metadata, healthy trackers, and a reasonable file size. Do not dump a long result list.
4. Confirm the selected source is legal, authorized, public-domain, or content the user has the right to download. If authorization is unclear for commercial content, do not send it to qBittorrent.
5. Call `qbt_list_torrents` before adding. If an equivalent torrent exists, report its current state instead of creating a duplicate.
6. Map movie to `filmes`, TV series to `series`, and anime to `animes`. Pass only the category to `qbt_add_torrent`, never a Windows path.
7. Verify that the bridge says the torrent was accepted. A search result is not a download.
8. Report title, season, category, destination, and initial state in a short response.
9. For progress, use `qbt_get_torrent_status` or `qbt_list_torrents` and report percentage, state, ETA, and speed.

Completion means qBittorrent accepted the source and returned the expected category and path. If this check fails, clearly state that the download did not start.

## Routing rules

- Movie: category `filmes`, internal path `/media/Filmes`, Windows folder `C:\Umbrel\home\Videos\Filmes`.
- TV series: category `series`, internal path `/media/Series`, Windows folder `C:\Umbrel\home\Videos\Series`.
- Anime: category `animes`, internal path `/media/Animes`, Windows folder `C:\Umbrel\home\Videos\Animes`.
- Unknown media: default internal path `/downloads`, Windows folder `C:\Umbrel\home\Downloads`.
- Preserve requested language and dubbing. Never silently substitute subtitles for Brazilian Portuguese dubbing.

Never use `localhost` from Hermes to reach qBittorrent.

## Safety and privacy

- Resolve credentials from the Hermes secret store or password file. Never print them.
- Never include cookies, passwords, secrets, or full magnet links in a response.
- Never remove torrents or files automatically.
- Never alter qBittorrent global settings from this skill.
- Use the smallest tool call that completes the request and validate its result.

## Verification checklist

- [ ] TorrentClaw search completed or was clearly unavailable.
- [ ] Source authorization was established or the action was declined.
- [ ] Media type mapped to the correct category.
- [ ] Duplicate check completed.
- [ ] `qbt_add_torrent` returned success.
- [ ] Returned path matches the requested category.
- [ ] No credential, cookie, or full magnet was exposed.
