# 部署与自动发布（两机拓扑，2026-10-20 拍板）

> A 机（付费 2C4G，本项目）+ B 机（免费 2C4G，smartServe/agent-all 仓库）。
> 拆机动机是故障域隔离与免费机利用，不是性能——单机 2C4G 本可承载。
> B 机侧细节见 agent-all 仓库 `docs/deploy.md`；本文管 A 机与两机关系。

## 一、两机分工

| | A 机（本项目） | B 机（agent-all） |
|---|---|---|
| 装什么 | **Docker + uv + git**（API 走 systemd 宿主机跑） | **只要 Docker + git**（构建在 GitHub Actions runner，机器只 pull 镜像） |
| 常驻 | PG18 + Neo4j（compose）、adkg-api（systemd，`deploy/systemd/adkg-api.service`） | gateway / web / redis / migrate（compose，镜像取 GHCR） |
| 镜像 | Ubuntu 24.04 + Docker 应用镜像（云商预装；别选纯 docker appliance——A 机要 systemd + uv 跑宿主进程） | 同左 |

内存预算：A 机 ~2.2G/4G（Neo4j 1.2G + PG 0.2G + API 0.4G + OS 0.4G）；B 机 ~0.9G/4G（gateway 0.45G 单 worker + nginx 0.05G + redis + OS）。

## 二、首次上线（一次性手工，此后 push 即发）

```bash
# ── A 机（本项目）────────────────────────────────────────────
# 1) 装 docker（应用镜像已带则跳过）+ uv + git；克隆仓库
git clone git@github.com:weizheng1992/ad-kg.git ~/ad-kg && cd ~/ad-kg
cp .env.example .env && vim .env                 # 填 LLM key、token、PG/Neo4j 口令

# 2) 基础设施（Neo4j 必须压内存，4G 机器默认配置会吃掉一半）
#    docker-compose.yml 的 neo4j 服务 environment 加两行：
#    NEO4J_server_memory_heap_max__size: 512m
#    NEO4J_server_memory_pagecache_size: 256m
docker network create shared-infra               # 跨机时 B 机也要建（空网即可，两机 compose 文件统一）
docker compose up -d

# 3) 数据 + 账号 + API 常驻
uv sync
uv run python scripts/init_db.py                 # 建表 + adkg_rw/adkg_ro + Neo4j 约束（幂等）
uv run python scripts/init_users.py              # web 登录账号（密码随机打印一次，或 ADKG_USER_PASSWORD= 指定）
HF_ENDPOINT=https://hf-mirror.com uv run python scripts/load_seed.py   # 种子+嵌入，2C 几分钟
sed -i "s/__USER__/deploy/g" deploy/systemd/adkg-api.service   # 换实际用户名
sudo cp deploy/systemd/adkg-api.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now adkg-api
curl -s http://127.0.0.1:8000/docs >/dev/null && echo "API OK"

# ── B 机（agent-all，概要；全文见其 docs/deploy.md）──────────
# 装 docker/git → 克隆 agent-all → 先配 WireGuard 隧道（§四）→ deploy/.env.prod
#   DATABASE_URL=postgres://agent_user:***@10.10.0.1:5433/agent_platform   # 隧道地址
# → ADKG_PG_HOST=10.10.0.1 ADKG_PG_ADMIN_PASSWORD=<A机PG口令> bash scripts/init_external_pg.sh
# → db:push + db:seed → compose pull && compose up -d
```

## 三、自动发布（push main 即发）

两仓同模式：`.github/workflows/ci.yml` —— PR 只跑测试；push main 测绿后 SSH 执行
`git pull → 初始化/迁移 → 重启 → 健康断言`（A 机 `/docs` 探活，B 机 `/api/health`）。

| 项 | A 机 | B 机 |
|---|---|---|
| Secrets | `DEPLOY_HOST` / `DEPLOY_USER` / `DEPLOY_SSH_KEY` | 同左（指向 B 机） |
| 产物 | 无镜像，git pull + `uv sync --frozen` | GHCR `smartserve-{gateway,web}`（sha+latest 双 tag，runner 构建） |
| 部署动作 | `init_db.py`（幂等）+ `systemctl restart adkg-api` | `compose pull && up -d`（migrate 自动先跑） |
| 回滚 | `git revert` push，CI 自动重发 | compose tag 指回上一个 sha 再 `up -d` |

部署用最小权限专用用户：git 拉取（deploy key）+ docker 组 + sudoers 仅 `systemctl restart adkg-api` 一条。

**GHCR 注意**：首次 push 后到 GitHub → Packages 把 `smartserve-gateway` / `smartserve-web` 设 **public**（默认 private，B 机匿名 pull 会 401）；国内直连 ghcr 拉不动时走 daocloud 代理 retag（`docker pull docker.m.daocloud.io/ghcr.io/weizheng1992/...` 后 retag 回原名）。

## 四、网络闸门（安全组是主边界）

- **两机无内网 → WireGuard 点对点隧道**（2026-10-20 拍板）：A 机 `10.10.0.1`、B 机 `10.10.0.2`，
  B→A 的 PG(5433) 全走隧道加密。配置：A 机 `[Interface] Address=10.10.0.1/24, ListenPort=51820` +
  `[Peer]`（B 公钥，AllowedIPs=10.10.0.2/32）；B 机 `[Interface] Address=10.10.0.2/24` + `[Peer]`
  （A 公钥，Endpoint=<A机公网IP>:51820，AllowedIPs=10.10.0.1/32，**PersistentKeepalive=25** 必须，
  免得 NAT 断了隧道不自知）。`systemctl enable --now wg-quick@wg0`，`ping 10.10.0.1` 验证
- **公网面只开**：A 机 UDP 51820（限 B 机 IP）+ 两台的 22（GitHub Actions 的 runner IP 动态，
  只能全开，key-only 登录 + fail2ban 兜底）；自家终端 SSH 也走 22
- 一律不对公网开放：**5433（PG）/ 8000（API）/ 7687（bolt）/ 7474（Neo4j 浏览器）**——
  PG 只经隧道到 B 机；adkg API 将来被 smartServe 消费时填隧道地址 `10.10.0.1:8000`（现未接线）
- **唯一公网面例外：web（2026-10-20 拍板；2026-10-24 真实系统化改会话制，spec §2）**——80/TCP 经宿主机
  nginx 开放：静态 `web/dist` + 反代 API 路径（auth/ask/graph/actions/guideline/ingest/cases/agent/creative
  及 creators/brands/settlements/stats/admin）到 `127.0.0.1:8000`。把门三层：① 服务端会话登录
  （`/auth/login` 校验 `app_user` scrypt 哈希 → `app_session` HttpOnly cookie，7 天滑动可吊销；
  账号由 `scripts/init_users.py` 开通，README §9.7「最小账号面」）② `resolve_identity` 优先级
  token > cookie > dev，cookie 失效即 401 fail-closed（~~X-Adkg-Role 头换 token~~ 已撤，
  Bearer 直连路保留给 smartServe/eval）③ limit_req 限速（/ask 1r/s burst 3，防烧 LLM 配额）。
  HTTPS 上线时 `.env` 开 `ADKG_COOKIE_SECURE=on`（会话 cookie 加 Secure）。
  8000 本体仍不对公网，nginx 是唯一入口。web/dist 更新走 rsync（CI 自动化留待加厚时）。
  **nginx 配置真源：`deploy/nginx/adkg-demo.conf`（2026-10-23 落位、2026-10-24 改会话制；
  含探测路径 404，SPA fallback 不再对扫描器回 200；2026-10-27 起同名页面路径的文档请求
  ——浏览器直开/刷新 Accept 含 text/html——回落 SPA 不进 API，改本文件无需登机：CI 部署步自动
  同步重载）**

- **CI 全自动发布（2026-10-25 起）**：push main → runner 构建 web（bun）→ SSH 部署五步
  （代码 pull + uv.lock 自愈 → init_db → 重启 → web 静态发布 → nginx 配置同步重载 → 健康断言）。
  其中 web/nginx 两步需要 root **一次性授权**（之后 CI 全自动，无需再登 root）：

  ```bash
  ssh root@152.136.165.95   # 一次性（约 6 行）
  # 1) web 静态目录交 deploy（CI 用 adkg.new/adkg.old 原子轮换发布）
  chown -R deploy:deploy /var/www/adkg
  # 2) nginx 配置同步 + 校验/重载三条窄 sudoers（写 /etc/sudoers.d/adkg-ci）
  cat >/etc/sudoers.d/adkg-ci <<'EOF'
  deploy ALL=(root) NOPASSWD: /usr/bin/cp /home/deploy/ad-kg/deploy/nginx/adkg-demo.conf /etc/nginx/sites-available/adkg
  deploy ALL=(root) NOPASSWD: /usr/sbin/nginx -t
  deploy ALL=(root) NOPASSWD: /usr/sbin/systemctl reload nginx
  EOF
  chmod 440 /etc/sudoers.d/adkg-ci
  # 3) 首次手动应用一次（此后 CI 接管）
  cp /home/deploy/ad-kg/deploy/nginx/adkg-demo.conf /etc/nginx/sites-available/adkg
  nginx -t && systemctl reload nginx
  ```

  未授权前 CI 的这两步打 `SKIP:` 日志继续跑（不阻塞代码发布）；授权后自动生效。

- **运行三件套（2026-10-25）**：① **PG 连接池**——API 层统一走 `adkg/store/pg_pool.connect()`
  （psycopg_pool，按 DSN×选项×行工厂键缓存，min1/max8），替代每请求临时连接
  （agent ReAct 嵌套 /ask 曾可叠多个临时连接撞 `max_connections=100`）；脚本类批任务仍直连。
  ② **慢查询日志**——compose 里 postgres `log_min_duration_statement=200ms` +
  `log_lock_waits=on`（`docker logs adkg-postgres` 看），客户端 `statement_timeout` 兜底不变。
  ③ **docker 硬内存上限**——postgres 768m / neo4j 1280m（env 管堆，mem_limit 兜全进程）/
  mock-douyin 128m，4G 机防互挤。改 compose 后 `docker compose up -d <svc>` 重建即生效（数据在卷）。
- **飞书服务器报警（2026-10-25 起）**：两层——
  ① A 机 `deploy/alerts/health_alert.sh` 每 5 分钟（deploy 用户 crontab）巡检 API 探活/服务状态/
  磁盘>85%/内存>90%/负载>4，异常进群、30 分钟节流、恢复发恢复通知；webhook 存
  `~/ad-kg/.feishu_alert_url`（600 权限，永不入库）。
  ② CI 部署失败进群（`secrets.FEISHU_WEBHOOK`，repo Settings → Secrets → Actions 配置一次）。
- 凭据分层：`.env` 永不入库（两仓都是）；LLM key 只存服务器与本地，GitHub 只有 SSH 部署钥匙

## 五、边界约定（沿用 README §五 / §9.8 的精神）

- 批任务（评测、promptfoo、批量抽取、嵌入回填）**永不上服务器**——本地跑，服务器只承检索与裁决端点；
  **例外**：`load_seed` / `sync_feishu` 重灌类操作可在服务器执行（幂等），但 2C 上嵌入会吃满 CPU、
  把并发的 /ask 饿死（实测 120s 无响应，2026-10-20）——放低峰期执行，执行期间 /ask 短暂变慢属预期
- 服务器数据 = `load_seed` 种子 + 飞书增量（launchd 在本地，服务器侧不配）；重灌 = 本地重跑脚本推送
- 改设计先改 README（本文件只放部署运维，不承载设计约定）
