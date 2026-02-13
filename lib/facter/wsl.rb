require 'json'

Facter.add('wsl') do
  confine osfamily: 'windows'
  setcode do
    script = <<~'POWERSHELL'
      $wslFeature = (Get-WindowsOptionalFeature -Online -FeatureName 'Microsoft-Windows-Subsystem-Linux').State -eq 'Enabled'
      $rebootPending = (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending') -or
        (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired') -or
        ((Get-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager' -Name 'PendingFileRenameOperations' -ErrorAction SilentlyContinue) -ne $null)
      $featuresEnabled = $wslFeature
      $ready = $featuresEnabled -and (-not $rebootPending)

      @{
        features_enabled = $featuresEnabled
        reboot_pending = $rebootPending
        ready = $ready
      } | ConvertTo-Json -Compress
    POWERSHELL

    encoded = [script.encode('UTF-16LE')].pack('m0')
    output = Facter::Core::Execution.execute("powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand #{encoded}").to_s.strip
    parsed = JSON.parse(output)

    {
      'features_enabled' => parsed['features_enabled'] == true,
      'reboot_pending'   => parsed['reboot_pending'] == true,
      'ready'            => parsed['ready'] == true,
    }
  rescue StandardError
    {
      'features_enabled' => false,
      'reboot_pending'   => false,
      'ready'            => false,
    }
  end
end
