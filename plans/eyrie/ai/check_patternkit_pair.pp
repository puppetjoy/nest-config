# Inspect an already staged source pair on its serving host without deployment.
plan nest::eyrie::ai::check_patternkit_pair (
  Pattern[/\A[0-9a-f]{40}-[0-9a-f]{40}\z/] $pair,
  Pattern[/\Aregistry\.eyrie\/nest\/stage1\/server@sha256:[0-9a-f]{64}\z/] $image,
) {
  return run_script('nest/scripts/patternkit_pair_preflight.py', 'owl', 'Verify staged PatternKit and Atelier on Owl', {
    'arguments' => [$pair, $image],
  })
}
