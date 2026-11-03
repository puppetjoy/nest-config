# @summary Start, stop or inspect only the infrastructure test mirrors
#
# @param action Explicit lifecycle action; never changes Joyride TEST
plan nest::eyrie::test::infrastructure (
  Enum['start', 'stop', 'status'] $action  = 'status',
  Boolean                         $enabled = true,
) {
  if $enabled {
    run_script('nest/scripts/infrastructure_test.py', 'localhost', "${action} infrastructure test mirrors", {
      'arguments' => [$action],
    })
  }
}
