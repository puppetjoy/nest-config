class nest (
  # Required settings
  String              $kernel_tag,
  Stdlib::Host        $nestfs_hostname,
  Array[Stdlib::Host] $openvpn_servers,

  # Keys and user configuration
  String               $eyaml_public_key,
  Optional[Sensitive]  $eyaml_private_key = undef,
  Optional[String]     $pw_hash           = undef,
  Hash[String, String] $ssh_host_keys     = {},
  Hash[String, String] $ssh_private_keys  = {},
  String               $user              = 'joy',
  String               $user_fullname     = 'Joyful Lee',

  # Service discovery configuration
  Hash[Stdlib::Fqdn, Stdlib::Fqdn]        $cnames       = {},
  Array[Stdlib::Host]                     $cups_servers = [],
  Hash[Stdlib::Host, Integer]             $distcc_hosts = {},
  Hash[Stdlib::Fqdn, Stdlib::IP::Address] $fixed_ips    = {},
  Hash[String, Stdlib::IP::Address]       $host_records = {},
  Hash[Stdlib::Fqdn, Hash]                $hosts        = {},

  # Service toggles
  Boolean $distcc_server = false,
  Boolean $fileserver    = false,
  Boolean $fscache       = true,
  Boolean $puppet        = true,
  Boolean $public_ssh    = false,
  Boolean $router        = false,
  Boolean $vpn_client    = true,

  # System settings
  Optional[String]                  $arm_firmware_tag    = undef,
  Enum['off', 'sway', 'xmonad']     $autologin           = xmonad,
  Optional[Nest::BirdRole]          $bird_role           = undef,
  Enum['systemd', 'u-root']         $bootloader          = systemd,
  Integer[0]                        $boot_menu_delay     = 3,
  Optional[Integer]                 $cpus                = undef,
  Optional[String]                  $dtb_file            = undef,
  Optional[String]                  $dtb_overlay         = undef,
  Array[String]                     $external_interfaces = [],
  Boolean                           $isolate_smt         = false,
  Enum['persistent', 'volatile']    $journal             = persistent,
  Hash[String, Nest::Kconfig]       $kernel_config       = {},
  Array[String]                     $kernel_cmdline      = [],
  String                            $kernel_defconfig    = 'defconfig',
  Boolean                           $kernel_llvm         = false,
  Boolean                           $kexec               = false,
  Optional[String]                  $opensbi_tag         = undef,
  Array[String]                     $reset_filter_rules  = [],
  Optional[String]                  $soc                 = undef,
  Optional[String]                  $srv_zpool           = $facts['rpool'],
  Hash[String, Nest::Kconfig]       $uboot_config        = {},
  Optional[String]                  $uboot_defconfig     = undef,
  Optional[String]                  $uboot_tag           = undef,
  Optional[String]                  $uroot_tag           = undef,
  Optional[Integer]                 $uroot_delay         = undef,
  Enum['tcp', 'udp']                $vpn_transport       = udp,
  Boolean                           $wifi                = false,
  Boolean                           $wifi_power_save     = true,
  Optional[Sensitive[Hash]]         $wlans               = undef,
  Boolean                           $zfs_fork            = false,

  # Mail settings
  Optional[String] $gmail_username   = undef,
  Optional[String] $gmail_password   = undef,
  Enum['nullmailer', 'postfix'] $mta = nullmailer,

  # Package resources
  Array[String]      $packages         = [],
  Hash[String, Hash] $package_env      = {},
  Hash[String, Hash] $package_keywords = {},
  Hash[String, Hash] $package_unmask   = {},

  # Input settings
  Boolean $dvorak       = false,
  Boolean $swap_alt_win = false,

  # Output settings
  Float            $gui_scaling_factor  = 1.0,
  Float            $text_scaling_factor = $gui_scaling_factor,
  Array[String]    $monitor_layout      = [],
  Optional[String] $primary_monitor     = undef,

  # Other nest classes
  Array[String] $classes = [],
) {
  # Calculated values
  if $kernel_tag =~ /v([\d.]+(-rc\d+)?)/ {
    $kernel_version = $1
  } else {
    fail("Failed to determine kernel version from the tag '${kernel_tag}'")
  }

  $dpi = Integer(inline_template('<%= (@text_scaling_factor * 96.0).round %>'))
  $gui_scaling_factor_rounded = Integer(inline_template('<%= @gui_scaling_factor.round %>'))
  $text_scaling_factor_percent_of_gui = Float(inline_template('<%= (@dpi / (@gui_scaling_factor * 96.0)).round(3) %>'))
  $text_scaling_factor_percent_of_rounded_gui = Float(inline_template('<%= (@dpi / (@gui_scaling_factor_rounded * 96.0)).round(3) %>'))

  $console_font_sizes        = [16, 18, 20, 22, 24, 28, 32]
  $console_font_size_ideal   = 16 * $nest::text_scaling_factor
  $console_font_size_smaller = inline_template('<%= @console_font_sizes.reverse.find(16) { |size| size - @console_font_size_ideal <= 0 } %>')
  $console_font_size         = $facts['virtual'] ? {
    'vmware' => min($console_font_sizes),
    default  => $console_font_size_smaller,
  }

  $cursor_sizes        = [24, 32, 36, 40, 48, 64, 96]
  $cursor_size_ideal   = 24 * $nest::gui_scaling_factor
  $cursor_size_smaller = inline_template('<%= @cursor_sizes.reverse.find(24) { |size| size - @cursor_size_ideal <= 0 } %>')
  $cursor_size         = $cursor_size_smaller

  if $cpus {
    $concurrency = $cpus
  } elsif $isolate_smt {
    $concurrency = $facts['processors']['count'] / 2
  } elsif $facts['processors'] and $facts['processors']['count'] {
    $concurrency = $facts['processors']['count']
  } else {
    $concurrency = 1
  }

  # Resource defaults
  if $facts['os'] {
    case $facts['os']['family'] {
      'Gentoo': {
        Firewalld_zone {
          interfaces       => [],
          sources          => [],
          masquerade       => false,
          purge_rich_rules => true,
          purge_services   => true,
          purge_ports      => true,
        }

        # MariaDB defaults
        Mysql::Db {
          charset => 'utf8mb3',
          collate => 'utf8mb3_general_ci',
        }

        Service {
          provider => 'systemd',
        }

        Sysctl {
          target  => '/etc/sysctl.d/nest.conf',
          require => File['/etc/sysctl.d'],
        }

        # Effectively disable resources that can't be managed in containers
        if $facts['is_container'] {
          Service <||> {
            ensure => undef,
          }

          Sysctl <||> {
            apply => false,
          }

          Systemd::Daemon_reload <||> {
            enable => false,
          }
        }
      }

      'windows': {
        Concat {
          # The default is usually 0644, but Windows keeps changing it to 0674, so
          # just accept what it does.
          mode => '0674',
        }

        Package {
          provider => 'chocolatey',
        }
      }
    }
  }

  # Defaults above are dynamically scoped to classes contained below
  # See: https://www.puppet.com/docs/puppet/8/lang_scope.html#dynamic-scope

  # Contain classes and process knockouts from Hiera such that
  # Class['nest'] represents a complete configuration
  $knockouts = $classes.filter |$c| { $c =~ /^--/ }
  contain $classes.filter |$c| { !($c in $knockouts or "--${c}" in $knockouts) }
}
