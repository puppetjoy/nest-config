class nest::host::falcon {
  $talon_public_key = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKJ3ZH2elB6c0ors9H/mxWrJY1aXKzA4XxA6YCe3rpj9 talon@joyfullee.me'

  nest::lib::toolchain {
    [
      'aarch64-unknown-linux-gnu',
      'armv6j-unknown-linux-gnueabihf',
      'armv7a-unknown-linux-gnueabihf',
      'riscv64-unknown-linux-gnu',
    ]:
      # use defaults
    ;

    'arm-none-eabi':
      gcc_only => true,
    ;
  }

  file { '/root/.ssh/letsencrypt-rsync.sh':
    ensure  => file,
    mode    => '0755',
    owner   => 'root',
    group   => 'root',
    content => @(SCRIPT),
      #!/usr/bin/env zsh
      #
      # Lets Encrypt rsync wrapper
      # Prevent Talon gateway sync access from running anything except rsync
      # into /etc/letsencrypt

      if [[ $SSH_ORIGINAL_COMMAND != 'rsync '*' . /etc/letsencrypt/'* ]]; then
          print "Denied: ${SSH_ORIGINAL_COMMAND}" >&2
          exit 1
      fi

      exec "${(z)SSH_ORIGINAL_COMMAND}"
      | SCRIPT
  }

  file_line { 'falcon-root-authorized-key-talon-letsencrypt-rsync-from-gateway':
    path    => '/root/.ssh/authorized_keys',
    line    => "from=\"172.22.0.3\",command=\"/root/.ssh/letsencrypt-rsync.sh\",restrict ${talon_public_key}",
    match   => 'from="172\.22\.0\.3",command="/root/\.ssh/letsencrypt-rsync\.sh",restrict ssh-ed25519 .* talon@joyfullee\.me',
    require => File['/root/.ssh/letsencrypt-rsync.sh'],
  }
}
