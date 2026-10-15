###############################################################################
# Data sources
###############################################################################

# Available CVM image — Ubuntu 22.04
data "tencentcloud_image" "ubuntu" {
  image_name_regex = "Ubuntu Server 22.04"
  os_name          = "Ubuntu"
}

# Available zones
data "tencentcloud_zones" "default" {
  product = "cvm"
}
