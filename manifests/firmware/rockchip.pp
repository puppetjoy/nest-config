class nest::firmware::rockchip {
  vcsrepo { '/usr/src/rkbin':
    ensure   => latest,
    provider => git,
    source   => 'https://gitlab.james.tl/nest/forks/rkbin.git',
    revision => 'rockchip',
  }
}
