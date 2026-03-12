class nest::base::homebrew {
  class { 'homebrew':
    user => $nest::user,
  }
  ->
  Package <| provider == 'tap' |>
  ->
  Package <|
    provider == 'brew' or
    provider == 'brewcask' or
    provider == 'homebrew' or
    provider == undef
  |>


  #
  # Module fixes
  #
  include homebrew::install

  # Install can't run through 'su'
  Exec <| title == 'install-homebrew' |> {
    command     => $homebrew::install::homebrew_install_cmd,
    environment => "HOME=/Users/${homebrew::user}",
    user        => $homebrew::user,
  }

  Exec <| tag == 'homebrew::install' and title != 'install-homebrew' |> {
    require => Exec['install-homebrew'],
  }

  File <| tag == 'homebrew::install' |> {
    require => Exec['install-homebrew'],
  }
}
