class nest::base::homebrew {
  class { 'homebrew':
    install_user => $nest::user,
  }

  Class['homebrew'] -> Package <| provider == 'homebrew' or provider == undef |>
}
