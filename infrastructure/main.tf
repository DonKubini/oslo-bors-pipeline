# 1. Define the required Terraform providers
terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.0"
    }
  }
}

# 2. Configure the AzureRM Provider
provider "azurerm" {
  # The features block is strictly required to enable the provider, even if it is left empty
  features {}
}

# 3. Create the Resource Group
resource "azurerm_resource_group" "rg" {
  name     = var.rg_name
  location = var.location
}