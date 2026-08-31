require 'spec_helper'
require 'yaml'

RSpec.describe 'Rook Ceph BlueStore metadata placement' do
  let(:repo_root) { File.expand_path('../..', __dir__) }
  let(:cluster) do
    YAML.safe_load_file(File.join(repo_root, 'data/kubernetes/app/rook-ceph-cluster.yaml'), aliases: true)
  end
  let(:test_cluster) do
    YAML.safe_load_file(File.join(repo_root, 'data/kubernetes/app/rook-ceph-cluster/test.yaml'), aliases: true)
  end
  let(:hdd_device_set) do
    cluster.dig('values', 'cephClusterSpec', 'storage', 'storageClassDeviceSets').find do |device_set|
      device_set.fetch('name') == 'set2'
    end
  end
  let(:claims) do
    hdd_device_set.fetch('volumeClaimTemplates').to_h do |claim|
      [claim.dig('metadata', 'name'), claim.fetch('spec')]
    end
  end

  it 'keeps HDD data and BlueStore metadata on separate physical pools' do
    expect(claims.keys).to contain_exactly('data', 'metadata')
    expect(claims.fetch('data').fetch('storageClassName')).to eq('%{lookup(\'hdd_storage_class\')}')
    expect(claims.fetch('metadata').fetch('storageClassName')).to eq('%{lookup(\'hdd_metadata_storage_class\')}')
    expect(cluster.fetch('hdd_storage_class')).to eq('nest-crypt-block')
    expect(cluster.fetch('hdd_metadata_storage_class')).to eq('data-crypt-block')
  end

  it 'provisions raw block metadata volumes sized for each environment' do
    metadata = claims.fetch('metadata')

    expect(metadata.fetch('volumeMode')).to eq('Block')
    expect(metadata.fetch('accessModes')).to eq(['ReadWriteOnce'])
    expect(metadata.dig('resources', 'requests', 'storage')).to eq('%{lookup(\'hdd_metadata_volume_size\')}')
    expect(cluster.fetch('hdd_metadata_volume_size')).to eq('32Gi')
    expect(test_cluster.fetch('hdd_metadata_volume_size')).to eq('8Gi')
  end
end
