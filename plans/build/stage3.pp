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
# @param identityroot Host identity input, separate from publication destination
# @param identity_ca_sha256 Independently approved public CA PEM digest, required for frozen catalogs
# @param identity_reference Exact completed private identity generation UUID, required for frozen catalogs
# @param init Initialize the build container
# @param makeopts Override make flags (e.g. -j4)
# @param puppet_environment Puppet environment to use for final configuration
# @param profile Switch to this profile
# @param qemu_user_targets CPU architectures to emulate
# @param rsync_private_key_var Environment variable for rsync private key
# @param repo_revisions Complete gentoo/nest/haskell commit pins; isolated repositories, no sync
# @param stage2_image Exact Stage2 image reference; defaults to platform/variant tag
# @param catalog_inputs Exact installed config executor source/base; use its local modules, not a served environment
# @param root_publication Explicit staging/publication placement, optionally through a private shared archive and inventory target
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
  String            $identityroot          = $hostroot,
  Optional[String]  $identity_ca_sha256    = undef,
  Optional[String]  $identity_reference    = undef,
  Boolean           $init                  = true,
  Optional[String]  $makeopts              = undef,
  Optional[String]  $puppet_environment    = undef,
  Optional[String]  $profile               = undef,
  Array[String]     $qemu_user_targets     = lookup('nest::build::qemu_user_targets', default_value => []),
  String            $rsync_private_key_var = 'NEST_RSYNC_PRIVATE_KEY',
  Optional[Hash]    $repo_revisions        = undef,
  Optional[String]  $stage2_image          = undef,
  Optional[Hash]    $catalog_inputs        = undef,
  Optional[Hash]    $root_publication      = undef,
) {
  if $root_publication != undef {
    assert_type(Struct[{
      'release'      => Pattern[/\A[a-z0-9][a-z0-9._-]{0,127}\z/],
      'expectations' => Pattern[/\Asha256:[0-9a-f]{64}\z/],
      'staging'      => String[1],
      'staging_guid' => Pattern[/\A[1-9][0-9]{0,19}\z/],
      'receipts'     => String[1],
      'parent_guid'  => Pattern[/\A[1-9][0-9]{0,19}\z/],
      Optional['target']  => Pattern[/\A[a-z0-9][a-z0-9-]{0,62}\z/],
      Optional['archive'] => String[1],
    }], $root_publication)
    unless $catalog_inputs != undef and !$deploy and $hostroot == "/nest/releases/${root_publication['release']}/hosts/${hostname}" {
      fail('Local root publication requires frozen catalogs, the exact versioned hostroot and deploy=false')
    }
    $finish_args = [$container, $root_publication['staging'], $root_publication['staging_guid'],
      $root_publication['receipts'], $hostname, $root_publication['release'],
      $root_publication['parent_guid'], $root_publication['expectations'], $identityroot]
    # Keep sibling imports together in the verified executor, not Bolt's
    # single-script temporary upload directory.
    $finish_command = "python3 /opt/nest/files/build/finish-stage3-root.py ${finish_args.shellquote}"
    if $root_publication['target'] != undef {
      assert_type(String[1], $root_publication['archive'])
      $publication_targets = get_targets($root_publication['target'])
      unless $publication_targets.length == 1 and $publication_targets[0].config['transport'] == 'ssh' and $publication_targets[0].config['ssh']['user'] == 'joy' {
        fail('Remote publication requires one inventory-backed Joy SSH target')
      }
      $publication_target = $publication_targets[0]
    } elsif $root_publication['archive'] != undef {
      fail('A shared archive requires an explicit publication target')
    }
  }
  if $catalog_inputs != undef {
    if $deploy {
      fail('Frozen Stage 3 catalogs cannot publish through legacy running-container rsync')
    }
    assert_type(Pattern[/\A[0-9a-f]{64}\z/], $identity_ca_sha256)
    assert_type(Pattern[/\A[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\z/], $identity_reference)
    $identity_args = [$identityroot, $hostroot, $hostname, $identity_ca_sha256, '--identity-reference', $identity_reference]
    assert_type(Struct[{
      'source' => Pattern[/\A[0-9a-f]{40}\z/],
      'base'   => Pattern[/\A[a-z0-9][a-z0-9._:\/-]*@sha256:[0-9a-f]{64}\z/],
    }], $catalog_inputs)
    unless $build and $init and $repo_revisions != undef and $puppet_environment == undef {
      fail('Frozen Stage 3 catalogs require build, init, frozen repositories and no served Puppet environment')
    }
    # This opt-in path runs inside the accepted /opt/nest executor project.
    # Its retained inventory includes both Nest checkouts and every module.
    $check_catalog = "python3 /opt/nest/scripts/nest-executor-inputs.py check --source ${catalog_inputs['source'].shellquote} --base ${catalog_inputs['base'].shellquote} > /dev/null"
  }
  if $repo_revisions != undef {
    assert_type(Struct[{
      'gentoo'  => Pattern[/\A[0-9a-f]{40}\z/],
      'nest'    => Pattern[/\A[0-9a-f]{40}\z/],
      'haskell' => Pattern[/\A[0-9a-f]{40}\z/],
    }], $repo_revisions)
    assert_type(Pattern[/\A[a-z0-9][a-z0-9._:\/-]*@sha256:[0-9a-f]{64}\z/], $stage2_image)
    unless $build and $init {
      fail('Frozen Stage 3 repositories require build, init and an exact Stage 2 base')
    }
    $repos_volume_arg = "--volume=${container}-frozen-repos:/var/db/repos:nocopy"
    $repo_args = [$repo_revisions['gentoo'], $repo_revisions['nest'], $repo_revisions['haskell']]
  } else {
    $repos_volume_arg = ''
  }
  $ssh_auth_sock = system::env('SSH_AUTH_SOCK')
  $target = Target.new(name => $hostname, uri => "podman://${container}")
  $base_image = $stage2_image ? {
    undef   => "nest/stage2/${variant}:${platform}",
    default => $stage2_image,
  }

  if $catalog_inputs != undef {
    run_command($check_catalog, 'localhost', 'Verify frozen catalog executor before initialization')
    # Frozen builds consume preprovisioned private identity; they must not create
    # or repair it, nor copy a root over that same source through legacy defaults.
    run_script('nest/build/check-stage3-paths.py', 'localhost', arguments => $identity_args)
    if $root_publication != undef {
      if $root_publication['target'] != undef {
        $helper_template = "${root_publication['receipts']}/stage3-helpers.XXXXXXXX"
        $helpers = run_command("mktemp -d ${helper_template.shellquote}", $publication_target,
          'Stage publication helpers through ordinary Bolt escalation', { '_run_as' => 'root' }).first.value['stdout'].chomp
        # Keep the existing sibling imports together on the publication host.
        ['check-stage3-root.py', 'publish-stage3-root.py', 'materialize-stage3-root.py',
          'finish-stage3-root.py', 'transfer-stage3-root.py'].each |$helper| {
          upload_file("nest/build/${helper}", "${helpers}/${helper}", $publication_target, { '_run_as' => 'root' })
        }
        $remote_finish_path = "${helpers}/finish-stage3-root.py"
        $remote_transfer_path = "${helpers}/transfer-stage3-root.py"
        $remote_finish = "python3 ${remote_finish_path.shellquote} ${finish_args.shellquote}"
        run_command("${remote_finish} --check", $publication_target,
          'Admit native publication ZFS before build', { '_run_as' => 'root' })
        $export_args = [$container, $root_publication['archive']]
        run_command("python3 /opt/nest/files/build/transfer-stage3-root.py export-check ${export_args.shellquote}",
          'localhost', 'Admit private shared archive without creating it')
      } else {
        run_command("${finish_command} --check", 'localhost', 'Admit local Stage 3 publication placement before build')
      }
    }
  }

  if $init {
    run_command("podman rm -f ${container}", 'localhost', 'Stop and remove existing build container')
    if $repo_revisions != undef {
      run_command("podman volume rm -f ${container}-frozen-repos", 'localhost', 'Remove previous isolated build repositories')
    }

    if $catalog_inputs == undef and !empty($ssh_auth_sock) and run_command("test -S ${ssh_auth_sock}", 'localhost', 'Check SSH_AUTH_SOCK', '_catch_errors' => true).ok {
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
      ${repos_volume_arg} \
      ${ssh_auth_sock_volume} \
      ${qemu_user_targets.map |$arch| { "--volume=/usr/bin/qemu-${arch}:/usr/bin/qemu-${arch}:ro" }.join(' ')} \
      ${base_image.shellquote} \
      sleep infinity
      | CREATE

    run_command($podman_create_cmd, 'localhost', 'Create build container')
  }

  if $build {
    run_command("podman start ${container}", 'localhost', 'Start build container')

    if $repo_revisions != undef {
      run_script('nest/build/freeze-repos.py', $target, arguments => ['prepare'] + $repo_args)
    }
    apply_prep($target)

    if $catalog_inputs != undef {
      # One process admits a stable private capture and installs those exact
      # bytes in this disposable container. Puppet must not reopen the live tree.
      run_script('nest/build/check-stage3-paths.py', $target, arguments => $identity_args + ['--install'])
    }

    # Preserve and restore host identity info
    apply($target, '_description' => 'Set up host identity info') {
      if $catalog_inputs == undef {
        file { $identityroot:
          ensure => directory,
          mode   => '0555',
          owner  => 'root',
          group  => 'root',
        }
        ->
        exec { 'systemd-machine-id-setup':
          command => "/usr/bin/systemd-machine-id-setup --root=${identityroot.shellquote}",
          creates => "${identityroot}/etc/machine-id",
          before  => File['/etc/machine-id'],
        }

        file {
          "${identityroot}/etc/puppetlabs":
            ensure => directory,
            mode   => '0755',
            owner  => 'root',
            group  => 'root',
          ;

          "${identityroot}/etc/puppetlabs/puppet":
            ensure => directory,
            mode   => '0750',
            owner  => 'root',
            group  => 'puppet',
          ;

          "${identityroot}/etc/puppetlabs/puppet/ssl":
            ensure => directory,
            mode   => '0771',
            owner  => 'puppet',
            group  => 'puppet',
            before => File['/etc/puppetlabs/puppet/ssl'],
          ;
        }
        file { '/etc/machine-id':
          source => "${identityroot}/etc/machine-id",
        }
        ->
        # Puppet Agent will correct permissions on these files
        file { '/etc/puppetlabs/puppet/ssl':
          ensure  => directory,
          source  => "${identityroot}/etc/puppetlabs/puppet/ssl",
          recurse => true,
        }
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

    if $repo_revisions == undef {
      run_command('eix-sync -aq', $target, 'Sync Portage repos')
    }

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
    if $repo_revisions != undef {
      run_script('nest/build/freeze-repos.py', $target, arguments => ['check'] + $repo_args)
    }

    # Make the system consistent with the profile
    run_command('emerge --info', $target, 'Show Portage configuration')
    run_command('emerge --deep --newuse --update --verbose --with-bdeps=y @world', $target, 'Install packages')
    run_command('emerge --depclean', $target, 'Remove unused packages')

    # Apply the main configuration
    if $catalog_inputs != undef {
      run_command($check_catalog, 'localhost', 'Verify frozen catalog executor before configuration')
      run_script('nest/build/check-stage3-paths.py', 'localhost', arguments => $identity_args)
      # Bolt compiles from this exact executor project/module inventory. Never
      # fetch a newer catalog from a mutable server environment in frozen mode.
      apply($target, '_description' => 'Configure the host image from frozen local modules') { include nest }.nest::print_report
      run_command($check_catalog, 'localhost', 'Verify frozen catalog executor after configuration')
      run_script('nest/build/check-stage3-paths.py', 'localhost', arguments => $identity_args)
    } else {
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
    }
    if $repo_revisions != undef {
      run_script('nest/build/freeze-repos.py', $target, arguments => ['check'] + $repo_args)
    }

    run_command("podman stop ${container}", 'localhost', 'Stop build container')
  }

  if $root_publication != undef {
    run_command($check_catalog, 'localhost', 'Verify frozen executor before root publication')
    if $root_publication['target'] != undef {
      $transfer = parsejson(run_command("python3 /opt/nest/files/build/transfer-stage3-root.py export ${export_args.shellquote}",
        'localhost', 'Archive stopped root and frozen repositories on private shared storage').first.value['stdout'])
      assert_type(Struct[{
        'archive_digest' => Pattern[/\Asha256:[0-9a-f]{64}\z/],
        'content_digest' => Pattern[/\Asha256:[0-9a-f]{64}\z/],
      }], $transfer)
      $receive_args = [$container, $root_publication['archive'], $transfer['archive_digest'],
        $transfer['content_digest']] + $finish_args[1,8]
      $published = parsejson(run_command("python3 ${remote_transfer_path.shellquote} receive ${receive_args.shellquote}",
        $publication_target, 'Check transfer, seal and publish on native ZFS', { '_run_as' => 'root' }).first.value['stdout'])
    } else {
      $published = parsejson(run_command($finish_command, 'localhost', 'Materialize and publish stopped Stage 3 root').first.value['stdout'])
    }
    assert_type(Struct[{ 'root' => Struct[{
      'path'           => String[1],
      'dataset_guid'   => Pattern[/\A[1-9][0-9]{0,19}\z/],
      'content_digest' => Pattern[/\Asha256:[0-9a-f]{64}\z/],
    }] }], $published)
    unless $published['root']['path'] == $hostroot {
      fail('Published Stage 3 root path does not match the selected hostroot')
    }
    return($published)
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
