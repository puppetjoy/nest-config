class nest::firmware::rockchip {
  vcsrepo { '/usr/src/rkbin':
    ensure   => latest,
    provider => git,
    source   => 'https://gitlab.joyfullee.me/nest/forks/rkbin.git',
    revision => 'rockchip',
  }
}
