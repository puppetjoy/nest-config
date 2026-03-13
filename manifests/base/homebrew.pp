class nest::base::homebrew {
  class { 'homebrew':
    user    => $nest::user,
    require => Class['nest::base::sudo'],
  }
  ->
  Package <|
    provider == 'brew' or
    provider == 'brewcask' or
    provider == 'homebrew' or
    provider == 'tap' or
    provider == undef
  |>
}
