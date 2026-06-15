# Shared GitLab CLI package for Hermes runtimes and agent tool images
class nest::tool::gitlab_cli {
  nest::lib::package { 'dev-util/gitlab-cli':
    ensure   => installed,
    unstable => true,
  }
}
