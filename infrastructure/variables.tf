variable "location" {
  description = "The Azure region to deploy our resources"
  type        = string
  default     = "swedencentral"
}

variable "rg_name" {
  description = "The name of our new Terraform resource group"
  type        = string
  default     = "oslo-bors-terraform-rg"
}

variable "sql_admin_username" {
  description = "The administrator username of the SQL logical server"
  type        = string
  default     = "donkubini"
}

variable "sql_admin_password" {
  description = "The administrator password of the SQL logical server"
  type        = string
  sensitive   = true
  default     = "OsloBors2K15" # In a real enterprise, we would never hardcode this!
}

variable "azure_user_email" {
  description = "The email of the Azure user who will be the Entra Administrator"
  type        = string
  default     = "sismajak@cvut.cz"
}