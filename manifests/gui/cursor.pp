class nest::gui::cursor {
  case $facts['os']['family'] {
    'Gentoo': {
      $icons_dir = '/usr/share/icons'
      
      File {
        owner   => 'root',
        group   => 'root',
        require => Class['nest::gui::plasma'],
      }
    }

    'windows': {
      $icons_dir = 'C:/tools/cygwin/usr/share/icons'

      File {
        owner => 'Administrators',
        group => 'None',
      }
    }
  }

  file {
    default:
      ensure    => directory,
      mode      => '0644',
      recurse   => true,
      force     => true,
      purge     => true,
      backup    => false,
      show_diff => false,
    ;

    "${icons_dir}/breeze_cursors":
      source => 'puppet:///modules/nest/cursors/Breeze',
    ;

    "${icons_dir}/Breeze_Snow":
      source => 'puppet:///modules/nest/cursors/Breeze_Snow',
    ;
  }
}
