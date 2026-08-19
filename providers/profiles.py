# Dev Triangle MCP source maintenance contract
# 上下游: 上游是 server.py 的 mcp_health_check、agy 模型解析與後續 W05/W06 的 adapter、W13 的設定工具；讀 config/providers.<name>.json；只回傳解析結果，不發出任何網路請求、不寫設定檔（寫檔是 W13 的事）
# 檔案路徑: dev-triangle-mcp/providers/profiles.py
# 產生時間: 2026-08-19 11:45 +08:00
# 版本: v1.0
# 功能說明: 讀使用者自己寫的 profile 設定檔，回答「這個角色現在綁到哪個模型、哪個端點、金鑰放在哪個環境變數」。使用者沒填就明確報錯並講清楚要去填哪一行，絕不自己挑一個模型頂上
# 模組定位: A4 三層分離的載體。它「是」設定的讀取與驗證層；它「不是」HTTP 傳輸層（那是 providers/http.py）、「不是」設定的寫入層（那是 W13 的 tool_profile_set_role）、也「不是」預設值的來源
# 主要責任:
#   1. list_profiles() / profile_path() —— 掃 config/providers.*.json，profile 名稱由使用者自取
#   2. load_profile(name) —— 找不到即 raise ProfileNotFound 並列出可用清單；七個 slot key 缺一即 raise
#   3. resolve_role(profile, slot, overrides) —— A4.5 的覆寫順序，鏈的末端是 raise 不是 fallback
#   4. describe_profile(profile) —— 給 mcp_health_check 與 tool_profile_describe 用的摘要，含「哪些角色綁到同一個模型」
#   5. active_profile_name() —— 由 DEV_TRIANGLE_PROFILE 環境變數指定，沒指定就是沒有
# 維護提醒:
#   - 不得在本檔任何地方出現 or "某個內建值" 形式的 fallback。S4.9 silent_default_count 門檻是 0，而這裡是它唯一會發生的地方（INV-12）
#   - 不得在本檔或 config/providers.example.json 填入任何真實模型名。S4.8 的掃描會命中，而且那等於本專案替使用者決定（C10）
#   - 不得驗證 displayName。它是使用者的自由區，可中文、可空白、可 emoji、可重複；程式碼一旦 key 在它上面，使用者改個名字就會靜默失效
#   - slot key 是本專案固定的契約。要新增角色必須同時改 SLOT_KEYS 與所有 adapter，不得從設定檔或 NL 通道生出新 slot（INV-11、F10）
#   - kind == "cli" 的 model 留空與 kind == "api" 的 model 留空處置完全不同，見 docs/NOTES.md NOTE-004。統一兩者就會弄壞其中一個
# 驗證方式:
#   - python -m pytest -q tests\test_provider_profile.py
#   - python -c "from providers.profiles import list_profiles, load_profile; print(list_profiles()); print(load_profile('example').describe())"
# ------------------------------------------------------------

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from providers.redaction import looks_like_secret_value


# The slot keys are this project's contract. Users rename displayName, not these.
SLOT_KEYS: tuple[str, ...] = (
    "orchestrator",
    "contextBroker",
    "architect",
    "cloudWorker",
    "verifier",
    "diagnostician",
    "reporter",
)

KINDS = frozenset({"api", "jules", "local-suite", "cli", "mcp", "mcp-client"})
DIALECTS = frozenset({"openai", "anthropic", "gemini", "ollama"})

ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
PROFILE_NAME_RE = re.compile(r"^[a-z0-9-]+$")
PROFILE_FILE_PREFIX = "providers."
PROFILE_FILE_SUFFIX = ".json"

# Keys a user may add for their own documentation. The loader ignores them.
COMMENT_KEY_PREFIX = "_"


class ProfileError(Exception):
    """Configuration is present but wrong."""


class ProfileNotFound(ProfileError):
    """No profile file with that name."""


class RoleNotConfigured(ProfileError):
    """The slot exists but the user has not bound a model to it yet."""


class RoleDisabled(ProfileError):
    """The slot is deliberately turned off."""


@dataclass(frozen=True)
class RoleBinding:
    slot: str
    kind: str
    display_name: str = ""
    provider: str = ""
    dialect: str = ""
    model: str = ""
    base_url: str = ""
    api_key_env: str = ""
    max_input_tokens: int | None = None
    enabled: bool = False
    verified: bool = False
    command: str = ""
    # Passed to the CLI verbatim, before the prompt. This is where a model flag
    # goes if that CLI wants one; this project does not know which flag that is.
    args: tuple[str, ...] = field(default_factory=tuple)
    prompt_arg: str = ""
    # How the prompt reaches the CLI. stdin by default - see NOTE-013.
    prompt_via: str = "stdin"
    server: str = ""
    note: str = ""
    overrides_applied: tuple[str, ...] = field(default_factory=tuple)

    @property
    def configured(self) -> bool:
        if self.kind == "api":
            return bool(self.model) and bool(self.api_key_env)
        if self.kind == "cli":
            # A cli role needs a command. It does not need a model - see
            # docs/NOTES.md NOTE-004.
            return bool(self.command)
        return True

    @property
    def label(self) -> str:
        # Never key on this. Display only.
        return self.display_name or self.slot

    def to_dict(self) -> dict[str, Any]:
        # camelCase on the way out: this lands in jobs.json (INV-09).
        return {
            "slot": self.slot,
            "displayName": self.display_name,
            "kind": self.kind,
            "provider": self.provider,
            "dialect": self.dialect,
            "model": self.model,
            "baseUrl": self.base_url,
            "apiKeyEnv": self.api_key_env,
            "maxInputTokens": self.max_input_tokens,
            "enabled": self.enabled,
            "verified": self.verified,
            "configured": self.configured,
            "command": self.command,
            "args": list(self.args),
            "promptArg": self.prompt_arg,
            "promptVia": self.prompt_via,
            "overridesApplied": list(self.overrides_applied),
        }


@dataclass(frozen=True)
class Profile:
    name: str
    display_name: str
    path: Path
    roles: dict[str, RoleBinding]
    raw: dict[str, Any]

    @property
    def label(self) -> str:
        return self.display_name or self.name

    def describe(self) -> dict[str, Any]:
        return describe_profile(self)


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------


def config_dir() -> Path:
    override = os.environ.get("DEV_TRIANGLE_CONFIG_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parent.parent / "config"


def profile_path(name: str) -> Path:
    return config_dir() / f"{PROFILE_FILE_PREFIX}{name}{PROFILE_FILE_SUFFIX}"


def list_profiles() -> list[str]:
    directory = config_dir()
    if not directory.exists():
        return []
    names: list[str] = []
    for path in sorted(directory.glob(f"{PROFILE_FILE_PREFIX}*{PROFILE_FILE_SUFFIX}")):
        name = path.name[len(PROFILE_FILE_PREFIX) : -len(PROFILE_FILE_SUFFIX)]
        if name:
            names.append(name)
    return names


def active_profile_name() -> str:
    """Which profile the current process should use, or "" for none.

    There is deliberately no default profile name. "No profile selected" is a
    legitimate state that must behave like "not configured", not like "use the
    first one you find" (INV-12).
    """
    return os.environ.get("DEV_TRIANGLE_PROFILE", "").strip()


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def validate_api_key_env(value: str, where: str) -> str:
    """Accept an environment variable NAME. Reject a pasted credential."""
    candidate = (value or "").strip()
    if not candidate:
        return ""
    rule = looks_like_secret_value(candidate)
    if rule is not None:
        raise ProfileError(
            f"{where}: apiKeyEnv looks like an actual credential (matched {rule}). "
            "Do not put secrets in configuration or in chat. Set the value in an "
            "environment variable of your choosing and give me that variable's NAME instead."
        )
    if not ENV_NAME_RE.match(candidate):
        raise ProfileError(
            f"{where}: apiKeyEnv must be an environment variable name matching "
            f"{ENV_NAME_RE.pattern} (got {candidate!r}). It is a name, not a key."
        )
    return candidate


def _as_str(role: dict[str, Any], key: str, where: str) -> str:
    value = role.get(key, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ProfileError(f"{where}: {key} must be a string, got {type(value).__name__}.")
    return value.strip() if key != "displayName" else value


def _as_bool(role: dict[str, Any], key: str, where: str, default: bool) -> bool:
    value = role.get(key, default)
    if not isinstance(value, bool):
        raise ProfileError(f"{where}: {key} must be true or false.")
    return value


def _as_str_tuple(role: dict[str, Any], key: str, where: str) -> tuple[str, ...]:
    value = role.get(key)
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ProfileError(f"{where}: {key} must be a list of strings.")
    return tuple(value)


PROMPT_VIA_VALUES = ("stdin", "arg")


def _as_prompt_via(role: dict[str, Any], where: str) -> str:
    value = role.get("promptVia", "stdin")
    if not isinstance(value, str) or value not in PROMPT_VIA_VALUES:
        raise ProfileError(f"{where}: promptVia must be one of {list(PROMPT_VIA_VALUES)}.")
    return value


def _as_optional_int(role: dict[str, Any], key: str, where: str) -> int | None:
    value = role.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProfileError(f"{where}: {key} must be an integer or null.")
    if value <= 0:
        raise ProfileError(f"{where}: {key} must be positive when set.")
    return value


def parse_role(slot: str, role: dict[str, Any], where: str) -> RoleBinding:
    if not isinstance(role, dict):
        raise ProfileError(f"{where}: role must be an object.")

    kind = _as_str(role, "kind", where)
    if kind not in KINDS:
        raise ProfileError(
            f"{where}: kind must be one of {sorted(KINDS)} (got {kind!r}). "
            "kind selects which adapter runs; an invented value points at code that does not exist."
        )

    dialect = _as_str(role, "dialect", where)
    if dialect and dialect not in DIALECTS:
        raise ProfileError(
            f"{where}: dialect must be one of {sorted(DIALECTS)} (got {dialect!r}), or left empty."
        )

    return RoleBinding(
        slot=slot,
        kind=kind,
        # displayName is deliberately unvalidated: it is the user's free area.
        display_name=_as_str(role, "displayName", where),
        provider=_as_str(role, "provider", where),
        dialect=dialect,
        model=_as_str(role, "model", where),
        base_url=_as_str(role, "baseUrl", where),
        api_key_env=validate_api_key_env(_as_str(role, "apiKeyEnv", where), where),
        max_input_tokens=_as_optional_int(role, "maxInputTokens", where),
        enabled=_as_bool(role, "enabled", where, False),
        # Missing means unverified. Conservative side, per SAI A8.
        verified=_as_bool(role, "verified", where, False),
        command=_as_str(role, "command", where),
        args=_as_str_tuple(role, "args", where),
        prompt_arg=_as_str(role, "promptArg", where),
        prompt_via=_as_prompt_via(role, where),
        server=_as_str(role, "server", where),
        note=_as_str(role, "note", where),
    )


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_profile(name: str) -> Profile:
    """Load a profile by name.

    Raises ProfileNotFound when it does not exist. It never falls back to a
    default profile: "the name you gave me does not exist" and "here is some
    other profile" are very different answers, and only one of them is true.
    """
    requested = (name or "").strip()
    available = list_profiles()
    if not requested:
        raise ProfileNotFound(
            "No profile name given. Available profiles: "
            f"{available or 'none'}. Set DEV_TRIANGLE_PROFILE or pass profile explicitly."
        )
    if not PROFILE_NAME_RE.match(requested):
        raise ProfileError(
            f"Profile name {requested!r} must match {PROFILE_NAME_RE.pattern}. "
            f"Available profiles: {available or 'none'}."
        )

    path = profile_path(requested)
    if not path.exists():
        raise ProfileNotFound(
            f"Profile {requested!r} not found at {path}. Available profiles: {available or 'none'}."
        )

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProfileError(f"Profile {requested!r} at {path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ProfileError(f"Profile {requested!r} at {path} must be a JSON object.")

    roles_raw = raw.get("roles")
    if not isinstance(roles_raw, dict):
        raise ProfileError(f"Profile {requested!r} at {path} must have a roles object.")

    declared = {key for key in roles_raw if not key.startswith(COMMENT_KEY_PREFIX)}
    missing = [slot for slot in SLOT_KEYS if slot not in declared]
    unknown = sorted(declared - set(SLOT_KEYS))
    if missing or unknown:
        detail = []
        if missing:
            detail.append(f"missing slot keys: {missing}")
        if unknown:
            detail.append(f"unknown slot keys: {unknown}")
        hint = ""
        if missing and unknown:
            # The usual cause: someone renamed a slot key instead of setting
            # displayName. Renamed slots fail silently at runtime (F10), so this
            # has to stop the load rather than warn.
            hint = (
                " It looks like a slot key was renamed. Slot keys are fixed by this project and "
                "cannot be renamed; put your own naming in displayName instead."
            )
        raise ProfileError(f"Profile {requested!r} at {path}: " + "; ".join(detail) + "." + hint)

    roles: dict[str, RoleBinding] = {}
    for slot in SLOT_KEYS:
        roles[slot] = parse_role(slot, roles_raw[slot], f"Profile {requested!r} role {slot!r}")

    display_name = raw.get("displayName", "")
    if not isinstance(display_name, str):
        raise ProfileError(f"Profile {requested!r} at {path}: displayName must be a string.")

    return Profile(name=requested, display_name=display_name, path=path, roles=roles, raw=raw)


def load_active_profile() -> Profile | None:
    """Load whatever DEV_TRIANGLE_PROFILE points at, or None if unset.

    Returns None only for "no profile selected". A selected-but-broken profile
    still raises: silently ignoring it is exactly the failure INV-11 forbids.
    """
    name = active_profile_name()
    if not name:
        return None
    return load_profile(name)


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

OVERRIDABLE_FIELDS = ("displayName", "provider", "dialect", "model", "baseUrl", "apiKeyEnv")


def resolve_role(
    profile: Profile,
    slot: str,
    overrides: dict[str, Any] | None = None,
) -> RoleBinding:
    """Resolve one slot: per-call overrides > profile file > raise.

    The end of the chain is an error, not a default value. That is the whole
    point of A4.5 and the difference between C9 (do not hardcode) and C10
    (the user decides).
    """
    if slot not in SLOT_KEYS:
        raise ProfileError(
            f"Unknown role slot {slot!r}. This project has exactly these seven: {list(SLOT_KEYS)}. "
            "New slots cannot be created from configuration or from conversation."
        )

    binding = profile.roles[slot]
    applied: list[str] = []

    for key, value in (overrides or {}).items():
        if key not in OVERRIDABLE_FIELDS:
            raise ProfileError(f"Override {key!r} is not one of {list(OVERRIDABLE_FIELDS)}.")
        if value is None:
            continue
        if not isinstance(value, str):
            raise ProfileError(f"Override {key!r} must be a string.")
        where = f"Override for role {slot!r}"
        if key == "apiKeyEnv":
            binding = _replace(binding, api_key_env=validate_api_key_env(value, where))
        elif key == "dialect":
            if value and value not in DIALECTS:
                raise ProfileError(f"{where}: dialect must be one of {sorted(DIALECTS)}.")
            binding = _replace(binding, dialect=value)
        elif key == "displayName":
            binding = _replace(binding, display_name=value)
        elif key == "baseUrl":
            binding = _replace(binding, base_url=value.strip())
        elif key == "model":
            # An overridden model has not been checked against a model list.
            binding = _replace(binding, model=value.strip(), verified=False)
        else:
            binding = _replace(binding, provider=value.strip())
        applied.append(key)

    binding = _replace(binding, overrides_applied=tuple(applied))

    if not binding.enabled:
        raise RoleDisabled(
            f"ROLE_DISABLED: role {slot!r} ({binding.label}) is disabled in profile {profile.name!r}. "
            f"Set roles.{slot}.enabled to true in {profile.path} when you are ready to use it."
        )

    if binding.kind == "api":
        # NOTE(NOTE-004): api roles must fail here. cli roles must not.
        if not binding.model:
            raise RoleNotConfigured(
                f"ROLE_NOT_CONFIGURED: role {slot!r} ({binding.label}) has no model. "
                f"Fill roles.{slot}.model in {profile.path}. "
                "This project never picks a model for you."
            )
        if not binding.api_key_env:
            raise RoleNotConfigured(
                f"ROLE_NOT_CONFIGURED: role {slot!r} ({binding.label}) has no apiKeyEnv. "
                f"Fill roles.{slot}.apiKeyEnv in {profile.path} with the NAME of the environment "
                "variable that holds your key."
            )
        if not os.environ.get(binding.api_key_env, "").strip():
            raise RoleNotConfigured(
                f"ROLE_NOT_CONFIGURED: environment variable {binding.api_key_env} is empty, so role "
                f"{slot!r} ({binding.label}) has no credential. Set it in your shell; this project "
                "never stores key values."
            )

    if binding.kind == "cli" and not binding.command:
        # A cli role with no command has nothing to hand work to. Note this is
        # the command that is required, not the model - NOTE-004.
        raise RoleNotConfigured(
            f"ROLE_NOT_CONFIGURED: role {slot!r} ({binding.label}) is a cli role with no command. "
            f"Fill roles.{slot}.command in {profile.path} with the executable that should do the work."
        )

    return binding


def _replace(binding: RoleBinding, **changes: Any) -> RoleBinding:
    data = {
        "slot": binding.slot,
        "kind": binding.kind,
        "display_name": binding.display_name,
        "provider": binding.provider,
        "dialect": binding.dialect,
        "model": binding.model,
        "base_url": binding.base_url,
        "api_key_env": binding.api_key_env,
        "max_input_tokens": binding.max_input_tokens,
        "enabled": binding.enabled,
        "verified": binding.verified,
        "command": binding.command,
        "args": binding.args,
        "prompt_arg": binding.prompt_arg,
        "prompt_via": binding.prompt_via,
        "server": binding.server,
        "note": binding.note,
        "overrides_applied": binding.overrides_applied,
    }
    data.update(changes)
    return RoleBinding(**data)


# ---------------------------------------------------------------------------
# Description
# ---------------------------------------------------------------------------


WRITABLE_ROLE_FIELDS = ("displayName", "provider", "dialect", "model", "baseUrl", "apiKeyEnv", "verified")


def read_role_raw(profile_name: str, slot: str) -> dict[str, Any]:
    """Return the on-disk role object, so a change can record what it replaced."""
    path = profile_path(profile_name)
    raw = json.loads(path.read_text(encoding="utf-8"))
    role = raw.get("roles", {}).get(slot)
    if not isinstance(role, dict):
        raise ProfileError(f"Profile {profile_name!r} has no role {slot!r}.")
    return {key: value for key, value in role.items() if key in WRITABLE_ROLE_FIELDS}


def update_role_in_file(profile_name: str, slot: str, changes: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Write one slot's binding back to its profile file.

    Returns (before, after) so the caller can report and, later, reverse it.
    Only the fields in WRITABLE_ROLE_FIELDS are touched: kind, command, server
    and note describe the adapter, not the user's choice, and changing them from
    a conversation would point the slot at code that does not exist.
    """
    if slot not in SLOT_KEYS:
        raise ProfileError(
            f"Unknown role slot {slot!r}. This project has exactly these seven: {list(SLOT_KEYS)}."
        )
    unsupported = sorted(set(changes) - set(WRITABLE_ROLE_FIELDS))
    if unsupported:
        raise ProfileError(f"Fields {unsupported} cannot be set this way; writable fields are {list(WRITABLE_ROLE_FIELDS)}.")

    path = profile_path(profile_name)
    if not path.exists():
        raise ProfileNotFound(
            f"Profile {profile_name!r} not found at {path}. Available profiles: {list_profiles() or 'none'}."
        )
    raw = json.loads(path.read_text(encoding="utf-8"))
    roles = raw.get("roles")
    if not isinstance(roles, dict) or slot not in roles:
        raise ProfileError(f"Profile {profile_name!r} has no role {slot!r}.")

    role = roles[slot]
    before = {key: role.get(key) for key in changes}
    role.update(changes)

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)

    after = {key: role.get(key) for key in changes}
    return before, after


def describe_profile(profile: Profile) -> dict[str, Any]:
    roles = [binding.to_dict() for binding in profile.roles.values()]

    # A4.4 rule 2: sharing one model across two slots is legal and sometimes
    # deliberate, but it silently destroys the S7.2 shadow comparison, so it has
    # to be visible rather than merely allowed.
    by_target: dict[tuple[str, str], list[str]] = {}
    for binding in profile.roles.values():
        if binding.kind != "api" or not binding.model:
            continue
        by_target.setdefault((binding.base_url, binding.model), []).append(binding.slot)
    shared = [
        {"baseUrl": base_url, "model": model, "slots": slots}
        for (base_url, model), slots in by_target.items()
        if len(slots) > 1
    ]

    unconfigured = [
        binding.slot
        for binding in profile.roles.values()
        if binding.kind == "api" and not binding.configured
    ]
    unverified = [
        binding.slot
        for binding in profile.roles.values()
        if binding.kind == "api" and binding.model and not binding.verified
    ]

    return {
        "name": profile.name,
        "displayName": profile.label,
        "path": str(profile.path),
        "roles": roles,
        "unresolvedRoles": unconfigured,
        "unresolvedRoleCount": len(unconfigured),
        "unverifiedModelSlots": unverified,
        "sharedModelSlots": shared,
        "availableProfiles": list_profiles(),
    }
