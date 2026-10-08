#!/bin/bash
# Установка ClassView на серверный ПК (ROSA / MOS Linux). Запуск: sudo ./install.sh
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Запустите через sudo"; exit 1; }
cd "$(dirname "$0")"
PREFIX=/opt/classview

echo "== Системные пакеты"
dnf install -y python3 ffmpeg mpv || { echo "!! Не удалось поставить python3/ffmpeg/mpv"; exit 1; }
# Qt 6.5+ на X11 требует xcb-cursor; имя пакета на ROSA может отличаться
for p in lib64xcb-util-cursor0 xcb-util-cursor libxcb-cursor0; do dnf install -y "$p" >/dev/null 2>&1 && break || true; done

echo "== Python-окружение в $PREFIX/venv"
mkdir -p "$PREFIX"
python3 -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install -q --upgrade pip
"$PREFIX/venv/bin/pip" install -q -r requirements.txt

echo "== Файлы приложения"
rm -rf "$PREFIX/classview"
cp -r classview "$PREFIX/"
cat > /usr/local/bin/classview <<LAUNCH
#!/bin/sh
cd $PREFIX && exec $PREFIX/venv/bin/python -m classview "\$@"
LAUNCH
chmod 755 /usr/local/bin/classview
install -m 644 classview.desktop /usr/share/applications/classview.desktop

echo "== Проверка"
if "$PREFIX/venv/bin/python" -c "import mpv" 2>/dev/null; then
  echo "   libmpv найдена — видео с низкой задержкой"
else
  echo "   !! libmpv не найдена — будет запасной плеер Qt (задержка выше). Поставьте пакет с libmpv."
fi
echo "Готово. Запуск: меню → ClassView или команда classview"
