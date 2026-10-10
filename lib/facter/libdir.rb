Facter.add('libdir') do
  confine osfamily: 'Gentoo'
  setcode do
    # Use the native ABI, not the running kernel's architecture (which can
    # differ in cross-architecture build containers or on multilib hosts).
    abi = Facter::Core::Execution.execute('/usr/bin/portageq envvar DEFAULT_ABI')
    if abi&.strip&.match?(%r{\A[a-zA-Z0-9_]+\z})
      directory = Facter::Core::Execution.execute("/usr/bin/portageq envvar LIBDIR_#{abi.strip}")
      directory.strip if directory&.strip&.match?(%r{\Alib(?:32|64)?\z})
    end
  end
end
