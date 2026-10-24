# The images the deploy pushes (docker buildx bake -f infra/images.hcl), tagged
# ${REGISTRY}/<app>:${TAG}, with their layers cached in GitHub's cache as in CI.
variable "REGISTRY" { default = "localhost" }
variable "TAG" { default = "dev" }

group "default" {
  targets = ["simulator", "engine", "dashboard", "notifier", "webhook"]
}

target "app" {
  name       = app
  matrix     = { app = ["simulator", "engine", "dashboard", "notifier"] }
  context    = app
  tags       = ["${REGISTRY}/${app}:${TAG}"]
  platforms  = ["linux/amd64"]
  cache-from = ["type=gha,scope=${app}"]
  cache-to   = ["type=gha,scope=${app},mode=max"]
}

target "webhook" {
  context    = "scripts"
  dockerfile = "webhook.Dockerfile"
  tags       = ["${REGISTRY}/webhook:${TAG}"]
  platforms  = ["linux/amd64"]
}
