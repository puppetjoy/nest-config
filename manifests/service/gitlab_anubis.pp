# Public GitLab filter. The internal GitLab and registry routes do not use it.
class nest::service::gitlab_anubis (
  Sensitive[String] $signing_key,
) {
  # Retire only dedicated renewal configuration, not certificate/key archives.
  file { [
    '/etc/letsencrypt/renewal/gitlab.james.tl.conf',
    '/etc/letsencrypt/renewal/registry.gitlab.james.tl.conf',
  ]:
    ensure => absent,
  }

  file_line { 'gitlab-retired-renewal-webroot':
    ensure            => absent,
    path              => '/etc/letsencrypt/renewal/gitlab.joyfullee.me.conf',
    match             => '^gitlab[.]james[.]tl = ',
    match_for_absence => true,
  }

  nest::lib::secret { 'gitlab-anubis-signing-key':
    value => $signing_key,
  }

  file { '/etc/gitlab-anubis.yaml':
    owner  => 'root',
    group  => 'root',
    mode   => '0644',
    source => 'puppet:///modules/nest/gitlab/anubis.yaml',
    notify => Service['container-gitlab-anubis'],
  }

  nest::lib::container { 'gitlab-anubis':
    # Upstream v1.28.2, immutable published image digest.
    image   => 'ghcr.io/techarohq/anubis@sha256:7be540e764715f583f2c6a429e94075a79942b935c2a96c462111c380bd12c21',
    network => 'host',
    env     => [
      'BIND=127.0.0.1:8923',
      'METRICS_BIND=127.0.0.1:8924',
      'TARGET=https://gitlab.eyrie',
      'TARGET_HOST=gitlab.eyrie',
      'SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt',
      'POLICY_FNAME=/etc/gitlab-anubis.yaml',
      'REDIRECT_DOMAINS=gitlab.joyfullee.me',
      'PUBLIC_URL=https://gitlab.joyfullee.me',
      'COOKIE_EXPIRATION_TIME=24h',
      'COOKIE_HTTP_ONLY=true',
      'COOKIE_SAME_SITE=Lax',
      'SLOG_LEVEL=WARN',
      'OG_PASSTHROUGH=false',
    ],
    secrets => { 'gitlab-anubis-signing-key' => 'ED25519_PRIVATE_KEY_HEX' },
    volumes => [
      '/etc/gitlab-anubis.yaml:/etc/gitlab-anubis.yaml:ro',
      '/etc/ssl/certs/ca-certificates.crt:/etc/ssl/certs/ca-certificates.crt:ro',
    ],
    require => [File['/etc/gitlab-anubis.yaml'], Nest::Lib::Secret['gitlab-anubis-signing-key']],
    before  => Apache::Vhost['gitlab.joyfullee.me-ssl'],
  }
}
