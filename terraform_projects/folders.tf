# Carpeta Organizacional GOES (folders/402619928367)
resource "google_folder" "goes" {
  count        = var.goes_folder_id == "" ? 1 : 0
  display_name = "GOES"
  parent       = "organizations/${var.org_id}"
}

locals {
  resolved_folder_id = var.goes_folder_id != "" ? var.goes_folder_id : google_folder.goes[0].name
}
