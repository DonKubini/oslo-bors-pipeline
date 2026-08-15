# Get the details of the currently logged-in Azure user
data "azurerm_client_config" "current" {}

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

# 4. Create an Azure Container Registry (Basic Tier)
resource "azurerm_container_registry" "acr" {
  name                = "osloborsacrtf" # Must be globally unique, lowercase, no dashes
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  sku                 = "Basic"
  admin_enabled       = true
}

# 5. Create the Azure SQL Logical Server
resource "azurerm_mssql_server" "sql_server" {
  name                         = "oslo-bors-server-tf" # Must be globally unique
  resource_group_name          = azurerm_resource_group.rg.name
  location                     = azurerm_resource_group.rg.location
  version                      = "12.0"
  administrator_login          = var.sql_admin_username
  administrator_login_password = var.sql_admin_password

  # Tell Terraform that YOU are the Entra Administrator
  azuread_administrator {
    login_username = var.azure_user_email
    object_id      = data.azurerm_client_config.current.object_id
  }
}

# Automated database creation. Free tier is not available when deployed via Terraform.
# We will create the database manually in the Azure Portal after the server is provisioned.
/* 
# 6. Create the Azure SQL Database (Free Tier)
resource "azurerm_mssql_database" "sql_db" {
  name      = "oslo-bors-db-tf"
  server_id = azurerm_mssql_server.sql_server.id
  sku_name  = "GP_S_Gen5_2" # General Purpose, Serverless, Gen5, 2 vCores
  max_size_gb = 32 # Maximum size for the free tier
  min_capacity = 0.5 # Minimum vCores for serverless
  auto_pause_delay_in_minutes = 60 # Auto-pause after 60 minutes of inactivity
  zone_redundant = false # Free tier does not support zone redundancy

  lifecycle {
    prevent_destroy = true
  }
}
*/

# 6. Manage already created database. Free tier is not available when deployed via Terraform.
resource "azurerm_mssql_database" "sql_db" {
  name      = "oslo-bors-db-tf"
  server_id = azurerm_mssql_server.sql_server.id
  sku_name  = "GP_S_Gen5_2" 
  storage_account_type = "Local" # Needs to be set to Local for the free tier

  lifecycle {
    prevent_destroy = true
  }
}

# 7. Allow Azure Services to access the SQL Server
resource "azurerm_mssql_firewall_rule" "allow_azure_services" {
  name             = "AllowAzureServices"
  server_id        = azurerm_mssql_server.sql_server.id
  
  # In Azure, setting start and end IP to 0.0.0.0 is the specific flag to "Allow Azure Services"
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

# 8. Create a User-Assigned Managed Identity (Entra ID)
resource "azurerm_user_assigned_identity" "job_identity" {
  name                = "oslo-bors-job-identity"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
}

# 9. Grant the Identity 'AcrPull' permissions on your Container Registry
resource "azurerm_role_assignment" "acr_pull" {
  scope                = azurerm_container_registry.acr.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.job_identity.principal_id
}

# 10. Create the Container Apps Environment
resource "azurerm_container_app_environment" "env" {
  name                = "oslo-bors-env-tf"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
}

# 11. Create the Scheduled Container App Job
resource "azurerm_container_app_job" "monthly_job" {
  name                         = "oslo-bors-monthly-job-tf"
  resource_group_name          = azurerm_resource_group.rg.name
  location                     = azurerm_resource_group.rg.location
  container_app_environment_id = azurerm_container_app_environment.env.id
  
  replica_timeout_in_seconds   = 1800
  replica_retry_limit          = 1

  # Attach the Entra ID we created
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.job_identity.id]
  }

  # Tell the app to use this specific identity to authenticate with the registry
  registry {
    server   = azurerm_container_registry.acr.login_server
    identity = azurerm_user_assigned_identity.job_identity.id
  }

  schedule_trigger_config {
    cron_expression = "0 0 1 * *"
  }

  template {
    container {
      name   = "pipeline-container"
      # We use a dummy image for the first deployment so the job provisions successfully
      image  = "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest"
      cpu    = 0.5
      memory = "1Gi"

      # Pass environment variables dynamically
      env {
        name  = "AZURE_SQL_SERVER"
        value = azurerm_mssql_server.sql_server.fully_qualified_domain_name
      }
      env {
        name  = "AZURE_SQL_DATABASE"
        value = azurerm_mssql_database.sql_db.name
      }

      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.job_identity.client_id
      }
    }
  }

  # Tell Terraform to let GitHub Actions manage the Docker image updates
  lifecycle {
    ignore_changes = [
      template[0].container[0].image
    ]
  }
  # EXPLICIT DEPENDENCY: Do not create the job until the pull permissions are fully granted!
  depends_on = [
    azurerm_role_assignment.acr_pull
  ]
}

## Setting up identity for github actions to update the job image automatically

# 1. Create a Managed Identity specifically for GitHub Actions
resource "azurerm_user_assigned_identity" "github_identity" {
  name                = "github-actions-identity"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
}

# 2. Give it Contributor access to your Resource Group so it can update the Job
resource "azurerm_role_assignment" "github_contributor" {
  scope                = azurerm_resource_group.rg.id
  role_definition_name = "Contributor"
  principal_id         = azurerm_user_assigned_identity.github_identity.principal_id
}

# 3. Create the OIDC Federation (The Trust Handshake)
resource "azurerm_federated_identity_credential" "github_oidc" {
  name                       = "github-actions-federation"
  audience                   = ["api://AzureADTokenExchange"]
  issuer                     = "https://token.actions.githubusercontent.com"
  user_assigned_identity_id  = azurerm_user_assigned_identity.github_identity.id
  subject                    = "repo:${var.github_repository}:ref:refs/heads/main"
}