moduledir '.modules'

# Required by everything
mod 'puppetlabs-stdlib', '9.4.0'
mod 'puppetlabs-concat', '9.0.0'

# Core types and providers
mod 'puppetlabs-augeas_core', '1.4.1'
mod 'puppetlabs-chocolatey', '8.0.0'
mod 'puppetlabs-host_core', '1.2.0'
mod 'puppetlabs-sshkeys_core', '2.4.0'
mod 'puppetlabs-zfs_core', '1.4.0'

# Bolt modules
#mod 'jtl-kubecm', '0.1.1'
mod 'kubecm', :git => 'git@gitlab.joyfullee.me:joy/kubecm.git', :branch => 'main'
mod 'reboot', :git => 'git@gitlab.joyfullee.me:nest/forks/puppet-reboot.git', :branch => 'main'
mod 'puppetlabs-ruby_task_helper', '0.6.1'

# My modules
mod 'nest', :git => 'git@gitlab.joyfullee.me:nest/config.git', :branch => :control_branch, :default_branch => 'main'
mod 'private', :git => 'git@gitlab.joyfullee.me:nest/private.git', :branch => 'main'

# Required by nest
mod 'puppet-archive', '7.1.0'
mod 'puppet-dnsquery', '5.0.1'
mod 'puppet-augeasproviders_sysctl', '3.1.0'
mod 'puppetlabs-apache', '12.2.0'
mod 'puppetlabs-inifile', '6.1.0'
mod 'puppetlabs-mysql', '15.0.0'
mod 'puppetlabs-powershell', '6.0.0'
mod 'puppetlabs-vcsrepo', :git => 'git@gitlab.joyfullee.me:nest/forks/puppet-vcsrepo.git', :branch => 'main'
mod 'puppet-firewalld', :git => 'git@gitlab.joyfullee.me:nest/forks/puppet-firewalld.git', :branch => 'fix-new-zone-creation'
mod 'puppet-nodejs', '10.0.0'
mod 'puppet-systemd', '7.1.0'
mod 'puppetlabs-windows_env', '5.0.0'
mod 'puppet-windows_firewall', '4.1.0'
mod 'theforeman-puppet', '18.0.0'
mod 'portage', :git => 'git@gitlab.joyfullee.me:nest/forks/puppet-portage.git', :branch => 'main'

# Required by puppetlabs-chocolatey and puppet-windows_firewall
mod 'puppetlabs-registry', '5.0.1'

# Required by puppetlabs-powershell
mod 'puppetlabs-pwshlib', '1.2.2'

# Required by theforeman-puppet
mod 'puppet-extlib', '7.0.0'

# Required by augeasproviders_sysctl
mod 'puppet-augeasproviders_core', '4.0.1'
