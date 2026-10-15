"""
Preview helper: stand in for the store's orders API.

app/services/get_data.py calls GET <orders_url> with start_date/end_date
(DD/MM/YYYY, one request per calendar year) and a bearer token, and expects a
JSON list of order dicts. This tiny server answers that call from the dataset
written by make_mock_orders.py, so the whole app can run locally with no store.
It is throwaway preview scaffolding, not part of the application.
"""
import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
ORDERS = json.loads((HERE / "mock_orders.json").read_text(encoding="utf-8"))

PORT = 5058
API_DATE_FORMAT = "%d/%m/%Y"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path.rstrip("/") != "/wp-json/wc-last-orders-json/v1/orders":
            self._json(404, {"error": "not found", "path": parsed.path})
            return

        params = parse_qs(parsed.query)
        start_raw = (params.get("start_date") or [None])[0]
        end_raw = (params.get("end_date") or [None])[0]

        rows = ORDERS
        try:
            if start_raw:
                start = datetime.strptime(start_raw, API_DATE_FORMAT)
                rows = [o for o in rows if datetime.strptime(o["order_date"], "%Y-%m-%d %H:%M:%S") >= start]
            if end_raw:
                # Both ends included: the API's end date is a whole day.
                end = datetime.strptime(end_raw, API_DATE_FORMAT).replace(hour=23, minute=59, second=59)
                rows = [o for o in rows if datetime.strptime(o["order_date"], "%Y-%m-%d %H:%M:%S") <= end]
        except ValueError as exc:
            self._json(400, {"error": f"bad date: {exc}"})
            return

        print(f"  served {len(rows):5d} orders  ({start_raw} .. {end_raw})")
        self._json(200, rows)

    def _json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # the print above is the useful log


if __name__ == "__main__":
    print(f"mock orders API on http://127.0.0.1:{PORT}/wp-json/wc-last-orders-json/v1/orders")
    print(f"{len(ORDERS)} orders loaded")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
