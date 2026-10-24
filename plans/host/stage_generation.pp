# Transfer and seal one explicitly selected host-local root generation.
#
# @param $targets Exactly one canonical inventory hostname matching policy
# @param $policy Exact generation placement, identity, digest and transfer-budget policy
# @param $manifest Complete runtime release manifest binding the versioned publication and content
# @param $check Read-only placement/content admission by default; false explicitly copies and seals
# @param $verify_only Verify an already sealed local generation and its retained receipts without publication access
# @param $output_dir Existing persistent supervisor directory; required before any executing transfer
# @param $binding Optional transaction/wave/stage association for retained sealed verification
plan nest::host::stage_generation (
  TargetSpec                     $targets,
  Hash                           $policy,
  Hash                           $manifest,
  Boolean                        $check       = true,
  Boolean                        $verify_only = false,
  Optional[Stdlib::Absolutepath] $output_dir  = undef,
  Optional[Hash]                 $binding     = undef,
) {
  if $binding != undef and (!$verify_only or $output_dir == undef) {
    fail_plan('Preparation binding requires retained sealed verification', 'nest/generation-binding')
  }
  $retention_context = $binding ? {
    undef   => {},
    default => { 'binding' => $binding },
  }
  if $verify_only and !$check {
    fail_plan('Sealed generation verification requires check=true; it never transfers', 'nest/generation-mode')
  }
  if !$check and $output_dir == undef {
    fail_plan('Executing generation transfer requires persistent supervisor report retention', 'nest/generation-retention')
  }
  $nodes = get_targets($targets)
  unless $nodes.length == 1 and $nodes[0].name == $policy['hostname'] and
    $nodes[0].name !~ Pattern[/\A(?:control[123]\.|[^.]*-console(?:\.|\z))/] {
    fail_plan('Generation staging requires one exact canonical non-console host', 'nest/generation-scope')
  }
  run_task('nest::update_generation_binding', 'localhost', {
    'manifest' => $manifest,
    'policies' => { $nodes[0].name => $policy },
  })
  if $output_dir != undef {
    run_task('nest::retain_generation_report', 'localhost', $retention_context + { 'output_dir' => $output_dir })
  }
  # Only public placement/digest/budget fields belong in this JSON. The helper
  # validates the complete schema and never logs file names or private content.
  $args = ['python3', '/usr/libexec/nest/transfer-generation.py', $policy.to_json]
  $command = $verify_only ? {
    true    => $args + ['--verify'],
    default => $check ? {
      true    => $args + ['--check'],
      default => $args,
    },
  }
  $kind = $verify_only ? {
    true    => 'nest_generation_verification_report',
    default => 'nest_generation_transfer_report',
  }
  $native = run_command($command.shellquote, $nodes[0], 'Check or stage exact immutable root generation', '_run_as' => 'root')
  $report = parsejson($native.results[0].value['stdout'])
  unless $report['kind'] == $kind and $report['schema'] == 1 and
    $report['policy'] == $policy and $report['read_only'] == $check and
    $report['sealed'] == ($verify_only or !$check) and $report['reset_authorized'] == false and
    (!$verify_only or $report['reset_capacity_admitted'] == false) {
    fail_plan('Generation staging did not return the exact expected bound result; never replay', 'nest/generation-result')
  }
  if $output_dir != undef {
    $retained = run_task('nest::retain_generation_report', 'localhost', $retention_context + {
      'output_dir'  => $output_dir,
      'report'      => $native.results[0].value['stdout'],
      'policy'      => $policy,
      'check'       => $check,
      'verify_only' => $verify_only,
    })
    if $binding != undef and $retained.results[0].value['preparation'] != $binding {
      fail_plan('Generation retention lost preparation binding; never replay', 'nest/generation-binding')
    }
    return({ 'report' => $report, 'retained' => $retained.results[0].value })
  }
  return($report)
}
