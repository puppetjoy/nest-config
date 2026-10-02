# Common cross-compilers served by Nest build hosts.
class nest::lib::toolchains (
  Hash $env = {},
) {
  $targets = [
    'aarch64-unknown-linux-gnu',
    'armv6j-unknown-linux-gnueabihf',
    'armv7a-unknown-linux-gnueabihf',
    'riscv64-unknown-linux-gnu',
    'arm-none-eabi',
  ]

  $targets.each |$target| {
    nest::lib::toolchain { $target:
      env      => $env,
      gcc_only => $target == 'arm-none-eabi',
    }
  }

  # Crossdev shares overlay configuration; bootstrap one target at a time.
  $targets.reduce(undef) |$previous, $target| {
    if $previous {
      Nest::Lib::Toolchain[$previous] -> Nest::Lib::Toolchain[$target]
    }
    $target
  }
}
