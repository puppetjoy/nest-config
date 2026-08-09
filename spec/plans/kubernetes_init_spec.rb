require 'spec_helper'

RSpec.describe 'nest::kubernetes::init safety ordering' do
  let(:repo_root) { File.expand_path('../..', __dir__) }
  let(:init_plan) { File.read(File.join(repo_root, 'plans/kubernetes/init.pp')) }
  let(:vip_plan) { File.read(File.join(repo_root, 'plans/kubernetes/generate_kube_vip_manifest.pp')) }
  let(:upgrade_plan) { File.read(File.join(repo_root, 'plans/kubernetes/upgrade_node.pp')) }

  it 'validates a redundant advertiser subset before host mutation' do
    subset_validation = init_plan.index('vip_advertisers must contain unique members')
    redundancy_validation = init_plan.index('vip_advertisers must retain at least two')
    first_mutation = init_plan.index("run_command('systemctl start crio'")

    expect(subset_validation).to be < first_mutation
    expect(redundancy_validation).to be < first_mutation
  end

  it 'proves replacement Pods, BGP routes, and VIP readiness before withdrawal' do
    pod_gate = init_plan.index('Require intended kube-vip mirror Pods before withdrawal')
    route_gate = init_plan.index('kube-vip BGP route from peer observer')
    ready_gate = init_plan.index('Require API VIP readiness before advertiser withdrawal')
    withdrawal = init_plan.index('advertise => false')

    expect([pod_gate, route_gate, ready_gate].max).to be < withdrawal
    expect(init_plan).to include('Wait for kube-vip BGP route withdrawal')
    expect(init_plan).to include('Require API VIP continuity after advertiser withdrawal')
  end

  it 're-advertises every excluded member and verifies rollback health on failure' do
    expect(init_plan).to include('kube-vip advertiser withdrawal failed; re-advertising excluded members')
    expect(init_plan).to match(%r{targets => \$excluded_vip_nodes,\n\s+vip\s+=> \$vip,})
    expect(init_plan).to include('kube-vip BGP route after rollback from peer observer')
    expect(init_plan).to include('Require API VIP readiness after re-advertisement rollback')
    expect(init_plan).to include('nest/kubernetes-kube-vip-rollback-failed')
  end

  it 'bootstraps on local etcd before serially reconciling final read endpoints' do
    bootstrap = init_plan.index('etcd_servers           => []')
    join = init_plan.index('run_command($full_kubeadm_join_cmd')
    reconcile = init_plan.index("run_plan('nest::kubernetes::reconcile_control_plane'")

    expect(bootstrap).to be < join
    expect(join).to be < reconcile
    expect(init_plan).to include('$nodes.each |$node|')
  end

  it 'uses strict member reconciliation in the control-plane upgrade path' do
    expect(upgrade_plan).to include('test -f /etc/kubernetes/manifests/kube-apiserver.yaml')
    expect(upgrade_plan).to include('requires explicit final etcd_servers for strict reconciliation')
    expect(upgrade_plan).to include("run_plan('nest::kubernetes::reconcile_control_plane'")
    fail_closed = upgrade_plan.index('requires explicit final etcd_servers for strict reconciliation')
    first_mutation = upgrade_plan.index("run_command('eix-sync -a'")
    reconcile = upgrade_plan.index("run_plan('nest::kubernetes::reconcile_control_plane'")

    expect(fail_closed).to be < first_mutation
    expect(first_mutation).to be < reconcile
  end

  it 'checks every advertiser from a different BGP observer including rollback' do
    expect(init_plan).to include('$observer = ($nodes - $node)[0]')
    expect(init_plan).to include('$excluded_route_observer = ($nodes - $excluded_node)[0]')
    expect(init_plan).to include('$rollback_observer = ($nodes - $rollback_node)[0]')
  end

  it 'renders replacement static manifests outside the watched directory before atomic install' do
    expect(vip_plan).to include('temporary="$(mktemp /tmp/kube-vip.XXXXXX.yaml)"')
    expect(vip_plan).to include('test -s "$temporary"')
    expect(vip_plan.index('test -s "$temporary"')).to be < vip_plan.index('install -m 0600 "$temporary" "$manifest"')
  end
end
