#!/usr/bin/env python3
"""Generate IP allocation PDF for 192.168.1.1 - 192.168.1.125"""

from fpdf import FPDF
from datetime import date

ALLOCATIONS = {
    1: ("Router/Gateway", "Network"),
    11: ("NAS (UGreen)", "Storage"),
    15: ("Traefik (CT 102 on aux2)", "Reverse Proxy"),
    18: ("aux (Proxmox host)", "Hypervisor"),
    19: ("PBS (Proxmox Backup Server)", "Backup"),
    20: ("Gitea (CT 103 on helm) [legacy LXC]", "Swarm: gitea stack"),
    21: ("Portainer (CT 104 on helm) [legacy LXC]", "Swarm: portainer stack"),
    22: ("Infisical (CT 105 on helm) [legacy LXC]", "Swarm: infisical stack"),
    23: ("Swarm Manager (CT 106 on aux)", "Docker Swarm"),
    24: ("Swarm Worker 1 (CT 107 on helm)", "Docker Swarm"),
    25: ("Swarm Worker 2 (CT 108 on msi)", "Docker Swarm"),
    51: ("Technitium DNS (CT 101 on aux2)", "DNS Server"),
    69: ("ai NUC (Proxmox host)", "Hypervisor"),
    74: ("msi (Proxmox host) + Audio Pipeline", "Hypervisor"),
    77: ("helm (Proxmox host)", "Hypervisor"),
    80: ("aux2 (Proxmox host)", "Hypervisor"),
    95: ("Workstation (GPU)", "Workstation"),
    110: ("Email RAG + Open WebUI (VM 401 on ai)", "AI / VM"),
}

pdf = FPDF()
pdf.set_auto_page_break(auto=True, margin=15)
pdf.add_page()

# Title
pdf.set_font("Helvetica", "B", 18)
pdf.cell(0, 12, "Uptonx Homelab - IP Allocation", new_x="LMARGIN", new_y="NEXT")
pdf.set_font("Helvetica", "", 10)
pdf.set_text_color(100, 100, 100)
pdf.cell(0, 6, f"192.168.1.1 - 192.168.1.125  |  Generated {date.today()}", new_x="LMARGIN", new_y="NEXT")
pdf.ln(4)

# Table header
pdf.set_text_color(0, 0, 0)
pdf.set_font("Helvetica", "B", 10)
pdf.set_fill_color(40, 40, 40)
pdf.set_text_color(255, 255, 255)
pdf.cell(30, 8, "IP", border=1, fill=True)
pdf.cell(90, 8, "Host / Service", border=1, fill=True)
pdf.cell(60, 8, "Role", border=1, fill=True)
pdf.cell(0, 8, "Status", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")

pdf.set_font("Helvetica", "", 9)
pdf.set_text_color(0, 0, 0)

for i in range(1, 126):
    ip = f"192.168.1.{i}"
    if i in ALLOCATIONS:
        host, role = ALLOCATIONS[i]
        status = "USED"
        # Color: green-ish for used
        pdf.set_fill_color(220, 240, 220)
    else:
        host = ""
        role = ""
        status = "FREE"
        pdf.set_fill_color(245, 245, 245)

    pdf.cell(30, 7, ip, border=1, fill=True)
    pdf.cell(90, 7, host, border=1, fill=True)
    pdf.cell(60, 7, role, border=1, fill=True)

    if status == "USED":
        pdf.set_text_color(0, 120, 0)
    else:
        pdf.set_text_color(160, 160, 160)
    pdf.cell(0, 7, status, border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)

# Summary
pdf.ln(6)
used = len(ALLOCATIONS)
free = 125 - used
pdf.set_font("Helvetica", "B", 11)
pdf.cell(0, 8, f"Summary: {used} used, {free} free out of 125 addresses", new_x="LMARGIN", new_y="NEXT")

pdf.output("/home/chris/uptonx-homelab/uptonx-ip-allocation.pdf")
print("Generated uptonx-ip-allocation.pdf")
