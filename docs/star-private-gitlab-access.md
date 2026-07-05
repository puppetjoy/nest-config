# Star private GitLab read access

Star's supported path for Joy-owned private GitLab repository reads is shell
Git over the profile-local SSH identity, not the secure browser's GitLab web
UI. The secure browser may land on the GitLab sign-in page unless Joy has an
interactive web session, while the shell path can use Star's SSH key without
exposing key material to the agent.

Use the normal Git SSH URL for the repository:

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
Do not inspect or print the private key. A safe read check is a bounded clone
or `git ls-remote` against the specific repository.

If future Star private-repo reads fail, first verify that the profile-local
key file and config exist with `0600` permissions and that the Star profile
environment includes `GIT_SSH_COMMAND`. Do not fall back to Joy's browser
session or another agent's GitLab token unless Joy explicitly authorizes that
identity boundary change.
