#!/bin/sh
# A 机健康巡检 → 飞书群机器人报警（crontab 每 5 分钟）
# 安装：见 docs/deployment.md §五；webhook URL 存 ~/ad-kg/.feishu_alert_url（600 权限，永不入库）
# 节流：同一故障 30 分钟内只报一次（状态文件 /tmp/adkg_alert_state），恢复时发恢复通知
set -u
URL_FILE="$HOME/ad-kg/.feishu_alert_url"
STATE="/tmp/adkg_alert_state"
[ -r "$URL_FILE" ] || exit 0
WEBHOOK=$(cat "$URL_FILE")

send() {  # send "标题" "正文"
  curl -sS -m 10 -X POST "$WEBHOOK" -H 'Content-Type: application/json' \
    -d "{\"msg_type\":\"text\",\"content\":{\"text\":\"[$(hostname)] $1\n$2\"}}" >/dev/null 2>&1
}

issues=""
curl -fsS -m 5 http://127.0.0.1:8000/docs >/dev/null 2>&1 || issues="$issues\n• adkg-api /docs 探活失败"
systemctl is-active adkg-api >/dev/null 2>&1 || issues="$issues\n• adkg-api 服务非 active"
DISK=$(df -P / | awk 'NR==2{gsub("%","");print $5}')
[ "$DISK" -gt 85 ] 2>/dev/null && issues="$issues\n• 磁盘使用 ${DISK}%"
MEM=$(free -m | awk 'NR==2{printf "%d", $3*100/$2}')
[ "$MEM" -gt 90 ] 2>/dev/null && issues="$issues"\n"• 内存使用 ${MEM}%"
LOAD1=$(cut -d' ' -f1 /proc/loadavg 2>/dev/null || echo 0)
awk "BEGIN{exit !($LOAD1 > 4)}" 2>/dev/null && issues="$issues\n• 负载 ${LOAD1}"

now=$(date +%s)
last=$(cat "$STATE" 2>/dev/null || echo 0)
if [ -n "${issues#\n}" ] && [ -n "$issues" ]; then
  [ $((now - last)) -ge 1800 ] && {
    send "🚨 AdKG 服务器报警" "$(echo "$issues" | sed 's/^\\n//')$(printf '\n时间: %s' "$(date '+%F %T')")"
    echo "$now" > "$STATE"
  }
elif [ "$last" != "0" ]; then   # 此前报过警且现已恢复
  send "✅ AdKG 恢复" "巡检全部通过（$(date '+%F %T')）"
  echo 0 > "$STATE"
fi
