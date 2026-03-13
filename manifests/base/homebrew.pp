class nest::base::homebrew {
  require nest::base::sudo

  class { 'homebrew':
    user => $nest::user,
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
