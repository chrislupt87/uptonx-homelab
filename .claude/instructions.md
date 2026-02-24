# Claude Code Instructions — UptonX Homelab

Read this file and README.md at the start of every session.

## Who I Am
Chris — self-employed, running UptonX homelab in Toronto.
Shell: zsh. No cloud if self-hosted exists. Copy-paste ready commands always.

## Node Roles (Swarm Labels)
| Label   | Node            | IP             |
|---------|-----------------|----------------|
| control | Control node    | 192.168.1.77   |
| ai      | AI NUC          | 192.168.1.69   |
| gpu     | MSI workstation | 192.168.1.74   |
| camera  | Frigate node    | 192.168.1.80   |
| general | Aux             | 192.168.1.18   |

## Stack File Pattern
Every service gets a stack.yml using placement constraints to pin to the right node.
All services share the `uptonx` overlay network.
Secrets via Docker secrets or /opt/uptonx/env/ files — never hardcoded.

## When Adding A Service
1. Create services/<category>/<service>/stack.yml
2. Create services/<category>/<service>/README.md
3. Add to main README.md service map
