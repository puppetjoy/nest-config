define nest::lib::repo (
  Boolean          $default  = false,
  Boolean          $unstable = false,
  Optional[String] $url      = undef,
) {
  include 'nest::lib::repos'

  tag 'profile'

  $default_content = $default ? {
    true    => "[DEFAULT]\nmain-repo = ${name}\n\n",
    default => '',
  }

  if $url {
    $repo_content = @("END_REPO")
      [${name}]
      location = /var/db/repos/${name}
      sync-type = git
      sync-uri = ${url}
      sync-depth = 1
      sync-git-verify-commit-signature = no
      auto-sync = yes
      | END_REPO

    vcsrepo { "/var/db/repos/${name}":
      ensure   => present,
      force    => true, # clone over existing content
      provider => git,
      source   => $url,
      depth    => 1,
    }
  } else {
    $repo_content = @("END_REPO")
      [${name}]
      location = /var/db/repos/${name}
      auto-sync = no
      | END_REPO
  }

  $accept_keywords_ensure = $unstable ? {
    true    => present,
    default => absent,
  }

  file {
    default:
      mode  => '0644',
      owner => 'root',
      group => 'root',
    ;

    "/etc/portage/repos.conf/${name}.conf":
      content => "${default_content}${repo_content}",
    ;

    "/etc/portage/package.accept_keywords/${name}":
      ensure  => $accept_keywords_ensure,
      content => "*/*::${name} ~*\n",
    ;

    "/var/db/repos/${name}":
      ensure => directory,
    ;
  }
}
