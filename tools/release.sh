#!/bin/bash
# Folio Draw release checks (display :96): engine tests, UI audits (source), deb, installed tests in jammy, nolo and noble, and Wayland passes on noble.
set -e
/home/claude/mounts.sh
bash /home/claude/folio-draw/sync.sh
chroot /srv/jammy bash -c 'cd /src/folio-draw/engine && cargo build --release 2>&1 | tail -1'
echo "== engine tests"
chroot /srv/jammy bash -c 'cd /src/folio-draw/engine && cargo test --release 2>&1 | grep -E "test result|FAILED|panicked"' | tee /tmp/claude-0/draw96_engine.log
grep -q FAILED /tmp/claude-0/draw96_engine.log && exit 1
echo "== UI audits (source)"
for t in ${UI_TESTS:-ui_audit tools_audit dialog_audit theme_audit deep_audit emb_audit d2_audit d3_audit}; do
  chroot /srv/jammy bash -c "cd /src/folio-draw/tests && DISPLAY=:96 AUDIT_OUT=/tmp/aud_$t timeout 1200 python3 $t.py > /tmp/src_$t.log 2>&1" || { echo "FAIL $t"; tail -30 /srv/jammy/tmp/src_$t.log; exit 1; }
  echo "$t: $(grep -E 'checks' /srv/jammy/tmp/src_$t.log | tail -1)"
done
echo "== X2-01 desktop themes (source)"
chroot /srv/jammy bash -c "cd /src/folio-draw/tests && DISPLAY=:96 AUDIT_OUT=/tmp/aud_x201 timeout 1800 sh theme_run.sh > /tmp/src_x201.log 2>&1" || { echo "FAIL x201"; grep -E "^FAIL|^--" /srv/jammy/tmp/src_x201.log | head -30; exit 1; }
grep -E "^-- |checks" /srv/jammy/tmp/src_x201.log
echo "== deb"
chroot /srv/jammy bash -c 'cd /src/folio-draw && ./build-deb.sh 2>&1 | tail -1'
V=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' /home/claude/folio-draw/folio_draw/__init__.py)
DEB=folio-draw_${V}_amd64.deb
cp /srv/jammy/src/folio-draw/build/$DEB /home/claude/out/
for R in /srv/jammy /srv/nolo /srv/noble; do
  echo "== installed in $R"
  cp /home/claude/out/$DEB $R/tmp/
  flock /home/claude/.dpkg.lock chroot $R bash -c "dpkg -i /tmp/$DEB >/dev/null 2>&1 || (apt-get -f install -y >/dev/null 2>&1); dpkg -l folio-draw | tail -1 | awk '{print \$1, \$3}'"
  rm -rf $R/tmp/insttests && mkdir -p $R/tmp/insttests && cp -r /home/claude/folio-draw/tests $R/tmp/insttests/
  for t in ${INST_TESTS:-ui_audit emb_audit d2_audit d3_audit}; do
    chroot $R bash -c "cd /tmp/insttests/tests && DISPLAY=:96 AUDIT_OUT=/tmp/inst_$t timeout 1200 python3 $t.py > /tmp/inst_$t.log 2>&1" || { echo "FAIL installed $t"; tail -30 $R/tmp/inst_$t.log; exit 1; }
    chroot $R bash -c "python3 -c 'import folio_draw,sys; print(folio_draw.__file__)'" | grep -q /usr/lib || { echo "not the installed package"; exit 1; }
    echo "$t: $(grep -E 'checks' $R/tmp/inst_$t.log | tail -1)"
  done
  chroot $R bash -c "cd /tmp/insttests/tests && DISPLAY=:96 AUDIT_OUT=/tmp/inst_x201 timeout 1800 sh theme_run.sh > /tmp/inst_x201.log 2>&1" || { echo "FAIL installed x201"; grep -E "^FAIL|^--" $R/tmp/inst_x201.log | head; exit 1; }
  echo "x201: $(grep -c 'checks, 0 failed' $R/tmp/inst_x201.log)/3 themes pass"
  chroot $R bash -c "cd /tmp && folio-draw --embroider /tmp/insttests/tests/data/dsa.gif -o /tmp/cli.pes"
done
echo "== Wayland (24.04, installed)"
for t in ui_audit d3_audit; do
  chroot /srv/noble bash -c "cd /tmp/insttests/tests && export DISPLAY=:96; AUDIT_OUT=/tmp/wl_$t timeout 1200 /tmp/wl.sh python3 $t.py > /tmp/wl_$t.log 2>&1" || { echo "FAIL wayland $t"; grep -E "^FAIL|Traceback" -A3 /srv/noble/tmp/wl_$t.log | head -30; exit 1; }
  echo "wayland $t: $(grep -E 'checks' /srv/noble/tmp/wl_$t.log | tail -1)"
done
chroot /srv/noble bash -c "cd /tmp/insttests/tests && export DISPLAY=:96; AUDIT_OUT=/tmp/wl_x201 timeout 1800 /tmp/wl.sh sh theme_run.sh > /tmp/wl_x201.log 2>&1" || { echo "FAIL wayland x201"; grep -E "^FAIL|^--|Traceback" /srv/noble/tmp/wl_x201.log | head -30; exit 1; }
echo "wayland x201: $(grep -c 'checks, 0 failed' /srv/noble/tmp/wl_x201.log)/3 themes pass"
