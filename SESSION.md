# Session Log

## 2026-02-28 — Initial Nomad Cluster Setup

### Completed
- Created Ubuntu 24.04 LXC (CT 100) on helm (192.168.1.77)
  - Hostname: nomad, IP: 192.168.1.101/24
  - 2 cores, 2GB RAM, 512MB swap, 20GB disk
  - Unprivileged, nesting enabled
- Installed packages: curl, wget, unzip, gnupg, lsb-release, ca-certificates
- Enabled root SSH, copied workstation SSH key
- Installed Nomad 1.11.2 server+client on LXC
- Installed Nomad 1.11.2 client on workstation (192.168.1.95)
- Verified 2-node cluster operational (both nodes ready)
- Ran test batch job: "UptonX cluster is alive!"
- Nomad UI accessible at http://192.168.1.101:4646
- Saved configs to repo under nomad/configs/

### Next Steps
- Add more Nomad clients (aux, ai, msi) as needed
- Deploy first real workload (e.g., Traefik, monitoring)
- Set up Nomad ACLs for production use
- Consider Consul for service discovery
- Set up Nomad job specs directory for services
