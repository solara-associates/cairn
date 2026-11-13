terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }

  # Local backend for now (R0-16 scope). Before any real apply, move this to
  # a GCS backend bucket per environment — see README.md "What Allan must
  # provide" — so state isn't only on one engineer's machine.
  backend "local" {
    path = "terraform.tfstate"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
