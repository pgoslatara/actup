terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

resource "google_compute_instance" "vm_instance" {
  name         = var.instance_name
  machine_type = "e2-standard-32"

  allow_stopping_for_update = true
  boot_disk {
    initialize_params {
      image = "projects/cos-cloud/global/images/family/cos-stable"
      size  = 2048 # 2 TB
      type  = "pd-ssd"
    }
  }
  metadata_startup_script = <<EOT
#!/bin/bash
# --- Pull and Run the Container Image ---
docker run --name actup --pull=always -d ghcr.io/pgoslatara/actup:latest
EOT
  network_interface {
    access_config {}
    network = "default"
  }
  tags = ["ssh-access"]
  zone = var.zone
}

resource "google_compute_firewall" "allow_ssh_from_anywhere" {
  project = var.project_id
  name    = "allow-ssh-from-anywhere-to-my-instance"
  network = "default"
  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["ssh-access"]
  description   = "Allows SSH (port 22) from all IPs to instances tagged 'ssh-access'."
}
