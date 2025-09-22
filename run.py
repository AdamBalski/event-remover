from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.request
import logging
import uuid
import urllib
import threading
import os
import logging

logging.basicConfig(level=logging.DEBUG)

logFormatter = logging.Formatter("%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s")
rootLogger = logging.getLogger()

fileHandler = logging.FileHandler("./log.log")
fileHandler.setFormatter(logFormatter)
rootLogger.addHandler(fileHandler)

consoleHandler = logging.StreamHandler()
consoleHandler.setFormatter(logFormatter)
rootLogger.addHandler(consoleHandler)

"""
Takes an iCal event and returns True iff event is not a lecture
:param event: iCal event as a string (RFC5545 formatted VEVENT statement)
:returns: True iff event is not a lecture
"""
EVENTS_PREDICATE = lambda event: "Wykład" not in event\
        and "Blokada" not in event

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

def get_from_env_or_fail(var: str) -> str:
    res = os.environ.get(var)
    if res:
        return res
    raise Exception(f"Env variables {var} is required, but was not supplied, failing...")

thread_local_storage = threading.local()
def reset_trace_id():
    thread_local_storage.trace_id = uuid.uuid4()
    return thread_local_storage.trace_id
def get_trace_id():
    if (value := getattr(thread_local_storage, "trace_id", None)) is not None:
        return value
    return reset_trace_id()

UI_HTML="Error: Not loaded"
class RequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __send_response(self, status_code, response):
        print("CORS request received")
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
        return "OK"

    def __is_url_smelly(self, decoded):
        return not decoded.startswith('https://plan.agh.edu.pl')

    def __transformed(self, url):
        qs = urllib.parse.parse_qs(url.query)
        if "path" not in qs:
            return 400, f"Expecting a URL encoded link to an ics file on the Internet in 'path' query parameter. Trace id: {get_trace_id()}"
        decoded = urllib.parse.unquote(qs["path"][0])
        if self.__is_url_smelly(decoded):
            return 400, f"This URL smells funky. We only accept URLs prefixed by 'https://plan.agh.edu.pl', Trace id: {get_trace_id()}"
        
        try:
            logging.debug(f"Fetching URL: {decoded}. Trace id: {get_trace_id()}")
            with urllib.request.urlopen(decoded) as response:
                ics = response.read().decode('utf-8')
                result = filter_events(ics, EVENTS_PREDICATE)
                return 200, result
        except Exception as e:
            print(e)
            return 500, "Something bad happened"


    def __resolve_path(self, url):
        path_handlers = { "/": self.__index, "/transformed": self.__transformed, "/healthz": self.__healthz }
        path = url.path
        if path not in path_handlers:
            return self.__not_found
        return path_handlers[path]

    def do_GET(self):
        reset_trace_id()
        logging.info("GET request,\nPath: %s\nHeaders:\n%s\nTraceId: %s\n", str(self.path), str(self.headers), get_trace_id())
        response = "GET request for {}".format(self.path).encode('utf-8')
        url = urllib.parse.urlparse(self.path)
        handler = self.__resolve_path(url)
        status_code, response = handler(url)
        self.__send_response(status_code, response)

def load_ui():
    with open("./ui.html", "r") as file:
        global UI_HTML
        UI_HTML = file.read().replace("<<ORIGIN>>", get_from_env_or_fail("ORIGIN"))

def run(server_class=HTTPServer, handler_class=RequestHandler):
    server_address = ('', int(get_from_env_or_fail("PORT")))
    httpd = server_class(server_address, handler_class)
    logging.info('Server starting...\n')
    try:
        load_ui()
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()
    logging.info('Stopping server...\n')

if __name__ == '__main__':
    run()

