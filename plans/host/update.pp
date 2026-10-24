# Update the operating system
#
# @param $targets Nodes to update
# @param $reset Update using reset method
# @param $reboot Reboot the system after updating
# @param $run_puppet Run Puppet to complete update (only if rebooted)
# @param $mode Legacy execution, planning, stored transaction observation or explicit preparation
# @param $policy Complete wave policy for plan/observe/prepare modes
# @param $preparation Exact per-host native transaction, root generation and capacity policy paths
# @param $observations Exact per-host stored transaction identities for read-only status
# @param $output_dir Existing canonical supervisor directory for retained reports
# @param $maintenance Exact per-controller survivor/storage/physical admission inputs for preparation
# @param $release_manifest Complete runtime release manifest, required only for preparation
plan nest::host::update (
  TargetSpec                                   $targets,
  Boolean                                      $reset            = true,
  Boolean                                      $reboot           = false,
  Boolean                                      $run_puppet       = true,
  Enum['legacy', 'plan', 'observe', 'prepare'] $mode             = 'legacy',
  Optional[Hash]                               $policy           = undef,
  Optional[Hash]                               $preparation      = undef,
  Optional[Hash]                               $observations     = undef,
  Optional[Stdlib::Absolutepath]               $output_dir       = undef,
  Optional[Hash]                               $maintenance      = undef,
  Optional[Hash]                               $release_manifest = undef,
) {
  if ($mode == 'prepare') != ($release_manifest != undef) {
    fail_plan('Preparation requires the complete release_manifest; other modes refuse it', 'nest/update-generation-binding')
  }
  if $mode in ['prepare', 'observe'] {
    if $policy == undef or $output_dir == undef or $reboot or !$reset {
      fail_plan('Transaction modes require policy, output_dir, reset=true and reboot=false', 'nest/update-prepare-inputs')
    }
    if $mode == 'prepare' {
      if $preparation == undef or $observations != undef {
        fail_plan('Prepare mode requires preparation and refuses observation inputs', 'nest/update-prepare-inputs')
      }
      $input_task = 'nest::update_prepare_inputs'
      $inputs = $preparation
      $result_kind = 'nest_update_preparation'
    } else {
      if $observations == undef or $preparation != undef {
        fail_plan('Observe mode requires observations and refuses preparation inputs', 'nest/update-observe-inputs')
      }
      $input_task = 'nest::update_observe_inputs'
      $inputs = $observations
      $result_kind = 'nest_update_observation'
    }
    $nodes = get_targets($targets)
    # Maintenance policy and native hostname receipts use canonical inventory
    # names. Never reinterpret a qualified controller as an ordinary leaf, or
    # silently rewrite its transaction identity to a guessed short name.
    if $mode == 'prepare' and $nodes.any |$node| { $node.name =~ Pattern[/\Acontrol[123]\./] } {
      fail_plan('Controller preparation requires canonical control1/control2/control3 inventory names and bound maintenance inputs', 'nest/maintenance-scope')
    }
    $bound = run_task($input_task, 'localhost', {
      'policy'  => $policy,
      'targets' => $nodes.map |$node| { $node.name },
      'inputs'  => $inputs,
    }).results[0].value
    if $mode == 'prepare' {
      $generation_policies = $bound['inputs'].reduce({}) |$memo, $entry| {
        $memo + { $entry[0] => $entry[1]['generation_policy'] }
      }
      # Reconcile the COMPLETE scope before maintenance, backup or generation
      # contact. Native checks remain separate resource admission.
      run_task('nest::update_generation_binding', 'localhost', {
        'manifest' => $release_manifest,
        'policies' => $generation_policies,
        'scope'    => $policy,
      })
    }
    $controllers = $nodes.filter |$node| { $node.name in ['control1', 'control2', 'control3'] }.map |$node| { $node.name }
    if $mode == 'prepare' and !$controllers.empty {
      if $maintenance == undef or $maintenance.keys.sort != $controllers.sort or
        !$maintenance.values.all |$entry| {
          $entry =~ Hash and $entry.keys.sort == ['advertisers', 'ceph_fsid', 'client', 'physical_domains', 'survivor'] and
            $entry['ceph_fsid'] =~ Pattern[/\A[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\z/]
        } {
        fail_plan('Controller preparation requires exact complete per-controller maintenance inputs', 'nest/maintenance-scope')
      }
      if $bound['waves'].any |$wave| { $wave.any |$name| { $name in $controllers } and $wave.length != 1 } {
        fail_plan('Controller preparation must be isolated from every concurrent host preparation', 'nest/maintenance-wave')
      }
      # Validate every controller before preparing any host. Repeat immediately
      # before each affected native command: an earlier sample is not a lease.
      $controllers.each |$name| {
        run_plan('nest::kubernetes::check_control_plane_maintenance', $maintenance[$name] + { 'target' => $name })
      }
    } elsif $maintenance != undef {
      fail_plan('Maintenance inputs apply only to controller preparation', 'nest/maintenance-scope')
    }
    # Check ALL supervisor destinations before the first native reset. This is
    # read-only validation, not a promise of future disk space or writeability.
    $bound['inputs'].each |$name, $input| {
      run_task('nest::retain_update_report', 'localhost', {
        'action'      => 'check',
        'transaction' => $input['transaction'],
        'release'     => $bound['release'],
        'hostname'    => $name,
        'output_dir'  => $output_dir,
      })
    }
    if $mode == 'prepare' {
      # Verify ALL selected local seals before the first reset, without source
      # publication access, transfer, provisioning or automatic repair.
      $generation_preflight = $bound['inputs'].map |$name, $input| {
        $generation_binding = {
          'transaction'   => $input['transaction'],
          'policy_sha256' => $bound['policy_sha256'],
          'stage'         => 'preflight',
        }
        $verified = run_plan('nest::host::stage_generation', {
          'targets'     => $name,
          'policy'      => $input['generation_policy'],
          'manifest'    => $release_manifest,
          'verify_only' => true,
          'output_dir'  => $output_dir,
          'binding'     => $generation_binding,
        })
        $retained = $verified['retained']
        unless $retained =~ Hash and $retained['kind'] == 'nest_generation_retention_receipt' and
          $retained['readback_verified'] == true and $retained['sealed'] == true and
          $retained['hostname'] == $name and $retained['release'] == $bound['release'] and $retained['reset_authorized'] == false and
          $retained['preparation'] == $generation_binding {
          fail_plan('Generation verification was not retained; no reset started', 'nest/update-generation-retention')
        }
        $retained
      }
      # A seal is not reset capacity. Admit ALL hosts through the native read-only
      # planner before any reset; these observations are never execution leases.
      $capacity_preflight = $bound['inputs'].map |$name, $input| {
        $retained = run_plan('nest::host::check_update_capacity', {
          'target'     => $name,
          'release'    => $bound['release'],
          'inputs'     => $input,
          'output_dir' => $output_dir,
        })
        if $retained['capacity_admitted'] != true or $retained['readback_verified'] != true {
          fail_plan('Native capacity admission was not retained; no reset started', 'nest/update-capacity-preflight')
        }
        $retained
      }
      # Verify every declared existing generation before ANY native reset, then
      # repeat affected checks at initiation. Never capture or prune on failure.
      $backup_preflight = $bound['backup_requirements'].map |$name, $checks| {
        $checks.map |$check| {
          run_plan('nest::host::check_update_backup', {
            'check'     => $check,
            'retention' => {
              'transaction'   => $bound['inputs'][$name]['transaction'],
              'release'       => $bound['release'],
              'hostname'      => $name,
              'policy_sha256' => $bound['policy_sha256'],
              'stage'         => 'preflight',
              'output_dir'    => $output_dir,
            },
          })
        }
      }
      if !$backup_preflight.flatten.all |$receipt| { $receipt['verification_retained'] == true and $receipt['hold_checked'] == true and $receipt['readback_verified'] == true } {
        fail_plan('Backup verification was not retained; no reset started', 'nest/update-backup-retention')
      }
    } else {
      $generation_preflight = []
      $capacity_preflight = []
      $backup_preflight = []
    }
    $waves = $bound['waves'].map |$wave| {
      # parallelize waits for the whole wave, including retention, before the
      # next wave starts. A failure never starts the next wave or a reboot.
      parallelize($wave) |$name| {
        $node = $nodes.filter |$candidate| { $candidate.name == $name }[0]
        if $mode == 'prepare' and $name in $controllers {
          run_plan('nest::kubernetes::check_control_plane_maintenance', $maintenance[$name] + { 'target' => $name })
        }
        if $mode == 'prepare' {
          $backup_verification = $bound['backup_requirements'][$name].map |$check| {
            run_plan('nest::host::check_update_backup', {
              'check'     => $check,
              'retention' => {
                'transaction'   => $bound['inputs'][$name]['transaction'],
                'release'       => $bound['release'],
                'hostname'      => $name,
                'policy_sha256' => $bound['policy_sha256'],
                'stage'         => 'initiation',
                'output_dir'    => $output_dir,
              },
            })
          }
          if !$backup_verification.all |$receipt| { $receipt['verification_retained'] == true and $receipt['hold_checked'] == true and $receipt['readback_verified'] == true } {
            fail_plan('Backup verification was not retained; no new reset started', 'nest/update-backup-retention')
          }
          # A seal observation is not a lease. Repeat after readiness/backup
          # work, then re-admit time and exact inputs before native initiation.
          $generation_binding = {
            'transaction'   => $bound['inputs'][$name]['transaction'],
            'policy_sha256' => $bound['policy_sha256'],
            'stage'         => 'initiation',
          }
          $verified = run_plan('nest::host::stage_generation', {
            'targets'     => $name,
            'policy'      => $bound['inputs'][$name]['generation_policy'],
            'manifest'    => $release_manifest,
            'verify_only' => true,
            'output_dir'  => $output_dir,
            'binding'     => $generation_binding,
          })
          $generation_verification = $verified['retained']
          unless $generation_verification =~ Hash and $generation_verification['kind'] == 'nest_generation_retention_receipt' and
            $generation_verification['readback_verified'] == true and $generation_verification['sealed'] == true and
            $generation_verification['hostname'] == $name and $generation_verification['release'] == $bound['release'] and $generation_verification['reset_authorized'] == false and
            $generation_verification['preparation'] == $generation_binding {
            fail_plan('Generation verification was not retained; no new reset started', 'nest/update-generation-retention')
          }
          # Initial admission is not a lease. Maintenance, destination checks
          # and earlier waves may outlast the exact preparation window. Recheck
          # on the supervisor immediately before EACH host command, not only
          # once per wave. Never interrupt or replay an already started reset.
          $admitted = run_task('nest::update_prepare_inputs', 'localhost', {
            'policy'  => $policy,
            'targets' => $nodes.map |$candidate| { $candidate.name },
            'inputs'  => $inputs,
          }).results[0].value
          if $admitted['policy_sha256'] != $bound['policy_sha256'] or $admitted['inputs_sha256'] != $bound['inputs_sha256'] or
            $admitted['commands'][$name] != $bound['commands'][$name] {
            fail_plan('Preparation policy changed during admission; no new host command started', 'nest/update-prepare-inputs')
          }
        } else {
          $backup_verification = []
          $generation_verification = undef
        }
        $native = run_command($bound['commands'][$name].shellquote, $node, 'Run exact native transaction command', {
          '_run_as'       => 'root',
          '_catch_errors' => true,
        })
        $stdout = $native.results[0].value['stdout']
        # Retain a valid stopped/failed receipt too. Initialization, transport
        # or malformed-output failures refuse; they are never replayed.
        $receipt = run_task('nest::retain_update_report', 'localhost', {
          'report'      => $stdout,
          'transaction' => $bound['inputs'][$name]['transaction'],
          'release'     => $bound['release'],
          'hostname'    => $name,
          'output_dir'  => $output_dir,
        }).results[0].value
        if $mode == 'prepare' and (!$native.ok or $receipt['state'] != 'prepared') {
          fail_plan('Preparation failed or did not produce a prepared receipt; inspect retained state, never replay automatically', 'nest/update-prepare-failed')
        }
        if $mode == 'observe' and (!$native.ok or $receipt['observation_retained'] != true) {
          fail_plan('Native status did not produce a retained live observation', 'nest/update-observe-failed')
        }
        $receipt + { 'backup_verification' => $backup_verification, 'generation_verification' => $generation_verification }
      }
    }
    return({
      'kind'                 => $result_kind,
      'schema'               => 1,
      'policy_sha256'        => $bound['policy_sha256'],
      'waves'                => $waves,
      'generation_preflight' => $generation_preflight,
      'capacity_preflight'   => $capacity_preflight,
      'backup_preflight'     => $backup_preflight,
      'reboot_eligible'      => [],
      'acceptance_recorded'  => false,
    })
  }
  if $preparation != undef or $observations != undef or $output_dir != undef or $maintenance != undef {
    fail_plan('Transaction inputs require their explicit prepare or observe mode', 'nest/update-prepare-inputs')
  }
  if $mode == 'plan' {
    if $policy == undef or $reboot or !$reset {
      fail_plan('Wave planning requires policy, reset=true and reboot=false', 'nest/update-wave-policy')
    }
    $nodes = get_targets($targets)
    $wave_plan = run_task('nest::update_wave_plan', 'localhost', {
      'policy'  => $policy,
      'targets' => $nodes.map |$node| { $node.name },
    })
    return($wave_plan.results[0].value)
  }
  if $policy != undef {
    fail_plan('Wave policy is planning-only; it cannot authorize legacy execution', 'nest/update-wave-policy')
  }
  $legacy_nodes = get_targets($targets)
  if $legacy_nodes.any |$node| { $node.name =~ Pattern[/\A[^.]*-console(?:\.|\z)/] } {
    fail_plan('Recovery consoles are excluded from operating system updates; no host in this selection was updated', 'nest/update-excluded-console')
  }
  if $legacy_nodes.any |$node| { $node.name =~ Pattern[/\Acontrol[123](?:\.|\z)/] } {
    fail_plan('Legacy updates cannot admit a control-plane outage; use explicit bound preparation and maintenance policy', 'nest/maintenance-scope')
  }
  if $reset {
    $verb = 'reset'
  } else {
    $verb = 'update'
  }

  # Fail the plan on any preparation error. Never replay an ambiguous reset
  # with legacy --resume, or allow a failed target into the reboot phase.
  run_command("nest ${verb}", $legacy_nodes, "${verb.capitalize} the operating system")

  if $reboot {
    $legacy_names = $legacy_nodes.map |$node| { $node.name }
    run_plan('nest::host::reboot', $legacy_names, _description => 'Reboot the system')

    if $run_puppet {
      run_plan('nest::puppet::run', $legacy_names, _description => 'Run Puppet to complete update')
    }
  }
}
