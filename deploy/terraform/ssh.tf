###############################################################################
# SSH key pair for CVM access
############################################################################---

resource "tencentcloud_key_pair" "main" {
  key_name   = replace("${var.project_name}_ssh_key", "-", "_")
  public_key = var.ssh_public_key
}
