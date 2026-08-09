# frozen_string_literal: true

require 'json'
require 'open3'
require 'rbconfig'
require 'tempfile'

RSpec.describe 'validate-etcd-cluster' do
  let(:repo_root) { File.expand_path('../..', __dir__) }
  let(:script) { File.join(repo_root, 'files/kubernetes/validate-etcd-cluster.rb') }
  let(:names) { ['control1', 'control2', 'control3'] }
  let(:ids) { [11, 22, 33] }
  let(:leader) { 33 }
  let(:members) do
    {
      'members' => names.zip(ids).map do |name, id|
        { 'ID' => id, 'name' => name, 'isLearner' => false }
      end,
    }
  end
  let(:statuses) do
    ids.each_with_index.map do |id, index|
      {
        'Endpoint' => "https://172.22.4.#{index + 7}:2379",
        'Status' => {
          'header' => { 'member_id' => id },
          'leader' => leader,
          'raftAppliedIndex' => 1000 + index,
        },
      }
    end
  end

  def validate(statuses, members, max_lag: 100)
    Tempfile.create('etcd-status') do |status_file|
      Tempfile.create('etcd-members') do |members_file|
        status_file.write(JSON.dump(statuses))
        status_file.flush
        members_file.write(JSON.dump(members))
        members_file.flush
        return Open3.capture3(
          RbConfig.ruby,
          script,
          status_file.path,
          members_file.path,
          max_lag.to_s,
          *names,
        )
      end
    end
  end

  it 'accepts the exact healthy voting topology with bounded lag' do
    stdout, stderr, status = validate(statuses, members)

    expect(status).to be_success
    expect(stderr).to be_empty
    expect(stdout).to include('members=control1,control2,control3', 'applied_index_lag=2')
  end

  it 'rejects missing members' do
    _stdout, stderr, status = validate(statuses.drop(1), { 'members' => members.fetch('members').drop(1) })

    expect(status).not_to be_success
    expect(stderr).to include('expected 3 endpoint statuses, got 2')
  end

  it 'rejects learners' do
    learner_members = Marshal.load(Marshal.dump(members))
    learner_members.fetch('members').first['isLearner'] = true
    _stdout, stderr, status = validate(statuses, learner_members)

    expect(status).not_to be_success
    expect(stderr).to include('learners are not allowed')
  end

  it 'rejects inconsistent leaders' do
    inconsistent = Marshal.load(Marshal.dump(statuses))
    inconsistent.first.fetch('Status')['leader'] = 22
    _stdout, stderr, status = validate(inconsistent, members)

    expect(status).not_to be_success
    expect(stderr).to include('expected one nonzero leader')
  end

  it 'rejects excessive applied-index lag' do
    lagging = Marshal.load(Marshal.dump(statuses))
    lagging.first.fetch('Status')['raftAppliedIndex'] = 500
    _stdout, stderr, status = validate(lagging, members, max_lag: 100)

    expect(status).not_to be_success
    expect(stderr).to include('applied-index lag 502 exceeds 100')
  end
end
