# Generate a label name <= 8 characters from hostname, prioritizing suffix after dash.
#
# @param hostname The hostname to convert to a label name
# @return [String] A label name <= 8 characters
#
# @example Basic usage
#   nest::labelname('kestrel-console') # => 'kconsole'
#   nest::labelname('eagle-gui')       # => 'eaglegui'
#   nest::labelname('falcon-gui12')    # => 'falgui12'
#   nest::labelname('foobarbaz12')     # => 'foobar12'
#   nest::labelname('short')           # => 'short'
#
function nest::labelname(String $hostname) >> String {
  $digits = $hostname ? {
    /(\d+)$/ => $1,
    default  => '',
  }

  if length($hostname) > 8 {
    $base = $digits ? {
      ''      => $hostname,
      default => $hostname[0, length($hostname) - length($digits)],
    }

    # If there's a dash, prioritize the suffix after the last dash
    if $base =~ /-/ {
      $parts = split($base, '-')
      $prefix = $parts[0]
      $suffix_parts = $parts[1, length($parts) - 1]
      $suffix = join($suffix_parts, '-')

      # Calculate how much space we have for the label
      $available = 8 - length($digits)

      # Guard against non-positive available space
      if $available <= 0 {
        $hostname
      } else {
        # Try to fit as much of the suffix as possible, then prefix
        if length($suffix) >= $available {
          # Use only suffix if it fills or exceeds available space
          "${suffix[0, $available]}${digits}"
        } else {
          # Use full suffix and as much prefix as fits
          $prefix_len = $available - length($suffix)
          "${prefix[0, $prefix_len]}${suffix}${digits}"
        }
      }
    } else {
      # No dash: use old logic (prefix + digits)
      $available = 8 - length($digits)
      if $available <= 0 {
        $hostname
      } else {
        "${base[0, $available]}${digits}"
      }
    }
  } else {
    $hostname
  }
}
