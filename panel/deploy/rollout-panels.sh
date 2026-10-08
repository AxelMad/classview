#!/bin/bash
# Массовая установка панельной части ClassView на все панели корпуса.
# Запуск с сервера:  ./rollout-panels.sh panels.csv <пароль_потоков> [--dry-run]
# CSV: строки hostname,ip. Берутся только p1747-...
# Пароль sudo для панелей спрашивается один раз в начале (единый на все панели).
set -uo pipefail

CSV="${1:-}"
STREAM_PASS="${2:-}"
DRY=""
[ "${3:-}" = "--dry-run" ] && DRY="1"
[ -n "$CSV" ] && [ -n "$STREAM_PASS" ] || { echo "Использование: $0 panels.csv <пароль_потоков> [--dry-run]"; exit 1; }
[ -f "$CSV" ] || { echo "Нет файла $CSV"; exit 1; }

SSH_USER="${SSH_USER:-admin}"
SCHOOL="${SCHOOL:-}"   # номер школы для фильтра hostname; пусто = любые панели p*
PKG_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DIR_URL="${DIR_URL:-http://127.0.0.1:8781}"
DIR_TOKEN="${DIR_TOKEN:-}"
SSH_OPTS="-o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new"

# Пароль sudo для панелей (единый). В файл не пишется, живёт только в памяти процесса.
SUDO_PASS=""
if [ -z "$DRY" ]; then
    read -rsp "Пароль sudo для панелей (единый): " SUDO_PASS; echo
    [ -n "$SUDO_PASS" ] || { echo "Пустой пароль — отмена"; exit 1; }
fi

ok=0; fail=0; skip=0
declare -a REPORT

resolve_ip() {
    local host="$1" csv_ip="$2" ip=""
    if [ -n "$DIR_TOKEN" ]; then
        ip="$(curl -s -H "X-Filedrop-Token: $DIR_TOKEN" "$DIR_URL/resolve?name=$host" \
              | grep -oP '"ip":"\K[^"]+' || true)"
    fi
    echo "${ip:-$csv_ip}"
}

# Установка на одну панель. Пароль sudo подаётся в stdin для sudo -S.
install_panel() {   # $1=ip
    local ip="$1"
    scp -q $SSH_OPTS -r "$PKG_DIR" "$SSH_USER@$ip:/tmp/classview-panel" || return 1
    # -S читает пароль из stdin; -p '' убирает подсказку; остальной вывод install.sh идёт как обычно
    printf '%s\n' "$SUDO_PASS" | ssh $SSH_OPTS "$SSH_USER@$ip" \
        "cd /tmp/classview-panel && sudo -S -p '' ./install.sh '$STREAM_PASS' && rm -rf /tmp/classview-panel"
}

# Проверка: поднять поток на 2 с, снять статус службы и имя микрофона.
probe_panel() {   # $1=ip -> "служба|микрофон"
    local ip="$1"
    printf '%s\n' "$SUDO_PASS" | ssh $SSH_OPTS "$SSH_USER@$ip" "sudo -S -p '' bash -s" <<'REMOTE'
svc="$(systemctl is-active classview-panel 2>/dev/null || echo unknown)"
timeout 8 ffmpeg -hide_banner -loglevel error -rtsp_transport tcp \
  -i "rtsp://127.0.0.1:8554/cam" -t 2 -f null - >/dev/null 2>&1 || true
mic="$(journalctl -u classview-panel --since '30 sec ago' --no-pager 2>/dev/null \
       | grep -o 'микрофон=[^ ]*' | tail -1)"
case "$mic" in
  *TOUCHDEVICE*) mic="TOUCHDEVICE ok" ;;
  *default*)     mic="default (!)" ;;
  микрофон=*)    mic="${mic#микрофон=}" ;;
  *)             mic="звук=нет?" ;;
esac
echo "${svc}|${mic}"
REMOTE
}

while IFS=, read -r host csv_ip _; do
    host="$(echo "$host" | tr -d ' \r')"
    [ -z "$host" ] && continue
    case "$host" in \#*) continue ;; esac
    case "$host" in hostname) continue ;; esac
    # берём только панели: имя начинается с p<SCHOOL>- (если SCHOOL задан) или p<цифры>- иначе
    if [ -n "$SCHOOL" ]; then
        case "$host" in "p${SCHOOL}-"*) : ;; *) skip=$((skip+1)); continue ;; esac
    else
        case "$host" in p[0-9]*-*-*-*) : ;; *) skip=$((skip+1)); continue ;; esac
    fi

    ip="$(resolve_ip "$host" "$(echo "$csv_ip" | tr -d ' \r')")"
    if [ -z "$ip" ]; then
        echo "[$host] нет IP — пропуск"; fail=$((fail+1)); REPORT+=("$host|—|нет IP|—"); continue
    fi

    echo "== $host ($ip)"
    if [ -n "$DRY" ]; then
        echo "   [dry-run] IP получен, установка пропущена"
        ok=$((ok+1)); REPORT+=("$host|$ip|dry-run|—"); continue
    fi

    if install_panel "$ip"; then
        echo "   установка OK, проверяю поток…"
        probe="$(probe_panel "$ip" 2>/dev/null | tail -1)"
        [ -z "$probe" ] && probe="unknown|проба не удалась"
        svc="${probe%%|*}"; mic="${probe#*|}"
        echo "   служба: $svc | микрофон: $mic"
        ok=$((ok+1)); REPORT+=("$host|$ip|$svc|$mic")
    else
        echo "   ОШИБКА установки"; fail=$((fail+1)); REPORT+=("$host|$ip|ошибка|—")
    fi
done < "$CSV"

echo
echo "════════════════════════ СВОДКА ════════════════════════"
printf "%-15s %-16s %-9s %s\n" "Кабинет" "IP" "Служба" "Микрофон"
echo "--------------------------------------------------------------------"
for r in "${REPORT[@]}"; do
    IFS='|' read -r h i s m <<< "$r"
    printf "%-15s %-16s %-9s %s\n" "$h" "$i" "$s" "$m"
done
echo "--------------------------------------------------------------------"
echo "Успешно: $ok, ошибок: $fail, пропущено (не панели): $skip"
echo
echo "На что смотреть:"
echo "  • Служба ≠ active — панель не поднялась (journalctl -u classview-panel на ней)."
echo "  • Микрофон 'default (!)' или 'звук=нет?' — нет рабочего TOUCHDEVICE-микрофона."
echo "  • Группа video у учителя применится после его перезахода/перезагрузки панели."
