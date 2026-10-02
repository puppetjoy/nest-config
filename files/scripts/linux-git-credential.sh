#!/bin/sh
# Git credential protocol: return the project-only token for this exact repo.
# Never persist credentials supplied by Git or answer another repository.
[ "$1" = get ] || exit 0
protocol= host= path=
while IFS='=' read -r key value; do
  case "$key" in
    protocol) protocol=$value ;;
    host) host=$value ;;
    path) path=$value ;;
  esac
done
[ "$protocol" = https ] || exit 0
[ "$host" = gitlab.joyfullee.me ] || exit 0
[ "$path" = nest/forks/linux.git ] || exit 0
exec /bin/cat /etc/nest-linux-git-credential
