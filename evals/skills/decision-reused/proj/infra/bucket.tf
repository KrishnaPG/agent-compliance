resource "google_storage_bucket" "exports" {
  name     = "exports"
  location = "EU"
  lifecycle_rule {
    condition { age = 30 }
    action { type = "Delete" }
  }
}
