class nest::tool::minicom {
  include 'nest' # for nest::user

  User <| title == $nest::user |> {
    groups +> 'dialout',
  }

  nest::lib::package { 'net-dialup/minicom':
    ensure => installed,
  }
}
