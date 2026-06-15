# Generic Hermes agent terminal-runtime tool image
#
# The image stays profile-data-free, but includes the shared CLI tooling agents
# need to exercise normal GitLab MR workflows from container-backed terminals.
class nest::tool::agent {
  contain nest::tool::gitlab_cli
}
