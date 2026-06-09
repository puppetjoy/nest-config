#!/usr/bin/env python3
"""Daily consolidated Nest release/update digest for Joy.

The digest is intentionally a no-agent Hermes cron script: it does its own
source/live-pin discovery, upstream polling, classification, state dedupe, and
Telegram-ready formatting without spending model tokens. It prints nothing when
there is no actionable/watch-worthy drift unless --force is used for review or
manual sampling.
"""
from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import importlib.metadata as metadata
import json
import os
import re
import subprocess
import sys
import textwrap
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

REPO = Path(os.environ.get("NEST_CONFIG_REPO", "/home/joy/projects/nest/config"))
HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
STATE_PATH = HERMES_HOME / "state" / "release-digest.json"
USER_AGENT = "Hermes consolidated release digest"


class WatcherError(RuntimeError):
    pass


@dataclass(frozen=True)
class Component:
    id: str
    label: str
    stack: str
    current: str
    latest: str
    classification: str
    priority: str
    context: str
    url: str = ""


@dataclass(frozen=True)
class WatchResult:
    stack: str
    components: list[Component]
    errors: list[str]


def read(path: Path) -> str:
    try:
        return path.read_text()
    except OSError as exc:
        raise WatcherError(f"could not read {path}: {exc}") from exc


def run(cmd: list[str], timeout: int = 120) -> str:
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT, timeout=timeout)
    except subprocess.CalledProcessError as exc:
        raise WatcherError(f"command failed: {cmd!r}\n{exc.output.strip()}") from exc
    except subprocess.TimeoutExpired as exc:
        raise WatcherError(f"command timed out: {cmd!r}") from exc


def fetch_bytes(url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> bytes:
    req_headers = {"User-Agent": USER_AGENT, "Accept": "application/json, text/xml, */*"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as exc:  # noqa: BLE001 - watchdog should report API/network failures compactly
        raise WatcherError(f"could not fetch {url}: {exc}") from exc


def fetch_json(url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> dict[str, Any]:
    return json.loads(fetch_bytes(url, headers=headers, timeout=timeout).decode())


def fetch_text(url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> str:
    return fetch_bytes(url, headers=headers, timeout=timeout).decode("utf-8", errors="replace")


def version_key(version: str | None) -> tuple[Any, ...]:
    if not version:
        return ()
    cleaned = version.strip().lstrip("v")
    parts: list[Any] = []
    for part in re.split(r"([0-9]+)", cleaned):
        if not part:
            continue
        parts.append(int(part) if part.isdigit() else part)
    return tuple(parts)


def newer(latest: str, current: str) -> bool:
    return version_key(latest) > version_key(current)


def first_match(pattern: str, text: str, label: str, flags: int = re.S | re.M) -> str:
    match = re.search(pattern, text, flags)
    if not match:
        raise WatcherError(f"could not find {label}")
    return match.group(1).strip()


def chart_index_latest(url: str, chart_name: str, *, stable_only: bool = True) -> dict[str, str]:
    text = fetch_text(url)
    # Minimal YAML-ish parser for Helm index entries; avoids a PyYAML dependency
    # in cron's standard-library-only path.
    in_chart = False
    rows: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if re.match(rf"^  {re.escape(chart_name)}:\s*$", line):
            in_chart = True
            continue
        if in_chart and re.match(r"^  [A-Za-z0-9_.-]+:\s*$", line) and not line.strip().startswith("-"):
            break
        if not in_chart:
            continue
        if line.startswith("  - "):
            if current:
                rows.append(current)
            current = {}
            line = line[4:]
            if ":" in line:
                key, value = line.split(":", 1)
                current[key.strip()] = value.strip().strip('"')
            continue
        if current is not None and line.startswith("    ") and ":" in line:
            key, value = line.split(":", 1)
            current[key.strip()] = value.strip().strip('"')
    if current:
        rows.append(current)
    if stable_only:
        stable_rows = [row for row in rows if not re.search(r"(?i)(?:-|\b)(alpha|beta|rc|pre|prerelease|dev|develop|snapshot|nightly)", row.get("version", ""))]
        if stable_rows:
            rows = stable_rows
    if not rows:
        raise WatcherError(f"could not find {chart_name} entries in {url}")
    return max(rows, key=lambda row: version_key(row.get("version", "")))


def ghcr_token(repo: str) -> str:
    data = fetch_json(f"https://ghcr.io/token?scope=repository:{repo}:pull")
    token = str(data.get("token") or "")
    if not token:
        raise WatcherError(f"GHCR did not return a token for {repo}")
    return token


def ghcr_tags(repo: str, max_pages: int = 100) -> list[str]:
    token = ghcr_token(repo)
    tags: list[str] = []
    last = ""
    for _ in range(max_pages):
        query = "?n=100"
        if last:
            query += "&last=" + urllib.parse.quote(last)
        data = fetch_json(f"https://ghcr.io/v2/{repo}/tags/list{query}", headers={"Authorization": f"Bearer {token}"})
        batch = [str(t) for t in data.get("tags") or []]
        if not batch:
            break
        tags.extend(batch)
        if len(batch) < 100:
            break
        last = batch[-1]
    return sorted(set(tags))


def docker_tags(image: str, prefix: str) -> list[str]:
    url = f"https://registry.hub.docker.com/v2/repositories/{image}/tags?page_size=100&name={urllib.parse.quote(prefix)}"
    tags: list[str] = []
    seen: set[str] = set()
    while url and url not in seen:
        seen.add(url)
        data = fetch_json(url)
        tags.extend(str(row.get("name") or "") for row in data.get("results") or [])
        url = str(data.get("next") or "")
    return sorted(set(t for t in tags if t))


def installed_hermes_version() -> str:
    for dist in ("hermes-agent", "hermes_agent"):
        try:
            return metadata.version(dist)
        except metadata.PackageNotFoundError:
            pass
    venv_python = Path("/opt/hermes-agent/venv/bin/python")
    if venv_python.exists():
        code = """
import importlib.metadata as m
for d in ('hermes-agent', 'hermes_agent'):
    try:
        print(m.version(d))
        break
    except m.PackageNotFoundError:
        pass
"""
        try:
            out = run([str(venv_python), "-c", code], timeout=10).strip().splitlines()
            if out:
                return out[0]
        except WatcherError:
            pass
    return "unknown"


def summarize_release(body: str, limit: int = 4) -> str:
    items: list[str] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line or not line.startswith(("-", "*")):
            continue
        item = re.sub(r"^[-*]\s*", "", line).strip()
        if not item or item.lower().startswith(("full changelog", "compare:")):
            continue
        if len(item) > 170:
            item = item[:167].rstrip() + "…"
        items.append(item)
        if len(items) >= limit:
            break
    return "; ".join(items)


def comp(stack: str, component_id: str, label: str, current: str, latest: str, classification: str, priority: str, context: str, url: str = "") -> Component | None:
    if not latest or not current or not newer(latest, current):
        return None
    return Component(component_id, label, stack, current, latest, classification, priority, context, url)


def watch_hermes() -> WatchResult:
    release = fetch_json("https://api.github.com/repos/NousResearch/hermes-agent/releases/latest", headers={"Accept": "application/vnd.github+json"})
    tag = str(release.get("tag_name") or "")
    text = "\n".join(str(release.get(k) or "") for k in ("name", "tag_name", "body"))
    version = first_match(r"\bv?(\d+\.\d+\.\d+)\b", text, "Hermes release version", flags=0)
    current = installed_hermes_version()
    item = comp(
        "Hermes",
        "hermes-agent",
        "Hermes Agent release",
        current,
        version,
        "action needed",
        "high",
        "Update the Nest fork/rolling tag and run Puppet only after checking Joy's patch-stack workflow. " + summarize_release(str(release.get("body") or "")),
        str(release.get("html_url") or f"https://github.com/NousResearch/hermes-agent/releases/tag/{tag}"),
    )
    return WatchResult("Hermes", [item] if item else [], [])


def parse_atom_feed(url: str) -> list[dict[str, str]]:
    root = ET.fromstring(fetch_text(url))
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries = []
    for entry in root.findall("atom:entry", ns):
        title = entry.findtext("atom:title", default="", namespaces=ns)
        link_el = entry.find("atom:link", ns)
        link = link_el.attrib.get("href", "") if link_el is not None else ""
        updated = entry.findtext("atom:updated", default="", namespaces=ns)
        summary = entry.findtext("atom:summary", default="", namespaces=ns) or entry.findtext("atom:content", default="", namespaces=ns)
        entries.append({"title": title, "link": link, "updated": updated, "summary": summary})
    return entries


def gitlab_versions_from_title(title: str) -> list[str]:
    if "not yet released" in title.lower():
        return []
    versions: list[str] = []
    for raw in re.findall(r"\b\d+\.\d+(?:\.\d+)?\b", title):
        if raw.count(".") == 1:
            raw = raw + ".0"
        versions.append(raw)
    return versions


def gitlab_version_from_feed(title: str) -> str:
    versions = gitlab_versions_from_title(title)
    return max(versions, key=version_key) if versions else ""


def gitlab_current_version() -> str:
    url = os.environ.get("GITLAB_URL")
    token = os.environ.get("GITLAB_TOKEN")
    if not url or not token:
        return "unknown"
    data = fetch_json(f"{url.rstrip('/')}/api/v4/version", headers={"PRIVATE-TOKEN": token})
    return str(data.get("version") or "unknown")


def watch_gitlab() -> WatchResult:
    entries = parse_atom_feed("https://docs.gitlab.com/releases/releases.xml") + parse_atom_feed("https://docs.gitlab.com/releases/patch-releases.xml")
    latest_entry = max((e for e in entries if gitlab_version_from_feed(e["title"])), key=lambda e: version_key(gitlab_version_from_feed(e["title"])))
    latest = gitlab_version_from_feed(latest_entry["title"])
    current = gitlab_current_version()
    chart = ""
    try:
        chart_rows = chart_index_latest("https://charts.gitlab.io/index.yaml", "gitlab")
        if str(chart_rows.get("appVersion") or "") == latest:
            chart = str(chart_rows.get("version") or "")
    except WatcherError:
        chart = "unknown"
    context = "Self-managed GitLab release cadence item; plan test/prod Helm, hawk Omnibus, custom Workhorse, and runners rather than upgrading automatically."
    if chart:
        context += f" Matching/latest chart context: {chart}."
    item = comp("GitLab", "gitlab", "Self-managed GitLab", current, latest, "action needed", "high", context, latest_entry.get("link", ""))
    return WatchResult("GitLab", [item] if item else [], [])


def watch_vaultwarden() -> WatchResult:
    app = read(REPO / "data/kubernetes/app/vaultwarden.yaml")
    plan = read(REPO / "plans/eyrie/vaultwarden/deploy.yaml")
    current = {
        "server": first_match(r"(?m)^\s*tag:\s*['\"]?([^'\"\s]+)['\"]?\s*$", app, "Vaultwarden image tag", flags=0),
        "chart": first_match(r"chart:\s*'guerzon/vaultwarden'.*?\n\s*repo_url:\s*'https://guerzon.github.io/vaultwarden'.*?\n\s*version:\s*'([^']+)'", plan, "Vaultwarden chart"),
        "mariadb": first_match(r"chart:\s*'oci://registry-1\.docker\.io/bitnamicharts/mariadb'.*?\n\s*version:\s*'([^']+)'", plan, "Vaultwarden MariaDB chart"),
    }
    release = fetch_json("https://api.github.com/repos/dani-garcia/vaultwarden/releases/latest")
    server_latest = str(release.get("tag_name") or "").lstrip("v")
    run(["helm", "repo", "add", "guerzon", "https://guerzon.github.io/vaultwarden"], timeout=60)
    run(["helm", "repo", "update", "guerzon"], timeout=90)
    chart_rows = json.loads(run(["helm", "search", "repo", "guerzon/vaultwarden", "--versions", "-o", "json"], timeout=60))
    chart_latest = chart_rows[0]
    mariadb = run(["helm", "show", "chart", "oci://registry-1.docker.io/bitnamicharts/mariadb"], timeout=120)
    mariadb_latest = first_match(r"(?m)^version:\s*([^\s]+)\s*$", mariadb, "latest MariaDB chart", flags=0)
    mariadb_app = first_match(r"(?m)^appVersion:\s*['\"]?([^'\"\s]+)['\"]?\s*$", mariadb, "latest MariaDB appVersion", flags=0)
    items = [
        comp("Vaultwarden", "vaultwarden-server", "Vaultwarden server image", current["server"], server_latest, "action needed", "high", "Server image is behind; review release notes and roll test before prod.", str(release.get("html_url") or "")),
        comp("Vaultwarden", "vaultwarden-chart", "guerzon/vaultwarden Helm chart", current["chart"], str(chart_latest.get("version") or ""), "watch only", "low" if str(chart_latest.get("app_version") or "") == current["server"] else "medium", f"Chart appVersion {chart_latest.get('app_version') or 'unknown'} vs pinned server {current['server']}; render before rollout.", "https://github.com/guerzon/vaultwarden/releases"),
        comp("Vaultwarden", "vaultwarden-mariadb", "Bitnami MariaDB chart", current["mariadb"], mariadb_latest, "action needed", "medium-high", f"Database subchart movement; backup and test-first rollout required. Latest MariaDB appVersion {mariadb_app}.", "https://github.com/bitnami/charts/tree/main/bitnami/mariadb"),
    ]
    return WatchResult("Vaultwarden", [i for i in items if i], [])


def watch_wordpress() -> WatchResult:
    plan = read(REPO / "plans/eyrie/wordpress/deploy.yaml")
    values = read(REPO / "data/kubernetes/app/wordpress.yaml")
    current_chart = first_match(r"chart:\s*'oci://registry-1\.docker\.io/bitnamicharts/wordpress'.*?\n\s*version:\s*'([^']+)'", plan, "WordPress chart")
    local_image = first_match(r"(?ms)^values:.*?^\s{2}image:\s*\n\s{4}tag:\s*['\"]?([^'\"\s]+)['\"]?\s*$", values, "WordPress image tag")
    chart = run(["helm", "show", "chart", "oci://registry-1.docker.io/bitnamicharts/wordpress"], timeout=180)
    latest_chart = first_match(r"(?m)^version:\s*([^\s]+)\s*$", chart, "latest WordPress chart", flags=0)
    app_version = first_match(r"(?m)^appVersion:\s*['\"]?([^'\"\s]+)['\"]?\s*$", chart, "latest WordPress appVersion", flags=0)
    wp_data = fetch_json("https://api.wordpress.org/core/version-check/1.7/")
    offers = wp_data.get("offers") or []
    core = str((next((o for o in offers if o.get("response") == "upgrade"), offers[0]) if offers else {}).get("current") or "")
    items = [
        comp("WordPress", "wordpress-chart", "Bitnami WordPress chart", current_chart, latest_chart, "watch only", "medium", f"Chart/scaffolding drift. Current source image tag is {local_image}; latest chart appVersion is {app_version}. Render and inspect images before rollout.", "https://github.com/bitnami/charts/tree/main/bitnami/wordpress"),
        comp("WordPress", "wordpress-core", "WordPress core upstream", app_version, core, "watch only", "medium", "Upstream core is newer than latest Bitnami image metadata; live sites may self-update, but container scaffolding may lag.", "https://wordpress.org/download/releases/"),
    ]
    return WatchResult("WordPress", [i for i in items if i], [])


def installed_python_package_version(pkgname: str) -> str:
    venv_python = Path("/opt/hermes-agent/venv/bin/python")
    code = f"""
import importlib.metadata as m
try:
    print(m.version({pkgname!r}))
except m.PackageNotFoundError:
    pass
"""
    if venv_python.exists():
        try:
            out = run([str(venv_python), "-c", code], timeout=10).strip().splitlines()
            if out:
                return out[0]
        except WatcherError:
            pass
    try:
        return metadata.version(pkgname)
    except metadata.PackageNotFoundError:
        return "unknown"


def watch_honcho() -> WatchResult:
    values = read(REPO / "data/kubernetes/app/honcho.yaml")
    current = {
        "honcho": first_match(r"(?m)^honcho_image:\s*ghcr\.io/plastic-labs/honcho:(\S+)\s*$", values, "Honcho image", flags=0),
        "honcho_ai": installed_python_package_version("honcho-ai"),
        "postgres": first_match(r"(?m)^postgres_image:\s*ghcr\.io/cloudnative-pg/postgresql:(\S+)\s*$", values, "CNPG Postgres image", flags=0),
        "redis": first_match(r"(?m)^\s*image:\s*docker\.io/library/redis:(\S+)\s*$", values, "Redis image", flags=0),
    }
    honcho_latest = max([t for t in ghcr_tags("plastic-labs/honcho") if re.fullmatch(r"v\d+\.\d+\.\d+", t)], key=version_key)
    honcho_ai_latest = str((fetch_json("https://pypi.org/pypi/honcho-ai/json").get("info") or {}).get("version") or "")
    pg_major = re.match(r"^(\d+)\.", current["postgres"])
    pg_latest = max([t for t in ghcr_tags("cloudnative-pg/postgresql") if pg_major and re.fullmatch(rf"{pg_major.group(1)}\.\d+(?:-\d+)?", t)], key=version_key)
    redis_major = re.match(r"^(\d+)", current["redis"])
    redis_latest = max([t for t in docker_tags("library/redis", redis_major.group(1) + "." if redis_major else "") if redis_major and re.fullmatch(rf"{redis_major.group(1)}\.\d+(?:\.\d+)?", t)], key=version_key)
    items = [
        comp("Honcho", "honcho-server", "Honcho server image", current["honcho"], honcho_latest, "action needed", "high", "Honcho API/deriver image is behind; roll through test and verify /health plus queue/deriver behavior.", "https://github.com/plastic-labs/honcho/pkgs/container/honcho"),
        comp("Honcho", "honcho-ai", "honcho-ai Python SDK", current["honcho_ai"], honcho_ai_latest, "watch only", "medium", "Hermes venv dependency floor is behind; review SDK/API compatibility before raising it.", "https://pypi.org/project/honcho-ai/"),
        comp("Honcho", "honcho-postgres", "CNPG PostgreSQL image", current["postgres"], pg_latest, "action needed", "medium-high", "Database image drift on current major line; backup first and use CNPG health gates.", "https://github.com/cloudnative-pg/postgres-containers/pkgs/container/postgresql"),
        comp("Honcho", "honcho-redis", "Redis image", current["redis"], redis_latest, "watch only", "medium", "Cache/queue plumbing image drift; verify Redis readiness and deriver queue behavior after rollout.", "https://hub.docker.com/_/redis/tags"),
    ]
    return WatchResult("Honcho", [i for i in items if i], [])


def ceph_latest_tag() -> str:
    data = fetch_json("https://quay.io/api/v1/repository/ceph/ceph/tag/?limit=100&onlyActiveTags=true")
    tags = [str(t.get("name") or "") for t in data.get("tags") or []]
    stable = [t for t in tags if re.fullmatch(r"v\d+\.\d+\.\d+(?:-\d{8})?", t)]
    if not stable:
        raise WatcherError("could not find Ceph image tags")
    return max(stable, key=version_key)


def watch_kubernetes_platform() -> WatchResult:
    prod = read(REPO / "plans/kubernetes/deploy_ceph.pp")
    test = read(REPO / "plans/eyrie/test/deploy_ceph.pp")
    network = read(REPO / "plans/kubernetes/deploy_network.yaml")
    ingress = read(REPO / "plans/kubernetes/deploy_ingress.yaml")
    eyrie_ingress = read(REPO / "plans/eyrie/deploy_ingress.yaml")
    test_ingress = read(REPO / "plans/eyrie/test/deploy_ingress.yaml")
    monitoring = read(REPO / "plans/kubernetes/deploy_monitoring.yaml")
    test_monitoring = read(REPO / "plans/eyrie/test/deploy_monitoring.yaml")
    storage = read(REPO / "plans/kubernetes/deploy_storage.yaml")
    ceph_values = read(REPO / "data/kubernetes/app/rook-ceph-cluster.yaml")
    rook_versions = re.findall(r"'chart'\s*=>\s*'rook-release/rook-ceph(?:-cluster)?'.*?'version'\s*=>\s*'([^']+)'", prod + "\n" + test, re.S)
    if not rook_versions:
        raise WatcherError("could not find Rook chart pins")
    pins = {
        "rook": sorted(set(rook_versions), key=version_key)[-1],
        "ceph": first_match(r"(?m)^\s*repository:\s*quay\.io/ceph/ceph\s*\n\s*tag:\s*(v\S+)\s*$", ceph_values, "Ceph image tag", flags=0),
        "calico": first_match(r"(?ms)^\s+chart:\s*'projectcalico/tigera-operator'\s*$.*?^\s+version:\s*'([^']+)'\s*$", network, "Calico chart"),
        "metallb": first_match(r"(?ms)^\s+chart:\s*'metallb/metallb'\s*$.*?^\s+version:\s*'([^']+)'\s*$", network, "MetalLB chart"),
        "cert_manager": first_match(r"(?ms)^\s+chart:\s*'oci://quay\.io/jetstack/charts/cert-manager'\s*$.*?^\s+version:\s*'([^']+)'\s*$", ingress, "cert-manager chart"),
        "contour": sorted(set(re.findall(r"(?ms)^\s+chart:\s*'contour/contour'\s*$.*?^\s+version:\s*'([^']+)'\s*$", "\n".join([ingress, eyrie_ingress, test_ingress]))), key=version_key)[-1],
        "kube_prometheus": sorted(set(re.findall(r"(?ms)^\s+chart:\s*'prometheus-community/kube-prometheus-stack'\s*$.*?^\s+version:\s*'([^']+)'\s*$", "\n".join([monitoring, test_monitoring]))), key=version_key)[-1],
        "nfs_csi": first_match(r"(?ms)^\s+chart:\s*'csi-driver-nfs/csi-driver-nfs'\s*$.*?^\s+version:\s*'([^']+)'\s*$", storage, "NFS CSI chart"),
        "zfs_localpv": first_match(r"(?ms)^\s+chart:\s*'openebs-zfslocalpv/zfs-localpv'\s*$.*?^\s+version:\s*'([^']+)'\s*$", storage, "ZFS LocalPV chart"),
    }
    rook_rel = fetch_json("https://api.github.com/repos/rook/rook/releases/latest")
    cert_rel = fetch_json("https://api.github.com/repos/cert-manager/cert-manager/releases/latest")
    latest = {
        "rook": str(rook_rel.get("tag_name") or "").lstrip("v"),
        "ceph": ceph_latest_tag(),
        "calico": str(chart_index_latest("https://docs.tigera.io/calico/charts/index.yaml", "tigera-operator").get("version") or "").lstrip("v"),
        "metallb": str(chart_index_latest("https://metallb.github.io/metallb/index.yaml", "metallb").get("version") or ""),
        "cert_manager": str(cert_rel.get("tag_name") or "").lstrip("v"),
        "contour": str(chart_index_latest("https://projectcontour.github.io/helm-charts/index.yaml", "contour").get("version") or ""),
        "kube_prometheus": str(chart_index_latest("https://prometheus-community.github.io/helm-charts/index.yaml", "kube-prometheus-stack").get("version") or ""),
        "nfs_csi": str(chart_index_latest("https://raw.githubusercontent.com/kubernetes-csi/csi-driver-nfs/master/charts/index.yaml", "csi-driver-nfs").get("version") or ""),
        "zfs_localpv": str(chart_index_latest("https://openebs.github.io/zfs-localpv/index.yaml", "zfs-localpv").get("version") or ""),
    }
    contexts = {
        "rook": ("Rook/Ceph chart", "action needed", "high", "Storage-platform maintenance: preflight both clusters, roll test, wait for Ready/HEALTH_OK, then prod."),
        "ceph": ("Ceph daemon image", "action needed", "high", "Ceph data-plane maintenance: do not silently combine with chart bumps; require explicit storage window gates."),
        "calico": ("Calico/Tigera chart", "action needed", "high", "Foundational network maintenance: render, roll network component, verify Tigerastatus, APIService, node readiness."),
        "metallb": ("MetalLB chart", "action needed", "high", "Load-balancer/BGP maintenance: verify controller, speaker, FRR-k8s/backend, VIP advertisements and routes."),
        "cert_manager": ("cert-manager chart", "action needed", "medium-high", "Certificate platform maintenance: verify webhook/cainjector/controller and all Certificates Ready."),
        "contour": ("Contour chart", "action needed", "medium-high", "Ingress dataplane maintenance: roll test before prod/role releases and verify Envoy/VIP/HTTP paths."),
        "kube_prometheus": ("kube-prometheus-stack chart", "watch only", "medium", "Observability platform maintenance: preserve test/prod split and verify Prometheus/Grafana/provisioned dashboards."),
        "nfs_csi": ("NFS CSI driver chart", "watch only", "medium", "Storage-adjacent driver maintenance: verify controller/node daemonsets and PVCs remain Bound."),
        "zfs_localpv": ("ZFS LocalPV chart", "watch only", "medium", "Node-local storage driver maintenance: verify CRDs, storage classes, daemonsets, and PVC health."),
    }
    items: list[Component] = []
    for key, latest_version in latest.items():
        label, classification, priority, context = contexts[key]
        item = comp("Kubernetes platform", f"k8s-{key}", label, pins[key], latest_version, classification, priority, context)
        if item:
            items.append(item)
    return WatchResult("Kubernetes platform", items, [])


WATCHERS: list[Callable[[], WatchResult]] = [
    watch_hermes,
    watch_gitlab,
    watch_vaultwarden,
    watch_wordpress,
    watch_honcho,
    watch_kubernetes_platform,
]


def load_state(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def item_signature(item: Component) -> dict[str, str]:
    return {
        "id": item.id,
        "current": item.current,
        "latest": item.latest,
        "classification": item.classification,
        "priority": item.priority,
    }


def digest_signature(items: list[Component], errors: list[str]) -> str:
    payload = {
        "items": [item_signature(i) for i in sorted(items, key=lambda x: x.id)],
        "errors": sorted(errors),
    }
    return json.dumps(payload, sort_keys=True)


def render_digest(items: list[Component], errors: list[str], *, force: bool, checked_at: dt.datetime) -> str:
    if not items and not errors and not force:
        return ""
    lines = ["Joy, here is the daily Nest release digest.", ""]
    if items:
        groups = ["action needed", "watch only", "no action"]
        for classification in groups:
            bucket = [i for i in items if i.classification == classification]
            if not bucket:
                continue
            lines.append(classification.upper())
            for item in sorted(bucket, key=lambda i: (i.stack, i.priority, i.label)):
                lines.append(f"- {item.stack}: {item.label} {item.current} -> {item.latest}")
                lines.append(f"  Priority: {item.priority}")
                lines.append(f"  Context: {item.context.strip()}")
                if item.url:
                    lines.append(f"  Source: {item.url}")
            lines.append("")
    else:
        lines.append("NO ACTION")
        lines.append("- No actionable or watch-worthy release drift found across the consolidated watcher set.")
        lines.append("")
    if errors:
        lines.append("WATCHER ERRORS")
        for err in errors:
            lines.append(f"- {err}")
        lines.append("")
    lines.append(f"Checked: {checked_at.isoformat()}")
    lines.append("Scope: Hermes Agent, GitLab, Vaultwarden, WordPress, Honcho, Kubernetes platform (Rook/Ceph, Calico, MetalLB, Contour, cert-manager, kube-prometheus-stack, NFS CSI, ZFS LocalPV).")
    return "\n".join(lines).rstrip() + "\n"


def offline_sample() -> str:
    checked_at = dt.datetime(2026, 6, 8, 20, 0, tzinfo=dt.timezone.utc)
    items = [
        Component("vaultwarden-chart", "guerzon/vaultwarden Helm chart", "Vaultwarden", "0.37.0", "0.38.0", "watch only", "low", "Chart-only maintenance: appVersion still matches the pinned server image; render before deciding whether to roll.", "https://github.com/guerzon/vaultwarden/releases"),
        Component("k8s-rook", "Rook/Ceph chart", "Kubernetes platform", "1.18.2", "1.19.0", "action needed", "high", "Storage-platform maintenance: schedule a storage window; preflight test/prod Ceph health before rollout.", "https://github.com/rook/rook/releases"),
    ]
    return render_digest(items, [], force=True, checked_at=checked_at)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="print a digest even when all checks are clear or already reported")
    parser.add_argument("--dry-run", action="store_true", help="do not update state")
    parser.add_argument("--state-file", type=Path, default=STATE_PATH)
    parser.add_argument("--offline-sample", action="store_true", help="print a deterministic non-sensitive example digest and exit")
    args = parser.parse_args(argv)

    if args.offline_sample:
        print(offline_sample(), end="")
        return 0

    checked_at = dt.datetime.now(dt.timezone.utc)
    all_items: list[Component] = []
    errors: list[str] = []
    for watcher in WATCHERS:
        try:
            result = watcher()
            all_items.extend(result.components)
            errors.extend(f"{result.stack}: {err}" for err in result.errors)
        except Exception as exc:  # noqa: BLE001 - continue other stacks and report concise failure
            errors.append(f"{watcher.__name__.removeprefix('watch_').replace('_', ' ')}: {type(exc).__name__}: {exc}")

    state = load_state(args.state_file)
    signature = digest_signature(all_items, errors)
    state.update({
        "last_checked_at": checked_at.isoformat(),
        "last_signature": signature,
        "last_item_count": len(all_items),
        "last_error_count": len(errors),
        "last_components": [item_signature(item) for item in all_items],
    })

    already_reported = state.get("last_reported_signature") == signature
    should_print = args.force or errors or (bool(all_items) and not already_reported)
    if should_print:
        output = render_digest(all_items, errors, force=args.force, checked_at=checked_at)
        print(output, end="")
        state["last_reported_signature"] = signature
        state["last_reported_at"] = checked_at.isoformat()
    if not args.dry_run:
        save_state(args.state_file, state)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        raise SystemExit(1)
