FROM nest/tools/bolt

ARG BRANCH
ARG REPOSITORY

ENV BOLT_PROJECT=/opt/nest
RUN git clone -b "$BRANCH" "$REPOSITORY" "$BOLT_PROJECT"
RUN --mount=type=secret,id=ssh_private_key "$BOLT_PROJECT/bin/ci-bolt-module-install"
RUN ln -s "${BOLT_PROJECT}/bin/build" /usr/local/bin/build
