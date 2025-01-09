# Snapshot and migrate ROOT to encrypted dataset
#
# @param targets Hosts to encrypt
# @param keylocation Key URI (e.g. 'file:///...') on the host or 'prompt'
plan nest::zfs::encrypt_rpool (
  TargetSpec $targets,
  String     $keylocation = 'prompt',
) {
  if $keylocation == 'prompt' {
    $passphrase = prompt('Encryption passphrase', 'sensitive' => true)

    if $passphrase.unwrap.length < 8 {
      fail('Passphrase must be at least 8 characters long')
    }

    if prompt('Encryption passphrase (again)', 'sensitive' => true).unwrap != $passphrase.unwrap {
      fail('Passphrases do not match')
    }

    $echo_passphrase = "echo ${passphrase.unwrap.shellquote} | "
  } else {
    $echo_passphrase = ''
  }

  parallelize(get_targets($targets)) |$t| {
    run_command("zfs snapshot -r ${t}@encrypt", $t, {
      '_run_as' => 'root',
    })

    $zfs_create_cmd = "${echo_passphrase}zfs create -o encryption=aes-128-gcm \
                        -o keyformat=passphrase -o keylocation=${keylocation} ${t}/crypt"
    run_command($zfs_create_cmd, $t, "zfs create ${t}/crypt", {
      '_run_as' => 'root',
    })

    run_command("zfs create -o atime=off ${t}/crypt/ROOT", $t, {
      '_run_as' => 'root',
    })

    $current_fs = run_command("zfs list -H -o name \$(findmnt -n -o SOURCE /)", $t, 'Get current BE', {
      '_run_as' => 'root',
    }).first.value['stdout'].chomp.regsubst('^.*?/', '')

    $datasets = {
      $current_fs           => '-o mountpoint=/',
      "${current_fs}/debug" => '-o mountpoint=/usr/lib/debug -o compression=zstd',
      "${current_fs}/src"   => '-o mountpoint=/usr/src -o compression=zstd',
      "${current_fs}/var"   => '-o mountpoint=/var',
      'home'                => '-o mountpoint=/home',
      'home/james'          => '-o mountpoint=/home/james',
      'swap'                => '-o refreservation=none',
    }

    $datasets.each |$fs, $opts| {
      run_command("zfs send -v ${t}/${fs}@encrypt | zfs receive -uv ${opts} ${t}/crypt/${fs}", $t, {
        '_run_as' => 'root',
      })

      unless $fs == 'swap' {
        run_command("zfs set canmount=noauto ${t}/${fs}", $t, {
          '_run_as' => 'root',
        })
      }
    }

    run_command("swapoff /dev/zvol/${t}/swap && zfs destroy -r ${t}/swap", $t, {
      '_run_as' => 'root',
    })

    run_command("zpool set bootfs=${t}/crypt/${current_fs} ${t}", $t, {
      '_run_as' => 'root',
    })
  }
}
