class nest::service::bitwarden (
  String $admin_token,
  String $database_password,
  String $smtp_username,
  String $smtp_password,
) {
  if defined(Class['nest::kubernetes']) {
    $database_url = base64('encode', "mysql://${nest::kubernetes::service}:${database_password}@${nest::kubernetes::service}-mariadb/${nest::kubernetes::service}")

    # See: https://github.com/dani-garcia/vaultwarden/wiki/Enabling-admin-page#secure-the-admin_token
    $admin_token_hash = generate(
      '/bin/sh',
      '-c',
      "echo -n ${admin_token.shellquote} | argon2 `openssl rand -base64 32` -e -id -k 65540 -t 3 -p 4",
    ).chomp
  } else {
    nest::lib::srv { 'bitwarden': }
    ->
    file { '/srv/bitwarden/data':
      ensure => directory,
      mode   => '0755',
      owner  => 'root',
      group  => 'root',
    }
    ->
    nest::lib::container { 'bitwarden':
      image   => 'vaultwarden/server',
      dns     => '172.22.4.3',
      env     => [
        'DOMAIN=https://vault.thesatelliteoflove.net',
        "ADMIN_TOKEN=${admin_token}",
        "DATABASE_URL=mysql://bitwarden:${database_password}@web.nest/bitwarden",
        'ENABLE_DB_WAL=false',
        'INVITATION_ORG_NAME=Bitwarden',
        'IP_HEADER=X-Forwarded-For',
        'SIGNUPS_ALLOWED=false',
        'SHOW_PASSWORD_HINT=false',
        'SMTP_HOST=smtp-relay.gmail.com',
        'SMTP_FROM=bitwarden@vault.thesatelliteoflove.net',
        'SMTP_FROM_NAME=Bitwarden',
        "SMTP_USERNAME=${smtp_username}",
        "SMTP_PASSWORD=${smtp_password}",
        'WEBSOCKET_ENABLED=true',
      ],
      publish => ['8080:80', '3012:3012'],
      volumes => ['/srv/bitwarden/data:/data'],
    }
  }
}
