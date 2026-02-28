datacenter = "uptonx"
data_dir   = "/opt/nomad/data"

advertise {
  http = "192.168.1.95"
  rpc  = "192.168.1.95"
  serf = "192.168.1.95"
}

server {
  enabled = false
}

client {
  enabled = true
  servers = ["192.168.1.101:4647"]

  meta {
    "node.type" = "workstation"
    "node.gpu"  = "amd-rx7600"
  }
}

plugin "raw_exec" {
  config {
    enabled = true
  }
}

plugin "docker" {
  config {
    allow_privileged = true
    volumes {
      enabled = true
    }
  }
}

telemetry {
  collection_interval        = "10s"
  prometheus_metrics          = true
  publish_allocation_metrics  = true
  publish_node_metrics        = true
}
