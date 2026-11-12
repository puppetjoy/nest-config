# Work GitLab access

`http://gitlab.puppet` is the canonical URL for the private work/lab GitLab
on Hawk. It is separate from Nest GitLab. The `.eyrie` namespace is reserved
for Kubernetes services; `joyfullee.me` is for personal public services.

## Resolution and transport

- Hawk resolves `gitlab.puppet` to `127.0.0.1` through Puppet-managed hosts data.
- Nest DNS resolves `gitlab.puppet` to Hawk's stable Nest VPN address,
  `172.22.0.2`. Clients require a working Nest route and private DNS.
- Static Nest clients route `.puppet` queries to Kestrel alongside their other
  private suffixes, rather than the public-DNS failover resolver.
- Existing lab VM mappings may continue to use the host-side bridge address
  `10.81.40.1` while that VM network is active. The bridge is not a dependency
  for host or Nest client access. Guest resolution must be verified in the
  actual lab; no guest mapping is changed by this configuration.
- `gitlab.localhost` is only a Hawk-local browser convenience. On Owl or in a
  VM it refers to that client's own loopback, not Hawk.

GitLab HTTP is published on Hawk port 80 and Git SSH on port 2222. This change
preserves existing HTTP service and access policy; it does not introduce TLS,
public ingress, additional firewall openings or a new GitLab instance.

## Quill

Quill's Hermes runtime runs on Owl, but its configured terminal backend executes
as `joy` on Hawk over SSH. Terminal commands therefore use Hawk's resolution.
The existing dedicated Git SSH identity and strict host-key verification remain
unchanged:

```sh
GIT_SSH_COMMAND='ssh -F /home/joy/.hermes/profiles/quill/.ssh/config' \
  git ls-remote ssh://git@gitlab.puppet:2222/puppet/puppet-modernization.git HEAD
quill-gitlab-api GET /api/v4/projects/3
```

The API helper preserves the canonical HTTP hostname while routing through its
existing restricted loopback SSH tunnel. It does not depend on `.puppet` DNS.

## Acceptance

With `vagrant-puppet0` inactive, verify Hawk resolves the canonical name to
loopback, Owl resolves it to `172.22.0.2`, both load `/users/sign_in`, and Quill's
ordinary Git and API commands can read the modernization project. Repeat scoped
Puppet noops to check convergence. An inactive guest is not a passed VM test.
