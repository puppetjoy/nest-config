FROM nest/tools/bolt

ARG BRANCH
ARG REPOSITORY

ENV BOLT_PROJECT=/opt/nest
RUN git clone -b "$BRANCH" "$REPOSITORY" "$BOLT_PROJECT"
RUN --mount=type=secret,id=ssh_private_key zsh -c 'set -e; \
    eval $(ssh-agent -s); \
    ssh-add /run/secrets/ssh_private_key; \
    printf "Resolver configuration:\n"; \
    cat /etc/resolv.conf; \
    printf "Targeted name lookups:\n"; \
    for host in gitlab.joyfullee.me registry.gitlab.joyfullee.me ssh.gitlab.eyrie forgeapi.puppet.com github.com; do \
      printf "== %s ==\n" "$host"; \
      getent hosts "$host" || true; \
    done; \
    printf "Route to Nest DNS:\n"; \
    ip route get 172.22.4.3 || true; \
    bolt module install --verbose'
RUN ln -s "${BOLT_PROJECT}/bin/build" /usr/local/bin/build
