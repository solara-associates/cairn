module "network" {
  source = "./modules/network"
  cidr   = "10.20.0.0/16"
}

module "database" {
  source   = "git::https://example.invalid/modules/db.git"
  version  = "2.0.0"
  replicas = 2
}
