#!/usr/bin/env bash
# Hubloom 本地一键启动 / 更新（Docker）
#
# 会拉起（本仓库 docker-compose）：
#   - Redis + Qdrant（端口已占用则复用现有服务）
#   - Postgres（hubloom_postgres；端口空闲才起，可用 HUBLOOM_SKIP_POSTGRES=1 跳过）
#   - Hubloom Serve（镜像 hubloom_serve，读 config/env.docker.yaml）
#
# 不会：
#   - 打包 / 部署示例站 Web（8080）
#   - 启动业务 API 容器（8000）——留给你其它服务；MCP 只检查 config 里的 swagger_url
#   - 强占已被其它容器占用的 6379 / 6333 / 5432
#
# 用法：
#   ./start.sh              # 构建并启动（含 Serve）
#   ./start.sh up           # 同上
#   ./start.sh update       # 拉代码、重建 Serve 镜像并重启
#   ./start.sh down         # 停 Serve + Redis/Qdrant（Postgres 默认保留）
#   ./start.sh down --all   # 上者 + 停 hubloom_postgres
#   ./start.sh restart      # 仅重启 Serve 容器
#   ./start.sh status       # 查看状态
#   ./start.sh logs         # 跟踪 Serve 容器日志
#   ./start.sh infra        # 仅起 Redis + Qdrant
#
# 环境变量（可选）：
#   HUBLOOM_SKIP_GIT=1      跳过 git pull
#   HUBLOOM_SKIP_POSTGRES=1 不启动 Postgres
#   HUBLOOM_NO_BUILD=1      不重建 Serve 镜像（仅 up -d）

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

COMPOSE=(docker compose -f "$ROOT/docker-compose.yml")
RUN_DIR="$ROOT/.run"
CFG="$ROOT/config/env.yaml"
CFG_DOCKER="$ROOT/config/env.docker.yaml"

die() {
  echo "错误: $*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "未找到命令「$1」，请先安装"
}

info() {
  echo ">>> $*"
}

ensure_dirs() {
  mkdir -p "$RUN_DIR" "$ROOT/logs" "$ROOT/data" "$ROOT/config"
}

ensure_config() {
  if [[ ! -f "$CFG" ]]; then
    cp "$ROOT/config/env.example.yaml" "$CFG"
    echo "已生成 config/env.yaml（来自 env.example.yaml），请先填好 llm / redis / mcp 等后再启动。"
    die "请编辑 config/env.yaml 后重新执行 ./start.sh"
  fi
}

# 容器内访问宿主机已发布端口（Redis/Postgres/业务 API/Qdrant 等）
generate_docker_config() {
  ensure_config
  info "生成容器配置 config/env.docker.yaml（localhost → host.docker.internal）…"
  sed -E \
    -e 's/@127\.0\.0\.1:/@host.docker.internal:/g' \
    -e 's/@localhost:/@host.docker.internal:/g' \
    -e 's|://127\.0\.0\.1:|://host.docker.internal:|g' \
    -e 's|://localhost:|://host.docker.internal:|g' \
    -e 's|http://127\.0\.0\.1:|http://host.docker.internal:|g' \
    -e 's|https://127\.0\.0\.1:|https://host.docker.internal:|g' \
    -e 's|http://localhost:|http://host.docker.internal:|g' \
    -e 's|https://localhost:|https://host.docker.internal:|g' \
    "$CFG" >"$CFG_DOCKER"

  # 确保 no_proxy 含 host.docker.internal（若配置里有 no_proxy 行则追加）
  if grep -qE '^[[:space:]]*no_proxy:' "$CFG_DOCKER"; then
    if ! grep -q 'host.docker.internal' "$CFG_DOCKER"; then
      sed -i.bak -E \
        's|(no_proxy:[[:space:]]*['\''"])|\1host.docker.internal,|' \
        "$CFG_DOCKER" && rm -f "${CFG_DOCKER}.bak"
    fi
  fi
}

stop_legacy_local_agent() {
  # 兼容：以前用 nohup 起的本机进程
  local pid_file="$RUN_DIR/hubloom.pid"
  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      info "停止旧的本机 Hubloom 进程 (pid=$pid)…"
      kill "$pid" 2>/dev/null || true
      sleep 1
      kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$pid_file"
  fi
}

serve_running() {
  docker inspect -f '{{.State.Running}}' hubloom_serve 2>/dev/null | grep -qx true \
    || docker inspect -f '{{.State.Running}}' Hubloom_serve 2>/dev/null | grep -qx true
}

stop_agent() {
  stop_legacy_local_agent
  # 兼容短暂用过的 Hubloom_serve
  if docker inspect hubloom_serve >/dev/null 2>&1 || docker inspect Hubloom_serve >/dev/null 2>&1; then
    info "停止 Hubloom Serve 容器…"
    "${COMPOSE[@]}" stop serve >/dev/null 2>&1 || true
    "${COMPOSE[@]}" rm -f serve >/dev/null 2>&1 || true
    docker rm -f hubloom_serve Hubloom_serve >/dev/null 2>&1 || true
  fi
}

start_agent() {
  ensure_dirs
  ensure_config
  need_cmd docker
  docker info >/dev/null 2>&1 || die "Docker 未运行，请先打开 Docker Desktop"

  stop_legacy_local_agent
  generate_docker_config

  if port_open 8765 && ! serve_running; then
    die "8765 已被其它进程占用，请先停止后再启动 Hubloom Serve"
  fi

  local build_args=()
  if [[ "${HUBLOOM_NO_BUILD:-0}" != "1" ]]; then
    build_args+=(--build)
    info "构建并启动 Hubloom Serve 容器…"
  else
    info "启动 Hubloom Serve 容器（跳过 build）…"
  fi

  "${COMPOSE[@]}" up -d "${build_args[@]}" serve

  wait_http "http://127.0.0.1:8765/docs" "Hubloom Serve" 60 || {
    echo "---- Serve 容器日志 ----" >&2
    "${COMPOSE[@]}" logs --tail=80 serve >&2 || true
    die "Hubloom Serve 未就绪"
  }
}

wait_http() {
  local url="$1"
  local name="$2"
  local max="${3:-60}"
  local i=0
  echo -n "等待 ${name} 就绪"
  while (( i < max )); do
    # 本地探活必须绕过 http_proxy，否则 127.0.0.1 会被代理成 502/超时
    if curl -fsS --noproxy '*' "$url" >/dev/null 2>&1; then
      echo " OK"
      return 0
    fi
    echo -n "."
    sleep 2
    ((i += 1)) || true
  done
  echo
  return 1
}

wait_tcp() {
  local host="$1"
  local port="$2"
  local name="$3"
  local max="${4:-30}"
  local i=0
  echo -n "等待 ${name} 就绪"
  while (( i < max )); do
    if (echo >/dev/tcp/"$host"/"$port") >/dev/null 2>&1; then
      echo " OK"
      return 0
    fi
    echo -n "."
    sleep 1
    ((i += 1)) || true
  done
  echo
  return 1
}

# 以「本机能否连上」为准；不要用 lsof（易误判），也不走代理
port_open() {
  local port="$1"
  (echo >/dev/tcp/127.0.0.1/"$port") >/dev/null 2>&1
}

qdrant_ready() {
  curl -fsS --noproxy '*' "http://127.0.0.1:6333/readyz" >/dev/null 2>&1
}

# 清掉已退出但仍占着发布端口的容器，避免 compose 无法 bind
remove_exited_publishers() {
  local port="$1"
  local ids
  ids="$(docker ps -aq --filter "status=exited" --filter "publish=${port}" 2>/dev/null || true)"
  if [[ -n "$ids" ]]; then
    info "清理已退出但仍占用 ${port} 映射的容器…"
    # shellcheck disable=SC2086
    docker rm -f $ids >/dev/null 2>&1 || true
  fi
}

swagger_url_from_config() {
  # 从 env.yaml 读 mcp.swagger_url；读不到则空
  if [[ ! -f "$CFG" ]]; then
    echo ""
    return 0
  fi
  local line
  line="$(grep -E '^[[:space:]]*swagger_url:' "$CFG" | head -1 || true)"
  if [[ -z "$line" ]]; then
    echo ""
    return 0
  fi
  # 去掉 key、引号、行内注释
  echo "$line" \
    | sed -E 's/^[[:space:]]*swagger_url:[[:space:]]*//' \
    | sed -E 's/[[:space:]]+#.*$//' \
    | sed -E 's/^["'\'']//; s/["'\'']$//' \
    | tr -d '\r'
}

cmd_infra_up() {
  need_cmd docker
  docker info >/dev/null 2>&1 || die "Docker 未运行，请先打开 Docker Desktop"

  local services=()

  if docker inspect -f '{{.State.Running}}' hubloom_redis 2>/dev/null | grep -qx true; then
    info "hubloom_redis 已在运行"
  elif port_open 6379; then
    info "6379 已可连接，复用现有 Redis（跳过 hubloom_redis）"
    # 仅清理未运行的本项目容器名，绝不能 rm 正在提供 6379 的实例
    for c in hubloom_redis Hubloom_redis; do
      if docker inspect "$c" >/dev/null 2>&1 \
        && ! docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null | grep -qx true; then
        docker rm -f "$c" >/dev/null 2>&1 || true
      fi
    done
  else
    remove_exited_publishers 6379
    docker rm -f Hubloom_redis >/dev/null 2>&1 || true
    services+=(redis)
  fi

  if docker inspect -f '{{.State.Running}}' hubloom_qdrant 2>/dev/null | grep -qx true \
    && qdrant_ready; then
    info "hubloom_qdrant 已在运行"
  elif port_open 6333 && qdrant_ready; then
    info "6333 上 Qdrant 已就绪，复用现有实例（跳过 hubloom_qdrant）"
  else
    if port_open 6333 && ! qdrant_ready; then
      die "6333 有进程在听，但不是可用的 Qdrant（/readyz 失败）。请停掉占用进程后重试，或改 docker-compose 端口。"
    fi
    remove_exited_publishers 6333
    docker rm -f Hubloom_qdrant >/dev/null 2>&1 || true
    # 常见：旧容器名就叫 qdrant、已退出但仍占映射
    if docker inspect qdrant >/dev/null 2>&1; then
      local st
      st="$(docker inspect -f '{{.State.Status}}' qdrant 2>/dev/null || true)"
      if [[ "$st" != "running" ]]; then
        info "移除已退出的旧 qdrant 容器，改由 hubloom_qdrant 启动…"
        docker rm -f qdrant >/dev/null 2>&1 || true
      fi
    fi
    services+=(qdrant)
  fi

  if ((${#services[@]} > 0)); then
    info "启动 Hubloom 基础设施：${services[*]}…"
    "${COMPOSE[@]}" up -d "${services[@]}"
  else
    info "Redis / Qdrant 均已可用，跳过 compose 启动"
  fi

  wait_tcp 127.0.0.1 6379 "Redis" 30 || die "Redis 未就绪"
  wait_http "http://127.0.0.1:6333/readyz" "Qdrant" 40 || die "Qdrant 未就绪"
}

cmd_infra_down() {
  need_cmd docker
  # 与 postgres 同 compose：只停 serve/redis/qdrant，默认保留 hubloom_postgres
  info "停止 Hubloom Serve / Redis / Qdrant（不影响其它项目容器）…"
  "${COMPOSE[@]}" stop serve redis qdrant >/dev/null 2>&1 || true
  "${COMPOSE[@]}" rm -f serve redis qdrant >/dev/null 2>&1 || true
}

update_hubloom_code() {
  if [[ "${HUBLOOM_SKIP_GIT:-0}" == "1" ]]; then
    info "跳过 git pull（HUBLOOM_SKIP_GIT=1）"
  elif [[ -d "$ROOT/.git" ]]; then
    info "更新 Hubloom 代码（git pull）…"
    if ! git -C "$ROOT" pull --ff-only; then
      echo "提示: git pull --ff-only 失败（可能有本地提交未推送或冲突），继续使用当前代码。"
    fi
  fi
}

cmd_postgres_up() {
  if [[ "${HUBLOOM_SKIP_POSTGRES:-0}" == "1" ]]; then
    info "跳过 Postgres（HUBLOOM_SKIP_POSTGRES=1）"
    return 0
  fi
  need_cmd docker
  docker info >/dev/null 2>&1 || die "Docker 未运行，请先打开 Docker Desktop"

  if docker inspect -f '{{.State.Running}}' hubloom_postgres 2>/dev/null | grep -qx true; then
    info "hubloom_postgres 已在运行"
    wait_tcp 127.0.0.1 5432 "Postgres" 10 || die "Postgres 未就绪"
    return 0
  fi

  if port_open 5432; then
    info "5432 已可连接，复用现有 Postgres（未启动 hubloom_postgres）"
    echo "提示: 若要用本仓 hubloom_postgres，请先停掉占用 5432 的容器后再执行 ./start.sh。"
    wait_tcp 127.0.0.1 5432 "Postgres" 10 || die "Postgres 未就绪"
    return 0
  fi

  remove_exited_publishers 5432
  # 兼容曾用过的业务仓容器名，避免已退出实例占映射
  docker rm -f personal_smart_system_postgres >/dev/null 2>&1 || true
  info "启动 hubloom_postgres…"
  "${COMPOSE[@]}" up -d postgres
  wait_tcp 127.0.0.1 5432 "Postgres" 40 || die "Postgres 未就绪"
}

cmd_postgres_down() {
  need_cmd docker
  info "停止 hubloom_postgres…"
  "${COMPOSE[@]}" stop postgres >/dev/null 2>&1 || true
  "${COMPOSE[@]}" rm -f postgres >/dev/null 2>&1 || true
}

check_mcp_swagger() {
  local url
  url="$(swagger_url_from_config)"
  if [[ -z "$url" ]]; then
    echo "提示: config 未配置 mcp.swagger_url，MCP 工具可能不可用。"
    return 0
  fi
  info "检查 MCP OpenAPI：$url"
  if wait_http "$url" "OpenAPI" 15; then
    return 0
  fi
  echo "提示: OpenAPI 暂不可用（$url）。"
  echo "      8000/8080 由你其它服务占用；请自行保证业务 API 已启动。"
  echo "      Hubloom 仍会继续启动。"
}

print_urls() {
  local swagger
  swagger="$(swagger_url_from_config)"
  [[ -n "$swagger" ]] || swagger="(未配置 mcp.swagger_url)"
  cat <<EOF

已就绪：
  Hubloom Serve   http://127.0.0.1:8765   （Docker: hubloom_serve）
  API 文档        http://127.0.0.1:8765/docs
  Redis           localhost:6379
  Qdrant          http://127.0.0.1:6333
  Postgres        localhost:5432   （Docker: hubloom_postgres）
  MCP OpenAPI     $swagger
  容器日志        ./start.sh logs

常用：
  ./start.sh update     # 拉代码 + 重建镜像 + 重启
  ./start.sh logs       # 看 Serve 容器日志
  ./start.sh status     # 状态
  ./start.sh down       # 停止 Serve + Redis/Qdrant
  ./start.sh down --all # 再停 hubloom_postgres

EOF
}

cmd_up() {
  ensure_dirs
  ensure_config
  cmd_infra_up
  cmd_postgres_up
  check_mcp_swagger
  update_hubloom_code
  start_agent
  print_urls
  cmd_status
}

cmd_update() {
  ensure_dirs
  ensure_config
  cmd_infra_up
  cmd_postgres_up
  check_mcp_swagger
  update_hubloom_code
  HUBLOOM_NO_BUILD=0 start_agent
  print_urls
}

cmd_down() {
  stop_agent
  cmd_infra_down
  if [[ "${1:-}" == "--all" ]]; then
    cmd_postgres_down
  else
    echo "提示: hubloom_postgres 仍在运行；如需一并停止：./start.sh down --all"
  fi
  echo "已停止 Hubloom Serve 与基础设施（未动 8000/8080 上的其它服务）。"
}

cmd_restart() {
  ensure_config
  generate_docker_config
  need_cmd docker
  info "重启 Hubloom Serve 容器…"
  "${COMPOSE[@]}" up -d serve
  wait_http "http://127.0.0.1:8765/docs" "Hubloom Serve" 60 || die "Hubloom Serve 未就绪"
  print_urls
}

cmd_status() {
  echo "== Hubloom Compose =="
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    "${COMPOSE[@]}" ps || true
  else
    echo "(Docker 不可用)"
  fi
}

cmd_logs() {
  need_cmd docker
  "${COMPOSE[@]}" logs -f --tail=200 serve
}

usage() {
  sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'
}

main() {
  local action="${1:-up}"
  case "$action" in
    up|start)
      cmd_up
      ;;
    update)
      cmd_update
      ;;
    down|stop)
      shift || true
      cmd_down "${1:-}"
      ;;
    restart)
      cmd_restart
      ;;
    infra)
      cmd_infra_up
      ;;
    status|ps)
      cmd_status
      ;;
    logs)
      cmd_logs
      ;;
    -h|--help|help)
      usage
      ;;
    *)
      die "未知命令「$action」。用 ./start.sh help 查看用法。"
      ;;
  esac
}

main "$@"
