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

resource "google_service_account" "actup_service_account" {
  account_id = "sa-actup"
}

resource "random_id" "bucket_suffix" {
  byte_length = 4
}

resource "google_storage_bucket" "actup_bucket" {
  name          = "actup-${random_id.bucket_suffix.hex}"
  location      = "EUROPE-WEST4"
  force_destroy = false
}

resource "google_storage_bucket_iam_member" "gcs_rw_access" {
  bucket = google_storage_bucket.actup_bucket.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.actup_service_account.email}"
}

resource "google_compute_instance" "vm_instance" {
  name         = var.instance_name
  machine_type = "custom-24-65536" # 32 CPU, 64 GB RAM

  allow_stopping_for_update = true
  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-11"
      size  = 4096 # 4 TB
      type  = "pd-ssd"
    }
  }
  metadata = {
    startup-script = <<-EOF
      #!/bin/bash
      echo "Starting Docker installation via startup script..."

      # Install Docker
      sudo apt-get update
      sudo apt-get install -y ca-certificates curl gnupg htop lsb-release nload python3-pip

      # Add Docker's official GPG key
      sudo mkdir -p /etc/apt/keyrings
      curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

      # Set up the Docker repository
      echo \
        "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
        $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

      sudo apt-get update
      sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

      sudo usermod -aG docker debian

      # Start and enable Docker service
      sudo systemctl start docker
      sudo systemctl enable docker

      echo "Docker installation complete. Verifying Docker version..."
      sudo docker --version

      # Install gsutil
      sudo apt-get install -y google-cloud-sdk

      # Configure SSD
      mkdir -p /actup/temp_scan
      sudo chown -R 1000:1000 /actup

      # Pull image
      docker pull ghcr.io/pgoslatara/actup:latest

      # Setup
      mkdir -p /actup/db
      chmod -R 777 /actup

      echo "Startup script finished."
    EOF
  }
  network_interface {
    access_config {}
    network = "default"
  }
  service_account {
    email  = google_service_account.actup_service_account.email
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
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
