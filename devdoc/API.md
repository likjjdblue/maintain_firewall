# 防火墙管理工具 API 文档

> 基于 firewalld 防火墙管理系统，提供规则的新增与删除能力。
> 后端：Python Flask | 防火墙：firewalld (Linux)

---

## 目录

- [基础说明](#基础说明)
- [核心概念](#核心概念)
- [通用响应格式](#通用响应格式)
- [错误码说明](#错误码说明)
- [1. 系统状态](#1-系统状态)
- [2. Zone（安全区域）管理](#2-zone安全区域管理)
- [3. 端口规则管理](#3-端口规则管理)
- [4. 服务规则管理](#4-服务规则管理)
- [5. 富规则管理（Rich Rule）](#5-富规则管理rich-rule)
- [6. 来源地址管理（Source）](#6-来源地址管理source)
- [附录：预定义 Zone 说明](#附录预定义-zone-说明)
- [附录：常见服务名称](#附录常见服务名称)

---

## 基础说明

### Base URL

```
http://<server-ip>:<port>/api/v1
```

### 请求规范

- 请求体格式：`Content-Type: application/json`
- 字符编码：UTF-8
- HTTP 方法：`GET` / `POST` / `DELETE`

### 运行时规则 vs 永久规则

firewalld 的规则分两类：

| 类型 | 说明 | 生效时机 | 重启后 |
|------|------|----------|--------|
| **runtime**（运行时） | 立即生效，不写入磁盘 | 即时 | 丢失 |
| **permanent**（永久） | 写入配置文件，需 reload 后生效 | reload 后 | 保留 |

> 本工具所有写操作默认同时操作 runtime 和 permanent，确保规则即时生效且重启后不丢失。
> 可通过请求参数 `permanent_only` 或 `runtime_only` 控制行为。

---

## 核心概念

### Zone（安全区域）

Zone 是 firewalld 的核心概念，代表网络连接的信任级别。每条规则都属于某个 Zone。
常用默认 Zone：`public`（公网）、`internal`（内网）、`trusted`（完全信任）。

### 规则类型

| 规则类型 | 说明 | 示例 |
|----------|------|------|
| **Port（端口）** | 开放/关闭指定端口 | `8080/tcp` |
| **Service（服务）** | 开放/关闭预定义服务 | `http`、`ssh` |
| **Rich Rule（富规则）** | 基于源 IP、目标、协议等的复合规则 | 允许特定 IP 访问特定端口 |
| **Source（来源地址）** | 将 IP/CIDR 绑定到 Zone | `192.168.1.0/24` → internal |

---

## 通用响应格式

所有接口统一返回如下 JSON 结构：

```json
{
  "success": true,
  "code": 200,
  "message": "操作成功",
  "data": {}
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `success` | boolean | 请求是否成功 |
| `code` | integer | 业务状态码 |
| `message` | string | 描述信息 |
| `data` | object / array / null | 返回数据 |

---

## 错误码说明

| code | HTTP 状态码 | 说明 |
|------|-------------|------|
| 200 | 200 | 成功 |
| 400 | 400 | 请求参数错误 |
| 404 | 404 | 资源不存在（如 Zone 不存在） |
| 409 | 409 | 规则已存在（重复添加） |
| 500 | 500 | 服务器内部错误（防火墙命令执行失败） |
| 403 | 403 | 禁止操作（如尝试启动/停止防火墙） |

---

## 1. 系统状态

### 1.1 获取防火墙状态

> 仅查询防火墙运行状态，**不提供启动/停止操作**。

**GET** `/status`

**响应示例：**

```json
{
  "success": true,
  "code": 200,
  "message": "查询成功",
  "data": {
    "state": "running",
    "default_zone": "public",
    "active_zones": {
      "public": {
        "interfaces": ["eth0"]
      },
      "internal": {
        "sources": ["192.168.1.0/24"]
      }
    },
    "firewalld_version": "1.3.4"
  }
}
```

| 字段 | 说明 |
|------|------|
| `state` | 防火墙状态：`running` / `not running` |
| `default_zone` | 当前默认 Zone |
| `active_zones` | 当前活跃的 Zone 及其绑定的网卡/来源 |
| `firewalld_version` | firewalld 版本号 |

---

## 2. Zone（安全区域）管理

### 2.1 获取所有 Zone 列表

**GET** `/zones`

**响应示例：**

```json
{
  "success": true,
  "code": 200,
  "message": "查询成功",
  "data": {
    "zones": ["block", "dmz", "drop", "external", "home", "internal", "public", "trusted", "work"]
  }
}
```

---

### 2.2 获取指定 Zone 的完整规则详情

**GET** `/zones/{zone_name}`

**路径参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `zone_name` | string | 是 | Zone 名称，如 `public` |

**响应示例：**

```json
{
  "success": true,
  "code": 200,
  "message": "查询成功",
  "data": {
    "zone": "public",
    "target": "default",
    "interfaces": ["eth0"],
    "sources": [],
    "services": ["dhcpv6-client", "ssh"],
    "ports": ["8080/tcp", "9090/udp"],
    "rich_rules": [
      "rule family=\"ipv4\" source address=\"10.0.0.0/8\" service name=\"http\" accept"
    ]
  }
}
```

---

## 3. 端口规则管理

### 3.1 查询 Zone 内所有开放端口

**GET** `/zones/{zone_name}/ports`

**路径参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `zone_name` | string | 是 | Zone 名称 |

**响应示例：**

```json
{
  "success": true,
  "code": 200,
  "message": "查询成功",
  "data": {
    "zone": "public",
    "ports": ["80/tcp", "443/tcp", "8080-8090/tcp", "53/udp"]
  }
}
```

---

### 3.2 新增端口规则

**POST** `/zones/{zone_name}/ports`

**路径参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `zone_name` | string | 是 | Zone 名称 |

**请求体：**

```json
{
  "port": "8080",
  "protocol": "tcp",
  "source_ip": "192.168.1.0/24",
  "permanent_only": false,
  "runtime_only": false
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `port` | string | 是 | 端口号或范围，如 `8080`、`8000-8100` |
| `protocol` | string | 是 | 协议：`tcp` / `udp` / `sctp` / `dccp` |
| `source_ip` | string | 否 | 来源 IP 或 CIDR，如 `192.168.1.100` 或 `192.168.1.0/24`；指定后仅允许该来源访问此端口，后端将自动生成富规则（Rich Rule） |
| `permanent_only` | boolean | 否 | 仅写入永久配置（需手动 reload 生效），默认 `false` |
| `runtime_only` | boolean | 否 | 仅写入运行时（重启后失效），默认 `false` |

> 两个标志均为 `false` 时（默认），同时操作 runtime 和 permanent，变更即时生效且持久化。
> 指定 `source_ip` 时，后端实际执行的是富规则（Rich Rule）操作，而非普通端口开放。

**成功响应：**

```json
{
  "success": true,
  "code": 200,
  "message": "端口规则添加成功",
  "data": {
    "zone": "public",
    "port": "8080/tcp",
    "source_ip": "192.168.1.0/24",
    "permanent": true,
    "runtime": true
  }
}
```

**失败响应（规则已存在）：**

```json
{
  "success": false,
  "code": 409,
  "message": "端口规则 8080/tcp 已存在于 Zone public 中",
  "data": null
}
```

---

### 3.3 删除端口规则

**DELETE** `/zones/{zone_name}/ports`

**路径参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `zone_name` | string | 是 | Zone 名称 |

**请求体：**

```json
{
  "port": "8080",
  "protocol": "tcp",
  "source_ip": "192.168.1.0/24"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `port` | string | 是 | 端口号或范围 |
| `protocol` | string | 是 | 协议：`tcp` / `udp` / `sctp` / `dccp` |
| `source_ip` | string | 否 | 来源 IP 或 CIDR；若新增时指定了 `source_ip`，删除时也必须传入相同的值，后端将匹配对应的富规则进行删除 |

**成功响应：**

```json
{
  "success": true,
  "code": 200,
  "message": "端口规则删除成功",
  "data": {
    "zone": "public",
    "port": "8080/tcp",
    "source_ip": "192.168.1.0/24",
    "permanent": true,
    "runtime": true
  }
}
```

**失败响应（规则不存在）：**

```json
{
  "success": false,
  "code": 404,
  "message": "端口规则 8080/tcp 在 Zone public 中不存在",
  "data": null
}
```

---

## 4. 服务规则管理

> 服务是 firewalld 预定义的端口/协议组合，如 `http`（80/tcp）、`https`（443/tcp）、`ssh`（22/tcp）。
> 使用服务名比手动指定端口更便捷，且语义更清晰。

### 4.1 查询所有可用服务名

**GET** `/services`

**响应示例：**

```json
{
  "success": true,
  "code": 200,
  "message": "查询成功",
  "data": {
    "services": ["amanda", "bgp", "dns", "ftp", "http", "https", "mysql", "nfs", "smtp", "ssh", "telnet", "...]
  }
}
```

---

### 4.2 查询 Zone 内已启用的服务

**GET** `/zones/{zone_name}/services`

**路径参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `zone_name` | string | 是 | Zone 名称 |

**响应示例：**

```json
{
  "success": true,
  "code": 200,
  "message": "查询成功",
  "data": {
    "zone": "public",
    "services": ["ssh", "dhcpv6-client"]
  }
}
```

---

### 4.3 新增服务规则

**POST** `/zones/{zone_name}/services`

**路径参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `zone_name` | string | 是 | Zone 名称 |

**请求体：**

```json
{
  "service": "http",
  "permanent_only": false,
  "runtime_only": false
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `service` | string | 是 | 服务名称，如 `http`、`https`、`ssh` |
| `permanent_only` | boolean | 否 | 仅写入永久配置，默认 `false` |
| `runtime_only` | boolean | 否 | 仅写入运行时，默认 `false` |

**成功响应：**

```json
{
  "success": true,
  "code": 200,
  "message": "服务规则添加成功",
  "data": {
    "zone": "public",
    "service": "http",
    "permanent": true,
    "runtime": true
  }
}
```

---

### 4.4 删除服务规则

**DELETE** `/zones/{zone_name}/services`

**路径参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `zone_name` | string | 是 | Zone 名称 |

**请求体：**

```json
{
  "service": "http"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `service` | string | 是 | 服务名称 |

**成功响应：**

```json
{
  "success": true,
  "code": 200,
  "message": "服务规则删除成功",
  "data": {
    "zone": "public",
    "service": "http",
    "permanent": true,
    "runtime": true
  }
}
```

---

## 5. 富规则管理（Rich Rule）

> 富规则（Rich Rule）是 firewalld 的高级规则语言，支持基于源/目的 IP、协议、服务等组合条件进行精细化控制，并支持日志记录。
> 适用于需要针对特定 IP 地址放行或拒绝特定流量的场景。

### 富规则语法说明

```
rule [family="ipv4|ipv6"] [priority="N"]
  [source address="IP或CIDR" [invert="true"]]
  [destination address="IP或CIDR"]
  service name="服务名" | port port="端口" protocol="协议"
  [log [prefix="前缀"] [level="级别"]]
  accept | reject [type="icmp类型"] | drop
```

**优先级（priority）**：范围 -32768 到 32767，数值越小越先执行，默认 0。

**常用示例：**

```bash
# 允许 192.168.1.0/24 访问 HTTP
rule family="ipv4" source address="192.168.1.0/24" service name="http" accept

# 拒绝 10.0.0.5 的所有连接
rule family="ipv4" source address="10.0.0.5" reject

# 允许特定 IP 访问 8080 端口，并记录日志
rule family="ipv4" source address="10.10.10.100" port port="8080" protocol="tcp" log prefix="ALLOW-8080 " level="info" accept
```

---

### 5.1 查询 Zone 内所有富规则

**GET** `/zones/{zone_name}/rich-rules`

**路径参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `zone_name` | string | 是 | Zone 名称 |

**响应示例：**

```json
{
  "success": true,
  "code": 200,
  "message": "查询成功",
  "data": {
    "zone": "public",
    "rich_rules": [
      "rule family=\"ipv4\" source address=\"192.168.1.0/24\" service name=\"http\" accept",
      "rule family=\"ipv4\" source address=\"10.0.0.5\" reject"
    ]
  }
}
```

---

### 5.2 新增富规则

**POST** `/zones/{zone_name}/rich-rules`

**路径参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `zone_name` | string | 是 | Zone 名称 |

**请求体（方式一：直接传入规则字符串）：**

```json
{
  "rule": "rule family=\"ipv4\" source address=\"192.168.1.0/24\" service name=\"http\" accept",
  "permanent_only": false,
  "runtime_only": false
}
```

**请求体（方式二：结构化参数，由后端自动拼接规则）：**

```json
{
  "structured": true,
  "family": "ipv4",
  "source_address": "192.168.1.0/24",
  "source_invert": false,
  "destination_address": "",
  "service": "http",
  "port": "",
  "protocol": "",
  "action": "accept",
  "log_prefix": "",
  "log_level": "",
  "priority": 0,
  "permanent_only": false,
  "runtime_only": false
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `structured` | boolean | 否 | `true` 时使用结构化参数模式 |
| `rule` | string | 条件必填 | 原始富规则字符串（非结构化模式时必填） |
| `family` | string | 否 | IP 协议族：`ipv4` / `ipv6`，默认 `ipv4` |
| `source_address` | string | 否 | 来源 IP 或 CIDR，如 `192.168.1.0/24` |
| `source_invert` | boolean | 否 | 来源地址取反（排除该 IP），默认 `false` |
| `destination_address` | string | 否 | 目标 IP 或 CIDR |
| `service` | string | 条件必填 | 服务名（与 `port` 二选一） |
| `port` | string | 条件必填 | 端口号（与 `service` 二选一） |
| `protocol` | string | 条件必填 | 协议（`port` 模式时必填：`tcp` / `udp`） |
| `action` | string | 是 | 动作：`accept` / `reject` / `drop` |
| `log_prefix` | string | 否 | 日志前缀字符串 |
| `log_level` | string | 否 | 日志级别：`emerg` / `alert` / `crit` / `err` / `warning` / `notice` / `info` / `debug` |
| `priority` | integer | 否 | 规则优先级，范围 -32768~32767，默认 0 |
| `permanent_only` | boolean | 否 | 仅写入永久配置，默认 `false` |
| `runtime_only` | boolean | 否 | 仅写入运行时，默认 `false` |

**成功响应：**

```json
{
  "success": true,
  "code": 200,
  "message": "富规则添加成功",
  "data": {
    "zone": "public",
    "rule": "rule family=\"ipv4\" source address=\"192.168.1.0/24\" service name=\"http\" accept",
    "permanent": true,
    "runtime": true
  }
}
```

---

### 5.3 删除富规则

**DELETE** `/zones/{zone_name}/rich-rules`

**路径参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `zone_name` | string | 是 | Zone 名称 |

**请求体：**

```json
{
  "rule": "rule family=\"ipv4\" source address=\"192.168.1.0/24\" service name=\"http\" accept"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `rule` | string | 是 | 要删除的富规则完整字符串（需与已有规则完全一致） |

**成功响应：**

```json
{
  "success": true,
  "code": 200,
  "message": "富规则删除成功",
  "data": {
    "zone": "public",
    "rule": "rule family=\"ipv4\" source address=\"192.168.1.0/24\" service name=\"http\" accept",
    "permanent": true,
    "runtime": true
  }
}
```

---

## 6. 来源地址管理（Source）

> 将 IP 地址或 CIDR 网段绑定到指定 Zone，使该来源的所有流量按照该 Zone 的规则处理。
> 常用于将内网网段绑定到 `internal` Zone 以获得更宽松的访问权限。

### 6.1 查询 Zone 内所有来源地址

**GET** `/zones/{zone_name}/sources`

**路径参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `zone_name` | string | 是 | Zone 名称 |

**响应示例：**

```json
{
  "success": true,
  "code": 200,
  "message": "查询成功",
  "data": {
    "zone": "internal",
    "sources": ["192.168.1.0/24", "10.0.0.0/8"]
  }
}
```

---

### 6.2 新增来源地址

**POST** `/zones/{zone_name}/sources`

**路径参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `zone_name` | string | 是 | Zone 名称 |

**请求体：**

```json
{
  "source": "192.168.1.0/24",
  "permanent_only": false,
  "runtime_only": false
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `source` | string | 是 | IP 地址或 CIDR 网段，如 `192.168.1.100` 或 `192.168.1.0/24` |
| `permanent_only` | boolean | 否 | 仅写入永久配置，默认 `false` |
| `runtime_only` | boolean | 否 | 仅写入运行时，默认 `false` |

**成功响应：**

```json
{
  "success": true,
  "code": 200,
  "message": "来源地址添加成功",
  "data": {
    "zone": "internal",
    "source": "192.168.1.0/24",
    "permanent": true,
    "runtime": true
  }
}
```

---

### 6.3 删除来源地址

**DELETE** `/zones/{zone_name}/sources`

**路径参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `zone_name` | string | 是 | Zone 名称 |

**请求体：**

```json
{
  "source": "192.168.1.0/24"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `source` | string | 是 | 要删除的 IP 地址或 CIDR 网段 |

**成功响应：**

```json
{
  "success": true,
  "code": 200,
  "message": "来源地址删除成功",
  "data": {
    "zone": "internal",
    "source": "192.168.1.0/24",
    "permanent": true,
    "runtime": true
  }
}
```

---

## 附录：预定义 Zone 说明

| Zone 名称 | 信任级别 | 说明 | 典型用途 |
|-----------|----------|------|----------|
| `drop` | 最低 | 丢弃所有入站连接（无响应） | 黑洞策略 |
| `block` | 很低 | 拒绝所有入站连接（返回 ICMP 拒绝消息） | 明确拒绝 |
| `public` | 低 | 不受信任的公网环境（**默认 Zone**） | 公网网卡 |
| `external` | 低 | 开启 IP 伪装的外网环境（用于路由器） | NAT 出口 |
| `dmz` | 中低 | 非军事区，限制访问内网 | 对外服务器 |
| `work` | 中 | 工作网络，部分信任 | 办公室网络 |
| `home` | 中高 | 家庭网络，信任同网段设备 | 家庭网络 |
| `internal` | 高 | 内部网络，完全信任 | 内网网段 |
| `trusted` | 最高 | 接受所有连接 | 完全受信网络 |

---

## 附录：常见服务名称

| 服务名 | 默认端口/协议 | 说明 |
|--------|---------------|------|
| `ssh` | 22/tcp | SSH 远程连接 |
| `http` | 80/tcp | HTTP Web 服务 |
| `https` | 443/tcp | HTTPS Web 服务 |
| `dns` | 53/tcp+udp | DNS 域名解析 |
| `ftp` | 21/tcp | FTP 文件传输 |
| `smtp` | 25/tcp | 邮件发送 |
| `mysql` | 3306/tcp | MySQL 数据库 |
| `postgresql` | 5432/tcp | PostgreSQL 数据库 |
| `redis` | 6379/tcp | Redis 缓存 |
| `nfs` | 2049/tcp+udp | NFS 网络文件共享 |
| `samba` | 445/tcp | Windows 文件共享 |
| `dhcp` | 67/udp | DHCP 服务 |
| `dhcpv6-client` | 546/udp | DHCPv6 客户端 |

> 完整服务列表可通过 `GET /services` 接口查询。

---

## API 端点汇总

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/status` | 获取防火墙运行状态 |
| GET | `/api/v1/zones` | 获取所有 Zone 列表 |
| GET | `/api/v1/zones/{zone_name}` | 获取指定 Zone 完整规则 |
| GET | `/api/v1/zones/{zone_name}/ports` | 查询 Zone 开放的端口 |
| POST | `/api/v1/zones/{zone_name}/ports` | 新增端口规则 |
| DELETE | `/api/v1/zones/{zone_name}/ports` | 删除端口规则 |
| GET | `/api/v1/services` | 查询所有可用服务名 |
| GET | `/api/v1/zones/{zone_name}/services` | 查询 Zone 已启用的服务 |
| POST | `/api/v1/zones/{zone_name}/services` | 新增服务规则 |
| DELETE | `/api/v1/zones/{zone_name}/services` | 删除服务规则 |
| GET | `/api/v1/zones/{zone_name}/rich-rules` | 查询 Zone 内所有富规则 |
| POST | `/api/v1/zones/{zone_name}/rich-rules` | 新增富规则 |
| DELETE | `/api/v1/zones/{zone_name}/rich-rules` | 删除富规则 |
| GET | `/api/v1/zones/{zone_name}/sources` | 查询 Zone 内来源地址 |
| POST | `/api/v1/zones/{zone_name}/sources` | 新增来源地址 |
| DELETE | `/api/v1/zones/{zone_name}/sources` | 删除来源地址 |
