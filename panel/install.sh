#!/bin/bash
# Установка панельной части ClassView (ROSA / MOS Linux). Запуск: sudo ./install.sh <пароль_потоков>
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Запустите через sudo"; exit 1; }
cd "$(dirname "$0")"

STREAM_USER="viewer"
STREAM_PASS="${1:-}"
[ -n "$STREAM_PASS" ] || { echo "Использование: sudo ./install.sh <пароль_потоков>"; echo "(тот же пароль, что указан в GUI сервера)"; exit 1; }

PREFIX=/opt/classview
ARCH="$(uname -m)"
case "$ARCH" in
    x86_64) MTX_ARCH="amd64" ;;
    aarch64) MTX_ARCH="arm64v8" ;;
    *) echo "Неизвестная архитектура: $ARCH"; exit 1 ;;
esac

echo "== Системные пакеты"
dnf install -y ffmpeg v4l-utils alsa-utils python3 >/dev/null || { echo "!! Не удалось поставить пакеты"; exit 1; }

echo "== Каталоги"
mkdir -p "$PREFIX/bin" "$PREFIX/config" "$PREFIX/indicator"

echo "== MediaMTX"
if [ -f bin/mediamtx ]; then
    install -m 755 bin/mediamtx "$PREFIX/bin/mediamtx"
else
    echo "   bin/mediamtx нет в пакете — скачиваю..."
    ver="v1.9.3"
    tmp="$(mktemp -d)"
    curl -fsSL -o "$tmp/m.tgz" \
        "https://github.com/bluenviron/mediamtx/releases/download/${ver}/mediamtx_${ver}_linux_${MTX_ARCH}.tar.gz"
    tar xzf "$tmp/m.tgz" -C "$tmp"
    install -m 755 "$tmp/mediamtx" "$PREFIX/bin/mediamtx"
    rm -rf "$tmp"
fi

echo "== Скрипты и конфиг"
install -m 755 bin/classview-capture.sh "$PREFIX/bin/classview-capture.sh"
# Пароль потоков в конфиг
sed -e "s|__STREAM_USER__|${STREAM_USER}|" -e "s|__STREAM_PASS__|${STREAM_PASS}|" \
    config/mediamtx.yml > "$PREFIX/config/mediamtx.yml"
chmod 640 "$PREFIX/config/mediamtx.yml"

echo "== Индикатор в трее"
# Лёгкий venv только для PySide6 (для индикатора). Если система тяжёлая — можно пропустить.
if [ ! -x "$PREFIX/venv/bin/python" ]; then
    python3 -m venv "$PREFIX/venv"
    "$PREFIX/venv/bin/pip" install -q --upgrade pip
    "$PREFIX/venv/bin/pip" install -q PySide6
fi
install -m 755 indicator/classview-indicator.py "$PREFIX/indicator/classview-indicator.py"
# Автозапуск во всех пользовательских сессиях (учитель залогинен на seat0)
install -d /etc/xdg/autostart
install -m 644 indicator/classview-indicator.desktop /etc/xdg/autostart/classview-indicator.desktop


echo "== Доступ к камере для пользователя сессии"
# Пользователь активной графической сессии (учитель) должен быть в группе video,
# иначе runuser-ffmpeg не откроет камеру. Находим его и добавляем.
SESS_USER=""
for uid_dir in /run/user/*/pulse/native; do
    [ -S "$uid_dir" ] || continue
    uid="${uid_dir#/run/user/}"; uid="${uid%%/*}"
    [ "$uid" -ge 1000 ] 2>/dev/null || continue
    SESS_USER="$(getent passwd "$uid" | cut -d: -f1)"
    [ -n "$SESS_USER" ] && break
done
if [ -n "$SESS_USER" ]; then
    if ! id -nG "$SESS_USER" | tr ' ' '\n' | grep -qx video; then
        usermod -aG video "$SESS_USER"
        echo "   $SESS_USER добавлен в группу video (применится после его перезахода)"
    else
        echo "   $SESS_USER уже в группе video"
    fi
else
    echo "   !! Не найден пользователь графической сессии — добавьте в группу video вручную"
fi

echo "== Служба MediaMTX"
install -m 644 config/classview-panel.service /etc/systemd/system/classview-panel.service
systemctl daemon-reload
systemctl enable --now classview-panel.service

sleep 2
if systemctl is-active --quiet classview-panel.service; then
    echo "OK: служба запущена."
else
    echo "!! Служба не запустилась. Смотрите: journalctl -u classview-panel -n 30"
fi
echo "Готово. Индикатор появится у залогиненного пользователя после перезахода или команды:"
echo "  sudo -u <teacher> DISPLAY=:0 $PREFIX/venv/bin/python $PREFIX/indicator/classview-indicator.py &"
