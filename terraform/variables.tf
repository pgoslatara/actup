variable "project_id" {
  description = "The GCP project ID"
  type        = string
}

variable "region" {
  description = "The GCP region"
  type        = string
}

variable "zone" {
  description = "The GCP zone"
  type        = string
}

variable "instance_name" {
  description = "Name of the VM instance"
  type        = string
  default     = "actup-vm"
}
