# Google Calendar MCP — Learning Notes

Project: Build an MCP server that reads from Google Calendar, connect it to Claude Desktop.
Goal: Learn MCP concepts hands-on (start with `list_events` only, expand later).

---

## Quick-recall cheat sheet (read this first when revising)

- **MCP** = protocol letting an LLM client (Claude Desktop) discover and call tools exposed by a server (your script). Server ↔ client talk over a **transport** (we used `stdio`).
- **3 formats, not 2**: Format 1 = Claude Desktop ↔ LLM (Anthropic API, `tool_use`/`tool_result` blocks). Format 2 = Claude Desktop ↔ MCP server (JSON-RPC 2.0, `tools/list`/`tools/call`). Format 3 = MCP server ↔ any external API it calls (e.g. Google's own REST API) — ordinary, unrelated to MCP.
- **`@mcp.tool()`** turns a plain function into a discoverable tool: name ← function name, schema ← type hints, description ← docstring (docstring is FUNCTIONAL, not just documentation — LLM reads it to decide when/how to call).
- **`return`, never `print()`**, inside a tool function — stdout is a reserved channel for JSON-RPC messages only; `print()` corrupts it.
- **stdio transport** = OS-level pipes; Claude Desktop spawns your script as a subprocess and wires its stdin/stdout to itself at launch time (same mechanism as shell `|` piping).
- **Servers auto-launch** with Claude Desktop itself (every entry in `mcpServers` config), not on-demand — they run continuously in the background the whole time the app is open.
- **Config edits need a FULL quit** (Task Manager + system tray), not just closing the window, or changes won't be picked up.
- **OAuth**: `credentials.json` = app identity (Client ID/Secret). Browser consent popup = human authorization, scoped to `SCOPES` in code. `token.json` = saved proof of that consent (access token + refresh token) — browser popup only needed once, until scope changes or token is revoked.
- **Changing scope** (e.g. adding write access) → must delete `token.json` and re-consent; Google Cloud dashboard itself doesn't need touching (scopes are defined only in code, for a personal test-mode app).

---

## Environment

- **OS**: Windows
- **Editor**: VS Code + Claude Code extension
- **Test client**: Claude Desktop (separate app from Claude Code — Claude Desktop is what "connects" to your MCP server as a real client)

---

## Python Setup

- MCP Python SDK requires **Python 3.10+**
- On Windows, use `python` (not `python3` — that's a Mac/Linux convention)
- Check version: `python --version`
- Installing Python on Windows — **critical gotcha**: during installer, check **"Add python.exe to PATH"** on the first screen. Most common cause of Windows Python setup issues if missed.
- After installing/updating PATH, **close and reopen terminal** — PATH changes don't apply to already-open terminals.
- Installed: Python 3.12.x (upgraded from old 3.9.6, which was below the MCP SDK's minimum requirement)

---

## Concepts Covered So Far

### Claude Desktop vs Claude Code — different roles in this project
- **Claude Desktop**: a chat app that acts as the **MCP client**. It connects to your local MCP server and calls its tools (e.g. "what's on my calendar" → Desktop discovers your server's tools and calls `list_events`). It does not write/edit code.
- **Claude Code**: an agentic coding tool inside VS Code. It reads your codebase, writes/edits files (showing diffs before applying), runs terminal commands, and debugges by reading real error output. Used as the "hands" that implement what's been explained/decided — not a replacement for understanding *why* the code works.
- **How to launch Claude Code**: open integrated terminal in VS Code (**Ctrl + `**), type `claude`, hit enter. It auto-detects the project folder as its context.
- Approach for this project: concepts explained step-by-step in chat first → Claude Code used to actually write/run the agreed-upon code, not to autonomously decide the approach.

*(more to fill in as we build — auth, MCP tools, transport, etc.)*

### Virtual environments (venv)
- An isolated Python setup per project — its own installed packages, separate from system-wide Python. Prevents different projects' package versions from conflicting.
- Standard practice for any real Python project.

---

## Setup Commands Log

```
pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib mcp
```

### What each package does
- **google-api-python-client**: Google's official library for calling their APIs (Calendar, Gmail, Drive, etc.) — lets us request calendar data without hand-writing raw HTTP calls.
- **google-auth-httplib2**: bridge library connecting Google's auth system to the HTTP transport — plumbing, not used directly.
- **google-auth-oauthlib**: handles the OAuth flow (browser login + consent), gets access token + refresh token, manages token refresh automatically.
- **mcp**: official MCP Python SDK — lets us define calendar functions as proper MCP tools (with schemas, discovery) so Claude Desktop can find and call them.
- Summary: first three = "talk to Google Calendar", last one = "expose that to Claude via MCP".

---

## Google Cloud / OAuth Setup

### What is Google Cloud Console?
- Dashboard for Google Cloud Platform (GCP) — manages infra AND consumer APIs (Calendar, Gmail, Drive, Maps, etc.)
- For this project it's just the "admin panel" needed before any app (even a local script) can call Calendar API.
- Free for our usage — no billing needed.

### Steps completed
1. Created a Cloud project
2. Enabled the **Google Calendar API** for that project
3. Configured **OAuth consent screen** (now called "Google Auth Platform" in newer UI) — chose **External** user type (personal Gmail, not Workspace)
4. Added own Gmail as a **test user** under **Audience** section
5. Created OAuth credentials under **Clients** section — type **Desktop app**
6. Downloaded the credentials JSON file

### Key concepts
- **Audience section** = who's allowed to use the app. Since app isn't Google-verified, it's in restricted "Testing" mode — only emails explicitly added as test users can complete the OAuth login. Anyone else gets blocked.
- **Clients section** = registers an OAuth Client — a formal identity for the app so Google recognizes who's requesting access. Produces:
  - **Client ID** — public identifier (like an app username)
  - **Client Secret** — private key proving the app's identity (keep private, don't commit to Git)
- **Why "Desktop app" type** (not "Web app"): Desktop apps use a simpler OAuth flow (browser opens → user logs in → redirects to a local port on your machine). Web app type would require a real public HTTPS redirect URL, since it assumes a hosted server — not what we want for a local script.

### OAuth: app identity vs user consent — key distinction
- `credentials.json` proves who the **app** is (Client ID/Secret) — it does NOT grant access to any calendar data.
- The browser popup ("Allow" screen) is where the **human/user** explicitly consents, scoped to what's in `SCOPES`.
- First run = app identity + human consent combined → produces tokens.
- Every run after = app identity + saved token (`token.json`) → no popup needed.

### How `run_local_server()` actually works
- Not two separate programs — it's the **same Python process** temporarily acting as an HTTP server.
- Sequence: script opens a local port and listens → opens your real browser to Google's login/consent URL → you click Allow → Google redirects the browser to `http://localhost:<port>/?code=...` → the script's own listener (still same process, was just waiting/blocking) catches that incoming request and reads the `code` straight out of the URL → local server shuts down → script exchanges that code with Google's servers for actual tokens → tokens saved to `token.json`.
- This "local redirect catcher" pattern is standard for any CLI/desktop OAuth flow (GitHub CLI, AWS CLI, etc.) — browser is just borrowed briefly for the human-approval step.

### What's inside `token.json` and how it's used
- Contains: **access token** (short-lived, ~1 hour), **refresh token** (long-lived, used to silently get new access tokens), Client ID/Secret (for context), granted scopes, expiry timestamp.
- On every run: script checks if `token.json` exists → loads it instead of doing a fresh browser login.
- If the access token has expired, script uses the refresh token to silently get a new one (no browser popup) and rewrites `token.json` with the refreshed token.
- Net effect: browser popup only happens on the very first run; everything after is silent.
- **Security**: treat `token.json` like a password — anyone holding it can act as you within the granted scope, no login needed. Never commit to Git.
- **Revoking access**: can be done anytime via Google Account → "Third-party apps & services" — invalidates the refresh token, making `token.json` useless even if the file still exists.

---

## Milestone: Phases 1–3 complete ✅
- Google Cloud project created, Calendar API enabled, OAuth consent + test user configured, Desktop app credentials created
- Python venv set up, packages installed
- Standalone script (`list_events.py`) successfully authenticates and prints real calendar events
- `token.json` now saved — future runs won't need browser login
- **Next up (Phase 4)**: wrap this working logic as an actual MCP tool so Claude can call it

### Fixed along the way
- `datetime.datetime.utcnow()` is deprecated → replaced with `datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")`

---

## Phase 4: Building the MCP Server

### Minimal MCP server anatomy (hello_server.py example)
```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("hello-server")

@mcp.tool()
def say_hello(name: str) -> str:
    """Greet a person by name.

    Args:
        name: The name of the person to greet.

    Returns:
        A friendly greeting string addressed to the given name.
    """
    return f"Hello, {name}!"

if __name__ == "__main__":
    mcp.run(transport="stdio")
```
- **`FastMCP`**: high-level SDK class that handles MCP protocol plumbing (discovery, JSON-RPC message formatting/parsing) so you don't implement the spec by hand.
- **`FastMCP("hello-server")`**: creates the server and names it — this name is what a connecting client (Claude Desktop) sees.
- **`@mcp.tool()` decorator**: wraps a plain Python function to also register it as an MCP tool, without changing how the function behaves if called directly in Python.
- Three things get auto-derived from the function by the decorator — **nothing here is manual**:
  1. **Tool name** ← the function name
  2. **Input schema** ← the function's **type hints** (e.g. `name: str`). This is why type hints aren't optional style here — they directly generate what Claude reads to know what params to send.
  3. **Description** (incl. per-parameter descriptions) ← the **docstring**. The docstring is FUNCTIONAL, not just documentation — it's literally what the LLM reads to decide when/how to call the tool. A vague docstring → LLM calls the tool at the wrong time or with wrong params.
- **Rule of thumb**: any time you change a tool's parameters, update the function signature AND the docstring together, as a pair.
- `mcp.run(transport="stdio")`: this line actually **starts** the server (everything above just *defines* it). Swap `"stdio"` for `"streamable-http"` later for the localhost/HTTP version.

### stdio transport — deep dive
- Every process has 3 standard streams: **stdin** (input), **stdout** (normal output), **stderr** (error output). Originates from Unix/Linux process design.
- Normally in a terminal: stdin = keyboard, stdout = terminal screen. But these can be **redirected** to something else entirely (another program, a file, a pipe).
- **How MCP uses this**: Claude Desktop launches the server script as a subprocess and connects the subprocess's stdin/stdout not to a terminal, but to itself — Claude Desktop writes MCP protocol (JSON-RPC) messages into the server's stdin, reads responses from the server's stdout. The SDK handles JSON-RPC formatting/parsing internally — you never touch raw JSON-RPC in your Python code.
- **Why running the script manually in a terminal just "hangs"**: stdin is connected to your keyboard in that case, so the server is correctly waiting for MCP-formatted messages on stdin — but nothing valid is arriving, since a human isn't the intended other end. Not a bug — expected behavior.
- **The OS mechanism behind this (pipes)**: when one process launches another, the *launching* process decides what the new process's stdin/stdout connect to, via OS-level process-spawning APIs (e.g. `subprocess.Popen` in Python; Claude Desktop uses the equivalent). It creates **pipes** — OS-managed memory buffers with a write-end and read-end, not a network connection or a file. Claude Desktop holds the write-end of the "stdin pipe" (to send messages) and the read-end of the "stdout pipe" (to read responses). The child script has no idea this is happening — it just does normal read-stdin/write-stdout calls; the OS transparently points those at the pipe instead of a terminal.
- **Same mechanism as shell piping**: `python script1.py | python script2.py` — the `|` operator connects script1's stdout to script2's stdin using this exact pipe mechanism. Claude Desktop launching an MCP server works identically, just done programmatically instead of typed in a shell.
- **Key takeaway**: stdin/stdout aren't "reassigned" after the process starts — they're decided **at process creation time** by whichever process does the launching.

### Connecting a local MCP server to Claude Desktop

**Config file location varies by install method (Windows):**
- Direct `.exe` installer: `%APPDATA%\Claude\claude_desktop_config.json`
- Microsoft Store / MSIX install: `C:\Users\<You>\AppData\Local\Packages\Claude_<hash>\LocalCache\Roaming\Claude\claude_desktop_config.json`
- To find which one is actually in use: Settings → Developer → "Edit Config" — this opens the real file Claude Desktop reads from (though note: this button has had bugs in some versions pointing to the wrong file — worth sanity-checking file content matches expectations).
- Settings → Developer → "Local MCP servers" section shows connected servers and a live "No servers added" / server list status — the most reliable way to confirm config is actually being read.
- Note: the "Connectors" section (Gmail, Slack, Google Calendar (Web), GitHub etc.) is a SEPARATE system for remote/OAuth-based connectors — not the same as local `mcpServers` JSON config. Don't confuse the two.

**Adding a server — add a new top-level `mcpServers` key:**
```json
{
  "preferences": { ... existing content, untouched ... },
  "mcpServers": {
    "hello-server": {
      "command": "D:\\AI\\MCP\\Google Calendar\\venv\\Scripts\\python.exe",
      "args": ["D:\\AI\\MCP\\Google Calendar\\hello_server.py"]
    }
  }
}
```
- Label (`"hello-server"`) is arbitrary, just an identifier you choose.
- `"command"` must point to the **venv's own python.exe**, not system Python — otherwise it hits `ModuleNotFoundError` since MCP/API packages are only installed inside the venv.
- To find the exact venv python path: `Get-Command python` (in PowerShell, with venv active) — `where python` doesn't reliably work in PowerShell.
- `"args"` = same as what you'd type after `python` on the command line, but using full paths (Claude Desktop isn't running from your project folder).
- **JSON escaping gotcha**: Windows paths need every backslash doubled (`\\`) since `\` is a JSON escape character.

**Debugging lesson — "closing the window" ≠ fully quitting the app**
- After editing config, Claude Desktop must be **fully restarted** to re-read it.
- Simply closing the window often just minimizes it to the system tray / leaves background processes running — the OLD config stays loaded in memory.
- Fix: open Task Manager (Ctrl+Shift+Esc), end all "Claude" processes; also check the system tray (hidden icons, up-arrow near clock) and quit from there. Then relaunch fresh.
- General debugging habit worth keeping: when an app "isn't picking up a config change," check whether it's actually fully restarted before assuming the config itself is wrong.

### How Claude Desktop "knows" a tool exists (discovery mechanism)
- When `mcp = FastMCP("hello-server")` runs and `@mcp.tool()` decorates a function, the `FastMCP` object builds an internal **registry** — a mapping of tool name → function + auto-derived schema (params from type hints, description from docstring). This happens the moment the script starts, before any client connects.
- When `mcp.run(transport="stdio")` executes, the server starts listening on stdin.
- Right after launching the server process, Claude Desktop sends a `tools/list`-style MCP protocol request down the stdin pipe — "what tools do you have?"
- The SDK (not code you wrote) handles this request automatically, reading the internal registry and sending back each tool's name/description/schema as a structured response.
- Claude Desktop stores this list; the model then sees it as available context for deciding when/how to call a tool, similar to how any LLM sees its available toolset.
- **Bottom line**: the server doesn't get "discovered" by magic — it explicitly reports its own tool list the moment a client connects. `@mcp.tool()`'s real job is building that reportable registry.

---

## Milestone: End-to-end MCP round trip working ✅
- `hello_server.py` (minimal tool: `say_hello`) successfully wired into Claude Desktop
- Full loop confirmed live: user request → Claude matches intent to tool → **permission prompt shown before running** (Claude Desktop's safety mechanism — tools aren't silently auto-executed) → approved → call sent over stdio → server function runs → result returned → Claude presents it in natural language
- Debugging win: traced a "tool not showing up" issue to an incomplete app restart (background process still running old config), not a config/JSON problem
- **Next session**: swap `say_hello`'s toy logic for the already-working `list_events` Google Calendar code, using the same `@mcp.tool()` pattern and same config wiring — mechanics are already proven, remaining work is mostly transplanting real logic in.

---

## The two message formats in a tool call

There are **two distinct JSON formats** involved whenever a tool gets used — easy to conflate, worth keeping separate.

### Format 1 — Anthropic's tool_use format
- **Used between**: Claude Desktop ↔ the LLM (Claude model, via Anthropic's API)
- Fixed/documented as part of the **Anthropic API spec** — the model was trained to produce this exact structure when it decides to use a tool.
- Example (model deciding to call a tool):
  ```json
  { "type": "tool_use", "id": "toolu_01A2b3", "name": "say_hello", "input": { "name": "ABC" } }
  ```
- Example (result fed back to the model):
  ```json
  { "type": "tool_result", "tool_use_id": "toolu_01A2b3", "content": "Hello, ABC!" }
  ```
- The LLM **never sees Format 2** directly — it only ever speaks Format 1.

### Format 2 — MCP protocol (JSON-RPC 2.0)
- **Used between**: Claude Desktop ↔ the MCP server (our Python script)
- Public, open, documented spec (the actual "Model Context Protocol") — NOT proprietary to Anthropic. This is what lets any MCP client talk to any MCP server, and vice versa.
- Discovery example (`tools/list`) — happens once, at connection time:
  ```json
  // request
  { "jsonrpc": "2.0", "id": 1, "method": "tools/list" }
  // response
  { "jsonrpc": "2.0", "id": 1, "result": { "tools": [ { "name": "say_hello", "description": "...", "inputSchema": {...} } ] } }
  ```
- Invocation example (`tools/call`) — happens every single time a tool is actually called (not just once):
  ```json
  // request
  { "jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": { "name": "say_hello", "arguments": { "name": "ABC" } } }
  // response
  { "jsonrpc": "2.0", "id": 2, "result": { "content": [ { "type": "text", "text": "Hello, ABC!" } ] } }
  ```
- The MCP server **never sees Format 1** directly — it only ever speaks Format 2.

### Claude Desktop's role: the translator
- Claude Desktop is the ONLY component that speaks both formats — because it's the only thing directly talking to both the LLM and the MCP server.
- Full round trip for one tool call: plain text (user) → **Format 1** (model decides to call tool) → *(permission prompt shown here — not a wire format, just UI)* → **Format 2** (sent to server) → *[real Python function call happens here]* → **Format 2** (server responds) → **Format 1** (result fed back to model) → plain text (final reply to user).
- Format 1 and Format 2 each appear **twice** per tool call — once going out toward execution, once coming back with the result. Discovery (Format 2, `tools/list`) is the only piece that's genuinely once-per-connection, not once-per-call.
- Every message in JSON-RPC (Format 2) carries an `"id"` — pairs requests with matching responses since multiple things could be in flight.

### How tool triggering actually works (three-layer handoff)
1. **The LLM decides** whether/how to call a tool — generates a Format 1 `tool_use` block based on your message + the tool list learned during discovery. Not a hardcoded rule — a generated output, same mechanism as any other model output.
2. **Claude Desktop's client-side logic** intercepts this, shows the permission prompt before proceeding (safety gate, not part of either wire format).
3. **The MCP SDK's dispatch logic** (server-side) receives the Format 2 `tools/call` message, looks up the tool name in its internal registry (built during discovery from `@mcp.tool()`), and makes the actual, literal Python function call.

### How discovery builds the registry (recap)
- `FastMCP("name")` + `@mcp.tool()` decorators build an internal registry (tool name → function + schema) the moment the script starts running — before any client even connects.
- `mcp.run(transport="stdio")` starts listening; when a client connects and sends `tools/list`, the SDK reads this registry and reports it back automatically (not code you write yourself).

---

## Phase 4 continued: calendar_server.py (real tool, replacing hello_server.py)

- New file, separate from `list_events.py` (which stays as the standalone "proof it works" script). Reuses the same `get_credentials()` OAuth logic verbatim — already proven working, nothing changed there.
- Same `@mcp.tool()` pattern as `hello_server.py`, just wrapping the real calendar logic instead of a toy greeting.

### New concepts vs. hello_server.py

**Optional parameter with a default value**
```python
def list_events(max_results: int = 10) -> str:
```
- `= 10` makes the parameter optional in the generated MCP schema. Claude can omit it (uses default 10) or supply a specific value (e.g. `max_results=3` for "show me my next 3 events"). Type hints + defaults directly shape what the LLM is required vs. allowed to omit.

**`return` instead of `print` — critical structural difference**
- The original `list_events.py` used `print()` since a human was reading terminal output directly.
- MCP tools must **return** a value instead — the return value is what becomes the tool's result (gets wrapped into the Format 2 `content` block, eventually reaches the model as Format 1's `tool_result`).
- Error handling also returns a message string (`return f"An error occurred: {error}"`) instead of printing it — otherwise the client would silently get nothing back.

**Why print() is actually dangerous in an MCP server (not just "wasted output")**
- **stdout is the exact channel Claude Desktop reads MCP protocol (Format 2, JSON-RPC) messages from.** It's a reserved, structured channel once a server is running under MCP — not a free-for-all output stream like a normal script.
- A stray `print()` writes plain text into that same stdout stream, which Claude Desktop expects to contain ONLY valid JSON-RPC messages → causes a parsing error / corrupted message / broken connection.
- **Rule**: any debug output in a real MCP server must go to `stderr`, never `print()` (which defaults to stdout).

**How `return` actually becomes a Format 2 message on the wire**
1. Function does `return <value>` — a plain Python value, nothing special.
2. The `FastMCP` framework (SDK code, not something you write) catches that return value.
3. SDK wraps it into the proper Format 2 structure, e.g.:
   ```json
   { "jsonrpc": "2.0", "id": 2, "result": { "content": [ { "type": "text", "text": "<returned string>" } ] } }
   ```
4. SDK writes that complete JSON-RPC message to stdout — the only thing that's supposed to touch stdout during normal operation.
- **Takeaway**: you never manually format JSON-RPC or touch stdout yourself — you just return normal Python values; the SDK handles turning that into a properly structured protocol message. This is exactly why a stray `print()` is a real bug, not just noise — it injects raw non-JSON-RPC text into a channel meant only for the SDK's own structured messages.

### Server lifecycle — when do the configured servers actually run?
- Servers are launched by **Claude Desktop itself**, at its own startup — not on-demand per request, not started manually.
- On launch, Claude Desktop reads `claude_desktop_config.json` and immediately spawns a subprocess for **every** entry under `mcpServers` — so all configured servers (e.g. both `hello-server` and `calendar-server`) start together, run continuously in the background, and stay alive for as long as Claude Desktop is open.
- Discovery (`tools/list`) happens right after each server launches — so the full tool list from every configured server is known before you even open a chat window.
- Verifiable in Task Manager: one `python.exe` process per configured server, running the whole time Claude Desktop is open.
- This is why a config edit requires a **full restart** — the spawned processes and loaded config are fixed at Claude Desktop's own startup.
- Contrast with the planned localhost/HTTP version: there, the server would be started **manually** by the user, running independently in its own terminal regardless of whether Claude Desktop is open — Claude Desktop would just be a client connecting to an already-running service, not the one spawning/owning it.

### Full end-to-end trace, one complete example
Scenario: Claude Desktop is open (servers already running in the background). User asks for calendar events.

1. **Startup (already happened)**: launching Claude Desktop spawns both configured server processes immediately; each completes discovery, so Claude Desktop already knows about tools like `say_hello` and `list_events` before any chat starts.
2. **User asks a question** — e.g. "what's on my calendar next week?" (plain text).
3. **Claude Desktop → LLM (Format 1)**: sends the user's message plus the full list of discovered tools from *every* configured server (not just calendar-server).
4. **LLM → Claude Desktop (Format 1)**: the model's response *is* a `tool_use` block — e.g. `name: "list_events"` with whatever arguments it decides on (for this tool, only `max_results` is available — there's no date-range parameter, so "next week" has to be approximated by the LLM as some result count, or it may ask for clarification. A real current limitation shaped directly by how the tool's schema was designed).
5. **Claude Desktop → correct MCP server (Format 2)**: translates the `tool_use` block into a `tools/call` JSON-RPC message, sent over stdio to whichever server owns that tool.
6. **Server SDK dispatches**: looks up the tool in its registry, calls the actual Python function, which calls the real Google Calendar API and gets results.
7. **Server → Claude Desktop (Format 2)**: function's return value gets wrapped into a JSON-RPC result message, sent back over stdio.
8. **Claude Desktop → LLM (Format 1)**: translates the Format 2 result into a `tool_result` block, feeds it back to the model.
9. **LLM → Claude Desktop (Format 1)**: model generates the final natural-language reply based on the tool result.
10. **Claude Desktop displays the reply** to the user as plain text.

---

## COMPLETE REFERENCE TRACE — real example, all layers, with sample data

Scenario: user asks "What's on my calendar?" — `calendar-server` already running, discovery already done.

**1. User → Claude Desktop** (plain text)
```
What's on my calendar?
```

**2. Claude Desktop → LLM** (Format 1 — Anthropic API request; includes full discovered tool list from ALL configured servers, not just calendar-server)
```json
{
  "messages": [{"role": "user", "content": "What's on my calendar?"}],
  "tools": [
    {"name": "say_hello", "description": "...", "input_schema": {...}},
    {"name": "list_events", "description": "...", "input_schema": {"max_results": "integer, default 10"}}
  ]
}
```

**3. LLM → Claude Desktop** (Format 1 — tool_use block)
```json
{
  "type": "tool_use",
  "id": "toolu_01xYz",
  "name": "list_events",
  "input": { "max_results": 10 }
}
```
Note: tool has no date-range parameter, only a result count — model approximates "what's on my calendar" this way.

**4. Claude Desktop → MCP server** (Format 2 — JSON-RPC `tools/call`, over stdio)
```json
{
  "jsonrpc": "2.0",
  "id": 7,
  "method": "tools/call",
  "params": { "name": "list_events", "arguments": { "max_results": 10 } }
}
```

**5. MCP server → Google Calendar API** (a THIRD, separate format — Google's own REST/HTTPS API, not Format 1 or Format 2)
```
GET https://www.googleapis.com/calendar/v3/calendars/primary/events
    ?timeMin=2026-07-20T...Z
    &maxResults=10
    &singleEvents=true
    &orderBy=startTime
Authorization: Bearer <access_token_from_token.json>
```

**6. Google Calendar API → MCP server** (Google's REST JSON response)
```json
{
  "items": [
    {
      "summary": "Demo for Claude",
      "start": { "dateTime": "2026-07-23T16:00:00+05:30" },
      "end": { "dateTime": "2026-07-23T17:00:00+05:30" }
    }
  ]
}
```
Python code in `list_events()` processes this into a plain string: `"2026-07-23T16:00:00+05:30  Demo for Claude"`.

**7. MCP server → Claude Desktop** (Format 2 — JSON-RPC result)
```json
{
  "jsonrpc": "2.0",
  "id": 7,
  "result": {
    "content": [ { "type": "text", "text": "2026-07-23T16:00:00+05:30  Demo for Claude" } ]
  }
}
```

**8. Claude Desktop → LLM** (Format 1 — tool_result block)
```json
{
  "type": "tool_result",
  "tool_use_id": "toolu_01xYz",
  "content": "2026-07-23T16:00:00+05:30  Demo for Claude"
}
```

**9. LLM → Claude Desktop** (Format 1 — final plain text response, no special structure now)
```json
{ "type": "text", "text": "Found one event coming up: Demo for Claude, Thursday, July 23, 4:00–5:00 PM..." }
```

**10. Claude Desktop → user** (plain text, rendered in UI)
```
Found one now — looks like it was just added:
Demo for Claude
Thursday, July 23, 4:00 – 5:00 PM (IST)
Nothing else on the calendar for the next 7 days.
```

**Key thing to remember**: 3 distinct formats total, not 2 — Format 1 (Claude Desktop ↔ LLM), Format 2 (Claude Desktop ↔ MCP server), and a third, ordinary REST/HTTPS format (MCP server ↔ Google Calendar API, or any external API a tool happens to call). The MCP server isn't just a relay — it does real independent work (auth check/refresh, the actual HTTP call, parsing the response) between receiving the Format 2 request and sending the Format 2 result.

---

## Milestone: Real Google Calendar MCP tool working end-to-end ✅
- `calendar_server.py` (`list_events` tool, wraps proven auth logic from `list_events.py`) successfully wired into Claude Desktop alongside `hello-server`
- Asked Claude Desktop "What's on my calendar?" — got back a real, correct answer sourced from actual Google Calendar data, permission-gated, full round trip through Format 1 ↔ Format 2 ↔ Google's REST API
- Current limitation noted: tool only supports `max_results` (a count), not an actual date range — good candidate for the "expand later" phase
- **Possible next steps**: add `create_event`, add proper date-range filtering (`days_ahead` param or explicit start/end), try the localhost/HTTP transport variant, or clean up `hello-server` from config once confident everything's stable

---

## Commands Reference

```
python --version                          # check Python version
cd "D:\AI\MCP\Google Calendar"             # navigate to project (quotes needed — space in folder name)
venv\Scripts\activate                      # activate venv — prompt shows (venv) when active
python list_events.py                      # run standalone auth+events script
python calendar_server.py                  # sanity-check MCP server doesn't crash (Ctrl+C to stop — it will "hang", that's expected)
```

Claude Desktop config file (MSIX install):
```
C:\Users\Helllo\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json
```

---

## Next step already planned: adding `create_event` (write access)

Discussed but not yet built — plan to attempt this one mostly unassisted as a practice rep.

1. **Change scope** in `calendar_server.py`: `SCOPES = ["https://www.googleapis.com/auth/calendar.events"]` (or full `.../auth/calendar`)
2. **Delete `token.json`** — old one was issued under read-only scope, won't work for writes; next run triggers a fresh browser consent (will show a broader permission request)
3. **Write `create_event(...)`** — new function, same `@mcp.tool()` pattern, needs:
   - Parameters: likely title/summary, start time, end time (maybe attendees/description later) — each documented in the docstring, since the LLM has to correctly extract structured data from a natural sentence like "schedule a meeting tomorrow at 3pm for an hour" — a harder parsing job than `list_events`'s single optional integer
   - Calls `service.events().insert(...)` instead of `.list(...)`
   - Builds Google's expected nested payload shape (`{"summary": ..., "start": {"dateTime": ..., "timeZone": ...}, "end": {...}}`) — inverse of how `list_events` currently parses a response
   - Design decision to make: strict ISO datetime input from the LLM (more reliable) vs. looser natural input parsed in code (more natural, more complexity)
4. **No Claude Desktop config change needed** — it points at the whole file/process, not individual functions; a restart alone picks up the new tool via discovery
5. Also worth adding at some point: proper date-range filtering for `list_events` (currently only supports a result count via `max_results`, not an actual date range — a known current limitation)

## Other possible extensions (not yet started)
- Try the **localhost/HTTP transport** variant (`streamable-http` instead of `stdio`) — server runs independently, started manually, Claude Desktop just connects as a client rather than owning the process
- Clean up `hello-server` from config once confident everything's stable (optional — no harm in leaving it as a sanity-check fallback)
