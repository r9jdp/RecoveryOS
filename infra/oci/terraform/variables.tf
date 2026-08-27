variable "tenancy_ocid" {
  description = "Root tenancy OCID used to discover availability domains."
  type        = string
}

variable "compartment_ocid" {
  description = "Compartment in which RecoveryOS resources are created."
  type        = string
}

variable "region" {
  description = "OCI home region, for example ap-hyderabad-1."
  type        = string
}

variable "availability_domain_index" {
  description = "Availability domain index. Change this when Always Free A1 capacity is unavailable."
  type        = number
  default     = 0
}

variable "ssh_public_key" {
  description = "OpenSSH public key installed for the recoveryos deploy user."
  type        = string

  validation {
    condition     = can(regex("^(ssh-ed25519|ssh-rsa) ", var.ssh_public_key))
    error_message = "ssh_public_key must be an OpenSSH public key, not a private key or file path."
  }
}

variable "ssh_ingress_cidr" {
  description = "Single trusted operator CIDR allowed to SSH, normally your current public_ip/32."
  type        = string

  validation {
    condition     = can(cidrnetmask(var.ssh_ingress_cidr)) && var.ssh_ingress_cidr != "0.0.0.0/0"
    error_message = "Use a valid restricted IPv4 CIDR; unrestricted SSH is intentionally rejected."
  }
}

variable "instance_display_name" {
  description = "OCI display name for the RecoveryOS VM."
  type        = string
  default     = "recoveryos"
}

variable "instance_ocpus" {
  description = "Ampere A1 OCPUs. Keep total tenancy usage within Always Free limits."
  type        = number
  default     = 2

  validation {
    condition     = var.instance_ocpus >= 1 && var.instance_ocpus <= 4
    error_message = "instance_ocpus must remain between 1 and the Always Free A1 tenancy limit of 4."
  }
}

variable "instance_memory_gb" {
  description = "Ampere A1 memory in GiB. Twelve GiB supports staging and production on one VM."
  type        = number
  default     = 12

  validation {
    condition     = var.instance_memory_gb >= 6 && var.instance_memory_gb <= 24
    error_message = "instance_memory_gb must remain between 6 and the Always Free A1 tenancy limit of 24 GiB."
  }
}

variable "boot_volume_size_gb" {
  description = "Boot volume size in GiB. Confirm aggregate block-volume use remains free eligible."
  type        = number
  default     = 50

  validation {
    condition     = var.boot_volume_size_gb >= 50 && var.boot_volume_size_gb <= 200
    error_message = "boot_volume_size_gb must remain within the OCI 50-200 GiB boot-volume range and free-tier aggregate budget."
  }
}

variable "vcn_cidr" {
  description = "VCN IPv4 CIDR."
  type        = string
  default     = "10.42.0.0/16"
}

variable "subnet_cidr" {
  description = "Public subnet IPv4 CIDR."
  type        = string
  default     = "10.42.1.0/24"
}
