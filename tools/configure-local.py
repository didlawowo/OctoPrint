"""Provision the fork while OctoPrint is stopped; never run printer commands."""

import argparse
import copy
import datetime as dt
import ipaddress
import os
import secrets
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ("127.0.0.1/32", "::1/128")
PRIVATE = tuple(
    ipaddress.ip_network(value)
    for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
)


def networks(value):
    """Only localhost and explicitly supplied private subnets may auto-login."""
    result = list(LOCAL)
    for item in value.split(","):
        if not item.strip():
            continue
        network = ipaddress.ip_network(item.strip(), strict=True)
        if str(network) not in LOCAL and not any(
            network.version == parent.version and network.subnet_of(parent)
            for parent in PRIVATE
        ):
            raise ValueError("Auto-login requires localhost or an explicit private subnet")
        if str(network) not in result:
            result.append(str(network))
    return result


def read_mapping(path):
    if path.is_symlink():
        raise ValueError(f"Refusing a symlink: {path}")
    if not path.exists():
        return {}
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"Expected a YAML mapping: {path}")
    return value


def merge_defaults(existing, defaults):
    """Never replace an existing operator setting with a preset default."""
    result = copy.deepcopy(existing)
    for key, value in defaults.items():
        if key not in result or result[key] is None:
            result[key] = copy.deepcopy(value)
        elif isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_defaults(result[key], value)
    return result


def plan(existing, preset, username, allowed_networks):
    result = merge_defaults(existing, preset)
    server = result.setdefault("server", {})
    access = result.setdefault("accessControl", {})
    if not isinstance(server, dict) or not isinstance(access, dict):
        raise ValueError("server and accessControl must be YAML mappings")
    # This explicit task completes the current setup; it does not disable plugins.
    server["firstRun"] = False
    seen = server.setdefault("seenWizards", {})
    if not isinstance(seen, dict):
        raise ValueError("server.seenWizards must be a YAML mapping")
    for key, version in (("corewizard", 4), ("file_check", 1)):
        previous = seen.get(key)
        if previous is None or (isinstance(previous, int) and previous < version):
            seen[key] = version
    access.update(
        autologinLocal=True, autologinAs=username, localNetworks=allowed_networks
    )
    return result


def write_private(path, data):
    """Create a private file without overwriting an existing path or symlink."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(data)


def apply_changes(settings, previous, desired, prefix=()):
    for key, value in desired.items():
        old = previous.get(key)
        path = (*prefix, key)
        if isinstance(value, dict):
            apply_changes(settings, old if isinstance(old, dict) else {}, value, path)
        elif key not in previous or old != value:
            settings.set(list(path), value, force=True)


def provision(basedir, preset_path, username=None, network_list=""):
    # Validate before OctoPrint initializes or migrates any persistent files.
    basedir = basedir.expanduser().resolve()
    allowed = networks(network_list)
    preset = read_mapping(preset_path)
    if not preset:
        raise ValueError("The preset file is missing or empty")
    config = basedir / "config.yaml"
    existing = read_mapping(config)
    access = existing.get("accessControl") or {}
    if not isinstance(access, dict):
        raise ValueError("accessControl must be a YAML mapping")
    for kind in ("user", "group"):
        expected = f"octoprint.access.{kind}s.Filebased{kind.title()}Manager"
        if access.get(f"{kind}Manager", expected) != expected:
            raise ValueError("Custom account managers require manual provisioning")
        if access.get(f"{kind}file"):
            raise ValueError("Custom user/group file paths require manual provisioning")
    for filename in ("users.yaml", "groups.yaml", "atelier-credentials.yaml"):
        path = basedir / filename
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError(f"Refusing a non-regular file: {path}")
    # Validate structures even when a user's account name is not known yet.
    plan(existing, preset, username or "atelier", allowed)
    basedir.mkdir(parents=True, exist_ok=True)
    if config.exists():
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = basedir / f"config.yaml.before-atelier-{stamp}"
        write_private(backup, config.read_text(encoding="utf-8"))
        print(f"Configuration backup: {backup}")

    # Use the same managers and password hashing as `octoprint user`, not a
    # handwritten users.yaml and never an account shared between SD images.
    from octoprint import init_settings
    from octoprint.access import ADMIN_GROUP, USER_GROUP
    from octoprint.access.groups import FilebasedGroupManager
    from octoprint.access.permissions import Permissions
    from octoprint.access.users import FilebasedUserManager

    settings = init_settings(str(basedir), str(config))
    manager = FilebasedUserManager(FilebasedGroupManager(), settings=settings)
    users = manager.get_all_users()
    if users:
        candidates = [
            u for u in users if u.is_active and u.has_permission(Permissions.ADMIN)
        ]
        if username:
            candidates = [u for u in candidates if u.get_id() == username]
        if len(candidates) != 1:
            raise ValueError("Select one existing active administrator with LOCAL_USER=...")
        username = candidates[0].get_id()
    else:
        username = username or "atelier"
        if not username.strip() or username != username.strip():
            raise ValueError("Invalid account name")
        password = secrets.token_urlsafe(32)
        credentials = basedir / "atelier-credentials.yaml"
        write_private(
            credentials,
            yaml.safe_dump({"username": username, "password": password}),
        )
        try:
            manager.add_user(
                username, password, active=True, groups=[USER_GROUP, ADMIN_GROUP]
            )
        except Exception:
            # Keep recovery credentials if account creation partially succeeded.
            raise RuntimeError(
                f"Account creation failed; recovery file: {credentials}"
            ) from None
        print(f"Private recovery credentials (mode 0600): {credentials}")

    desired = plan(existing, preset, username, allowed)
    apply_changes(settings, existing, desired)
    settings.save()
    print(
        f"Atelier configured for account {username!r}; auto-login from {', '.join(allowed)}"
    )
    print("Printer profile, serial port and camera settings were not invented or reset.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--basedir", required=True, type=Path)
    parser.add_argument("--preset", type=Path, default=ROOT / "configs/atelier-local.yaml")
    parser.add_argument("--user", default="")
    parser.add_argument("--networks", default="")
    args = parser.parse_args()
    try:
        provision(args.basedir, args.preset, args.user or None, args.networks)
    except (OSError, ValueError, RuntimeError, yaml.YAMLError) as error:
        parser.exit(1, f"Configuration failed: {error}\n")


if __name__ == "__main__":
    main()
