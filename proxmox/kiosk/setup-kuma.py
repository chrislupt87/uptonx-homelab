#!/usr/bin/env python3
"""One-time setup for Uptime Kuma using uptime-kuma-api."""
from uptime_kuma_api import UptimeKumaApi, MonitorType

api = UptimeKumaApi("http://127.0.0.1:3001")

# Setup admin (first run only)
try:
    api.setup("admin", "Terry87!")
    print("Admin account created")
except Exception as e:
    print(f"Setup: {e}")

api.login("admin", "Terry87!")
print("Logged in")

# Add monitors
monitors = [
    {"name": "Frigate NVR",       "type": MonitorType.HTTP, "url": "http://192.168.1.18:5000"},
    {"name": "Traefik",           "type": MonitorType.HTTP, "url": "http://192.168.1.15:8080/api/version"},
    {"name": "Portainer",         "type": MonitorType.HTTP, "url": "http://192.168.1.23:9000"},
    {"name": "Double-Take",       "type": MonitorType.HTTP, "url": "http://192.168.1.69:3000"},
    {"name": "CompreFace",        "type": MonitorType.HTTP, "url": "http://192.168.1.69:8000"},
    {"name": "n8n Video",         "type": MonitorType.HTTP, "url": "http://192.168.1.69:5678"},
    {"name": "Email RAG",         "type": MonitorType.HTTP, "url": "http://192.168.1.110:3000"},
    {"name": "Open WebUI",        "type": MonitorType.HTTP, "url": "http://192.168.1.110:8080"},
    {"name": "Technitium DNS",    "type": MonitorType.HTTP, "url": "http://192.168.1.51:5380"},
    {"name": "Home Assistant",    "type": MonitorType.HTTP, "url": "http://192.168.1.14:8123"},
    {"name": "helm (Proxmox)",    "type": MonitorType.PORT, "hostname": "192.168.1.77", "port": 8006},
    {"name": "aux (Proxmox)",     "type": MonitorType.PORT, "hostname": "192.168.1.18", "port": 8006},
    {"name": "aux2 (Proxmox)",    "type": MonitorType.PORT, "hostname": "192.168.1.80", "port": 8006},
    {"name": "ai NUC (Proxmox)",  "type": MonitorType.PORT, "hostname": "192.168.1.69", "port": 8006},
    {"name": "msi (Proxmox)",     "type": MonitorType.PORT, "hostname": "192.168.1.74", "port": 8006},
    {"name": "Audio Pipeline",    "type": MonitorType.HTTP, "url": "http://192.168.1.74:8090"},
]

monitor_ids = []
for m in monitors:
    try:
        result = api.add_monitor(**m, interval=60)
        mid = result.get("monitorID", "?")
        monitor_ids.append(mid)
        print(f"  Added: {m['name']} (id={mid})")
    except Exception as e:
        print(f"  Failed: {m['name']}: {e}")

print(f"\nTotal: {len(monitor_ids)} monitors")

# Create status page
try:
    api.add_status_page("Homelab Status", "homelab")
    print("Status page created")
except Exception as e:
    print(f"Status page: {e}")

# Save with monitor groups
if not monitor_ids:
    monitor_ids = list(range(1, 17))

api.save_status_page(
    slug="homelab",
    title="Homelab Status",
    theme="dark",
    published=True,
    showTags=False,
    showPoweredBy=False,
    publicGroupList=[
        {
            "name": "Services",
            "weight": 1,
            "monitorList": [{"id": mid} for mid in monitor_ids[:10]],
        },
        {
            "name": "Infrastructure",
            "weight": 2,
            "monitorList": [{"id": mid} for mid in monitor_ids[10:]],
        },
    ],
)
print("Status page saved with monitor groups")

api.disconnect()
print("Done!")
