#!/usr/bin/env python3
"""Lightweight system stats API for the kiosk dashboard.

Polls Proxmox hosts via their API and serves aggregated stats as JSON.
Runs on port 8088.
"""
import json
import ssl
import time
import threading
import urllib.request
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler

HOSTS = [
    {"name": "helm",  "ip": "192.168.1.77",  "node": "helm"},
    {"name": "aux",   "ip": "192.168.1.18",  "node": "aux"},
    {"name": "aux2",  "ip": "192.168.1.80",  "node": "aux2"},
    {"name": "ai",    "ip": "192.168.1.69",  "node": "ai"},
    {"name": "msi",   "ip": "192.168.1.74",  "node": "msi"},
]

PVE_USER = "root@pam"
PVE_PASS = "Terry87!"
POLL_INTERVAL = 10
PORT = 8088

# Shared state
stats_cache = []
ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE


def get_pve_ticket(ip):
    """Authenticate to Proxmox and return (ticket, csrf_token)."""
    url = f"https://{ip}:8006/api2/json/access/ticket"
    data = urllib.parse.urlencode({"username": PVE_USER, "password": PVE_PASS}).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, context=ssl_ctx, timeout=5) as resp:
        result = json.loads(resp.read())["data"]
        return result["ticket"], result["CSRFPreventionToken"]


def get_node_status(ip, node, ticket):
    """Fetch node status from Proxmox API."""
    url = f"https://{ip}:8006/api2/json/nodes/{node}/status"
    req = urllib.request.Request(url)
    req.add_header("Cookie", f"PVEAuthCookie={ticket}")
    with urllib.request.urlopen(req, context=ssl_ctx, timeout=5) as resp:
        return json.loads(resp.read())["data"]


def format_bytes(b):
    """Format bytes to human-readable string."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


def format_uptime(seconds):
    """Format seconds to human-readable uptime."""
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    if days > 0:
        return f"{days}d {hours}h"
    mins = int((seconds % 3600) // 60)
    return f"{hours}h {mins}m"


def poll_host(host):
    """Poll a single host and return stats dict."""
    try:
        ticket, _ = get_pve_ticket(host["ip"])
        status = get_node_status(host["ip"], host["node"], ticket)

        cpu_pct = status.get("cpu", 0) * 100
        mem_used = status.get("memory", {}).get("used", 0)
        mem_total = status.get("memory", {}).get("total", 0)
        mem_pct = (mem_used / mem_total * 100) if mem_total > 0 else 0
        loadavg = status.get("loadavg", ["-", "-", "-"])
        uptime = status.get("uptime", 0)

        return {
            "name": host["name"],
            "ip": host["ip"],
            "online": True,
            "cpu": round(cpu_pct, 1),
            "mem_used": format_bytes(mem_used),
            "mem_total": format_bytes(mem_total),
            "mem_pct": round(mem_pct, 1),
            "load": f"{loadavg[0]} / {loadavg[1]} / {loadavg[2]}",
            "uptime": format_uptime(uptime),
        }
    except Exception:
        return {
            "name": host["name"],
            "ip": host["ip"],
            "online": False,
            "cpu": 0, "mem_used": "-", "mem_total": "-", "mem_pct": 0,
            "load": "-", "uptime": "-",
        }


def poll_loop():
    """Background loop that polls all hosts."""
    global stats_cache
    while True:
        results = []
        for host in HOSTS:
            results.append(poll_host(host))
        stats_cache = results
        time.sleep(POLL_INTERVAL)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/stats":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(stats_cache).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress request logs


if __name__ == "__main__":
    # Start polling in background
    t = threading.Thread(target=poll_loop, daemon=True)
    t.start()

    # Wait for first poll
    time.sleep(2)

    print(f"Stats API listening on :{PORT}")
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()
