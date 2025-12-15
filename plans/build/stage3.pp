# @summary Build complete images for specific hosts
#
# Use bin/build script to run this plan!
#
# @param container Build container name
# @param hostname Hostname of the image
# @param platform Build for this platform
# @param variant Build using this variant
# @param build Build the image
# @param deploy Deploy the image
# @param emerge_default_opts Override default emerge options (e.g. --jobs=4)
# @param hostroot Where the image gets deployed
# @param id Build ID
# @param init Initialize the build container
# @param makeopts Override make flags (e.g. -j4)
# @param puppet_environment Puppet environment to use for final configuration
# @param profile Switch to this profile
# @param qemu_user_targets CPU architectures to emulate
# @param rsync_private_key_var Environment variable for rsync private key
plan nest::build::stage3 (
  String            $container,
  String            $hostname,
  String            $platform,
  String            $variant,
  Boolean           $build                 = true,
  Optional[String]  $cluster               = undef,
  Boolean           $deploy                = false,
  Optional[String]  $emerge_default_opts   = undef,
  String            $hostroot              = "/nest/hosts/${hostname}",
  Optional[Numeric] $id                    = undef,
  Boolean           $init                  = true,
  Optional[String]  $makeopts              = undef,
  Optional[String]  $puppet_environment    = undef,
  Optional[String]  $profile               = undef,
  Array[String]     $qemu_user_targets     = lookup('nest::build::qemu_user_targets', default_value => []),
  String            $rsync_private_key_var = 'NEST_RSYNC_PRIVATE_KEY',
) {
  $ssh_auth_sock = system::env('SSH_AUTH_SOCK')
  $target = Target.new(name => $hostname, uri => "podman://${container}")

  if $init {
    run_command("podman rm -f ${container}", 'localhost', 'Stop and remove existing build container')

    if !empty($ssh_auth_sock) and run_command("test -S ${ssh_auth_sock}", 'localhost', 'Check SSH_AUTH_SOCK', '_catch_errors' => true).ok {
      $ssh_auth_sock_volume = "--volume=${ssh_auth_sock}:${ssh_auth_sock}:ro"
    } else {
      $ssh_auth_sock_volume = ''
    }

    $podman_create_cmd = @("CREATE"/L)
      podman create \
      --init \
      --hostname=${hostname} \
      --name=${container} \
      --no-hosts \
      --pull=always \
      --volume=/falcon:/falcon \
      --volume=/nest:/nest \
      ${ssh_auth_sock_volume} \
      ${qemu_user_targets.map |$arch| { "--volume=/usr/bin/qemu-${arch}:/usr/bin/qemu-${arch}:ro" }.join(' ')} \
      "nest/stage2/${variant}:${platform}" \
      sleep infinity
      | CREATE

    run_command($podman_create_cmd, 'localhost', 'Create build container')
  }

  if $build {
    run_command("podman start ${container}", 'localhost', 'Start build container')

    apply_prep($target)

    # Preserve and restore host identity info
    apply($target, '_description' => 'Set up host identity info') {
      file { $hostroot:
        ensure => directory,
        mode   => '0555',
        owner  => 'root',
        group  => 'root',
      }
      ->
      exec { 'systemd-machine-id-setup':
        command => "/usr/bin/systemd-machine-id-setup --root=${hostroot.shellquote}",
        creates => "${hostroot}/etc/machine-id",
      }
      ->
      file {
        '/etc/machine-id':
          source => "${hostroot}/etc/machine-id",
        ;

        "${hostroot}/etc/puppetlabs":
          ensure => directory,
          mode   => '0755',
          owner  => 'root',
          group  => 'root',
        ;

        "${hostroot}/etc/puppetlabs/puppet":
          ensure => directory,
          mode   => '0750',
          owner  => 'root',
          group  => 'puppet',
        ;

        "${hostroot}/etc/puppetlabs/puppet/ssl":
          ensure => directory,
          mode   => '0771',
          owner  => 'puppet',
          group  => 'puppet',
        ;

        # Puppet Agent will correct permissions on these files
        '/etc/puppetlabs/puppet/ssl':
          ensure  => directory,
          source  => "${hostroot}/etc/puppetlabs/puppet/ssl",
          recurse => true,
        ;
      }

      if $cluster {
        file { '/etc/puppetlabs/puppet/csr_attributes.yaml':
          mode    => '0640',
          owner   => 'root',
          group   => 'puppet',
          content => {
            'extension_requests' => {
              'pp_cluster' => $cluster,
            },
          }.stdlib::to_yaml,
        }
      }
    }.nest::print_report

    run_command('eix-sync -aq', $target, 'Sync Portage repos')

    if $profile {
      run_command("eselect profile set nest:${profile}", $target, "Switch to profile ${profile}")
    }

    # Set up the build environment
    add_facts($target, {
      'build'               => 'stage3',
      'emerge_default_opts' => $emerge_default_opts,
      'makeopts'            => $makeopts,
    })

    # Configure Portage and Puppet
    run_command("sh -c 'echo profile > /.apply_tags'", $target, 'Set Puppet tags for profile run')
    apply($target, '_description' => 'Configure the profile') { include nest }.nest::print_report
    run_command('rm /.apply_tags', $target, 'Clear Puppet apply settings')

    # Make the system consistent with the profile
    run_command('emerge --info', $target, 'Show Portage configuration')
    run_command('emerge --deep --newuse --update --verbose --with-bdeps=y @world', $target, 'Install packages')
    run_command('emerge --depclean', $target, 'Remove unused packages')

    # Apply the main configuration
    if !empty($puppet_environment) {
      $puppet_environment_args = ['--environment', $puppet_environment]
    } else {
      $puppet_environment_args = []
    }
    $puppet_cmd = ['puppet', 'agent', $puppet_environment_args, '--test'].flatten.shellquote
    $puppet_script = "${puppet_cmd} || [ \$? -eq 2 ]"
    run_command("sh -c ${puppet_script.shellquote}", $target, 'Configure the host image', '_env_vars' => {
      'FACTER_build' => 'stage3',
    })

    run_command("podman stop ${container}", 'localhost', 'Stop build container')
  }

  if $deploy {
    run_command("podman start ${container}", 'localhost', 'Start build container')

    $rsync_script = @("RSYNC"/$)
      () {
        rsync -e "ssh -i \$1" \
          --archive --acls --hard-links --xattrs \
          --delete \
          --delete-excluded \
          --exclude='/run/**' \
          --exclude='/tmp/**' \
          --info=stats2 \
          --one-file-system \
          / root@falcon:${hostroot.shellquote}
      } =(<<< \$SSH_PRIVATE_KEY)
      | RSYNC

    run_command("zsh -c ${rsync_script.shellquote}", $target, 'Rsync the image', '_env_vars' => {
      'SSH_AUTH_SOCK'   => $ssh_auth_sock,
      'SSH_PRIVATE_KEY' => system::env($rsync_private_key_var),
    })

    run_command("podman stop ${container}", 'localhost', 'Stop build container')
  }
}
