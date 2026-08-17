"""Drives the Asyntai plugin on a real Mattermost server.

Creates a team and channel, runs the slash command, sends a direct message to
the bot, and checks what the bot posted back. It also checks the two failure
paths: no API key, and an error from Asyntai.

The plugin is pointed at a stub of the Asyntai API (stub_api.py), so no real
messages are spent and no account is needed.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

MM = os.environ.get("MM_URL", "http://localhost:8065")
TOKEN = os.environ.get("MM_TOKEN", "")
STUB = os.environ.get("STUB_URL", "http://localhost:9000")
PLUGIN_ID = "com.asyntai.chatbot"

failures = []


def check(name, ok, detail=""):
    print(("  OK   " if ok else "  FAIL ") + name + (("  <- " + str(detail)) if not ok and detail else ""))
    if not ok:
        failures.append(name)


def api(path, method="GET", body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(MM + path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + (token or TOKEN))
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        return {"_status": e.code, "_body": e.read().decode()[:300]}


def set_plugin_config(**overrides):
    cfg = api("/api/v4/config")
    settings = {
        "apikey": "test-key-12345",
        "websiteid": "",
        "allowdirectmessages": True,
        "apibaseurl": STUB_INTERNAL,
    }
    settings.update(overrides)
    cfg["PluginSettings"]["Plugins"][PLUGIN_ID] = settings
    api("/api/v4/config", "PUT", cfg)
    # The plugin reloads its configuration asynchronously.
    time.sleep(2)


STUB_INTERNAL = os.environ.get("STUB_INTERNAL", "http://asyntai-stub:9000")


def latest_posts(channel_id, limit=10):
    return api("/api/v4/channels/%s/posts?per_page=%d" % (channel_id, limit))


def wait_for_bot_post(channel_id, since_ids, timeout=25):
    """Waits for a post from the bot that was not there before."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        posts = latest_posts(channel_id)
        for pid in posts.get("order", []):
            if pid in since_ids:
                continue
            post = posts["posts"][pid]
            if post.get("user_id") == BOT_ID:
                return post
        time.sleep(1)
    return None


if not TOKEN:
    print("MM_TOKEN is required")
    sys.exit(2)

print("Setting up")
me = api("/api/v4/users/me")
check("signed in as an administrator", "system_admin" in me.get("roles", ""), me.get("roles"))

bots = api("/api/v4/bots")
bot = next((b for b in bots if b.get("username") == "asyntai"), None)
check("the plugin created the Asyntai bot", bot is not None)
BOT_ID = bot["user_id"] if bot else ""
check("the bot is owned by the plugin", bot and bot.get("owner_id") == PLUGIN_ID)

team = api("/api/v4/teams", "POST", {"name": "asyntai-test", "display_name": "Asyntai Test", "type": "O"})
if team.get("_status") == 400:
    team = next(t for t in api("/api/v4/teams") if t["name"] == "asyntai-test")
api("/api/v4/teams/%s/members" % team["id"], "POST", {"team_id": team["id"], "user_id": me["id"]})

channel = api("/api/v4/channels", "POST", {
    "team_id": team["id"], "name": "asyntai-test-channel",
    "display_name": "Asyntai Test Channel", "type": "O",
})
if channel.get("_status") == 400:
    channel = api("/api/v4/teams/%s/channels/name/asyntai-test-channel" % team["id"])
check("a test channel exists", "id" in channel, channel)

set_plugin_config()

print("The slash command")
before = set(latest_posts(channel["id"]).get("order", []))
resp = api("/api/v4/commands/execute", "POST", {
    "channel_id": channel["id"], "team_id": team["id"],
    "command": "/asyntai what is your refund policy",
})
check("the command is accepted", "_status" not in resp, resp)

post = wait_for_bot_post(channel["id"], before)
check("the bot answers in the channel", post is not None)
if post:
    check("the answer contains the reply text", "refund window is 30 days" in post["message"], post["message"][:120])
    # The old version pasted the question in bold above the answer, which read
    # as the bot talking to itself. The answer must now stand alone.
    check("the answer is not padded with the question",
          not post["message"].startswith("**"), post["message"][:120])

# The question must appear as a post from the person who asked, not from the
# bot, so the channel reads as a conversation.
posts = latest_posts(channel["id"])
mine = [posts["posts"][pid] for pid in posts.get("order", [])
        if posts["posts"][pid].get("user_id") == me["id"]]
check("the question is shown under the asker's name",
      any("what is your refund policy" in p.get("message", "") for p in mine),
      [p.get("message", "")[:50] for p in mine[:3]])

print("An empty question")
resp = api("/api/v4/commands/execute", "POST", {
    "channel_id": channel["id"], "team_id": team["id"], "command": "/asyntai",
})
check("an empty question gets guidance, not an error",
      "Ask a question" in json.dumps(resp), resp)

print("Direct message to the bot")
dm = api("/api/v4/channels/direct", "POST", [me["id"], BOT_ID])
check("a direct channel with the bot opens", "id" in dm, dm)
before = set(latest_posts(dm["id"]).get("order", []))
api("/api/v4/posts", "POST", {"channel_id": dm["id"], "message": "how long is shipping"})
post = wait_for_bot_post(dm["id"], before)
check("the bot answers a direct message", post is not None)
if post:
    check("the direct answer is just the answer", not post["message"].startswith("**"), post["message"][:80])

print("The bot does not answer itself")
before = set(latest_posts(dm["id"]).get("order", []))
time.sleep(4)
after = latest_posts(dm["id"])
extra = [p for p in after.get("order", []) if p not in before]
check("no runaway loop of bot replies", len(extra) == 0, extra)

print("When Asyntai returns an error")
before = set(latest_posts(dm["id"]).get("order", []))
api("/api/v4/posts", "POST", {"channel_id": dm["id"], "message": "make it fail"})
post = wait_for_bot_post(dm["id"], before)
check("the failure is reported to the user", post is not None and "could not answer" in post["message"].lower(),
      post["message"][:120] if post else None)
check("the reason from Asyntai is shown", post is not None and "limit" in post["message"].lower(),
      post["message"][:120] if post else None)

print("With no API key set")
set_plugin_config(apikey="")
resp = api("/api/v4/commands/execute", "POST", {
    "channel_id": channel["id"], "team_id": team["id"], "command": "/asyntai anything",
})
check("the command explains that setup is needed", "not set up yet" in json.dumps(resp), resp)

before = set(latest_posts(dm["id"]).get("order", []))
api("/api/v4/posts", "POST", {"channel_id": dm["id"], "message": "still nothing"})
time.sleep(6)
after = latest_posts(dm["id"])
extra = [p for p in after.get("order", []) if p not in before and after["posts"][p]["user_id"] == BOT_ID]
check("direct messages stay silent without a key", len(extra) == 0, extra)

print("With direct messages switched off")
set_plugin_config(allowdirectmessages=False)
before = set(latest_posts(dm["id"]).get("order", []))
api("/api/v4/posts", "POST", {"channel_id": dm["id"], "message": "are you there"})
time.sleep(6)
after = latest_posts(dm["id"])
extra = [p for p in after.get("order", []) if p not in before and after["posts"][p]["user_id"] == BOT_ID]
check("the bot ignores direct messages", len(extra) == 0, extra)

print("What reached the Asyntai API")
with urllib.request.urlopen(STUB + "/_calls") as r:
    calls = json.load(r)
check("the API key was sent as a bearer token",
      any(c["auth"] == "Bearer test-key-12345" for c in calls))
check("the plugin identifies itself",
      any("Asyntai-Mattermost-Plugin" in c.get("agent", "") for c in calls))
check("each conversation has its own session",
      len({c["body"].get("session_id") for c in calls if c["body"].get("session_id")}) >= 2,
      [c["body"].get("session_id") for c in calls])

set_plugin_config()

print()
if failures:
    print("%d TEST(S) FAILED" % len(failures))
    sys.exit(1)
print("ALL TESTS PASSED")
