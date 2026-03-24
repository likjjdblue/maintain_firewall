"""
防火墙管理工具后端服务
基于 firewalld，通过 firewall-cmd 命令行进行规则管理
仅支持规则的新增与删除，不提供防火墙启停操作
"""

import re
import subprocess

from flask import Flask, jsonify, request

app = Flask(__name__)

API_PREFIX = "/api/v1"

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

VALID_PROTOCOLS = {"tcp", "udp", "sctp", "dccp"}
VALID_ACTIONS = {"accept", "reject", "drop"}
VALID_LOG_LEVELS = {"emerg", "alert", "crit", "err", "warning", "notice", "info", "debug"}
VALID_FAMILIES = {"ipv4", "ipv6"}

PORT_PATTERN = re.compile(r"^\d+(-\d+)?$")
CIDR_PATTERN = re.compile(
    r"^(\d{1,3}\.){3}\d{1,3}(/\d{1,2})?$"
    r"|^([0-9a-fA-F:]+)(/\d{1,3})?$"
)


def run_cmd(args: list[str]) -> tuple[bool, str]:
    """执行 firewall-cmd 命令，返回 (成功, 输出内容)"""
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=15,
        )
        output = result.stdout.strip() or result.stderr.strip()
        return result.returncode == 0, output
    except FileNotFoundError:
        return False, "firewall-cmd 未找到，请确认 firewalld 已安装"
    except subprocess.TimeoutExpired:
        return False, "命令执行超时"


def ok(data=None, message="操作成功", http_status=200):
    return jsonify({"success": True, "code": http_status, "message": message, "data": data}), http_status


def err(message, code, http_status=None):
    if http_status is None:
        http_status = code
    return jsonify({"success": False, "code": code, "message": message, "data": None}), http_status


def get_all_zones() -> list[str]:
    ok_, out = run_cmd(["firewall-cmd", "--get-zones"])
    if not ok_:
        return []
    return out.split()


def zone_exists(zone: str) -> bool:
    return zone in get_all_zones()


def parse_persistence_flags(body: dict) -> tuple[bool, bool]:
    """解析 permanent_only / runtime_only，返回 (apply_runtime, apply_permanent)"""
    permanent_only = bool(body.get("permanent_only", False))
    runtime_only = bool(body.get("runtime_only", False))
    if permanent_only:
        return False, True
    if runtime_only:
        return True, False
    return True, True  # 默认两者都应用


def build_rich_rule(
    family: str,
    source_address: str,
    source_invert: bool,
    destination_address: str,
    service: str,
    port: str,
    protocol: str,
    action: str,
    log_prefix: str,
    log_level: str,
    priority: int,
) -> tuple[str | None, str | None]:
    """
    根据结构化参数拼接富规则字符串。
    返回 (rule_string, error_message)，成功时 error_message 为 None。
    """
    if family and family not in VALID_FAMILIES:
        return None, f"family 参数无效，允许值：{', '.join(VALID_FAMILIES)}"
    if action not in VALID_ACTIONS:
        return None, f"action 参数无效，允许值：{', '.join(VALID_ACTIONS)}"
    if not service and not port:
        return None, "service 与 port 必须提供其中一个"
    if service and port:
        return None, "service 与 port 不能同时提供"
    if port and not protocol:
        return None, "指定 port 时必须同时提供 protocol"
    if protocol and protocol not in VALID_PROTOCOLS:
        return None, f"protocol 参数无效，允许值：{', '.join(VALID_PROTOCOLS)}"
    if log_level and log_level not in VALID_LOG_LEVELS:
        return None, f"log_level 参数无效，允许值：{', '.join(VALID_LOG_LEVELS)}"
    if not -32768 <= priority <= 32767:
        return None, "priority 范围为 -32768 到 32767"

    parts = ["rule"]
    if family:
        parts.append(f'family="{family}"')
    if priority != 0:
        parts.append(f'priority="{priority}"')
    if source_address:
        invert_str = ' invert="true"' if source_invert else ""
        parts.append(f'source address="{source_address}"{invert_str}')
    if destination_address:
        parts.append(f'destination address="{destination_address}"')
    if service:
        parts.append(f'service name="{service}"')
    elif port:
        parts.append(f'port port="{port}" protocol="{protocol}"')
    if log_prefix or log_level:
        log_part = "log"
        if log_prefix:
            log_part += f' prefix="{log_prefix}"'
        if log_level:
            log_part += f' level="{log_level}"'
        parts.append(log_part)
    parts.append(action)

    return " ".join(parts), None


def apply_rule_cmd(base_args: list[str], apply_runtime: bool, apply_permanent: bool) -> tuple[bool, str]:
    """
    对 runtime 和/或 permanent 执行同一条规则命令。
    base_args 不含 --permanent，例如：
      ["firewall-cmd", "--zone=public", "--add-port=8080/tcp"]
    """
    if apply_runtime:
        ok_, out = run_cmd(base_args)
        if not ok_:
            return False, out

    if apply_permanent:
        ok_, out = run_cmd(base_args + ["--permanent"])
        if not ok_:
            return False, out

    return True, ""


# ---------------------------------------------------------------------------
# 1. 系统状态
# ---------------------------------------------------------------------------

@app.get(f"{API_PREFIX}/status")
def get_status():
    ok_, state_out = run_cmd(["firewall-cmd", "--state"])
    state = "running" if ok_ else "not running"

    ok_, default_zone = run_cmd(["firewall-cmd", "--get-default-zone"])
    default_zone = default_zone if ok_ else ""

    active_zones: dict = {}
    ok_, az_out = run_cmd(["firewall-cmd", "--get-active-zones"])
    if ok_ and az_out:
        current_zone = None
        for line in az_out.splitlines():
            line = line.strip()
            if not line:
                continue
            if not line.startswith(" ") and ":" not in line:
                current_zone = line
                active_zones[current_zone] = {}
            elif current_zone and line.startswith("interfaces:"):
                active_zones[current_zone]["interfaces"] = line.replace("interfaces:", "").split()
            elif current_zone and line.startswith("sources:"):
                active_zones[current_zone]["sources"] = line.replace("sources:", "").split()

    ok_, version_out = run_cmd(["firewall-cmd", "--version"])
    version = version_out if ok_ else "unknown"

    return ok({
        "state": state,
        "default_zone": default_zone,
        "active_zones": active_zones,
        "firewalld_version": version,
    }, "查询成功")


# ---------------------------------------------------------------------------
# 2. Zone 管理
# ---------------------------------------------------------------------------

@app.get(f"{API_PREFIX}/zones")
def list_zones():
    zones = get_all_zones()
    if not zones:
        return err("获取 Zone 列表失败，请确认 firewalld 服务正在运行", 500)
    return ok({"zones": zones}, "查询成功")


@app.get(f"{API_PREFIX}/zones/<zone_name>")
def get_zone(zone_name: str):
    if not zone_exists(zone_name):
        return err(f"Zone '{zone_name}' 不存在", 404)

    def query(flag):
        success, out = run_cmd(["firewall-cmd", f"--zone={zone_name}", flag])
        return out.split() if success and out else []

    def query_str(flag):
        success, out = run_cmd(["firewall-cmd", f"--zone={zone_name}", flag])
        return out if success else ""

    ok_, target_out = run_cmd(["firewall-cmd", f"--zone={zone_name}", "--get-target"])
    target = target_out if ok_ else "default"

    ok_, rr_out = run_cmd(["firewall-cmd", f"--zone={zone_name}", "--list-rich-rules"])
    rich_rules = [r.strip() for r in rr_out.splitlines() if r.strip()] if ok_ else []

    return ok({
        "zone": zone_name,
        "target": target,
        "interfaces": query("--list-interfaces"),
        "sources": query("--list-sources"),
        "services": query("--list-services"),
        "ports": query("--list-ports"),
        "rich_rules": rich_rules,
    }, "查询成功")


# ---------------------------------------------------------------------------
# 3. 端口规则管理
# ---------------------------------------------------------------------------

@app.get(f"{API_PREFIX}/zones/<zone_name>/ports")
def list_ports(zone_name: str):
    if not zone_exists(zone_name):
        return err(f"Zone '{zone_name}' 不存在", 404)

    ok_, out = run_cmd(["firewall-cmd", f"--zone={zone_name}", "--list-ports"])
    if not ok_:
        return err(f"查询端口规则失败：{out}", 500)
    ports = out.split() if out else []
    return ok({"zone": zone_name, "ports": ports}, "查询成功")


@app.post(f"{API_PREFIX}/zones/<zone_name>/ports")
def add_port(zone_name: str):
    if not zone_exists(zone_name):
        return err(f"Zone '{zone_name}' 不存在", 404)

    body = request.get_json(silent=True) or {}
    port = str(body.get("port", "")).strip()
    protocol = str(body.get("protocol", "")).strip().lower()
    source_ip = str(body.get("source_ip", "")).strip()

    if not port:
        return err("缺少必填参数：port", 400)
    if not PORT_PATTERN.match(port):
        return err("port 格式无效，示例：8080 或 8000-8100", 400)
    if protocol not in VALID_PROTOCOLS:
        return err(f"protocol 参数无效，允许值：{', '.join(VALID_PROTOCOLS)}", 400)
    if source_ip and not CIDR_PATTERN.match(source_ip):
        return err("source_ip 格式无效，示例：192.168.1.0/24 或 10.0.0.1", 400)

    apply_runtime, apply_permanent = parse_persistence_flags(body)
    port_proto = f"{port}/{protocol}"

    if source_ip:
        # 指定源 IP 时使用富规则
        rule = f'rule family="ipv4" source address="{source_ip}" port port="{port}" protocol="{protocol}" accept'
        # 检查富规则是否已存在
        ok_, existing = run_cmd(["firewall-cmd", f"--zone={zone_name}", "--list-rich-rules"])
        if ok_ and rule in existing:
            return err(f"端口规则 {port_proto} (source: {source_ip}) 已存在于 Zone {zone_name} 中", 409)

        base_args = ["firewall-cmd", f"--zone={zone_name}", f"--add-rich-rule={rule}"]
        success, out = apply_rule_cmd(base_args, apply_runtime, apply_permanent)
        if not success:
            return err(f"添加端口规则失败：{out}", 500)
        return ok({
            "zone": zone_name,
            "port": port_proto,
            "source_ip": source_ip,
            "permanent": apply_permanent,
            "runtime": apply_runtime,
        }, "端口规则添加成功")
    else:
        # 无源 IP 限制，使用普通端口开放
        ok_, existing = run_cmd(["firewall-cmd", f"--zone={zone_name}", "--list-ports"])
        if ok_ and port_proto in existing.split():
            return err(f"端口规则 {port_proto} 已存在于 Zone {zone_name} 中", 409)

        base_args = ["firewall-cmd", f"--zone={zone_name}", f"--add-port={port_proto}"]
        success, out = apply_rule_cmd(base_args, apply_runtime, apply_permanent)
        if not success:
            return err(f"添加端口规则失败：{out}", 500)
        return ok({
            "zone": zone_name,
            "port": port_proto,
            "source_ip": None,
            "permanent": apply_permanent,
            "runtime": apply_runtime,
        }, "端口规则添加成功")


@app.delete(f"{API_PREFIX}/zones/<zone_name>/ports")
def delete_port(zone_name: str):
    if not zone_exists(zone_name):
        return err(f"Zone '{zone_name}' 不存在", 404)

    body = request.get_json(silent=True) or {}
    port = str(body.get("port", "")).strip()
    protocol = str(body.get("protocol", "")).strip().lower()
    source_ip = str(body.get("source_ip", "")).strip()

    if not port:
        return err("缺少必填参数：port", 400)
    if not PORT_PATTERN.match(port):
        return err("port 格式无效，示例：8080 或 8000-8100", 400)
    if protocol not in VALID_PROTOCOLS:
        return err(f"protocol 参数无效，允许值：{', '.join(VALID_PROTOCOLS)}", 400)
    if source_ip and not CIDR_PATTERN.match(source_ip):
        return err("source_ip 格式无效，示例：192.168.1.0/24 或 10.0.0.1", 400)

    apply_runtime, apply_permanent = parse_persistence_flags(body)
    port_proto = f"{port}/{protocol}"

    if source_ip:
        rule = f'rule family="ipv4" source address="{source_ip}" port port="{port}" protocol="{protocol}" accept'
        ok_, existing = run_cmd(["firewall-cmd", f"--zone={zone_name}", "--list-rich-rules"])
        if ok_ and rule not in existing:
            return err(f"端口规则 {port_proto} (source: {source_ip}) 在 Zone {zone_name} 中不存在", 404)

        base_args = ["firewall-cmd", f"--zone={zone_name}", f"--remove-rich-rule={rule}"]
        success, out = apply_rule_cmd(base_args, apply_runtime, apply_permanent)
        if not success:
            return err(f"删除端口规则失败：{out}", 500)
        return ok({
            "zone": zone_name,
            "port": port_proto,
            "source_ip": source_ip,
            "permanent": apply_permanent,
            "runtime": apply_runtime,
        }, "端口规则删除成功")
    else:
        ok_, existing = run_cmd(["firewall-cmd", f"--zone={zone_name}", "--list-ports"])
        if ok_ and port_proto not in existing.split():
            return err(f"端口规则 {port_proto} 在 Zone {zone_name} 中不存在", 404)

        base_args = ["firewall-cmd", f"--zone={zone_name}", f"--remove-port={port_proto}"]
        success, out = apply_rule_cmd(base_args, apply_runtime, apply_permanent)
        if not success:
            return err(f"删除端口规则失败：{out}", 500)
        return ok({
            "zone": zone_name,
            "port": port_proto,
            "source_ip": None,
            "permanent": apply_permanent,
            "runtime": apply_runtime,
        }, "端口规则删除成功")


# ---------------------------------------------------------------------------
# 4. 服务规则管理
# ---------------------------------------------------------------------------

@app.get(f"{API_PREFIX}/services")
def list_all_services():
    ok_, out = run_cmd(["firewall-cmd", "--get-services"])
    if not ok_:
        return err(f"获取服务列表失败：{out}", 500)
    services = sorted(out.split())
    return ok({"services": services}, "查询成功")


@app.get(f"{API_PREFIX}/zones/<zone_name>/services")
def list_zone_services(zone_name: str):
    if not zone_exists(zone_name):
        return err(f"Zone '{zone_name}' 不存在", 404)

    ok_, out = run_cmd(["firewall-cmd", f"--zone={zone_name}", "--list-services"])
    if not ok_:
        return err(f"查询服务规则失败：{out}", 500)
    services = out.split() if out else []
    return ok({"zone": zone_name, "services": services}, "查询成功")


@app.post(f"{API_PREFIX}/zones/<zone_name>/services")
def add_service(zone_name: str):
    if not zone_exists(zone_name):
        return err(f"Zone '{zone_name}' 不存在", 404)

    body = request.get_json(silent=True) or {}
    service = str(body.get("service", "")).strip()
    if not service:
        return err("缺少必填参数：service", 400)

    # 校验服务是否是已知服务
    ok_, all_svc = run_cmd(["firewall-cmd", "--get-services"])
    if ok_ and service not in all_svc.split():
        return err(f"服务 '{service}' 不是有效的 firewalld 服务名", 400)

    # 检查是否已存在
    ok_, existing = run_cmd(["firewall-cmd", f"--zone={zone_name}", "--list-services"])
    if ok_ and service in existing.split():
        return err(f"服务规则 '{service}' 已存在于 Zone {zone_name} 中", 409)

    apply_runtime, apply_permanent = parse_persistence_flags(body)
    base_args = ["firewall-cmd", f"--zone={zone_name}", f"--add-service={service}"]
    success, out = apply_rule_cmd(base_args, apply_runtime, apply_permanent)
    if not success:
        return err(f"添加服务规则失败：{out}", 500)
    return ok({
        "zone": zone_name,
        "service": service,
        "permanent": apply_permanent,
        "runtime": apply_runtime,
    }, "服务规则添加成功")


@app.delete(f"{API_PREFIX}/zones/<zone_name>/services")
def delete_service(zone_name: str):
    if not zone_exists(zone_name):
        return err(f"Zone '{zone_name}' 不存在", 404)

    body = request.get_json(silent=True) or {}
    service = str(body.get("service", "")).strip()
    if not service:
        return err("缺少必填参数：service", 400)

    ok_, existing = run_cmd(["firewall-cmd", f"--zone={zone_name}", "--list-services"])
    if ok_ and service not in existing.split():
        return err(f"服务规则 '{service}' 在 Zone {zone_name} 中不存在", 404)

    apply_runtime, apply_permanent = parse_persistence_flags(body)
    base_args = ["firewall-cmd", f"--zone={zone_name}", f"--remove-service={service}"]
    success, out = apply_rule_cmd(base_args, apply_runtime, apply_permanent)
    if not success:
        return err(f"删除服务规则失败：{out}", 500)
    return ok({
        "zone": zone_name,
        "service": service,
        "permanent": apply_permanent,
        "runtime": apply_runtime,
    }, "服务规则删除成功")


# ---------------------------------------------------------------------------
# 5. 富规则管理（Rich Rule）
# ---------------------------------------------------------------------------

@app.get(f"{API_PREFIX}/zones/<zone_name>/rich-rules")
def list_rich_rules(zone_name: str):
    if not zone_exists(zone_name):
        return err(f"Zone '{zone_name}' 不存在", 404)

    ok_, out = run_cmd(["firewall-cmd", f"--zone={zone_name}", "--list-rich-rules"])
    if not ok_:
        return err(f"查询富规则失败：{out}", 500)
    rules = [r.strip() for r in out.splitlines() if r.strip()]
    return ok({"zone": zone_name, "rich_rules": rules}, "查询成功")


@app.post(f"{API_PREFIX}/zones/<zone_name>/rich-rules")
def add_rich_rule(zone_name: str):
    if not zone_exists(zone_name):
        return err(f"Zone '{zone_name}' 不存在", 404)

    body = request.get_json(silent=True) or {}
    apply_runtime, apply_permanent = parse_persistence_flags(body)

    if body.get("structured"):
        # 结构化参数模式
        rule, build_err = build_rich_rule(
            family=str(body.get("family", "ipv4")).strip(),
            source_address=str(body.get("source_address", "")).strip(),
            source_invert=bool(body.get("source_invert", False)),
            destination_address=str(body.get("destination_address", "")).strip(),
            service=str(body.get("service", "")).strip(),
            port=str(body.get("port", "")).strip(),
            protocol=str(body.get("protocol", "")).strip().lower(),
            action=str(body.get("action", "")).strip().lower(),
            log_prefix=str(body.get("log_prefix", "")).strip(),
            log_level=str(body.get("log_level", "")).strip().lower(),
            priority=int(body.get("priority", 0)),
        )
        if build_err:
            return err(f"富规则参数错误：{build_err}", 400)
    else:
        # 原始字符串模式
        rule = str(body.get("rule", "")).strip()
        if not rule:
            return err("缺少必填参数：rule（或使用 structured=true 模式）", 400)

    # 检查是否已存在
    ok_, existing = run_cmd(["firewall-cmd", f"--zone={zone_name}", "--list-rich-rules"])
    if ok_ and rule in existing:
        return err(f"富规则已存在于 Zone {zone_name} 中", 409)

    base_args = ["firewall-cmd", f"--zone={zone_name}", f"--add-rich-rule={rule}"]
    success, out = apply_rule_cmd(base_args, apply_runtime, apply_permanent)
    if not success:
        return err(f"添加富规则失败：{out}", 500)
    return ok({
        "zone": zone_name,
        "rule": rule,
        "permanent": apply_permanent,
        "runtime": apply_runtime,
    }, "富规则添加成功")


@app.delete(f"{API_PREFIX}/zones/<zone_name>/rich-rules")
def delete_rich_rule(zone_name: str):
    if not zone_exists(zone_name):
        return err(f"Zone '{zone_name}' 不存在", 404)

    body = request.get_json(silent=True) or {}
    rule = str(body.get("rule", "")).strip()
    if not rule:
        return err("缺少必填参数：rule", 400)

    ok_, existing = run_cmd(["firewall-cmd", f"--zone={zone_name}", "--list-rich-rules"])
    if ok_ and rule not in existing:
        return err(f"富规则在 Zone {zone_name} 中不存在", 404)

    apply_runtime, apply_permanent = parse_persistence_flags(body)
    base_args = ["firewall-cmd", f"--zone={zone_name}", f"--remove-rich-rule={rule}"]
    success, out = apply_rule_cmd(base_args, apply_runtime, apply_permanent)
    if not success:
        return err(f"删除富规则失败：{out}", 500)
    return ok({
        "zone": zone_name,
        "rule": rule,
        "permanent": apply_permanent,
        "runtime": apply_runtime,
    }, "富规则删除成功")


# ---------------------------------------------------------------------------
# 6. 来源地址管理（Source）
# ---------------------------------------------------------------------------

@app.get(f"{API_PREFIX}/zones/<zone_name>/sources")
def list_sources(zone_name: str):
    if not zone_exists(zone_name):
        return err(f"Zone '{zone_name}' 不存在", 404)

    ok_, out = run_cmd(["firewall-cmd", f"--zone={zone_name}", "--list-sources"])
    if not ok_:
        return err(f"查询来源地址失败：{out}", 500)
    sources = out.split() if out else []
    return ok({"zone": zone_name, "sources": sources}, "查询成功")


@app.post(f"{API_PREFIX}/zones/<zone_name>/sources")
def add_source(zone_name: str):
    if not zone_exists(zone_name):
        return err(f"Zone '{zone_name}' 不存在", 404)

    body = request.get_json(silent=True) or {}
    source = str(body.get("source", "")).strip()
    if not source:
        return err("缺少必填参数：source", 400)
    if not CIDR_PATTERN.match(source):
        return err("source 格式无效，示例：192.168.1.0/24 或 10.0.0.1", 400)

    ok_, existing = run_cmd(["firewall-cmd", f"--zone={zone_name}", "--list-sources"])
    if ok_ and source in existing.split():
        return err(f"来源地址 '{source}' 已存在于 Zone {zone_name} 中", 409)

    apply_runtime, apply_permanent = parse_persistence_flags(body)
    base_args = ["firewall-cmd", f"--zone={zone_name}", f"--add-source={source}"]
    success, out = apply_rule_cmd(base_args, apply_runtime, apply_permanent)
    if not success:
        return err(f"添加来源地址失败：{out}", 500)
    return ok({
        "zone": zone_name,
        "source": source,
        "permanent": apply_permanent,
        "runtime": apply_runtime,
    }, "来源地址添加成功")


@app.delete(f"{API_PREFIX}/zones/<zone_name>/sources")
def delete_source(zone_name: str):
    if not zone_exists(zone_name):
        return err(f"Zone '{zone_name}' 不存在", 404)

    body = request.get_json(silent=True) or {}
    source = str(body.get("source", "")).strip()
    if not source:
        return err("缺少必填参数：source", 400)

    ok_, existing = run_cmd(["firewall-cmd", f"--zone={zone_name}", "--list-sources"])
    if ok_ and source not in existing.split():
        return err(f"来源地址 '{source}' 在 Zone {zone_name} 中不存在", 404)

    apply_runtime, apply_permanent = parse_persistence_flags(body)
    base_args = ["firewall-cmd", f"--zone={zone_name}", f"--remove-source={source}"]
    success, out = apply_rule_cmd(base_args, apply_runtime, apply_permanent)
    if not success:
        return err(f"删除来源地址失败：{out}", 500)
    return ok({
        "zone": zone_name,
        "source": source,
        "permanent": apply_permanent,
        "runtime": apply_runtime,
    }, "来源地址删除成功")


# ---------------------------------------------------------------------------
# 全局错误处理
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(e):
    return err("接口路径不存在", 404)


@app.errorhandler(405)
def method_not_allowed(e):
    return err("HTTP 方法不被允许", 405)


@app.errorhandler(400)
def bad_request(e):
    return err("请求格式错误，请确认 Content-Type 为 application/json", 400)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
