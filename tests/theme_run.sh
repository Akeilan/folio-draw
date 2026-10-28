#!/bin/sh
# X2-01: x201_audit.py under a dark desktop (Draw following it, and Draw set to light) and a loud coloured one.
HERE="$(cd "$(dirname "$0")" && pwd)"
rc=0
for combo in dark: dark:light colour:; do
  t=${combo%%:*}; f=${combo#*:}
  echo "-- theme $t ${f:+(app $f)}"
  GTK_THEME=$(python3 "$HERE/themecheck.py" $t) FOLIO_THEME=$f python3 "$HERE/x201_audit.py" || rc=1
done
[ $rc = 0 ] && echo "x201: all themes pass, checks" || echo "x201: FAILED checks"
exit $rc
