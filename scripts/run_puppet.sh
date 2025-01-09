#!/bin/sh
#
# run_puppet
#
# Initiate a Puppet run without background agent conflicts
#

systemctl -q is-active puppet-run.timer && systemctl stop puppet-run
puppet agent --test $PUPPET_EXTRA_ARGS || [ $? -eq 2 ]
exit $?
