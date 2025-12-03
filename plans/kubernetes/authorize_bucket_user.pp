plan nest::kubernetes::authorize_bucket_user (
  Variant[String, Array[String]] $bucket,
  String                         $namespace,
  String                         $user,
  Boolean                        $authorize = true,
) {
  if $authorize {
    $buckets = [$bucket].flatten

    $buckets.each |$bucket_name| {
      # Config may not be available immediately after bucket creation so retry
      $bucket_config = ctrl::do_until(limit => 3, interval => 10) || {
        nest::kubernetes::bucket_config($bucket_name, $namespace)
      }

      unless $bucket_config {
        fail_plan("Could not retrieve bucket config for bucket ${bucket_name} in namespace ${namespace}")
      }

      # More access than necessary, but better than debugging issues later
      $policy = {
        'Version'   => '2012-10-17',
        'Statement' => [
          {
            'Effect'   => 'Allow',
            'Principal' => {
              'AWS' => ["arn:aws:iam:::user/${user}"],
            },
            'Action'   => 's3:*',
            'Resource' => [
              "arn:aws:s3:::${bucket_config['BUCKET_NAME']}",
              "arn:aws:s3:::${bucket_config['BUCKET_NAME']}/*",
            ],
          },
        ],
      }

      write_file($policy.stdlib::to_json_pretty, '/tmp/bucket-policy.json', 'localhost')

      $s3cmd = [
        's3cmd',
        "--access_key=${bucket_config['AWS_ACCESS_KEY_ID']}",
        "--secret_key=${bucket_config['AWS_SECRET_ACCESS_KEY']}",
        "--host=${bucket_config['BUCKET_HOST']}",
        "--host-bucket=%(bucket)s.${bucket_config['BUCKET_HOST']}",
        '--no-ssl',
        'setpolicy',
        '/tmp/bucket-policy.json',
        "s3://${bucket_config['BUCKET_NAME']}",
      ].shellquote

      run_command($s3cmd, 'localhost', "Set bucket policy for user ${user} on bucket ${bucket_name}")
    }
  }
}
