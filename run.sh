#!/usr/bin/env bash
# Lance ClawBody depuis son venv dédié.
#
#   ./run.sh                # mode console
#   ./run.sh --gradio       # interface web
#   ./run.sh --debug        # logs verbeux
#
# ClawBody a son propre venv : gradio plafonne pydantic à <=2.12.3 alors que
# reachy_mini 1.9.0 en demande >=2.12.5. Les deux ne peuvent pas cohabiter dans
# ../.venv sans casser le simulateur.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$HERE/.venv"

if [ ! -x "$VENV/bin/clawbody" ]; then
  echo "❌ venv absent ou incomplet : $VENV" >&2
  echo "   Réinstalle :" >&2
  echo "     uv venv --python 3.12 $VENV" >&2
  echo "     uv pip install --python $VENV/bin/python --override $HERE/overrides.txt -e '$HERE' reachy_mini==1.9.0 ultralytics supervision" >&2
  exit 1
fi

# GStreamer charge libgstpython.dylib, qui cherche libpython3.12.dylib via
# @rpath sans la trouver. Sans ça, chaque lancement crache un pavé de warnings
# et le plugin échoue. Même correctif que ../sim.sh.
PY_LIB="$("$VENV/bin/python" -c 'import sysconfig; print(sysconfig.get_config_var("LIBDIR"))')"
export DYLD_FALLBACK_LIBRARY_PATH="${PY_LIB}${DYLD_FALLBACK_LIBRARY_PATH:+:$DYLD_FALLBACK_LIBRARY_PATH}"

if [ ! -f "$HERE/.env" ]; then
  echo "⚠️  $HERE/.env absent — copie .env.example et renseigne tes clés." >&2
fi

exec "$VENV/bin/clawbody" "$@"
