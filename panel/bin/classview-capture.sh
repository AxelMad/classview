#!/bin/bash
# Захват камеры (H.264) + микрофон через PulseAudio.
# Запускается MediaMTX (runOnDemand) от root, но ffmpeg исполняется ОТ ПОЛЬЗОВАТЕЛЯ активной
# графической сессии (учитель): тогда его собственные камера и PulseAudio открываются без cookie.
# $1 = имя пути (cam).
set -euo pipefail

RTSP_PORT="${RTSP_PORT:-8554}"
WIDTH="${WIDTH:-1280}"
HEIGHT="${HEIGHT:-720}"
FPS="${FPS:-25}"
PATH_NAME="${1:-cam}"

log() { echo "classview-capture: $*" >&2; }

find_camera() {
    for dev in /dev/video*; do
        [ -e "$dev" ] || continue
        if v4l2-ctl -d "$dev" --list-formats 2>/dev/null | grep -q 'H264'; then
            echo "$dev"; return 0
        fi
    done
    echo /dev/video0
}

# UID и имя пользователя активной графической сессии на seat0.
find_session() {   # печатает "UID USER" или ничего
    local sid seat type u uid
    while read -r sid _; do
        [ -z "$sid" ] && continue
        seat="$(loginctl show-session "$sid" -p Seat --value 2>/dev/null || true)"
        type="$(loginctl show-session "$sid" -p Type --value 2>/dev/null || true)"
        u="$(loginctl show-session "$sid" -p Name --value 2>/dev/null || true)"
        uid="$(loginctl show-session "$sid" -p User --value 2>/dev/null || true)"
        if [ "$seat" = "seat0" ] && { [ "$type" = "x11" ] || [ "$type" = "wayland" ]; } && [ -n "$uid" ]; then
            echo "$uid $u"; return 0
        fi
    done < <(loginctl list-sessions --no-legend 2>/dev/null)
    # запасной вариант: владелец первого Pulse-сокета
    for d in /run/user/*/pulse/native; do
        [ -S "$d" ] || continue
        uid="${d#/run/user/}"; uid="${uid%%/*}"
        echo "$uid $(getent passwd "$uid" | cut -d: -f1)"; return 0
    done
    return 1
}

CAM="$(find_camera)"
RTSP="rtsp://127.0.0.1:${RTSP_PORT}/${PATH_NAME}"

# Общая часть команды ffmpeg: видео с камеры без перекодирования.
run_video_only() {
    log "камера=$CAM звук=нет ${WIDTH}x${HEIGHT}@${FPS}"
    exec ffmpeg -hide_banner -loglevel warning \
        -f v4l2 -input_format h264 -video_size "${WIDTH}x${HEIGHT}" -framerate "$FPS" -thread_queue_size 512 -i "$CAM" \
        -map 0:v -c:v copy \
        -f rtsp -rtsp_transport tcp "$RTSP"
}

# Имя PulseAudio-источника микрофона: у камеры (C-Media) микрофон мёртвый,
# рабочий — микрофон тачскрина (в имени содержит TOUCHDEVICE). Полное имя на каждой
# панели своё (там серийник), поэтому ищем по подстроке. Запуск от пользователя сессии.
find_mic_source() {
    local uid="$1" user="$2"
    runuser -u "$user" -- env "XDG_RUNTIME_DIR=/run/user/${uid}" \
        ffmpeg -hide_banner -sources pulse 2>/dev/null \
        | sed -n 's/^[* ]*\(alsa_input[^ ]*\).*/\1/p' > /tmp/.cv_srcs.$$ || true
    local touch cmedia any
    touch="$(grep -i 'TOUCHDEVICE' /tmp/.cv_srcs.$$ | head -1)"
    cmedia="$(grep -i 'C-Media' /tmp/.cv_srcs.$$ | head -1)"
    any="$(grep -iv '\.monitor' /tmp/.cv_srcs.$$ | head -1)"
    rm -f /tmp/.cv_srcs.$$
    # приоритет: TOUCHDEVICE -> любой не-C-Media вход -> default
    if [ -n "$touch" ]; then echo "$touch"; return; fi
    if [ -n "$any" ] && [ "$any" != "$cmedia" ]; then echo "$any"; return; fi
    echo "default"
}

SESS="$(find_session || true)"
if [ -z "$SESS" ]; then
    run_video_only
fi
UID_ACT="${SESS%% *}"
USER_ACT="${SESS##* }"

if [ ! -S "/run/user/${UID_ACT}/pulse/native" ]; then
    log "нет Pulse-сокета у $USER_ACT (uid=$UID_ACT) — только видео"
    run_video_only
fi

MIC="$(find_mic_source "$UID_ACT" "$USER_ACT")"
log "камера=$CAM микрофон=$MIC запуск от $USER_ACT (uid=$UID_ACT) ${WIDTH}x${HEIGHT}@${FPS}"
# runuser стартует ffmpeg в сессии учителя: его камера и Pulse доступны без cookie.
# thread_queue_size поднят против блокировки очереди; aresample выравнивает звук под видео.
exec runuser -u "$USER_ACT" -- env "XDG_RUNTIME_DIR=/run/user/${UID_ACT}" \
    ffmpeg -hide_banner -loglevel warning \
    -f v4l2 -input_format h264 -video_size "${WIDTH}x${HEIGHT}" -framerate "$FPS" -thread_queue_size 1024 -i "$CAM" \
    -f pulse -thread_queue_size 1024 -i "$MIC" \
    -map 0:v -map 1:a \
    -c:v copy \
    -c:a libopus -b:a 48k -ac 1 -application audio \
    -af "aresample=async=1:min_hard_comp=0.1:first_pts=0" \
    -f rtsp -rtsp_transport tcp "$RTSP"
