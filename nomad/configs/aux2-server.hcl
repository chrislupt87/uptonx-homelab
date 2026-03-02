datacenter = "uptonx"
data_dir   = "/opt/nomad/data"

advertise {
  http = "192.168.1.102"
  rpc  = "192.168.1.102"
  serf = "192.168.1.102"
}

server {
  enabled          = true
  bootstrap_expect = 3
  server_join {
    retry_join = ["192.168.1.101", "192.168.1.104"]
  }
}

client {
  enabled = true
  servers = ["192.168.1.101:4647", "192.168.1.102:4647", "192.168.1.104:4647"]

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
