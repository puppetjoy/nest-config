# Star private GitLab access

Star's supported path for Joy-owned private GitLab repositories is the
profile-local shell identity, not the secure browser's GitLab web UI. The
secure browser may land on the GitLab sign-in page unless Joy has an
interactive web session, while the shell path can use Star's dedicated GitLab
SSH key and profile-local `glab` token without exposing credential material to
the agent.

Use the normal Git SSH URL for repository reads and pushes:

```sh
git clone git@gitlab.joyfullee.me:<group>/<project>.git
```

The Star profile environment sets:

```sh
GITLAB_HOST=gitlab.joyfullee.me
GITLAB_URL=https://gitlab.joyfullee.me
GIT_SSH_COMMAND='ssh -F /home/joy/.hermes/profiles/star/.ssh/config -o ControlMaster=no -o ControlPath=none'
```

The matching Star SSH config maps `gitlab.joyfullee.me` to
`ssh.gitlab.eyrie`, uses user `git`, and points SSH at
`/home/joy/.hermes/profiles/star/.ssh/id_ed25519` with `IdentitiesOnly yes`.
Do not inspect or print the private key.

Star also has a Puppet-managed profile-local `glab` config at
`/home/joy/.hermes/profiles/star/glab/config.yml`. Its token is scoped for
GitLab API issue/work-item workflows on Star-owned planning threads, including
creating safe issue notes in `joy/wardrobe-rebuild`. Do not print token
contents. Safe checks are bounded reads such as `glab issue list --repo
joy/wardrobe-rebuild`, plus harmless notes or issue/work-item updates that do
not include secrets or personal data.

If future Star private-repo or issue/work-item operations fail, first verify
that the profile-local key/config files exist with `0600` permissions, that the
Star profile environment includes `GIT_SSH_COMMAND`, and that `GLAB_CONFIG_DIR`
points at `/home/joy/.hermes/profiles/star/glab`. Do not fall back to Joy's
browser session or another agent's GitLab token unless Joy explicitly
authorizes that identity boundary change.
