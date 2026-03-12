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
}
