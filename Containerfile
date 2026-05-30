FROM nest/tools/bolt

ARG BRANCH
ARG REPOSITORY

ENV BOLT_PROJECT=/opt/nest
RUN git clone -b "$BRANCH" "$REPOSITORY" "$BOLT_PROJECT"
RUN --mount=type=secret,id=ssh_private_key zsh -c 'set -x; eval $(ssh-agent -s); ssh-add /run/secrets/ssh_private_key; bolt module install --force --verbose || { status=$?; echo "bolt module install failed with status $status"; echo "generated Puppetfile:"; sed -n "1,220p" /opt/nest/Puppetfile; echo "module directory snapshot:"; find /opt/nest/.modules -maxdepth 2 -mindepth 1 -type d -print 2>/dev/null | sort | sed -n "1,220p"; echo "retrying sync directly with r10k debug output"; r10k puppetfile install --puppetfile /opt/nest/Puppetfile --moduledir /opt/nest/.modules --verbose debug; exit $status; }'
RUN ln -s "${BOLT_PROJECT}/bin/build" /usr/local/bin/build
