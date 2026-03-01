id        = "test-data"
name      = "test-data"
type      = "csi"
plugin_id = "nfs"

capability {
  access_mode     = "multi-node-multi-writer"
  attachment_mode = "file-system"
}

context {
  server            = "192.168.1.11"
  share             = "/volume1/UptonX/test"
  mountPermissions  = "0"
}

mount_options {
  fs_type     = "nfs"
  mount_flags = ["vers=3", "nolock"]
}
