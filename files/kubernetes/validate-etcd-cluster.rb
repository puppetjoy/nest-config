#!/usr/bin/env ruby
# frozen_string_literal: true

require 'json'

status_path, members_path, max_lag, *expected_names = ARGV
raise 'usage: validate-etcd-cluster STATUS MEMBERS MAX_LAG MEMBER...' if expected_names.empty?

statuses = JSON.parse(File.read(status_path))
members = JSON.parse(File.read(members_path)).fetch('members')
raise "expected #{expected_names.length} endpoint statuses, got #{statuses.length}" unless statuses.length == expected_names.length
raise "expected #{expected_names.length} members, got #{members.length}" unless members.length == expected_names.length

actual_names = members.map { |member| member.fetch('name') }
raise "member names differ: expected #{expected_names.sort.inspect}, got #{actual_names.sort.inspect}" unless actual_names.sort == expected_names.sort
raise 'etcd learners are not allowed in the rollout gate' if members.any? { |member| member['isLearner'] }

member_ids = members.map { |member| member.fetch('ID') }
status_ids = statuses.map { |entry| entry.fetch('Status').fetch('header').fetch('member_id') }
raise 'endpoint status does not cover every configured member exactly once' unless status_ids.sort == member_ids.sort

leader_ids = statuses.map { |entry| entry.fetch('Status').fetch('leader') }.uniq
raise "expected one nonzero leader, got #{leader_ids.inspect}" unless leader_ids.length == 1 && member_ids.include?(leader_ids.first) && !leader_ids.first.zero?

applied_indexes = statuses.map { |entry| entry.fetch('Status').fetch('raftAppliedIndex') }
observed_lag = applied_indexes.max - applied_indexes.min
raise "applied-index lag #{observed_lag} exceeds #{max_lag}" if observed_lag > Integer(max_lag, 10)

puts "members=#{actual_names.sort.join(',')} leader=#{leader_ids.first} applied_index_lag=#{observed_lag}"
