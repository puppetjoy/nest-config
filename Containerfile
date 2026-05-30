FROM nest/tools/bolt

ARG BRANCH
ARG REPOSITORY

ENV BOLT_PROJECT=/opt/nest
RUN git clone -b "$BRANCH" "$REPOSITORY" "$BOLT_PROJECT"
RUN --mount=type=secret,id=ssh_private_key zsh -c 'eval $(ssh-agent -s) && ssh-add /run/secrets/ssh_private_key && GIT_SSH_COMMAND="ssh -F none -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/tmp/gitlab_known_hosts" bolt module install'
RUN ln -s "${BOLT_PROJECT}/bin/build" /usr/local/bin/build
