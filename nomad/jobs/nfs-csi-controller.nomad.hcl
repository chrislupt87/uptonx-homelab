job "nfs-csi-controller" {
  datacenters = ["uptonx"]
  type        = "service"

  group "controller" {
    count = 1

    task "controller" {
      driver = "docker"

      config {
        image = "registry.k8s.io/sig-storage/nfsplugin:v4.13.1"

        args = [
          "--v=5",
          "--nodeid=${attr.unique.hostname}",
          "--endpoint=unix:///csi/csi.sock",
        ]

        # Required for LXC nodes where Docker AppArmor profiles can't load
        security_opt = ["apparmor=unconfined"]
      }

      csi_plugin {
        id        = "nfs"
        type      = "controller"
        mount_dir = "/csi"
      }

      resources {
        cpu    = 100
        memory = 128
      }
    }
  }
}
