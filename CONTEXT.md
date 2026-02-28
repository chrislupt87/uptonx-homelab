# UptonX Homelab — Infrastructure Context

## Orchestration
- **Scheduler**: HashiCorp Nomad 1.11.2
- **Datacenter**: uptonx
- **Region**: global

## Nodes

| Host | IP | Role | Notes |
|------|----|------|-------|
| helm | 192.168.1.77 | Proxmox host | Hypervisor, manages LXCs/VMs |
| nomad (CT 100) | 192.168.1.101 | Nomad server + client | Ubuntu 24.04 LXC on helm |
| uptonx-workstation | 192.168.1.95 | Nomad client | Kubuntu, AMD RX 7600 GPU |

## Nomad Cluster

- **Server**: 192.168.1.101 (single server, bootstrap_expect=1)
- **Clients**: 192.168.1.101, 192.168.1.95
- **UI**: http://192.168.1.101:4646
- **Configs**: `nomad/configs/`

## Running Services

| Service | Type | Status |
|---------|------|--------|
| Nomad cluster | Infrastructure | 2 nodes, operational |

## Network

- Subnet: 192.168.1.0/24
- Gateway: 192.168.1.1

## Other Infrastructure

| Host | IP | Role |
|------|----|------|
| pbs | 192.168.1.19 | Proxmox Backup Server |
| nas | 192.168.1.11 | UGreen NAS (user: chris-admin) |
| aux | 192.168.1.18 | Available |
| aux2 | 192.168.1.80 | Available |
| ai | 192.168.1.69 | AI NUC (available) |
| msi | 192.168.1.74 | MSI workstation (available) |
