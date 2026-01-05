output "instance_name" {
  description = "Name of the VM instance"
  value       = google_compute_instance.vm_instance.name
}

output "instance_zone" {
  description = "Zone of the VM instance"
  value       = google_compute_instance.vm_instance.zone
}

output "instance_ip" {
  description = "Public IP of the VM instance"
  value       = google_compute_instance.vm_instance.network_interface[0].access_config[0].nat_ip
}

output "ssh_command" {
  description = "Command to SSH into the instance"
  value       = "gcloud compute ssh ${google_compute_instance.vm_instance.name} --zone ${google_compute_instance.vm_instance.zone}"
}
