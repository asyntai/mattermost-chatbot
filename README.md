# Asyntai AI Chatbot for Mattermost

Ask a question in Mattermost and get an answer built from your own content.

Type `/asyntai how do I book leave` in any channel and the Asyntai bot posts the
answer where everyone can see it. Or send the bot a direct message and hold a
normal conversation with it.

Useful as an internal help desk. The questions people ask in a team chat all day
are the same ones already answered in your handbook, your policies and your
website, and now nobody has to go and find them.

Tested on Mattermost 11 (Team Edition), against the live Asyntai API.
Requires Mattermost 9.0 or newer.

## What you need

An Asyntai account **on a paid plan**. The bot reaches Asyntai over the API, and
API access is not part of the free plan. Get the key at
[asyntai.com](https://asyntai.com) under Settings, API.

## Install

1. Download `com.asyntai.chatbot.tar.gz` from the releases page.
2. In Mattermost go to **System Console → Plugins → Plugin Management** and
   upload it.
3. Enable the plugin.
4. Open **System Console → Plugins → Asyntai AI Chatbot** and paste your API key.

## Settings

**Asyntai API key.** The plugin does nothing until this is set. Both the slash
command and the bot say so plainly rather than failing silently.

**Website ID.** Leave empty to use your primary website in Asyntai. Set a numeric
ID to point the bot at a different one.

**Answer direct messages to the bot.** On by default. Turn it off to leave only
the slash command.

**API address.** Leave empty. It exists so the plugin can be pointed at a test
server.

## How it works

The plugin is a Go server plugin. On activation it creates a bot account called
`asyntai` and registers the `/asyntai` command.

Mattermost keeps a slash command private, so the channel would otherwise see a
bot answer with no question attached. Neither built in response type helps: the
default is invisible to everyone else, and `in_channel` posts the answer under
the asking person's name, which reads as if they answered themselves. So the
plugin posts the question as the person and the answer as the bot, and the
channel reads as a normal conversation.

Each conversation gets its own session, so follow up questions keep their
context. A question asked in a channel is tied to that channel and person; a
direct message conversation is tied to the person. Nothing is shared between
them.

The plugin only ever sends the question text and a session ID to Asyntai. It
does not send your channel history, your member list or anything else from
Mattermost.

## Files

```
plugin.json          manifest and the settings shown in the System Console
server/plugin.go     the bot, the command and the direct message handler
server/asyntai.go    the Asyntai API client
assets/icon.svg
tests/               a test suite that runs against a real Mattermost
```

## Build

Go 1.26 or newer:

```
cd server && go build -o dist/plugin-linux-amd64 .
```

Or build every platform and package the bundle with Docker, which is what the
release uses:

```
docker run --rm -v "$PWD:/src" -w /src/server golang:1.26 bash -lc '
  for t in linux-amd64 linux-arm64 darwin-amd64 darwin-arm64 windows-amd64; do
    os=${t%-*}; arch=${t#*-}; out=dist/plugin-$t
    [ "$os" = windows ] && out="$out.exe"
    CGO_ENABLED=0 GOOS=$os GOARCH=$arch go build -trimpath -o "$out" .
  done'
```

## Support

hello@asyntai.com
