function nest::ansi_to_rich(String[1] $source) >> String {
  $path = find_file($source)
  if $path == undef {
    fail("Could not find ANSI art source '${source}'")
  }

  $initial_state = {
    'out'   => '',
    'fg'    => undef,
    'bg'    => undef,
    'first' => true,
  }

  # lint:ignore:double_quoted_strings -- needs Unicode escape for ESC
  $result = file($path).split("\u001b").reduce($initial_state) |$state, $segment| {
  # lint:endignore
    if $state['first'] {
      $text = $segment
      $fg   = $state['fg']
      $bg   = $state['bg']
    } elsif $segment =~ /^\[[0-9;]*m/ {
      $code_end = $segment.index('m')
      $codes    = $segment[1, $code_end - 1]
      $text     = $segment[$code_end + 1, length($segment)]

      $reset_fg = ($codes == '') or ($codes =~ /(^|;)0(;|$)/) or ($codes =~ /(^|;)39(;|$)/)
      $reset_bg = ($codes == '') or ($codes =~ /(^|;)0(;|$)/) or ($codes =~ /(^|;)49(;|$)/)

      $base_fg = $reset_fg ? {
        true    => undef,
        default => $state['fg'],
      }
      $base_bg = $reset_bg ? {
        true    => undef,
        default => $state['bg'],
      }

      $fg = $codes =~ /(^|;)38;2;([0-9]+);([0-9]+);([0-9]+)(;|$)/ ? {
        true    => sprintf('#%02x%02x%02x', Integer($2), Integer($3), Integer($4)),
        default => $base_fg,
      }
      $bg = $codes =~ /(^|;)48;2;([0-9]+);([0-9]+);([0-9]+)(;|$)/ ? {
        true    => sprintf('#%02x%02x%02x', Integer($2), Integer($3), Integer($4)),
        default => $base_bg,
      }
    } else {
      $text = "\u001b${segment}"
      $fg   = $state['fg']
      $bg   = $state['bg']
    }

    if $fg == undef and $bg == undef {
      $style = undef
    } elsif $fg == undef {
      $style = "on ${bg}"
    } elsif $bg == undef {
      $style = $fg
    } else {
      $style = "${fg} on ${bg}"
    }

    $rich_text = $text.split('').reduce('') |$rich, $char| {
      if $char == "\n" {
        "${rich}${char}"
      } else {
        $escaped = $char ? {
          '['     => '\\[',
          ']'     => '\\]',
          '\\'    => '\\\\',
          default => $char,
        }
        if $style == undef {
          "${rich}${escaped}"
        } else {
          "${rich}[${style}]${escaped}[/]"
        }
      }
    };

    {
      'out'   => [$state['out'], $rich_text].join(''),
      'fg'    => $fg,
      'bg'    => $bg,
      'first' => false,
    }
  }

  $result['out']
}
