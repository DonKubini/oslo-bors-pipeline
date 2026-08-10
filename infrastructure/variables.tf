variable "location" {
  description = "The Azure region to deploy our resources"
  type        = string
  default     = "westeurope"
}

variable "rg_name" {
  description = "The name of our new Terraform resource group"
  type        = string
  default     = "oslo-bors-terraform-rg"
}