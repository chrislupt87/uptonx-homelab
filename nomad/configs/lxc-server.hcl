datacenter = "uptonx"
data_dir   = "/opt/nomad/data"

advertise {
  http = "192.168.1.101"
  rpc  = "192.168.1.101"
  serf = "192.168.1.101"
}

server {
  enabled          = true
  bootstrap_expect = 1
}

client {
  enabled = true
  servers = ["192.168.1.101:4647"]

  meta {
    "node.type" = "server-lxc"
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
