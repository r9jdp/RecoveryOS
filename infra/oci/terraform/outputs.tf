output "instance_id" {
  description = "OCI instance OCID."
  value       = oci_core_instance.recoveryos.id
}

output "public_ip" {
  description = "Public IP to use for DNS A records. The address remains attached for the life of this instance."
  value       = oci_core_instance.recoveryos.public_ip
}

output "ssh_command" {
  description = "Initial SSH command for the dedicated deploy user."
  value       = "ssh recoveryos@${oci_core_instance.recoveryos.public_ip}"
}
