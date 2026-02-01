# Library Management System MCP Server (Python)

Modular MCP server exposing the LMS backend as tools over Streamable HTTP.

## Structure
- `app.py` - uvicorn entrypoint; builds the Starlette/FastMCP app.
- `lms_mcp/config.py` - env + settings loader.
- `lms_mcp/http_client.py` - thin httpx client for the LMS API.
- `lms_mcp/middleware.py` - MCP auth + origin checks.
- `lms_mcp/tools.py` - tool registrations (each annotated with endpoint, params, returns).
- `lms_mcp/server.py` - wires FastMCP, tools, middleware, Starlette app.
- `.env.example` - sample configuration.

## Run locally
```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```
MCP endpoint (local): `http://0.0.0.0:8000/mcp`

## Quick setup (summary)
1) Install deps in a venv: `python -m venv .venv && .\.venv\Scripts\activate && pip install -r requirements.txt`
2) Start the server: `python app.py` (defaults to `0.0.0.0:8000` talking to the hosted LMS API).
3) In any MCP-compatible client, add the endpoint `http://127.0.0.1:8000/mcp` (or your remote host). If you set `MCP_API_KEYS`, include `Authorization: Bearer <key>`.
4) Call the `login` tool once with your email/password; all later tools will carry and refresh tokens automatically.

## Connect from an MCP client (local)
Point your MCP-compatible client at the local endpoint: `http://127.0.0.1:8000/mcp`.
If you enabled `MCP_API_KEYS`, include a `Authorization: Bearer <KEY>` header when registering.

## Deploy / remote MCP
With the standard LMS backend deployed, you typically just start the MCP server and connect:
- Start the server: `python app.py` (or `uvicorn app:app --host 0.0.0.0 --port 8000`).
- In your MCP client, register the endpoint `https://<host>/mcp` and, if configured, supply `Authorization: Bearer <MCP_API_KEY>`.
After registration, call the `login` tool once (email/password); later tool calls will auto-attach and refresh tokens.

Environment overrides are optional (e.g., different API URL, custom MCP API keys, or origin allowlist).

Defaults out of the box:
- API base: `https://librarymanagementsystem-be.vercel.app/api`
- MCP API keys: not required
- Allowed origins: `*`
- Host/port: `0.0.0.0:8000`

## Authentication layers
- MCP endpoint: optional `MCP_API_KEYS` (Bearer) + origin allowlist `MCP_ALLOWED_ORIGINS`.
- LMS API: per-tool `access_token` or default `LIBRARY_API_ACCESS_TOKEN`.
- Optional session login: `login(email, password)` caches access/refresh tokens per MCP session and auto-attaches them to later tool calls.

## Login & refresh flow
1) Run the `login` tool once with your email/password (or `auth_login` alias). Password is never stored; only tokens are cached in memory for the current MCP session.
2) All subsequent tools automatically send `Authorization: Bearer <accessToken>`.
3) If the cached token is near expiry, the MCP server silently refreshes it with the stored refresh token before the call.
4) If any API call returns 401, the MCP server attempts one refresh and retries once. If refresh fails, cached tokens are cleared and you'll be asked to log in again.

## Tool coverage (API list)
- Health: `GET /api/health`
- Books (public): `GET /api/books`, `/api/books/search`, `/api/books/{id}`, `/api/books/genres`
- Auth: `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me`, `PUT /api/auth/profile`
- User borrows: `POST /api/borrows`, `PUT /api/borrows/{id}/return`, `PUT /api/borrows/{id}/renew`, `GET /api/borrows/my-borrows`, `GET /api/borrows/current`, `GET /api/borrows/my-fines`, `PUT /api/borrows/{id}/pay-fine`
- Admin borrows: `GET /api/borrows`, `GET /api/borrows/overdue`, `GET /api/borrows/pending`, `PUT /api/borrows/{id}/approve`, `PUT /api/borrows/{id}/reject`
- Wishlist: `GET /api/wishlist`, `POST /api/wishlist/add/{bookId}`, `DELETE /api/wishlist/remove/{bookId}`, `GET /api/wishlist/check/{bookId}`
- Reviews: `GET /api/reviews/book/{bookId}`, `POST /api/reviews`, `PUT /api/reviews/{id}`, `DELETE /api/reviews/{id}`, `GET /api/reviews/my-review/{bookId}`
- Admin books: `POST /api/books`, `PUT /api/books/{id}`, `DELETE /api/books/{id}`
- Admin dashboard/users: `GET /api/admin/dashboard`, `GET /api/admin/users`, `GET /api/admin/users/{id}`, `PUT /api/admin/users/{id}/toggle-status`
- Images helper: builds `/api/images/{id}` URLs (no HTTP call)
