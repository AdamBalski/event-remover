from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
import os
import sys
import threading
import urllib
import urllib.request
import uuid
from datetime import datetime, timezone

from matching import parse_expression

"""
Takes an iCal event and returns True iff event is not a lecture
:param event: iCal event as a string (RFC5545 formatted VEVENT statement)
:returns: True iff event is not a lecture
"""
EVENTS_PREDICATE = lambda event: "Wykład" not in event\
        and "Blokada" not in event

DEFAULT_FILTER_EXPRESSION = 'NOT "Wykład" AND NOT "Blokada"'

thread_local_storage = threading.local()

def reset_trace_id():
    thread_local_storage.trace_id = str(uuid.uuid4())
    return thread_local_storage.trace_id

def get_trace_id():
    if (value := getattr(thread_local_storage, "trace_id", None)) is not None:
        return value
    return reset_trace_id()

def get_trace_id_if_present():
    return getattr(thread_local_storage, "trace_id", None)

class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        trace_id = getattr(record, "trace_id", None) or get_trace_id_if_present()
        if trace_id:
            payload["trace_id"] = str(trace_id)

        for field in ("method", "path", "status_code", "remote_addr", "port"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)

def configure_logging():
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)

configure_logging()
LOGGER = logging.getLogger("event_remover")

def filter_events(ical_text, predicate):
    """
    Parse all events as text between "BEGIN:VEVENT\n" and "END:VEVENT\n" including both directives,
    pass the events to the predicate given as argument and then return the ical string without events
    that don't match the predicate
    """
    # https://datatracker.ietf.org/doc/html/rfc5545
    result = []
    for line in (lines := iter(ical_text.split("\r\n"))):
        if line != "BEGIN:VEVENT":
            result.append(line)
            continue
        curr_event = ["BEGIN:VEVENT"]
        while (curr := next(lines)) != "END:VEVENT":
            curr_event.append(curr)
        curr_event.append("END:VEVENT")
        
        if predicate('\r\n'.join(curr_event)):
            result.extend(curr_event)

    result.append("") # adds newline at the end to adhere to RFC5545
    return '\r\n'.join(result)

def parse_usos_imports_param(qs):
    if "usosImports" not in qs:
        return []
    raw_payload = qs["usosImports"][0]
    try:
        parsed = json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid usosImports payload: {exc}")
    if not isinstance(parsed, list):
        raise ValueError("Invalid usosImports payload: expected a JSON array")
    normalized = []
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        details = str(entry.get("details", ""))
        name = str(entry.get("name", "")).strip()
        events = entry.get("events")
        if not isinstance(events, list):
            events = []
        normalized.append({"details": details, "name": name, "events": events})
    return normalized

def normalize_usos_event_entry(entry):
    if not isinstance(entry, dict):
        return None

    def _clean(value):
        return str(value).strip()

    date = _clean(entry.get("date", ""))
    start = _clean(entry.get("start", ""))
    end = _clean(entry.get("end", ""))
    if not (date and start and end):
        return None
    room = _clean(entry.get("room", ""))
    building = _clean(entry.get("building", ""))
    return {
        "date": date,
        "start": start,
        "end": end,
        "room": room,
        "building": building,
    }

def escape_ical_text(text: str) -> str:
    safe = text.replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,')
    safe = safe.replace('\r', '').replace('\n', '\\n')
    return safe

def to_ical_datetime(date_str: str, time_str: str):
    try:
        parsed = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        return parsed.strftime("%Y%m%dT%H%M%S")
    except ValueError:
        return None

def build_usos_event(summary: str, entry: dict):
    start_dt = to_ical_datetime(entry["date"], entry["start"])
    end_dt = to_ical_datetime(entry["date"], entry["end"])
    if not start_dt or not end_dt:
        return None
    location_parts = [entry.get("building", "").strip(), entry.get("room", "").strip()]
    location_parts = [part for part in location_parts if part]
    location = " - ".join(location_parts)
    description = f"Imported from USOS\\n{entry['date']} {entry['start']} - {entry['end']}"
    now = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uuid.uuid4()}@event-remover",
        f"DTSTAMP:{now}",
        f"DTSTART:{start_dt}",
        f"DTEND:{end_dt}",
        f"SUMMARY:{escape_ical_text(summary)}"
    ]
    if location:
        lines.append(f"LOCATION:{escape_ical_text(location)}")
    lines.append(f"DESCRIPTION:{escape_ical_text(description)}")
    lines.append("END:VEVENT")
    return '\r\n'.join(lines) + '\r\n'

def build_usos_events(usos_pairs):
    events = []
    for pair in usos_pairs:
        summary = pair.get("name", "").strip()
        if not summary:
            continue
        raw_events = pair.get("events")
        if not isinstance(raw_events, list) or not raw_events:
            continue
        normalized_entries = []
        for raw_entry in raw_events:
            normalized = normalize_usos_event_entry(raw_entry)
            if normalized:
                normalized_entries.append(normalized)
        if not normalized_entries:
            continue
        for entry in normalized_entries:
            event_block = build_usos_event(summary, entry)
            if event_block:
                events.append(event_block)
    return events

def append_events_to_ics(ics_text: str, events):
    if not events:
        return ics_text
    joined = ''.join(events)
    marker = "\r\nEND:VCALENDAR"
    idx = ics_text.rfind(marker)
    if idx == -1:
        return ics_text + joined
    prefix = ics_text[:idx]
    suffix = ics_text[idx:]
    if not prefix.endswith("\r\n"):
        prefix += "\r\n"
    return prefix + joined + suffix

def get_from_env_or_fail(var: str) -> str:
    res = os.environ.get(var)
    if res:
        return res
    raise Exception(f"Env variables {var} is required, but was not supplied, failing...")

UI_HTML="Error: Not loaded"
class RequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        _ = format
        _ = args
        return

    def __send_response(self, status_code, response):
        self.send_response(status_code)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Type', 'text/html')
        encoded = response.encode('utf-8')
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def __not_found(self, url):
        return 404, ""

    def __index(self, url):
        return 200, UI_HTML

    def __healthz(self, url):
        return 200, "OK"

    def __is_url_smelly(self, decoded):
        return not decoded.startswith('https://plan.agh.edu.pl')

    def __transformed(self, url):
        qs = urllib.parse.parse_qs(url.query)
        if "path" not in qs:
            return 400, f"Expecting a URL encoded link to an ics file on the Internet in 'path' query parameter. Trace id: {get_trace_id()}"
        decoded = urllib.parse.unquote(qs["path"][0])
        if self.__is_url_smelly(decoded):
            return 400, f"This URL smells funky. We only accept URLs prefixed by 'https://plan.agh.edu.pl', Trace id: {get_trace_id()}"
        
        # Build predicate based on optional 'q' parameter using matching.py
        query_expr = qs.get("q", [DEFAULT_FILTER_EXPRESSION])[0]
        try:
            expr = parse_expression(query_expr)
        except Exception as e:
            LOGGER.exception("query.parse_failed")
            return 400, f"Invalid query expression in 'q': {e}. Trace id: {get_trace_id()}"

        try:
            usos_pairs = parse_usos_imports_param(qs)
        except ValueError as e:
            LOGGER.exception("usos_imports.parse_failed")
            return 400, f"Invalid usosImports payload: {e}. Trace id: {get_trace_id()}"

        predicate = lambda event: expr.match(event)

        try:
            LOGGER.info(
                "ics.fetch_started",
                extra={"path": decoded},
            )
            with urllib.request.urlopen(decoded) as response:
                ics = response.read().decode('utf-8')
                result = filter_events(ics, predicate)
                extra_events = build_usos_events(usos_pairs)
                result = append_events_to_ics(result, extra_events)
                return 200, result
        except Exception:
            LOGGER.exception("ics.processing_failed")
            return 500, "Something bad happened"


    def __resolve_path(self, url):
        path_handlers = { "/": self.__index, "/transformed": self.__transformed, "/healthz": self.__healthz }
        path = url.path
        if path not in path_handlers:
            return self.__not_found
        return path_handlers[path]

    def do_GET(self):
        reset_trace_id()
        LOGGER.info(
            "request.received",
            extra={
                "method": "GET",
                "path": self.path,
                "remote_addr": self.client_address[0],
            },
        )
        url = urllib.parse.urlparse(self.path)
        handler = self.__resolve_path(url)
        status_code, response = handler(url)
        self.__send_response(status_code, response)
        LOGGER.info(
            "request.completed",
            extra={
                "method": "GET",
                "path": self.path,
                "status_code": status_code,
                "remote_addr": self.client_address[0],
            },
        )

def load_ui():
    with open("./ui.html", "r", encoding="utf-8") as file:
        global UI_HTML
        UI_HTML = file.read().replace("<<ORIGIN>>", get_from_env_or_fail("BASE_URL"))

def run(server_class=HTTPServer, handler_class=RequestHandler):
    port = int(get_from_env_or_fail("PORT"))
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    LOGGER.info("server.starting", extra={"port": port})
    try:
        load_ui()
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()
    LOGGER.info("server.stopped")

if __name__ == '__main__':
    run()
