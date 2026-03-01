job "nfs-csi-nodes" {
  datacenters = ["uptonx"]
  type        = "system"

  group "nodes" {
    task "node" {
      driver = "docker"

      config {
        image = "registry.k8s.io/sig-storage/nfsplugin:v4.13.1"

        args = [
          "--v=5",
          "--nodeid=${attr.unique.hostname}",
          "--endpoint=unix:///csi/csi.sock",
        ]

        privileged = true
      }

      csi_plugin {
        id        = "nfs"
        type      = "node"
        mount_dir = "/csi"
      }

      resources {
        cpu    = 100
        memory = 128
      }
    }
  }
}
