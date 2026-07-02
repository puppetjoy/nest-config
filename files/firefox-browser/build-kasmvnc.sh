#!/bin/bash
set -euo pipefail

src_dir="${1:-/usr/src/KasmVNC}"
build_root="${KASMVNC_BUILD_ROOT:-/var/tmp/kasmvnc-build}"
src_link="${KASMVNC_SRC_LINK:-/src}"
parallelism="${KASMVNC_MAKE_JOBS:-$(nproc)}"
npm_command="${NPM_COMMAND:-npm}"
xorg_ver="${XORG_VER:-1.20.14}"

mkdir -p "$build_root" /opt/kasmweb/bin /opt/kasmweb/share/kasmvnc

cd "$src_dir"
git submodule update --init kasmweb

# KasmVNC v1.4.0 vendor helper scripts fetch a few current upstream CMake
# projects whose old cmake_minimum_required() values are rejected by modern
# CMake. Keep the source-build path deterministic by injecting the compatibility
# policy into those helper CMake calls before the upstream builder runs.
for cmake_helper in \
  "$src_dir/builder/build.sh" \
  "$src_dir/builder/scripts/build-tbb" \
  "$src_dir/builder/scripts/build-libjpeg-turbo" \
  "$src_dir/builder/scripts/build-cpuid"; do
  if [ -f "$cmake_helper" ] && ! grep -q 'CMAKE_POLICY_VERSION_MINIMUM' "$cmake_helper"; then
    sed -i 's/cmake /cmake -DCMAKE_POLICY_VERSION_MINIMUM=3.5 /g' "$cmake_helper"
  fi
done
if [ -f "$src_dir/CMakeLists.txt" ]; then
  sed -i 's/cmake_policy(SET CMP0022 OLD)/cmake_policy(SET CMP0022 NEW)/' "$src_dir/CMakeLists.txt"
fi
export PKG_CONFIG_PATH="/usr/local/lib64/pkgconfig:/usr/local/lib/pkgconfig:${PKG_CONFIG_PATH:-}"

# KasmVNC's upstream builder expects the source checkout at /src and writes
# intermediate release artifacts below /build. Keep those conventions inside the
# image build while making the Nest-owned source checkout explicit via
# nest::lib::src_repo.
if [ -e "$src_link" ] && [ "$(readlink -f "$src_link")" != "$(readlink -f "$src_dir")" ]; then
  rm -rf "$src_link"
fi
ln -sfn "$src_dir" "$src_link"
mkdir -p /build

# Build the browser client once from the pinned checkout, then build Xvnc with
# the bundled KasmVNC/Xorg patch flow. The helper script disables GnuTLS in its
# CMake invocation and serves TLS with the certificate passed to Xvnc at runtime.
cd "$src_dir/kasmweb"
"$npm_command" install --legacy-peer-deps
"$npm_command" run build

# KasmVNC's packaging target expects the already-built web client at
# builder/www. The upstream Docker build normally prepares that directory as a
# separate layer; in the Nest source-managed build, keep the handoff explicit so
# builder/build.sh can finish without depending on an ad-hoc image step.
rm -rf "$src_dir/builder/www"
cp -a "$src_dir/kasmweb/dist" "$src_dir/builder/www"

cd "$src_dir"
"$src_dir/builder/scripts/build-libjpeg-turbo"
"$src_dir/builder/scripts/build-webp"
"$src_dir/builder/scripts/build-cpuid"
rm -rf \
  CMakeCache.txt \
  CMakeFiles \
  cmake_install.cmake \
  cmake_uninstall.cmake \
  config.h
SCCACHE_DISABLE="${SCCACHE_DISABLE:-1}" \
CFLAGS="${CFLAGS:-} -std=gnu17" \
MAKEFLAGS="-j${parallelism}" \
XORG_VER="$xorg_ver" \
KASMVNC_BUILD_OS="gentoo" \
KASMVNC_BUILD_OS_CODENAME="nest" \
BUILD_TAG="" \
SCRIPTS_DIR="$src_dir/builder/scripts" \
./builder/build.sh

install -m 0755 "$src_dir/xorg.build/bin/Xvnc" /opt/kasmweb/bin/Xvnc
rm -rf /opt/kasmweb/share/kasmvnc/www
mkdir -p /opt/kasmweb/share/kasmvnc
cp -a "$src_dir/kasmweb/dist" /opt/kasmweb/share/kasmvnc/www
