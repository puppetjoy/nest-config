# Generate a stable locally administered unicast MAC for USB gadget Ethernet.
#
# @param machine_id The /etc/machine-id value used as a durable host seed
# @param role Which side of the gadget link the address belongs to
# @return [String] A colon-delimited MAC address
#
# @example Basic usage
#   nest::usbnet_stable_mac('00112233445566778899aabbccddeeff', 'dev')  # => '02:00:11:22:33:44'
#   nest::usbnet_stable_mac('00112233445566778899aabbccddeeff', 'host') # => '06:00:11:22:33:44'
#
function nest::usbnet_stable_mac(String[1] $machine_id, Enum['dev', 'host'] $role) >> String {
  $normalized = downcase(regsubst($machine_id, '[^0-9a-fA-F]', '', 'G'))

  if length($normalized) < 10 {
    fail("machine_id '${machine_id}' is too short to derive a USB gadget MAC address")
  }

  $prefix = $role ? {
    'dev'   => '02',
    'host'  => '06',
  }

  join([
    $prefix,
    $normalized[0, 2],
    $normalized[2, 2],
    $normalized[4, 2],
    $normalized[6, 2],
    $normalized[8, 2],
  ], ':')
}
