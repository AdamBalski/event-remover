# event-remover
Transform your AGH timetable iCal feed by removing events that match a filter (by default: lectures and placeholder blocks).

This is a tiny HTTP service that:
- Serves a simple UI (`ui.html`) to build a transformed link.
- Fetches your original iCal (.ics) from `https://plan.agh.edu.pl/...`.
- Filters events according to an expression (default: `NOT "Wykład" AND NOT "Blokada"`).
- Returns a valid RFC5545 iCal with matching events removed.

## How it works
- `run.py` exposes endpoints using Python's `http.server`.
  - `GET /` serves the UI (from `ui.html`).
  - `GET /transformed?path=<url-encoded-ics-url>[&q=<expr>]` fetches the original ICS, filters it, and returns transformed ICS.
  - `GET /healthz` returns `OK` for readiness checks.
- `matching.py` implements a small expression parser and evaluator used for event matching.
- Events are parsed as text blocks between `BEGIN:VEVENT` and `END:VEVENT` and tested with the predicate.

## UI usage (`/`)
- Paste your original AGH iCal URL (must start with `https://plan.agh.edu.pl/`).
- Optionally provide a filter expression (see below). Default is `NOT "Wykład" AND NOT "Blokada"`.
- Click "Transform" to get a new link pointing to `/transformed?...` on this service.

You can then import the transformed link into your calendar app.

## API
### `GET /transformed`
Parameters:
- `path` (required): URL-encoded original ICS URL (must start with `https://plan.agh.edu.pl`).
- `q` (optional): filter expression. Defaults to `NOT "Wykład" AND NOT "Blokada"`.

Responses:
- `200 OK` with transformed ICS
- `400 Bad Request` if the URL is invalid (wrong origin) or the filter expression is invalid.
- `500 Internal Server Error` for unexpected failures.

## Filtering syntax
The `q` parameter is parsed by a simple recursive-descent parser supporting:
- Quoted literals: `"some phrase"` (double quotes, `\"` escapes supported inside quotes)
- Operators: `NOT`, `AND`, `OR`
- Parentheses: `( ... )`

Precedence:
1. `NOT`
2. `AND`
3. `OR`

Semantics:
- A literal matches if the quoted text is a substring of the raw text of a `VEVENT` block.
- Operators combine sub-expressions in the obvious way.

Examples:
- Exclude lectures and placeholder blocks (default):
  - `NOT "Wykład" AND NOT "Blokada"`
- Keep only labs:
  - `"Laboratorium"`
- Exclude labs or exams:
  - `NOT ("Laboratorium" OR "Egzamin")`
- Exclude placeholder blocks and lectures except for "Image Processing" Lectures
    - `(NOT "Wykład" or "Image Processing") AND NOT "Blokada"`

## Requirements
- Python 3.8+ (standard library only; no external dependencies)
- Environment variables:
    - `PORT` – TCP port to listen on (e.g., `8080`).
    - `ORIGIN` – Base URL used by the UI to construct links (e.g., `http://localhost:8080`).

## Quick start
```bash
export PORT=8080
export ORIGIN="http://localhost:8080"
python3 run.py
# Open http://localhost:8080 in your browser
```


## Logs & troubleshooting
- Logs are written to `./log.log` and to console with timestamps and a per-request trace id.
- If `/transformed` returns 400 with a trace id, check the server logs for the parsing/validation error.
- Ensure your `path` really starts with `https://plan.agh.edu.pl` (hard check in the server).


## Deployment
There is a helper script `deploy.sh` for remote deploys via SSH.

Required environment on the local machine before running `deploy.sh`:
- `REMOTE_USERNAME`, `REMOTE_HOST`, `REMOTE_PORT` – SSH target.
- `PORT`, `ORIGIN` – forwarded to the remote process environment.

What it does:
1. Kills the previous process (`pkill -f 'EVENT_REMOVER'`).
2. Clones/updates the repo.
3. Starts `python3 run.py` under `nohup` with `PORT` and `ORIGIN` set.
4. Waits for `/healthz` to return `OK`.

## License
MIT. See `LICENSE`.
