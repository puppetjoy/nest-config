# Quiesce the obsolete writer before replacing runtime code
class nest::app::hermes::retired_lifecycle {
  tag 'hermes_native_lifecycle_cutover'

  nest::lib::user_service { 'retire-hermes-agent-request-moving-tickets-timer':
    ensure => stopped,
    enable => false,
    unit   => 'hermes-agent-request-moving-tickets.timer',
    target => 'timers.target',
    user   => $nest::user,
  }

  nest::lib::user_service { 'retire-hermes-agent-request-moving-tickets-service':
    ensure  => stopped,
    enable  => false,
    unit    => 'hermes-agent-request-moving-tickets.service',
    user    => $nest::user,
    require => Nest::Lib::User_service['retire-hermes-agent-request-moving-tickets-timer'],
  }
}
