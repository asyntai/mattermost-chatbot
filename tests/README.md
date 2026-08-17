# Tests

`test_plugin.py` drives the plugin on a real Mattermost server. 22 checks, all
passing on Mattermost 11 Team Edition.

It covers the slash command, direct messages to the bot, both failure paths, and
what actually reaches the Asyntai API.

No real Asyntai account is used. The plugin is pointed at `stub_api.py`, a small
stand-in that copies the real contract: bearer auth, `POST /api/v1/chat/`, and
the same JSON for success and failure. Asking it "make it fail" returns a plan
limit error, which is how the error path is tested.

## Run

Start Mattermost and Postgres, upload and enable the plugin, then:

```
docker run -d --name asyntai-stub --network mattermost_default -p 9000:9000 \
  -v "$PWD:/app" -w /app python:3.11-alpine python stub_api.py

MM_TOKEN=<admin token> python test_plugin.py
```

Get an admin token without typing a password into a browser:

```
curl -s -i -X POST http://localhost:8065/api/v4/users/login \
  -H "Content-Type: application/json" \
  -d '{"login_id":"admin@example.invalid","password":"..."}' | grep -i '^token:'
```

Environment variables:

```
MM_URL=http://localhost:8065        the server the tests drive
MM_TOKEN=...                        an administrator's session token
STUB_URL=http://localhost:9000      the stub, as seen from your machine
STUB_INTERNAL=http://asyntai-stub:9000   the stub, as seen from Mattermost
```

`STUB_INTERNAL` is separate on purpose. The plugin runs inside the Mattermost
container, so it reaches the stub by container name, not by localhost.

## Notes

Plugin settings are stored in the server configuration under
`PluginSettings.Plugins["com.asyntai.chatbot"]`, and the keys are **lower case**:
`apikey`, `websiteid`, `allowdirectmessages`, `apibaseurl`. The manifest declares
them as `APIKey`, `WebsiteID` and so on, but Mattermost lower cases them on the
way in. Writing them in the manifest's casing silently does nothing.

The plugin reloads its configuration asynchronously, so the tests wait a moment
after every change.

Building with `go build ... | tail` hides the exit code and reports success even
when compilation failed. Build without a pipe, and check the binaries exist.
